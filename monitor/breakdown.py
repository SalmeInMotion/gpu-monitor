"""Who is using it: the per-process breakdown behind each meter.

Double-clicking VRAM, RAM, GPU usage or CPU asks for one of these. The
kind is the metric's own key, so there is one vocabulary and no mapping
to keep in step.

Entries are grouped by executable, because one browser is fifty processes
and a list of fifty "msedge.exe" rows answers nothing, and anything under
the kind's threshold is left out. Ivan set both — 16 MB for the memory
meters, 5% for the usage ones.

No Qt in here on purpose — this runs on the sampler thread, where a walk
of the process table cannot stutter the card.
"""

from __future__ import annotations

import logging
import os
import re

log = logging.getLogger("gpu_monitor.breakdown")

try:
    import psutil
except ImportError:  # pragma: no cover - depends on the machine
    psutil = None

from .winproc import (command_line, denied, image_path, image_path_unopened,
                      listening_ports, services_by_pid, snapshot,
                      window_titles, working_sets)

# The metric keys from metrics.py; `Metric.breakdown` just says whether a
# row has one, and the kind is the key itself.
KIND_VRAM = "vram"
KIND_RAM = "ram"
KIND_GPU = "gpu"
KIND_CPU = "cpu"

MEMORY_KINDS = frozenset({KIND_VRAM, KIND_RAM})
USAGE_KINDS = frozenset({KIND_GPU, KIND_CPU})

# 512 MB, then 16 MB for an afternoon, then 256 -- all Ivan's, all on
# 2026-08-27. 16 admitted the small named services he had asked for and
# 113 rows with them; his verdict on seeing it was that anything that
# small is not relevant to a list whose question is "what is eating this".
# 256 MB is where it rests: about 32 rows here.
HIDE_BELOW_BYTES = 256 * 1024 * 1024
HIDE_BELOW_PERCENT = 5.0

# Killing any of these takes Windows down with it, so they are listed but
# never selectable. Names are lowercase, without the .exe.
PROTECTED = frozenset({
    # Windows itself. Ending any of these blue-screens or blanks the
    # session, so they are listed -- they really are using the machine --
    # but can never be selected.
    "system", "system idle process", "secure system", "registry",
    "memory compression",   # NT's name for it
    "memcompression",       # psutil's name for the same process
    "smss", "csrss", "wininit", "winlogon",
    "services", "lsass", "lsaiso", "fontdrvhost", "svchost",
    "dwm",                  # the compositor: killing it blanks every window
    "audiodg", "wudfhost", "sihost", "ctfmon",
})

# 100-nanosecond units per second, the resolution NT reports CPU time in.
_TICKS_PER_SECOND = 1e7


def threshold_for(kind):
    return HIDE_BELOW_BYTES if kind in MEMORY_KINDS else HIDE_BELOW_PERCENT


class Entry:
    """One executable, and every process of it that counts toward a meter.

    `value` is bytes for the memory kinds and a percentage for the usage
    ones; `fmt_value` is what knows which.
    """

    __slots__ = ("name", "value", "pids", "detail")

    def __init__(self, name, value, pids, detail=""):
        self.name = name
        self.value = value
        self.pids = list(pids)
        # The full command line, for rows whose name had to be worked out
        # rather than read off the executable. The panel shows it on hover.
        self.detail = detail

    @property
    def protected(self):
        return self.name.lower() in PROTECTED

    def __repr__(self):
        return f"<Entry {self.name} {self.value:.1f} x{len(self.pids)}>"


def _tidy(name):
    """"msedge.exe" -> "msedge". The extension is the same on every row."""
    return name[:-4] if name.lower().endswith(".exe") else name


# --- what a generic host is actually running --------------------------------
#
# "python" answers nothing: it was 30 GB of video memory on AI-cachofo and
# 51 unrelated processes on this machine. The executable is only a host;
# what it was told to run is on its command line, one PEB read away
# (measured: 0.03 ms per process, 2 ms for all 75 hosts here).

# Interpreters and runtimes: their own name identifies nobody.
GENERIC_HOSTS = frozenset({
    "python", "pythonw", "py", "node", "electron", "deno", "bun",
    "java", "javaw", "ruby", "perl", "php", "dotnet", "mono",
    "powershell", "pwsh", "cmd", "wscript", "cscript",
})

