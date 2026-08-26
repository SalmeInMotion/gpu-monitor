"""Every process, its name and its working set, in one system call.

`psutil.process_iter(["memory_info"])` opens a handle per process to ask
each one how much memory it holds. On this machine, with 461 processes,
that measured **1574 ms** — enough to freeze the card every time the
breakdown panel refreshes.

`NtQuerySystemInformation(SystemProcessInformation)` returns the whole
table in a single buffer, which is where Task Manager gets its own list.
Same numbers, about two orders of magnitude cheaper.

It is an undocumented-but-stable NT call, so everything here is wrapped:
if the struct ever stops matching, `working_sets()` returns None and the
caller falls back to psutil rather than showing invented figures.
"""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

log = logging.getLogger("gpu_monitor.winproc")

SYSTEM_PROCESS_INFORMATION = 5
STATUS_INFO_LENGTH_MISMATCH = 0xC0000004


class UNICODE_STRING(ctypes.Structure):
    _fields_ = [("Length", wintypes.USHORT),
                ("MaximumLength", wintypes.USHORT),
                ("Buffer", ctypes.c_void_p)]


class SYSTEM_PROCESS_INFO(ctypes.Structure):
    """Only as far as WorkingSetSize; the rest of the struct is ignored.

    Field order and widths are what make this work — ctypes inserts the
    x64 padding on its own as long as each field has its real C type
    (ULONG stays 4 bytes, HANDLE and SIZE_T become 8).
    """

    _fields_ = [
        ("NextEntryOffset", wintypes.ULONG),
        ("NumberOfThreads", wintypes.ULONG),
        ("WorkingSetPrivateSize", ctypes.c_longlong),
        ("HardFaultCount", wintypes.ULONG),
        ("NumberOfThreadsHighWatermark", wintypes.ULONG),
        ("CycleTime", ctypes.c_ulonglong),
        ("CreateTime", ctypes.c_longlong),
        ("UserTime", ctypes.c_longlong),
        ("KernelTime", ctypes.c_longlong),
        ("ImageName", UNICODE_STRING),
        ("BasePriority", ctypes.c_long),
        ("UniqueProcessId", ctypes.c_void_p),
        ("InheritedFromUniqueProcessId", ctypes.c_void_p),
        ("HandleCount", wintypes.ULONG),
        ("SessionId", wintypes.ULONG),
        ("UniqueProcessKey", ctypes.c_size_t),
        ("PeakVirtualSize", ctypes.c_size_t),
        ("VirtualSize", ctypes.c_size_t),
        ("PageFaultCount", wintypes.ULONG),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
    ]


try:
    _ntdll = ctypes.WinDLL("ntdll.dll")
    _ntdll.NtQuerySystemInformation.restype = ctypes.c_ulong
    _ntdll.NtQuerySystemInformation.argtypes = [
        ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong)]
except (OSError, AttributeError):  # pragma: no cover - not Windows
    _ntdll = None


def working_sets():
    """[(pid, name, working_set_bytes), ...] or None if the call failed.

    The System Idle Process (pid 0) is dropped: its "working set" is an
    artefact and it is not something anyone is going to close.
    """
    if _ntdll is None:
        return None
    size = ctypes.c_ulong(1 << 20)
    for _ in range(6):
        buf = ctypes.create_string_buffer(size.value)
        needed = ctypes.c_ulong(0)
        status = _ntdll.NtQuerySystemInformation(
            SYSTEM_PROCESS_INFORMATION, buf, size.value, ctypes.byref(needed))
        if status == 0:
            break
        if status != STATUS_INFO_LENGTH_MISMATCH:
            log.debug("NtQuerySystemInformation failed: 0x%08X", status)
            return None
        # The table grows between the sizing call and the real one, so ask
        # for what it wanted plus room for the processes started since.
        size = ctypes.c_ulong(max(needed.value, size.value) + (1 << 18))
    else:
        log.debug("NtQuerySystemInformation kept outgrowing the buffer")
        return None

    out = []
    offset = 0
    base = ctypes.addressof(buf)
    while True:
        entry = SYSTEM_PROCESS_INFO.from_address(base + offset)
        pid = entry.UniqueProcessId or 0
        if pid:
            name = "?"
            if entry.ImageName.Buffer and entry.ImageName.Length:
                try:
                    name = ctypes.wstring_at(
                        entry.ImageName.Buffer, entry.ImageName.Length // 2)
                except (OSError, ValueError):
                    name = "?"
            out.append((int(pid), name, int(entry.WorkingSetSize)))
        if not entry.NextEntryOffset:
            break
        offset += entry.NextEntryOffset
        if offset >= len(buf):          # malformed chain; do not walk off
            log.debug("process table chain ran past the buffer")
            return None
    return out or None
