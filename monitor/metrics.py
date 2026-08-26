"""The metric registry: what the monitor can show, and how each reads.

Every row in the overlay is one entry here. A metric knows how to turn a
raw sample (see sampler.py) into the three things the ia-usage row layout
needs: a value on the right, a 0..1 fraction for the bar, and a caption
underneath. Adding a metric means adding one METRICS entry — the overlay,
the preferences list and the settings defaults all read from this table.

Fractions are honest: a metric only gets a bar when it has a real
denominator (used/total, draw/limit, current/max). Temperature borrows
nvidia-smi's own thermal headroom for its ceiling, see gpu_temp_max().
"""

from __future__ import annotations

# Groups, in display order. The GPU header takes the adapter's own name at
# runtime (like ia-usage puts "Claude" over Claude's bars).
GROUP_GPU = "gpu"
GROUP_SYSTEM = "system"

GROUP_ORDER = (GROUP_GPU, GROUP_SYSTEM)
GROUP_LABELS = {GROUP_GPU: "GPU", GROUP_SYSTEM: "System"}

# How a metric's bar is coloured. QUOTA gets ia-usage's green -> amber ->
# red bands, because filling it up really is the problem. LOAD gets the
# flat accent: a GPU pinned at 98% is doing its job, and painting that red
# is how a user learns to ignore red.
RAMP_QUOTA = "quota"
RAMP_LOAD = "load"

# Fallback thermal ceiling when the driver does not report headroom.
# 90 C is where consumer GeForce parts start their thermal slowdown.
TEMP_CEILING_FALLBACK = 90.0
TEMP_FLOOR = 30.0

_GB = 1024.0


def _fmt_gb(mib):
    """MiB -> a compact GB string. Below 10 GB a decimal still carries
    information; above it, it is noise on a 1 Hz readout."""
    gb = mib / 1024.0
    return f"{gb:.1f}" if gb < 10 else f"{gb:.0f}"


def gpu_temp_max(sample):
    """The temperature this GPU actually throttles at.

    nvidia-smi's temperature.gpu.tlimit is not a temperature: it is the
    number of degrees still left before the thermal limit kicks in. So
    the limit itself is current + tlimit, which is exact per board
    instead of a guessed constant. Falls back to a fixed ceiling when the
    field is unsupported (older drivers, some datacenter parts report
    N/A).
    """
    temp = sample.get("temp")
    tlimit = sample.get("temp_tlimit")
    if temp is not None and tlimit is not None:
        ceiling = temp + tlimit
        # A tlimit of 0 (already throttling) would pin the bar at 100%,
        # which is correct; a nonsense sub-floor value would not.
        if ceiling >= TEMP_FLOOR + 10:
            return ceiling
    return TEMP_CEILING_FALLBACK


class Metric:
    """One readable line of the overlay.

    fraction/value/caption each take the whole sample dict rather than a
    single number, because several rows are a ratio of two fields and one
    (temperature) needs a denominator computed from a third.
    """

    def __init__(self, key, label, group, fraction, value, caption=None,
                 default=True, needs=(), ramp=RAMP_LOAD, breakdown=None):
        self.key = key
        self.label = label
        self.group = group
        self._fraction = fraction
        self._value = value
        self._caption = caption
        self.default = default
        self.ramp = ramp
        # "gpu" / "ram" for the two meters whose bar can be clicked to see
        # which processes are holding that memory; None for the rest.
        self.breakdown = breakdown
        # sample keys that must be non-None for this row to have data
        self.needs = tuple(needs)

    def available(self, sample):
        return all(sample.get(k) is not None for k in self.needs)

    def fraction(self, sample):
        """0..1 for the bar, or None for a row that has no meaningful
        denominator (drawn as a value with no bar)."""
        if not self.available(sample):
            return None
        return self._fraction(sample)

    def value(self, sample):
        if not self.available(sample):
            return "--"
        return self._value(sample)

    def caption(self, sample):
        if self._caption is None or not self.available(sample):
            return ""
        return self._caption(sample)


def _clamp01(v):
    return 0.0 if v < 0 else (1.0 if v > 1 else v)


METRICS = (
    Metric(
        "vram", "VRAM", GROUP_GPU,
        fraction=lambda s: _clamp01(s["mem_used"] / s["mem_total"]),
        value=lambda s: f"{s['mem_used'] / s['mem_total'] * 100:.0f}%",
        caption=lambda s: (f"{_fmt_gb(s['mem_used'])} / "
                           f"{_fmt_gb(s['mem_total'])} GB"),
        needs=("mem_used", "mem_total"),
        ramp=RAMP_QUOTA,
        breakdown="gpu",
    ),
    Metric(
        "gpu", "GPU usage", GROUP_GPU,
        fraction=lambda s: _clamp01(s["util"] / 100.0),
        value=lambda s: f"{s['util']:.0f}%",
        caption=lambda s: (f"{s['clock']:.0f} MHz" if s.get("clock") else ""),
        needs=("util",),
    ),
    Metric(
        "temp", "Temperature", GROUP_GPU,
        fraction=lambda s: _clamp01(
            (s["temp"] - TEMP_FLOOR) / max(1.0, gpu_temp_max(s) - TEMP_FLOOR)),
        value=lambda s: f"{s['temp']:.0f}°C",
        caption=lambda s: f"throttles at {gpu_temp_max(s):.0f}°C",
        needs=("temp",),
        ramp=RAMP_QUOTA,
    ),
    Metric(
        "power", "Power", GROUP_GPU,
        fraction=lambda s: _clamp01(s["power"] / s["power_limit"]),
        value=lambda s: f"{s['power']:.0f} W",
        caption=lambda s: f"limit {s['power_limit']:.0f} W",
        needs=("power", "power_limit"),
    ),
    Metric(
        "fan", "Fan", GROUP_GPU,
        fraction=lambda s: _clamp01(s["fan"] / 100.0),
        value=lambda s: f"{s['fan']:.0f}%",
        default=False,
        needs=("fan",),
    ),
    Metric(
        "clock", "Core clock", GROUP_GPU,
        fraction=lambda s: _clamp01(s["clock"] / s["clock_max"]),
        value=lambda s: f"{s['clock']:.0f} MHz",
        caption=lambda s: f"max {s['clock_max']:.0f} MHz",
        default=False,
        needs=("clock", "clock_max"),
    ),
    Metric(
        "cpu", "CPU", GROUP_SYSTEM,
        fraction=lambda s: _clamp01(s["cpu"] / 100.0),
        value=lambda s: f"{s['cpu']:.0f}%",
        caption=lambda s: (f"{s['cpu_freq'] / 1000:.1f} GHz"
                           if s.get("cpu_freq") else ""),
        needs=("cpu",),
    ),
    Metric(
        "ram", "RAM", GROUP_SYSTEM,
        fraction=lambda s: _clamp01(s["ram_used"] / s["ram_total"]),
        value=lambda s: f"{s['ram_used'] / s['ram_total'] * 100:.0f}%",
        caption=lambda s: (f"{_fmt_gb(s['ram_used'])} / "
                           f"{_fmt_gb(s['ram_total'])} GB"),
        needs=("ram_used", "ram_total"),
        ramp=RAMP_QUOTA,
        breakdown="ram",
    ),
)

BY_KEY = {m.key: m for m in METRICS}
METRIC_KEYS = tuple(m.key for m in METRICS)

# What settings.json starts with, and what a missing key falls back to.
DEFAULT_SHOW = {m.key: m.default for m in METRICS}


def metrics_in(group):
    return tuple(m for m in METRICS if m.group == group)