# Script names every second project uses, so the folder above them is what
# the thing is actually called: C:\ComfyUI\main.py is "ComfyUI".
_ANONYMOUS_SCRIPTS = frozenset({
    "main", "app", "run", "start", "server", "serve", "cli", "index",
    "__main__", "manage", "setup", "service", "daemon", "bootstrap",
    "launch", "init", "program", "entry", "wsgi", "asgi",
})

# Folders that are part of every layout and name no project either.
_ANONYMOUS_DIRS = frozenset({
    "bin", "src", "lib", "app", "dist", "build", "out", "scripts",
    "script", "venv", ".venv", "env", ".env", "node_modules",
    "site-packages", "tools", "backend", "frontend", "server", "code",
    "current", "release", "debug",
    # Windows' own plumbing, which is above half the paths on the machine
    "windows", "system32", "syswow64", "program files",
    "program files (x86)", "programdata", "users", "appdata", "local",
    "locallow", "roaming", "programs", "temp",
})

# Flags whose next token is the thing being run.
_TAKES_A_MODULE = frozenset({"-m"})
_TAKES_A_PATH = frozenset({"-jar", "-file", "/c", "/k"})
# Flags that carry an argument of their own, which must not be mistaken
# for the script: `java -cp <classpath> com.foo.Main`.
_TAKES_SOMETHING_ELSE = frozenset({"-cp", "-classpath", "--class-path",
                                   "-x", "--user-data-dir"})
# Flags followed by source code rather than a path. Without this, the text
# of `python -c "..."` gets split on its slashes and a fragment of the
# program becomes the row's name -- which is exactly what happened.
_INLINE_CODE = frozenset({"-c", "-e", "--eval", "-command", "-encodedcommand",
                          "-enc", "-ec"})

# What a row says when it is allowed to see the process but not to ask
# what it is doing -- an elevated one. Windows gives no way round it short
# of elevating the monitor, which is a bad trade for a thing that watches.
OUT_OF_REACH = ("Runs with more privilege than the monitor, so Windows "
                "will not say what it is running.")

_VERSIONISH = re.compile(r"[vV]?[\d._]+")
_DRIVE = re.compile(r"[A-Za-z]:")
_WINDOWS_DIR = (os.environ.get("SystemRoot") or "C:\\Windows").lower()


def _target_of(argv):
    """('module'|'path', what it runs) from a command line, or None.

    argv[0] is the interpreter; the answer is the first bare argument, or
    whatever a flag like -m or -jar introduces.
    """
    rest = argv[1:]
    i = 0
    while i < len(rest):
        token = rest[i]
        low = token.lower()
        following = rest[i + 1] if i + 1 < len(rest) else None
        if low in _TAKES_A_MODULE:
            return ("module", following) if following else None
        if low in _TAKES_A_PATH:
            return ("path", following) if following else None
        if low in _INLINE_CODE:
            return None             # code, not a name; stop looking
        if low in _TAKES_SOMETHING_ELSE:
            i += 2
            continue
        if token.startswith("-") or token.startswith("/"):
            i += 1                  # a flag we do not need to understand
            continue
        return ("path", token)
    return None


def _label_from_path(path):
    """C:\\ComfyUI\\main.py -> ComfyUI, .../houdini-claude/tools/mcp_server.py
    -> mcp_server. None when nothing along the path names anything.

    Returning None rather than a shrug matters: the caller has other paths
    to try, and a bare `main.py` must not stop it from reaching the
    virtualenv that says ComfyUI.
    """
    parts = [p for p in re.split(r"[\\/]+", path) if p]
    if not parts:
        return None
    stem = os.path.splitext(parts[-1])[0]
    if stem and stem.lower() not in _ANONYMOUS_SCRIPTS \
            and stem.lower() not in GENERIC_HOSTS:
        return stem
    for folder in reversed(parts[:-1]):
        if _DRIVE.fullmatch(folder) or _VERSIONISH.fullmatch(folder):
            continue
        if folder.lower() in _ANONYMOUS_DIRS or folder.lower() in GENERIC_HOSTS:
            continue
        return folder
    return None


def _tells_us_something(label, host):
    """Would this label be an answer, or just the question again?

    "Python311 (python)" and "WindowsPowerShell (powershell)" are the two
    that came out of a live machine: the host's own name, spelled longer.
    """
    if not label:
        return False
    return host.lower() not in label.lower() \
        and not _VERSIONISH.fullmatch(label)


def _is_the_systems_own(path):
    """Under C:\\Windows, so it names an installation rather than a project."""
    return bool(path) and path.lower().startswith(_WINDOWS_DIR)


