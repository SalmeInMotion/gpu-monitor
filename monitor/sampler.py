"""Data source: one nvidia-smi call plus psutil, off the UI thread.

Runs on its own QThread and emits a plain dict; the overlay never blocks
on a subprocess. Every field is Optional — a missing driver, a laptop
without an NVIDIA GPU, or a field the board does not report all arrive
here as None and the affected rows fall back to "--" instead of
disappearing (see metrics.Metric.available).

nvidia-smi is spawned once per tick rather than kept alive in `-l` loop
mode: the loop process saves the ~50ms spawn but has to be babysat
(buffering, respawn after a driver reset, orphaning on a force-kill) for
a cost that is invisible at 1 Hz. The previous tkinter version did the
same and never showed up in a profile.
"""

from __future__ import annotations

import logging
import os
import subprocess

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal

from . import breakdown as bd
from .gpu_pdh import PdhGpu

log = logging.getLogger("gpu_monitor.sampler")

# Keeps a console window from flashing on every tick under pythonw.
_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

# nvidia-smi answers in ASCII, so this is prophylactic rather than a live fix:
# it keeps the tool out of the locale-decoding trap the media tools fell into.
# Under capture_output a decode error dies on a reader thread instead of
# raising, leaving stderr=None -- and the error path below calls .stderr.strip().
_TEXT_IO = {"text": True, "encoding": "utf-8", "errors": "replace"}

# Only supported since driver R535; see the retry in query_gpu.
_OPTIONAL = "temperature.gpu.tlimit"

# Order matters: it is the order the CSV columns come back in.
_FIELDS = (
    "name",
    "memory.used",
    "memory.total",
    "utilization.gpu",
    "temperature.gpu",
    "temperature.gpu.tlimit",
    "power.draw",
    "power.limit",
    "fan.speed",
    "clocks.gr",
    "clocks.max.gr",
)

# CSV column -> sample key. Column 0 (name) is handled separately since it
# is the only non-numeric one.
_NUMERIC_KEYS = (
    "mem_used", "mem_total", "util", "temp", "temp_tlimit",
    "power", "power_limit", "fan", "clock", "clock_max",
)

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:  # pragma: no cover - depends on the machine
    HAS_PSUTIL = False
    log.warning("psutil not installed: CPU and RAM rows will read '--'")


