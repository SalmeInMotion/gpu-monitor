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
    _ntdll.NtQueryInformationProcess.restype = ctypes.c_ulong
    _ntdll.NtQueryInformationProcess.argtypes = [
        wintypes.HANDLE, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong)]
except (OSError, AttributeError):  # pragma: no cover - not Windows
    _ntdll = None

try:
    _kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL,
                                      wintypes.DWORD]
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    _kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD)]
    _shell32 = ctypes.WinDLL("shell32.dll")
    _shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    _shell32.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR,
                                            ctypes.POINTER(ctypes.c_int)]
except (OSError, AttributeError):  # pragma: no cover - not Windows
    _kernel32 = _shell32 = None


def snapshot():
    """[(pid, name, working_set_bytes, cpu_100ns), ...] or None.

    One call answers both questions the breakdown panels ask. CPU time is
    kernel + user in 100-nanosecond units, which is a running total: a
    percentage is the difference between two of these over the wall time
    between them, which is exactly what Task Manager does.

    The System Idle Process (pid 0) is dropped: its "working set" is an
    artefact and its CPU time is the definition of doing nothing.
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
            out.append((int(pid), name, int(entry.WorkingSetSize),
                        int(entry.KernelTime) + int(entry.UserTime)))
        if not entry.NextEntryOffset:
            break
        offset += entry.NextEntryOffset
        if offset >= len(buf):          # malformed chain; do not walk off
            log.debug("process table chain ran past the buffer")
            return None
    return out or None


# --- one process, with only the rights Windows gives away freely --------
#
# psutil reads a command line out of the target's PEB, which needs
# PROCESS_VM_READ -- a right an ordinary process does not get over an
# elevated one. That is not a corner case: it is how AI-cachofo's ComfyUI
# runs, and the card there showed a bare "python" holding 30 GB while an
# SSH shell (a full token) could read the same process perfectly.
#
# ProcessCommandLineInformation asks the kernel for the string instead, and
# is satisfied by PROCESS_QUERY_LIMITED_INFORMATION -- which same-user
# processes are granted across the elevation boundary. Windows 8.1+.

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_COMMAND_LINE_INFORMATION = 60


def _open(pid):
    if _kernel32 is None or not pid:
        return None
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,
                                   False, pid)
    return handle or None


def command_line(pid):
    """The process's command line, already split into argv. None if the
    system will not say -- protected processes still refuse."""
    if _ntdll is None or _shell32 is None:
        return None
    handle = _open(pid)
    if handle is None:
        return None
    try:
        needed = ctypes.c_ulong(0)
        # Ask with nothing: the answer is the length, as STATUS_INFO_
        # LENGTH_MISMATCH. The string is variable-length, so there is no
        # sensible size to guess.
        _ntdll.NtQueryInformationProcess(
            handle, PROCESS_COMMAND_LINE_INFORMATION, None, 0,
            ctypes.byref(needed))
        if not needed.value or needed.value > 1 << 20:
            return None
        buffer = ctypes.create_string_buffer(needed.value)
        status = _ntdll.NtQueryInformationProcess(
            handle, PROCESS_COMMAND_LINE_INFORMATION, buffer, needed.value,
            ctypes.byref(needed))
        if status:
            return None
        # A UNICODE_STRING whose Buffer points just past itself.
        text = ctypes.cast(buffer, ctypes.POINTER(UNICODE_STRING)).contents
        if not text.Length or not text.Buffer:
            return None
        line = ctypes.wstring_at(text.Buffer, text.Length // 2)
    except Exception as exc:            # pragma: no cover - shape change
        log.debug("command line for %s: %s", pid, exc)
        return None
    finally:
        _kernel32.CloseHandle(handle)

    count = ctypes.c_int(0)
    argv = _shell32.CommandLineToArgvW(line, ctypes.byref(count))
    if not argv:
        return [line]                   # unquotable, but still the truth
    try:
        return [argv[i] for i in range(count.value)]
    finally:
        ctypes.windll.kernel32.LocalFree(argv)


def image_path(pid):
    """Where the running executable lives, or None.

    QueryFullProcessImageNameW for the same reason as above: psutil's
    `exe()` needs rights an elevated target does not hand over.
    """
    handle = _open(pid)
    if handle is None:
        return None
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not _kernel32.QueryFullProcessImageNameW(handle, 0, buffer,
                                                    ctypes.byref(size)):
            return None
        return buffer.value or None
    except Exception:                   # pragma: no cover
        return None
    finally:
        _kernel32.CloseHandle(handle)


def working_sets():
    """[(pid, name, working_set_bytes), ...] -- snapshot() without the
    CPU column, for callers that only want memory."""
    rows = snapshot()
    if rows is None:
        return None
    return [(pid, name, ws) for pid, name, ws, _ in rows]