def describe(pid, host):
    """(what this host is running, its full command line).

    The label is None when nothing knowable says more than the executable
    already did, and the caller then leaves the row as it was.
    """
    # The kernel first: psutil reads the target's PEB, which an ordinary
    # process may not do to an elevated one -- and that is exactly the
    # case this feature exists for. See winproc.command_line.
    argv = command_line(pid)
    if not argv and psutil is not None:
        try:
            argv = psutil.Process(pid).cmdline()
        except Exception:
            argv = None
    if not argv:
        # Gone, or a protected process. Either way there is nothing to add.
        return None, ""
    line = " ".join(argv)

    target = _target_of(argv)
    if target and target[0] == "module" and target[1]:
        # `-m hub`: the module *is* the name, and splitting it on dots
        # would turn `http.server` into `http`.
        module = target[1]
        return (module if _tells_us_something(module, host) else None), line

    # Best first: what it was told to run, then the interpreter it was
    # invoked as, then the image actually running. A relative `main.py` is
    # why the first is not enough alone, and the second is not the third:
    # ComfyUI Desktop is launched through the project's own .venv but its
    # real image lives in a shared `standalone-env` that names nobody.
    #
    # Deliberately not the working directory. An interactive shell in
    # C:\IA\Tools is not "Tools" -- it is a shell, and saying so is the
    # honest answer.
    paths = []
    if target and target[1]:
        paths.append(target[1])
    paths.append(argv[0])
    running = image_path(pid)
    if running:
        paths.append(running)

    for path in paths:
        if _is_the_systems_own(path):
            continue                # an installation path, not a project
        label = _label_from_path(path)
        if _tells_us_something(label, host):
            return label, line
    return None, line


# --- inference servers: the model is the identity ---------------------------
#
# `llama-server` holding 23 GB of video memory is a true statement about
# nothing. What it has loaded is on its command line, but as a blob digest
# -- `--model ...\blobs\sha256-f5f1dd89...` -- because that is how Ollama
# stores them. The manifests beside the blobs turn it back into a name.

MODEL_HOSTS = frozenset({
    "llama-server", "ollama_llama_server", "llamafile", "koboldcpp",
})
_TAKES_A_MODEL = frozenset({"--model", "-m", "--model-path"})

_ollama_blobs = None


def ollama_names(rebuild=False):
    """{blob digest: "qwen3.8:latest"} from the manifests on disk."""
    global _ollama_blobs
    if _ollama_blobs is not None and not rebuild:
        return _ollama_blobs
    import glob
    import json
    found = {}
    root = os.path.join(os.path.expanduser("~"), ".ollama", "models",
                        "manifests")
    if os.path.isdir(root):
        for path in glob.glob(os.path.join(root, "**", "*"), recursive=True):
            if not os.path.isfile(path):
                continue
            try:
                with open(path, encoding="utf-8") as handle:
                    doc = json.load(handle)
            except Exception:
                continue
            # The manifest's own path is the model's name:
            # registry.ollama.ai/library/qwen3.8/latest -> qwen3.8:latest
            parts = os.path.relpath(path, root).replace(os.sep, "/").split("/")
            name = f"{parts[-2]}:{parts[-1]}" if len(parts) >= 2 else parts[-1]
            digests = [(layer.get("digest") or "")
                       for layer in doc.get("layers", ())]
            digests.append((doc.get("config") or {}).get("digest") or "")
            for digest in digests:
                if digest:
                    found[digest.replace(":", "-")] = name
    _ollama_blobs = found
    return found


def ollama_loaded():
    """[(model, bytes resident)] that Ollama says it currently holds.

    The last resort for a `llama-server` we may not open: HTTP knows
    nothing about elevation, so this answers where the command line does
    not -- and on AI-cachofo that is the only thing that does, since
    Ollama runs elevated there. Deliberately *not* attributed to a pid:
    two servers can be up, and matching them by size would be a guess
    dressed as a fact.
    """
    import json
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/ps",
                                    timeout=1.5) as answer:
            doc = json.loads(answer.read().decode("utf-8"))
    except Exception:
        return []       # not running, not listening, not our business
    out = []
    for model in doc.get("models", ()):
        name = model.get("name") or model.get("model")
        if name:
            out.append((name, int(model.get("size_vram")
                                  or model.get("size") or 0)))
    out.sort(key=lambda row: -row[1])
    return out


def _model_of(argv):
    """The model file an inference server was pointed at, or None."""
    for i, token in enumerate(argv[1:], start=1):
        if token.lower() in _TAKES_A_MODEL and i + 1 < len(argv):
            return argv[i + 1]
    return None


