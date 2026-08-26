"""Who is holding the memory: per-process breakdowns for the two bars.

Clicking the VRAM or RAM meter asks for one of these. Entries are grouped
by executable, because one browser is fifty processes and a list of fifty
"msedge.exe" rows answers nothing, and anything under HIDE_BELOW is left
out: the question is "what do I close", and a 40 MB process is never the
answer.

No Qt in here on purpose — this runs on the sampler thread, and walking a
few hundred processes takes long enough (50-150 ms) to stutter the card
if it ran on the UI one.
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

from .winproc import working_sets

KIND_GPU = "gpu"
KIND_RAM = "ram"

# Ivan's threshold: below this a process is not what is eating the memory.
HIDE_BELOW = 512 * 1024 * 1024

# Killing any of these takes Windows down with it, so they are listed but
# never selectable. Names are lowercase, without the .exe.
PROTECTED = frozenset({
    # Windows itself. Ending any of these blue-screens or blanks the
    # session, so they are listed -- they really are holding memory --
    # but can never be selected.
    "system", "system idle process", "secure system", "registry",
    "memory compression",   # NT's name for it
    "memcompression",       # psutil's name for the same process
    "smss", "csrss", "wininit", "winlogon",
    "services", "lsass", "lsaiso", "fontdrvhost", "svchost",
    "dwm",                  # the compositor: killing it blanks every window
    "audiodg", "wudfhost", "sihost", "ctfmon",
})

# Instance names look like:
#   pid_8644_luid_0x00000000_0x00014A29_phys_0
_PROC_INSTANCE = re.compile(r"pid_(\d+)_luid_(\S+?)_phys")


class Entry:
    """One executable, and every process of it that holds memory."""

    __slots__ = ("name", "bytes", "pids")

    def __init__(self, name, size, pids):
        self.name = name
        self.bytes = size
        self.pids = list(pids)

    @property
    def protected(self):
        return self.name.lower() in PROTECTED

    def __repr__(self):
        return f"<Entry {self.name} {self.bytes / 1024 ** 2:.0f}MiB x{len(self.pids)}>"


def _tidy(name):
    """"msedge.exe" -> "msedge". The extension is the same on every row."""
    return name[:-4] if name.lower().endswith(".exe") else name


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


def _collect(raw, names=None):
    """{pid: bytes} -> the sorted, filtered, grouped-by-executable list."""
    if psutil is None:
        return []
    if names is None:
        names = name_map()
    grouped = {}
    for pid, size in raw.items():
        if size <= 0:
            continue
        raw_name = names.get(pid)
        # Exited between the counter read and now, or not ours to look at.
        # Its memory is still real, so it goes in one bucket rather than
        # being dropped from a total the bar is showing.
        name = _tidy(raw_name) if raw_name else "(other)"
        slot = grouped.get(name)
        if slot is None:
            grouped[name] = Entry(name, size, [pid])
        else:
            slot.bytes += size
            slot.pids.append(pid)
    entries = [e for e in grouped.values() if e.bytes >= HIDE_BELOW]
    entries.sort(key=lambda e: e.bytes, reverse=True)
    return entries


def ram_entries():
    """System memory per executable.

    Working set, which is what Task Manager's own list is closest to.
    Summing it across the processes of one app slightly over-counts pages
    they share, and that is the right error to make here: the alternative
    (USS) means opening every process one by one and costs an order of
    magnitude more time for a number that moves the ranking barely at all.
    """
    rows = working_sets()
    if rows is not None:
        raw = {pid: ws for pid, _, ws in rows}
        names = {pid: name for pid, name, _ in rows}
        return _collect(raw, names)

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
    return _collect(raw, names)


def gpu_entries(pdh):
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
    return _collect(pdh.per_process())


def entries_for(kind, pdh=None):
    return gpu_entries(pdh) if kind == KIND_GPU else ram_entries()


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


def fmt_bytes(size):
    """The card's own idiom: a decimal below 10, none above."""
    gb = size / (1024.0 ** 3)
    if gb >= 10:
        return f"{gb:.0f} GB"
    if gb >= 1:
        return f"{gb:.1f} GB"
    return f"{size / (1024.0 ** 2):.0f} MB"
