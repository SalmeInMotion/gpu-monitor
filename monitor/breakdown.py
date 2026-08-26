"""Who is using it: the per-process breakdown behind each meter.

Double-clicking VRAM, RAM, GPU usage or CPU asks for one of these. The
kind is the metric's own key, so there is one vocabulary and no mapping
to keep in step.

Entries are grouped by executable, because one browser is fifty processes
and a list of fifty "msedge.exe" rows answers nothing, and anything under
the kind's threshold is left out: the question is "what do I close", and
a 40 MB or 0.2% process is never the answer. Ivan set both thresholds —
512 MB for the memory meters, 5% for the usage ones.

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

from .winproc import snapshot, working_sets

# The metric keys from metrics.py; `Metric.breakdown` just says whether a
# row has one, and the kind is the key itself.
KIND_VRAM = "vram"
KIND_RAM = "ram"
KIND_GPU = "gpu"
KIND_CPU = "cpu"

MEMORY_KINDS = frozenset({KIND_VRAM, KIND_RAM})
USAGE_KINDS = frozenset({KIND_GPU, KIND_CPU})

HIDE_BELOW_BYTES = 512 * 1024 * 1024
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

    __slots__ = ("name", "value", "pids")

    def __init__(self, name, value, pids):
        self.name = name
        self.value = value
        self.pids = list(pids)

    @property
    def protected(self):
        return self.name.lower() in PROTECTED

    def __repr__(self):
        return f"<Entry {self.name} {self.value:.1f} x{len(self.pids)}>"


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


def _collect(raw, names=None, threshold=HIDE_BELOW_BYTES):
    """{pid: value} -> the sorted, filtered, grouped-by-executable list."""
    if names is None:
        names = name_map()
    grouped = {}
    for pid, value in raw.items():
        if value <= 0:
            continue
        raw_name = names.get(pid)
        # Exited between the reading and now, or not ours to look at. It
        # is still real usage, so it goes in one bucket rather than being
        # dropped from a total the bar is showing.
        name = _tidy(raw_name) if raw_name else "(other)"
        slot = grouped.get(name)
        if slot is None:
            grouped[name] = Entry(name, value, [pid])
        else:
            slot.value += value
            slot.pids.append(pid)
    entries = [e for e in grouped.values() if e.value >= threshold]
    entries.sort(key=lambda e: e.value, reverse=True)
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
        return _collect(raw, names, HIDE_BELOW_BYTES)

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
    return _collect(raw, names, HIDE_BELOW_BYTES)


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
    return _collect(pdh.per_process(), None, HIDE_BELOW_BYTES)


# --- usage ------------------------------------------------------------------

def gpu_entries(pdh):
    """GPU utilisation per executable, on the card's own scale.

    Aggregated exactly as the whole-adapter figure is: within one process,
    sum its instances per engine type and take the busiest type. Adding
    the types together would let one process report 130%.
    """
    if pdh is None or not pdh.ok:
        return []
    return _collect(pdh.per_process_util(), None, HIDE_BELOW_PERCENT)


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
    return _collect(raw, after[2], HIDE_BELOW_PERCENT)


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
