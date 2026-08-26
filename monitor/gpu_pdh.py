"""Vendor-neutral GPU readings from Windows' own performance counters.

nvidia-smi is the better source when it exists — it is the only one that
reports temperature, power, fan and clocks. But it only exists on NVIDIA.
This backend reads the counters the Windows graphics kernel publishes for
*every* adapter, which is where Task Manager's own GPU figures come from,
so an AMD or Intel machine gets utilisation and video memory instead of
an empty card.

What it can and cannot do:

* utilisation  -- yes, per engine, aggregated the way Task Manager does it
* video memory -- yes, used; the total comes from the driver's registry key
* temperature, power, fan, clocks -- no. Windows publishes none of them;
  they need a vendor library (NVML, ADL) and are simply absent here.

Talks to PDH through ctypes rather than pywin32 so the app keeps its two
dependencies. The query is opened once and kept: utilisation is a rate
counter, so it needs two collections to mean anything, and reopening it
every second would make every reading zero.
"""

from __future__ import annotations

import ctypes
import logging
import re
from ctypes import wintypes

log = logging.getLogger("gpu_monitor.pdh")

# --- PDH -------------------------------------------------------------------

PDH_FMT_DOUBLE = 0x00000200
PDH_MORE_DATA = 0x800007D2
ERROR_SUCCESS = 0

# Wildcard instance paths. PdhAddCounter accepts (*) and
# PdhGetFormattedCounterArray then returns every matching instance, which
# is far cheaper than expanding the wildcard ourselves each tick.
COUNTER_ENGINE = r"\GPU Engine(*)\Utilization Percentage"
COUNTER_ADAPTER_MEM = r"\GPU Adapter Memory(*)\Dedicated Usage"
COUNTER_PROCESS_MEM = r"\GPU Process Memory(*)\Dedicated Usage"
# Per-process VRAM. NOT "Dedicated Usage", which counts committed address
# space: on this machine it summed to 46 GB while the adapter really held
# 5.6. "Local Usage" is memory resident in the adapter and sums to just
# under the adapter's own figure, the gap being driver allocations that
# belong to no process.
COUNTER_PROCESS_LOCAL = r"\GPU Process Memory(*)\Local Usage"

# "pid_8644_luid_0x00000000_0x00014A29_phys_0"
_INSTANCE = re.compile(r"(?:pid_(\d+)_)?luid_(\S+?)_phys")
# ..._phys_0_eng_0_engtype_3d -- the engine counter carries a type too
_ENGINE_INSTANCE = re.compile(
    r"pid_(\d+)_luid_(\S+?)_phys_\d+_eng_\d+_engtype_(\w+)")

# "pid_1956_luid_0x00000000_0x0000e9bf_phys_0_eng_0_engtype_3d"
_ENGTYPE = re.compile(r"engtype_(\w+)$")


class _VALUE(ctypes.Union):
    _fields_ = [
        ("longValue", ctypes.c_long),
        ("doubleValue", ctypes.c_double),
        ("largeValue", ctypes.c_longlong),
        ("AnsiStringValue", ctypes.c_char_p),
        ("WideStringValue", ctypes.c_wchar_p),
    ]


class PDH_FMT_COUNTERVALUE(ctypes.Structure):
    # ctypes inserts the 4 bytes of padding this needs on x64 by itself,
    # because the union is 8-byte aligned. Do not add an explicit pad.
    _fields_ = [("CStatus", wintypes.DWORD), ("value", _VALUE)]


class PDH_FMT_COUNTERVALUE_ITEM_W(ctypes.Structure):
    _fields_ = [("szName", wintypes.LPWSTR),
                ("FmtValue", PDH_FMT_COUNTERVALUE)]


try:
    _pdh = ctypes.WinDLL("pdh.dll")
except OSError:  # pragma: no cover - not Windows
    _pdh = None


def _declare(dll):
    """Give every PDH entry point a signature.

    Without a restype, ctypes hands back a *signed* 32-bit int, so
    PDH_MORE_DATA (0x800007D2) arrives as -2147481134 and every
    `status != PDH_MORE_DATA` test is wrong -- which read as "this
    machine has no GPU counters" on a machine with 869 of them.
    DWORD_PTR is pointer-sized, so it must be c_size_t, not DWORD.
    """
    status = ctypes.c_ulong
    dll.PdhOpenQueryW.restype = status
    dll.PdhOpenQueryW.argtypes = [wintypes.LPCWSTR, ctypes.c_size_t,
                                  ctypes.POINTER(wintypes.HANDLE)]
    dll.PdhAddEnglishCounterW.restype = status
    dll.PdhAddEnglishCounterW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR,
                                          ctypes.c_size_t,
                                          ctypes.POINTER(wintypes.HANDLE)]
    dll.PdhCollectQueryData.restype = status
    dll.PdhCollectQueryData.argtypes = [wintypes.HANDLE]
    dll.PdhGetFormattedCounterArrayW.restype = status
    dll.PdhGetFormattedCounterArrayW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    dll.PdhCloseQuery.restype = status
    dll.PdhCloseQuery.argtypes = [wintypes.HANDLE]