def describe_model(pid, host):
    """(the model it has loaded, its full command line)."""
    argv = command_line(pid)
    if not argv and psutil is not None:
        try:
            argv = psutil.Process(pid).cmdline()
        except Exception:
            argv = None
    if not argv:
        return None, ""
    line = " ".join(argv)
    path = _model_of(argv)
    if not path:
        return None, line
    stem = os.path.basename(path)
    known = ollama_names().get(stem)
    if known is None and stem.startswith("sha256-"):
        # A model pulled since we last looked. Re-read once, not every
        # refresh: a miss is the only thing that can mean it is stale.
        known = ollama_names(rebuild=True).get(stem)
    if known:
        return known, line
    # Not an Ollama blob: a plain .gguf names itself well enough.
    plain = os.path.splitext(stem)[0]
    return (plain if _tells_us_something(plain, host) else None), line


def name_map():
    """{pid: executable} in one sweep, for the GPU counters' bare pids."""
    rows = working_sets()
    if rows is not None:
        return {pid: name for pid, name, _ in rows}
    if psutil is None:
        return {}
    out = {}
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            out[proc.info["pid"]] = proc.info["name"] or "?"
        except Exception:
            continue
    return out


MAX_SERVICES_LISTED = 6


def _name_services(entries, contrib, kind):
    """Say which services a row is, for the rows that are services.

    `svchost` is as generic as `python` and cannot be treated the same
    way: it is 93 processes here, the biggest of them 82 MB, so splitting
    it per service would put every piece under the memory threshold as
    the 1.9 GB row would vanish altogether. The row stays whole; what it
    contains goes on the hover instead.
    """
    if not entries:
        return
    hosted = services_by_pid()
    if not hosted:
        return
    for entry in entries:
        rows = [(value, hosted.get(pid) or [])
                for value, pid in contrib.get(entry.name, ())]
        rows = [(value, names) for value, names in rows if names]
        if not rows:
            continue

        distinct = {tuple(names) for _, names in rows}
        alone = next(iter(distinct))
        if (len(rows) == len(entry.pids) and len(distinct) == 1
                and len(alone) == 1 and not entry.protected
                and _tells_us_something(alone[0], entry.name)):
            # Every process of this row is the same single service, so the
            # service *is* the row: MsMpEng -> Microsoft Defender. Never
            # for a protected name -- Entry.protected reads the name, and
            # renaming one would quietly make it selectable.
            entry.name = f"{alone[0]} ({entry.name})"
            continue

        rows.sort(key=lambda row: -row[0])
        lines = [f"{fmt_value(kind, value)}  {', '.join(names)}"
                 for value, names in rows[:MAX_SERVICES_LISTED]]
        left = len(rows) - len(lines)
        if left > 0:
            lines.append(f"and {left} more")
        if not entry.detail:
            entry.detail = "\n".join(lines)


def _collect(raw, names=None, threshold=HIDE_BELOW_BYTES, kind=KIND_RAM):
    """{pid: value} -> the sorted, filtered, grouped-by-executable list."""
    if names is None:
        names = name_map()
    grouped = {}
    # What each pid contributed, kept only until the services are named:
    # ranking them needs the per-process figures the grouping throws away.
    contrib = {}
    # Read at most once, and only if something is actually out of reach.
    ports = None
    for pid, value in raw.items():
        if value <= 0:
            continue
        raw_name = names.get(pid)
        # Exited between the reading and now, or not ours to look at. It
        # is still real usage, so it goes in one bucket rather than being
        # dropped from a total the bar is showing.
        name = _tidy(raw_name) if raw_name else "(other)"
        detail = ""
        if name.lower() in GENERIC_HOSTS or name.lower() in MODEL_HOSTS:
            # Group by what it is running, not by the thing running it, so
            # two unrelated tools are two rows instead of one meaningless
            # total -- and so an inference server names its model.
            if name.lower() in MODEL_HOSTS:
                label, line = describe_model(pid, name)
            else:
                label, line = describe(pid, name)
            if label:
                name = f"{label} ({name})"
                # Only then: a row that stayed "powershell" is eleven
                # different shells, and showing the first one's command
                # line as though it were the group's is a half-truth.
                detail = line
            elif denied(pid):
                # Not a shrug: the row can say why it has nothing to say,
                # and a listening port is often the whole answer anyway.
                if ports is None:
                    ports = listening_ports()
                heard = ports.get(pid) or []
                detail = OUT_OF_REACH
                if heard:
                    detail += "\nListening on " + ", ".join(
                        f"{kind} {port}" for kind, port in heard)
        slot = grouped.get(name)
        if slot is None:
            grouped[name] = Entry(name, value, [pid], detail)
        else:
            slot.value += value
            slot.pids.append(pid)
            if detail and not slot.detail:
                # A group can be part readable and part out of reach; the
                # note must not depend on which pid came back first.
                slot.detail = detail
        contrib.setdefault(name, []).append((value, pid))
    entries = [e for e in grouped.values() if e.value >= threshold]
    entries.sort(key=lambda e: e.value, reverse=True)
    _name_services(entries, contrib, kind)
    return entries