def _num(text):
    """nvidia-smi writes '[N/A]', '[Not Supported]' and friends for fields
    a board does not expose; all of them must read as absent, not zero."""
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _run_smi(fields):
    try:
        return subprocess.run(
            ["nvidia-smi", "--query-gpu=" + ",".join(fields),
             "--format=csv,noheader,nounits"],
            capture_output=True, timeout=4,
            creationflags=_CREATE_NO_WINDOW, **_TEXT_IO,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("nvidia-smi unavailable: %s", exc)
        return None


def query_gpu(index=0):
    """One sample of the GPU at `index`, or an all-None dict if nvidia-smi
    is missing, fails, or reports fewer GPUs than that."""
    blank = {k: None for k in _NUMERIC_KEYS}
    blank["gpu_name"] = None

    fields = _FIELDS
    out = _run_smi(fields)
    if out is not None and out.returncode != 0 and _OPTIONAL in fields:
        # nvidia-smi rejects an unknown field by name and exits non-zero
        # without printing any of the others, so one field added in a
        # recent driver takes the whole GPU block down on an older one
        # (temperature.gpu.tlimit arrived in R535). Drop it and retry;
        # metrics.gpu_temp_max already has a fallback ceiling for a
        # missing headroom reading.
        log.debug("retrying nvidia-smi without %s", _OPTIONAL)
        fields = tuple(f for f in _FIELDS if f != _OPTIONAL)
        out = _run_smi(fields)

    if out is None:
        return blank
    if out.returncode != 0:
        log.debug("nvidia-smi exit %s: %s", out.returncode, out.stderr.strip())
        return blank

    lines = [ln for ln in out.stdout.splitlines() if ln.strip()]
    if index >= len(lines):
        return blank

    parts = [p.strip() for p in lines[index].split(",")]
    if len(parts) < len(fields):
        log.debug("unexpected nvidia-smi output: %r", lines[index])
        return blank

    keys = [k for f, k in zip(_FIELDS[1:], _NUMERIC_KEYS) if f in fields]
    sample = dict(blank)
    sample.update(zip(keys, (_num(p) for p in parts[1:])))
    # "NVIDIA GeForce RTX 5090" -> "RTX 5090": the vendor words are the
    # same on every row and only eat width in a 300px card.
    name = parts[0]
    for prefix in ("NVIDIA GeForce ", "NVIDIA "):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    sample["gpu_name"] = name or None
    return sample


def query_system():
    """CPU and RAM. cpu_percent(interval=None) is the non-blocking form:
    it reports the load since the previous call, which is exactly one
    tick, so the sampler must have primed it once at startup."""
    if not HAS_PSUTIL:
        return {"cpu": None, "cpu_freq": None,
                "ram_used": None, "ram_total": None}
    out = {}
    try:
        out["cpu"] = psutil.cpu_percent(interval=None)
    except Exception as exc:  # psutil raises OS-specific errors
        log.debug("cpu_percent failed: %s", exc)
        out["cpu"] = None
    try:
        freq = psutil.cpu_freq()
        out["cpu_freq"] = freq.current if freq else None
    except Exception:
        # cpu_freq is not available on every Windows machine and is the
        # one field here that is decoration, not a metric.
        out["cpu_freq"] = None
    try:
        vm = psutil.virtual_memory()
        # MiB throughout, so the formatters in metrics.py have one unit.
        out["ram_used"] = vm.used / (1024.0 ** 2)
        out["ram_total"] = vm.total / (1024.0 ** 2)
    except Exception as exc:
        log.debug("virtual_memory failed: %s", exc)
        out["ram_used"] = out["ram_total"] = None
    return out


class SamplerWorker(QObject):
    """Lives on the sampler thread; owns the timer that drives polling."""

    sampled = Signal(dict)
    # (kind, [breakdown.Entry, ...]) -- computed here rather than on the UI
    # thread because walking the process table is milliseconds, not
    # microseconds, and the card animates at 60fps while it happens.
    breakdown = Signal(str, list)

    def __init__(self, interval_ms, gpu_index=0):
        super().__init__()
        self._interval_ms = interval_ms
        self._gpu_index = gpu_index
        self._timer = None
        # nvidia-smi is preferred because it is the only source for
        # temperature, power, fan and clocks; Windows' own counters are
        # the fallback on an AMD or Intel GPU, where they are all there is.
        self._use_nvidia = True
        self._pdh = None
        # CPU time is a running total, so a percentage needs two readings.
        # Kept between requests, so the second and later refreshes are a
        # straight difference over the panel's own 2s cadence.
        self._cpu_prev = None

    def start(self):
        if HAS_PSUTIL:
            try:
                psutil.cpu_percent(interval=None)  # prime the delta
            except Exception:
                pass
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._timer.start(self._interval_ms)
        self._tick()  # don't make the card wait a whole interval to fill in

    def set_interval(self, interval_ms):
        self._interval_ms = interval_ms
        if self._timer is not None:
            self._timer.start(interval_ms)

    def compute_breakdown(self, kind):
        """Answer one request for "who is holding this memory"."""
        try:
            if kind == bd.KIND_VRAM:
                entries = bd.vram_entries(self._ensure_pdh())
            elif kind == bd.KIND_GPU:
                entries = bd.gpu_entries(self._ensure_pdh())
            elif kind == bd.KIND_CPU:
                entries = self._cpu_breakdown()
            else:
                entries = bd.ram_entries()
        except Exception as exc:            # never take the thread down
            log.warning("breakdown(%s) failed: %s", kind, exc)
            entries = []
        self.breakdown.emit(kind, entries)

    def _cpu_breakdown(self):
        """Two readings of the process table, differenced.

        With no usable baseline the first request pays for one here: a
        300ms wait on *this* thread, which delays a card tick and nothing
        the user is looking at. Every later refresh differences against
        the previous request instead, over the panel's own 2s cadence.
        """
        now = bd.cpu_sample()
        if now is None:
            return []
        previous = self._cpu_prev
        if previous is None or (now[0] - previous[0]) > 10.0:
            import time
            previous = now
            time.sleep(0.30)
            now = bd.cpu_sample()
            if now is None:
                return []
        self._cpu_prev = now
        return bd.cpu_entries(previous, now)

    def _ensure_pdh(self):
        """The counters, opened on demand.

        On an NVIDIA machine nothing else needs them -- nvidia-smi feeds
        the card -- so opening a PDH query at startup there would be pure
        cost. The first click on the VRAM bar is what pays for it.
        """
        if self._pdh is None:
            self._pdh = PdhGpu()
        return self._pdh

    def shutdown(self):
        if self._timer is not None:
            self._timer.stop()
        if self._pdh is not None:
            self._pdh.close()
            self._pdh = None

    def _tick(self):
        sample = self._gpu()
        sample.update(query_system())
        self.sampled.emit(sample)

    def _gpu(self):
        if self._use_nvidia:
            sample = query_gpu(self._gpu_index)
            if sample.get("mem_total") is not None:
                sample["gpu_source"] = "nvidia-smi"
                return sample
            # Blank on the first try means no NVIDIA driver here; there is
            # no point paying for a failed process spawn every second for
            # the rest of the session.
            log.info("nvidia-smi returned nothing; using Windows GPU counters")
            self._use_nvidia = False

        self._ensure_pdh()
        blank = {k: None for k in _NUMERIC_KEYS}
        blank["gpu_name"] = None
        blank.update(self._pdh.sample())
        blank["gpu_source"] = "windows-counters" if self._pdh.ok else None
        return blank


class Sampler(QObject):
    """UI-side handle: owns the thread, re-emits samples on the UI thread.

    Qt delivers a signal across threads as a queued connection, so slots
    connected to `sampled` run on the UI thread and may touch widgets.
    """

    sampled = Signal(dict)
    breakdown = Signal(str, list)

    def __init__(self, interval_ms=1000, gpu_index=0, parent=None):
        super().__init__(parent)
        self._thread = QThread()
        self._thread.setObjectName("sampler")
        self._worker = SamplerWorker(interval_ms, gpu_index)
        self._worker.moveToThread(self._thread)
        self._worker.sampled.connect(self.sampled)
        self._worker.breakdown.connect(self.breakdown)
        self._thread.started.connect(self._worker.start)
        self._thread.finished.connect(self._worker.shutdown)

    def start(self):
        self._thread.start()

    def set_interval(self, interval_ms):
        # Queued: the timer belongs to the sampler thread and must be
        # restarted there, never from the UI thread.
        QTimer.singleShot(0, self._worker,
                          lambda: self._worker.set_interval(interval_ms))

    def request_breakdown(self, kind):
        """Ask for a breakdown; it arrives on the `breakdown` signal.

        Queued into the sampler thread, like set_interval: the work must
        not happen here, and the reply crosses back as a queued signal.
        """
        QTimer.singleShot(0, self._worker,
                          lambda: self._worker.compute_breakdown(kind))

    def stop(self):
        self._thread.quit()
        # quit() only unwinds the event loop once the tick in flight
        # returns, and a tick can legitimately take ~4s: query_gpu gives
        # nvidia-smi that long, and on timeout subprocess.run then kills
        # and reaps the child. Returning from a too-short wait leaves the
        # thread running, and ~QThread aborts the whole process when it
        # is destroyed in that state (measured: exit 0xC0000409, a silent
        # WER crash under pythonw).
        if not self._thread.wait(10000):
            log.warning("sampler thread did not stop; terminating")
            self._thread.terminate()
            self._thread.wait(2000)