if _pdh is not None:
    _declare(_pdh)


class _Query:
    """One open PDH query with a set of wildcard counters."""

    def __init__(self):
        self.handle = wintypes.HANDLE()
        self.counters = {}
        if _pdh is None:
            raise OSError("pdh.dll unavailable")
        status = _pdh.PdhOpenQueryW(None, 0, ctypes.byref(self.handle))
        if status != ERROR_SUCCESS:
            raise OSError(f"PdhOpenQuery failed: 0x{status & 0xFFFFFFFF:08X}")

    def add(self, key, path):
        """English counter names, whatever the OS language is. The
        localised names PdhAddCounter wants would make this fail on a
        Spanish Windows for no reason."""
        handle = wintypes.HANDLE()
        status = _pdh.PdhAddEnglishCounterW(
            self.handle, path, 0, ctypes.byref(handle))
        if status != ERROR_SUCCESS:
            log.debug("counter %s unavailable: 0x%08X", path,
                      status & 0xFFFFFFFF)
            return False
        self.counters[key] = handle
        return True

    def collect(self):
        return _pdh.PdhCollectQueryData(self.handle) == ERROR_SUCCESS

    def read(self, key):
        """Every instance of one wildcard counter, as {name: value}."""
        handle = self.counters.get(key)
        if handle is None:
            return {}
        size = wintypes.DWORD(0)
        count = wintypes.DWORD(0)
        status = _pdh.PdhGetFormattedCounterArrayW(
            handle, PDH_FMT_DOUBLE, ctypes.byref(size), ctypes.byref(count),
            None)
        if status != PDH_MORE_DATA or count.value == 0:
            # No instances at all is normal: nothing is using the GPU.
            return {}
        buf = (ctypes.c_byte * size.value)()
        status = _pdh.PdhGetFormattedCounterArrayW(
            handle, PDH_FMT_DOUBLE, ctypes.byref(size), ctypes.byref(count),
            ctypes.byref(buf))
        if status != ERROR_SUCCESS:
            return {}
        items = ctypes.cast(
            buf, ctypes.POINTER(PDH_FMT_COUNTERVALUE_ITEM_W * count.value))
        out = {}
        for item in items.contents:
            if item.FmtValue.CStatus == ERROR_SUCCESS:
                out[item.szName] = item.FmtValue.value.doubleValue
        return out

    def close(self):
        if self.handle:
            _pdh.PdhCloseQuery(self.handle)
            self.handle = wintypes.HANDLE()


# --- the adapter the counters belong to -------------------------------------

def adapter_info():
    """Name and total video memory, from the display driver's own key.

    Win32_VideoController.AdapterRAM is a 32-bit field and saturates at
    4 GB, which is useless on anything modern; the driver writes the real
    figure to HardwareInformation.qwMemorySize. Picks the adapter with the
    most memory, so a virtual display (Parsec, IDD) with none of its own
    never wins.
    """
    import winreg
    best = (0, None)
    class_key = (r"SYSTEM\CurrentControlSet\Control\Class"
                 r"\{4d36e968-e325-11ce-bfc1-08002be10318}")
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, class_key) as root:
            index = 0
            while True:
                try:
                    sub = winreg.EnumKey(root, index)
                except OSError:
                    break
                index += 1
                if not sub.isdigit():
                    continue
                try:
                    with winreg.OpenKey(root, sub) as key:
                        size = _reg_qword(key, "HardwareInformation.qwMemorySize")
                        if size is None:
                            size = _reg_qword(key, "HardwareInformation.MemorySize")
                        name = _reg_str(key, "DriverDesc")
                        if size and size > best[0]:
                            best = (size, name)
                except OSError:
                    continue
    except OSError as exc:
        log.debug("adapter registry unreadable: %s", exc)
    total_mib = best[0] / (1024.0 ** 2) if best[0] else None
    return best[1], total_mib


def _reg_qword(key, name):
    import winreg
    try:
        value, kind = winreg.QueryValueEx(key, name)
    except OSError:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, bytes) and len(value) in (4, 8):
        return int.from_bytes(value, "little")
    return None


def _reg_str(key, name):
    import winreg
    try:
        value, _ = winreg.QueryValueEx(key, name)
    except OSError:
        return None
    return str(value) if value else None


# --- the backend ------------------------------------------------------------

def _shorten(name):
    """"AMD Radeon(TM) 8060S Graphics" -> "Radeon 8060S" — the section
    header has one line and the vendor words are on every card."""
    if not name:
        return None
    name = re.sub(r"\((?:TM|R)\)|™|®", "", name).strip()
    for prefix in ("NVIDIA GeForce ", "NVIDIA ", "AMD ", "Intel(R) ", "Intel "):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return re.sub(r"\s+Graphics$", "", name).strip() or None