# --- memory ----------------------------------------------------------------

def ram_entries():
    """System memory per executable.

    Working set, which is what Task Manager's own list is closest to.
    Summing it across the processes of one app slightly over-counts pages
    they share, and that is the right error to make here: the alternative
    (USS) means opening every process one by one and costs an order of
    magnitude more time for a number that barely moves the ranking.
    """
    rows = working_sets()
    if rows is not None:
        raw = {pid: ws for pid, _, ws in rows}
        names = {pid: name for pid, name, _ in rows}
        return _collect(raw, names, HIDE_BELOW_BYTES, KIND_RAM)

    # Fallback for a Windows that no longer answers the NT call the same
    # way. Correct, just ~90x slower (1574 ms against 17 on this machine),
    # which is why it is not the first choice.
    if psutil is None:
        return []
    raw = {}
    names = {}
    for proc in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            info = proc.info["memory_info"]
            if info is None:
                continue
            pid = proc.info["pid"]
            raw[pid] = info.rss
            names[pid] = proc.info["name"] or "?"
        except Exception:
            continue
    return _collect(raw, names, HIDE_BELOW_BYTES, KIND_RAM)


def vram_entries(pdh):
    """Video memory per executable, from the counter that adds up.

    `Dedicated Usage` is the obvious choice and it is wrong: it counts
    address space a process has committed, not what is resident, and on
    this machine it summed to 46 GB against an adapter really using 5.6.
    `Local Usage` is memory actually resident in the adapter, and sums to
    just under the adapter's own figure — the gap being driver and kernel
    allocations that belong to no process.
    """
    if pdh is None or not pdh.ok:
        return []
    return _collect(pdh.per_process(), None, HIDE_BELOW_BYTES, KIND_VRAM)


# --- usage ------------------------------------------------------------------

def gpu_entries(pdh):
    """GPU utilisation per executable, on the card's own scale.

    Aggregated exactly as the whole-adapter figure is: within one process,
    sum its instances per engine type and take the busiest type. Adding
    the types together would let one process report 130%.
    """
    if pdh is None or not pdh.ok:
        return []
    return _collect(pdh.per_process_util(), None, HIDE_BELOW_PERCENT,
                    KIND_GPU)


def cpu_sample():
    """(monotonic seconds, {pid: cpu_100ns}, {pid: name}) or None.

    CPU time is a running total, so a percentage needs two of these.
    """
    rows = snapshot()
    if rows is None:
        return None
    import time
    return (time.monotonic(),
            {pid: cpu for pid, _, _, cpu in rows},
            {pid: name for pid, name, _, _ in rows})


def cpu_entries(before, after):
    """Percentage of the whole machine, per executable, between two
    cpu_sample() readings.

    Divided by the core count, so the rows are on the same scale as the
    card's own CPU meter and add up to roughly it — not to per-core
    percentages, where one busy thread would read 100 on a 32-thread box.
    """
    if not before or not after:
        return []
    elapsed = after[0] - before[0]
    if elapsed <= 0:
        return []
    cores = os.cpu_count() or 1
    span = elapsed * cores * _TICKS_PER_SECOND
    previous = before[1]
    raw = {}
    for pid, ticks in after[1].items():
        was = previous.get(pid)
        if was is None:
            continue        # started since the last reading; no baseline yet
        used = ticks - was
        if used > 0:
            raw[pid] = used / span * 100.0
    return _collect(raw, after[2], HIDE_BELOW_PERCENT, KIND_CPU)


# --- everything knowable about one row ---------------------------------------

DETAIL_PIDS = 12        # past this the window is a wall rather than an answer