class PdhGpu:
    """Reads what Windows knows about the GPU. Safe to construct on a
    machine with no counters at all: `ok` is then False and sample()
    returns an empty dict."""

    def __init__(self):
        self.ok = False
        self._query = None
        self._mem_key = None
        self._luid = None      # the adapter the bar and the list both mean
        self.name, self.mem_total = (None, None)
        try:
            self._open()
        except OSError as exc:
            log.info("Windows GPU counters unavailable: %s", exc)

    def _open(self):
        query = _Query()
        has_engine = query.add("engine", COUNTER_ENGINE)
        # Adapter-level memory is one figure per GPU; the per-process
        # counter has to be summed and double-counts shared allocations.
        # Prefer the former and fall back only if it is missing.
        if query.add("mem", COUNTER_ADAPTER_MEM):
            self._mem_key = "adapter"
        elif query.add("mem", COUNTER_PROCESS_MEM):
            self._mem_key = "process"
        # Optional: only needed when the breakdown panel is opened.
        query.add("procmem", COUNTER_PROCESS_LOCAL)
        if not has_engine and self._mem_key is None:
            query.close()
            raise OSError("no GPU counters on this system")
        # A rate counter is meaningless until its second collection.
        query.collect()
        self._query = query
        self.name, self.mem_total = adapter_info()
        self.name = _shorten(self.name)
        self.ok = True

    def sample(self):
        """{'gpu_name', 'util', 'mem_used', 'mem_total'} — all optional."""
        if not self.ok or self._query is None:
            return {}
        if not self._query.collect():
            return {}
        out = {"gpu_name": self.name, "mem_total": self.mem_total}

        engines = self._query.read("engine")
        if engines:
            # Task Manager does not add every engine together: it reports
            # the busiest engine *type* (3D, copy, video decode...), so a
            # card doing 90% 3D and 40% copy reads 90, not 130.
            by_type = {}
            for instance, value in engines.items():
                match = _ENGTYPE.search(instance)
                bucket = match.group(1) if match else "other"
                by_type[bucket] = by_type.get(bucket, 0.0) + value
            out["util"] = min(100.0, max(by_type.values()))

        memory = self._query.read("mem")
        if memory:
            if self._mem_key == "adapter":
                # One adapter, the busiest -- not the sum of all of them.
                # A machine here has three (the real GPU, a virtual
                # display, a render-only device) and summing them put
                # ~700 MiB of somebody else's memory on a bar whose total
                # comes from one card. It also has to agree with
                # per_process(), which can only speak for one adapter.
                instance = max(memory, key=memory.get)
                found = _INSTANCE.search(instance)
                self._luid = found.group(2) if found else None
                out["mem_used"] = memory[instance] / (1024.0 ** 2)
            else:
                out["mem_used"] = sum(memory.values()) / (1024.0 ** 2)
        return out

    def _resolve_luid(self):
        """Which adapter to speak for: the one holding the most memory."""
        memory = self._query.read("mem") if self._query else {}
        if not memory:
            return
        found = _INSTANCE.search(max(memory, key=memory.get))
        self._luid = found.group(2) if found else None

    def per_process_util(self):
        """{pid: percent} of GPU utilisation, on the adapter the bar shows.

        Aggregated per process the same way the whole-adapter figure is:
        sum that process's instances within an engine type, then take the
        busiest type. Summing across types instead would let a process
        doing 90% 3D and 40% copy report 130%.
        """
        if not self.ok or self._query is None:
            return {}
        self._query.collect()
        if self._luid is None:
            self._resolve_luid()
        by_pid = {}
        for instance, value in self._query.read("engine").items():
            found = _ENGINE_INSTANCE.match(instance)
            if not found:
                continue
            pid, luid, engtype = found.group(1), found.group(2), found.group(3)
            if self._luid and luid != self._luid:
                continue
            types = by_pid.setdefault(int(pid), {})
            types[engtype] = types.get(engtype, 0.0) + value
        return {pid: min(100.0, max(types.values()))
                for pid, types in by_pid.items() if types}

    def per_process(self):
        """{pid: bytes} of video memory, for the adapter the bar shows.

        Restricted to that adapter on purpose: the same process appears
        once per adapter it has touched, and adding those together would
        count a window manager's memory twice.
        """
        if not self.ok or self._query is None:
            return {}
        self._query.collect()
        if self._luid is None:
            # sample() normally settles this, but on an NVIDIA machine
            # nvidia-smi feeds the card and sample() is never called --
            # the breakdown is then the only user of this object.
            self._resolve_luid()
        out = {}
        for instance, value in self._query.read("procmem").items():
            found = _INSTANCE.search(instance)
            if not found or not found.group(1):
                continue
            if self._luid and found.group(2) != self._luid:
                continue
            pid = int(found.group(1))
            out[pid] = out.get(pid, 0.0) + value
        return out

    def close(self):
        if self._query is not None:
            self._query.close()
            self._query = None
        self.ok = False