def details(entry, kind):
    """The long answer behind a row, for the right-click "Show details".

    Deliberately says what it could *not* find as well as what it could:
    the whole point of this window is that the row's one line was not
    enough, and a blank where the command line should be is a worse
    answer than a sentence explaining why there isn't one.
    """
    ports = listening_ports()
    titles = window_titles()
    services = services_by_pid()
    host = _tidy(entry.name.split(" (")[-1].rstrip(")")).lower() \
        if "(" in entry.name else entry.name.lower()

    out = [f"{entry.name}    {fmt_value(kind, entry.value)}",
           f"{len(entry.pids)} process" + ("es" if len(entry.pids) != 1 else ""),
           ""]

    for pid in entry.pids[:DETAIL_PIDS]:
        out.append(f"pid {pid}")
        path = image_path(pid)
        out.append(f"    image      {path or 'unavailable'}")

        argv = command_line(pid)
        if argv:
            out.append(f"    command    {' '.join(argv)}")
            if host in MODEL_HOSTS:
                model = _model_of(argv)
                if model:
                    named = ollama_names().get(os.path.basename(model))
                    out.append(f"    model      {named or model}")
        elif denied(pid):
            out.append("    command    unavailable -- runs with more "
                       "privilege than the monitor")
        else:
            out.append("    command    unavailable")

        heard = ports.get(pid)
        if heard:
            out.append("    listening  " + ", ".join(
                f"{proto} {port}" for proto, port in heard))
        window = titles.get(pid)
        if window:
            out.append(f"    window     {window[0]}")
        running = services.get(pid)
        if running:
            out.append("    services   " + ", ".join(running))
        out.append("")

    left = len(entry.pids) - DETAIL_PIDS
    if left > 0:
        out.append(f"and {left} more process" + ("es" if left != 1 else ""))

    if host in MODEL_HOSTS:
        # Asked over HTTP, which no privilege boundary applies to. Kept
        # apart from the per-process block above and labelled with its
        # source, because it is what Ollama says it holds -- not something
        # any of these pids has been proven to be.
        held = ollama_loaded()
        if held:
            out.append("")
            out.append("Ollama reports loaded:")
            for model, resident in held:
                out.append(f"    {model}"
                           + (f"    {fmt_bytes(resident)}" if resident else ""))
    return "\n".join(out).rstrip()


# --- formatting -------------------------------------------------------------

def fmt_bytes(size):
    """The card's own idiom: a decimal below 10, none above."""
    gb = size / (1024.0 ** 3)
    if gb >= 10:
        return f"{gb:.0f} GB"
    if gb >= 1:
        return f"{gb:.1f} GB"
    return f"{size / (1024.0 ** 2):.0f} MB"


def fmt_value(kind, value):
    if kind in MEMORY_KINDS:
        return fmt_bytes(value)
    return f"{value:.0f}%" if value >= 10 else f"{value:.1f}%"


def fmt_threshold(kind):
    """How the panel words what it is leaving out."""
    if kind in MEMORY_KINDS:
        return fmt_bytes(HIDE_BELOW_BYTES)
    return f"{HIDE_BELOW_PERCENT:.0f}%"


# --- ending things ----------------------------------------------------------

def terminate(pids):
    """Kill these processes. Returns (ended, failed, skipped).

    Nothing graceful is attempted: on Windows there is no polite way to
    ask an arbitrary process to quit that does not involve posting to its
    windows and waiting, and this is the same thing Task Manager's "End
    task" does. Protected names never get this far — the UI does not let
    them be selected — and our own process is refused here as well, since
    a list that offers to kill the monitor showing it is a trap.
    """
    if psutil is None:
        return 0, 0, 0
    ended = failed = skipped = 0
    me = os.getpid()
    for pid in pids:
        if pid == me:
            skipped += 1
            continue
        try:
            proc = psutil.Process(pid)
            try:
                # rstrip(".exe") strips characters, not the suffix:
                # it would turn "chrome.exe" into "chrom"
                name = _tidy(proc.name()).lower()
            except psutil.AccessDenied:
                # A process we are not even allowed to name is one of
                # Windows' own. Refusing is the safe reading, and it
                # reports as skipped rather than as a failure the user
                # could fix by running as admin -- they should not.
                skipped += 1
                continue
            if name in PROTECTED:
                skipped += 1
                continue
            proc.terminate()
            ended += 1
        except psutil.NoSuchProcess:
            ended += 1          # already gone is the outcome we wanted
        except Exception as exc:
            log.info("could not end pid %s: %s", pid, exc)
            failed += 1
    return ended, failed, skipped
