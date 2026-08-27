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

try:
    _advapi32 = ctypes.WinDLL("advapi32.dll", use_last_error=True)
    _advapi32.OpenSCManagerW.restype = wintypes.HANDLE
    _advapi32.OpenSCManagerW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR,
                                         wintypes.DWORD]
    _advapi32.EnumServicesStatusExW.restype = wintypes.BOOL
    _advapi32.EnumServicesStatusExW.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.DWORD, wintypes.DWORD,
        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
        wintypes.LPCWSTR]
    _advapi32.CloseServiceHandle.argtypes = [wintypes.HANDLE]
except (OSError, AttributeError):  # pragma: no cover - not Windows
    _advapi32 = None

try:
    _iphlpapi = ctypes.WinDLL("iphlpapi.dll")
    _user32 = ctypes.WinDLL("user32.dll")
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                     wintypes.LPARAM)
except (OSError, AttributeError):  # pragma: no cover - not Windows
    _iphlpapi = _user32 = None
    WNDENUMPROC = None


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
ERROR_ACCESS_DENIED = 5


def denied(pid):
    """True when Windows refuses even a limited handle.

    Same user is not enough: an *elevated* process's DACL grants the
    Administrators group, and an ordinary token carries that group as
    deny-only, so nothing about it can be read. Measured on AI-cachofo,
    where ComfyUI starts elevated -- and WMI is no way round it either,
    `Win32_Process.CommandLine` comes back empty rather than refused.
    """
    if _kernel32 is None or not pid:
        return False
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,
                                   False, pid)
    if handle:
        _kernel32.CloseHandle(handle)
        return False
    return ctypes.get_last_error() == ERROR_ACCESS_DENIED


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


# Reading a process needs a handle. *Identifying* one does not, and these
# three are what is left when the handle is refused -- the case that made
# an elevated ComfyUI show up as a bare "python" holding 30 GB.

SYSTEM_PROCESS_ID_INFORMATION = 88


class SYSTEM_PROCESS_ID_INFO(ctypes.Structure):
    _fields_ = [("ProcessId", ctypes.c_void_p),
                ("ImageName", UNICODE_STRING)]


_dos_drives = None


def _to_drive_letter(nt_path):
    r"""\Device\HarddiskVolume3\Users\... -> C:\Users\...

    The kernel answers in device paths; nobody wants to read one.
    """
    global _dos_drives
    if not nt_path or not nt_path.startswith("\\Device\\"):
        return nt_path
    if _dos_drives is None or not any(
            nt_path.lower().startswith(d.lower()) for d in _dos_drives):
        _dos_drives = {}
        if _kernel32 is not None:
            target = ctypes.create_unicode_buffer(1024)
            for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                if ctypes.windll.kernel32.QueryDosDeviceW(
                        f"{letter}:", target, 1024):
                    _dos_drives[target.value] = f"{letter}:"
    for device, letter in (_dos_drives or {}).items():
        if nt_path.lower().startswith(device.lower() + "\\"):
            return letter + nt_path[len(device):]
    return nt_path


def image_path_unopened(pid):
    """The executable's path without opening the process at all.

    SystemProcessIdInformation takes a pid rather than a handle, so it
    answers for processes we are not allowed to touch. Two calls: the
    first is expected to fail, reporting how much room the name needs.
    """
    if _ntdll is None or not pid:
        return None
    try:
        info = SYSTEM_PROCESS_ID_INFO()
        info.ProcessId = ctypes.c_void_p(pid)
        info.ImageName.Length = 0
        info.ImageName.MaximumLength = 0
        info.ImageName.Buffer = None
        status = _ntdll.NtQuerySystemInformation(
            SYSTEM_PROCESS_ID_INFORMATION, ctypes.byref(info),
            ctypes.sizeof(info), None)
        if status != STATUS_INFO_LENGTH_MISMATCH:
            return None
        room = info.ImageName.MaximumLength
        if not room or room > 1 << 16:
            return None
        buffer = ctypes.create_unicode_buffer(room // 2 + 1)
        info.ImageName.Buffer = ctypes.cast(buffer, ctypes.c_void_p)
        if _ntdll.NtQuerySystemInformation(
                SYSTEM_PROCESS_ID_INFORMATION, ctypes.byref(info),
                ctypes.sizeof(info), None):
            return None
        return _to_drive_letter(
            ctypes.wstring_at(info.ImageName.Buffer, info.ImageName.Length // 2))
    except Exception as exc:            # pragma: no cover - shape change
        log.debug("unopened image path for %s: %s", pid, exc)
        return None


AF_INET = 2
TCP_TABLE_OWNER_PID_ALL = 5
UDP_TABLE_OWNER_PID = 1
MIB_TCP_STATE_LISTEN = 2


class MIB_TCPROW_OWNER_PID(ctypes.Structure):
    _fields_ = [("dwState", wintypes.DWORD),
                ("dwLocalAddr", wintypes.DWORD),
                ("dwLocalPort", wintypes.DWORD),
                ("dwRemoteAddr", wintypes.DWORD),
                ("dwRemotePort", wintypes.DWORD),
                ("dwOwningPid", wintypes.DWORD)]


class MIB_UDPROW_OWNER_PID(ctypes.Structure):
    _fields_ = [("dwLocalAddr", wintypes.DWORD),
                ("dwLocalPort", wintypes.DWORD),
                ("dwOwningPid", wintypes.DWORD)]


def _network_port(raw):
    """The tables keep the port in network order inside a DWORD."""
    return ((raw & 0xFF) << 8) | ((raw >> 8) & 0xFF)


def _connection_table(getter, row_type, table_class):
    size = wintypes.DWORD(0)
    getter(None, ctypes.byref(size), False, AF_INET, table_class, 0)
    if not size.value:
        return []
    buffer = ctypes.create_string_buffer(size.value)
    if getter(buffer, ctypes.byref(size), False, AF_INET, table_class, 0):
        return []
    count = ctypes.cast(buffer, ctypes.POINTER(wintypes.DWORD)).contents.value
    if not count:
        return []
    rows = ctypes.cast(ctypes.byref(buffer, ctypes.sizeof(wintypes.DWORD)),
                       ctypes.POINTER(row_type * count))
    return list(rows.contents)


def listening_ports():
    """{pid: [("tcp", 8188), ...]} -- what each process is listening on.

    No handle involved, so this works on the processes nothing else will
    talk about. A port is often the whole answer: 8188 is ComfyUI to
    anyone who has ever run it.
    """
    if _iphlpapi is None:
        return {}
    out = {}
    try:
        for row in _connection_table(_iphlpapi.GetExtendedTcpTable,
                                     MIB_TCPROW_OWNER_PID,
                                     TCP_TABLE_OWNER_PID_ALL):
            if row.dwState == MIB_TCP_STATE_LISTEN:
                out.setdefault(row.dwOwningPid, set()).add(
                    ("tcp", _network_port(row.dwLocalPort)))
        for row in _connection_table(_iphlpapi.GetExtendedUdpTable,
                                     MIB_UDPROW_OWNER_PID,
                                     UDP_TABLE_OWNER_PID):
            out.setdefault(row.dwOwningPid, set()).add(
                ("udp", _network_port(row.dwLocalPort)))
    except Exception as exc:            # pragma: no cover
        log.debug("connection tables: %s", exc)
        return {}
    return {pid: sorted(ports) for pid, ports in out.items()}


def window_titles():
    """{pid: [visible window titles]} -- also handle-free."""
    if _user32 is None:
        return {}
    out = {}

    def visit(hwnd, _):
        try:
            if not _user32.IsWindowVisible(hwnd):
                return True
            owner = wintypes.DWORD()
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            length = _user32.GetWindowTextLengthW(hwnd)
            if length:
                text = ctypes.create_unicode_buffer(length + 1)
                _user32.GetWindowTextW(hwnd, text, length + 1)
                if text.value.strip():
                    out.setdefault(owner.value, []).append(text.value)
        except Exception:               # pragma: no cover
            pass
        return True

    try:
        _user32.EnumWindows(WNDENUMPROC(visit), 0)
    except Exception as exc:            # pragma: no cover
        log.debug("window titles: %s", exc)
    return out


def image_path(pid):
    """Where the running executable lives, or None.

    QueryFullProcessImageNameW for the same reason as above: psutil's
    `exe()` needs rights an elevated target does not hand over. Falls back
    to the handle-free route when even that is refused.
    """
    handle = _open(pid)
    if handle is None:
        return image_path_unopened(pid)
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


# --- which services live in which process --------------------------------
#
# "svchost" is as much a non-answer as "python", and it is 93 processes
# holding 1.9 GB on this machine. The service control manager will say
# who they are: EnumServicesStatusEx returns every running service with
# the pid hosting it, in one call, and needs only
# SC_MANAGER_ENUMERATE_SERVICE -- which ordinary users have.

SC_MANAGER_ENUMERATE_SERVICE = 0x0004
SC_ENUM_PROCESS_INFO = 0
SERVICE_TYPE_ALL = 0x0000013F
SERVICE_ACTIVE = 0x00000001
ERROR_MORE_DATA = 234


class SERVICE_STATUS_PROCESS(ctypes.Structure):
    _fields_ = [("dwServiceType", wintypes.DWORD),
                ("dwCurrentState", wintypes.DWORD),
                ("dwControlsAccepted", wintypes.DWORD),
                ("dwWin32ExitCode", wintypes.DWORD),
                ("dwServiceSpecificExitCode", wintypes.DWORD),
                ("dwCheckPoint", wintypes.DWORD),
                ("dwWaitHint", wintypes.DWORD),
                ("dwProcessId", wintypes.DWORD),
                ("dwServiceFlags", wintypes.DWORD)]


class ENUM_SERVICE_STATUS_PROCESS(ctypes.Structure):
    _fields_ = [("lpServiceName", wintypes.LPWSTR),
                ("lpDisplayName", wintypes.LPWSTR),
                ("ServiceStatusProcess", SERVICE_STATUS_PROCESS)]


def services_by_pid():
    """{pid: [service display names]} for everything running, or {}.

    Display names, not keys: "Windows Update" reads better on a row than
    "wuauserv", and this is for looking at.
    """
    if _advapi32 is None:
        return {}
    manager = _advapi32.OpenSCManagerW(None, None,
                                       SC_MANAGER_ENUMERATE_SERVICE)
    if not manager:
        return {}
    try:
        needed = wintypes.DWORD(0)
        count = wintypes.DWORD(0)
        resume = wintypes.DWORD(0)
        # Ask with nothing to learn the size, as everywhere else here.
        _advapi32.EnumServicesStatusExW(
            manager, SC_ENUM_PROCESS_INFO, SERVICE_TYPE_ALL, SERVICE_ACTIVE,
            None, 0, ctypes.byref(needed), ctypes.byref(count),
            ctypes.byref(resume), None)
        if not needed.value or needed.value > 1 << 24:
            return {}
        buffer = ctypes.create_string_buffer(needed.value)
        ok = _advapi32.EnumServicesStatusExW(
            manager, SC_ENUM_PROCESS_INFO, SERVICE_TYPE_ALL, SERVICE_ACTIVE,
            buffer, needed.value, ctypes.byref(needed), ctypes.byref(count),
            ctypes.byref(resume), None)
        if not ok:
            return {}
        table = ctypes.cast(
            buffer, ctypes.POINTER(ENUM_SERVICE_STATUS_PROCESS * count.value))
        out = {}
        for row in table.contents:
            pid = row.ServiceStatusProcess.dwProcessId
            if not pid:
                continue            # a driver, or a service not running
            out.setdefault(pid, []).append(
                row.lpDisplayName or row.lpServiceName or "?")
        for names in out.values():
            names.sort(key=str.lower)
        return out
    except Exception as exc:            # pragma: no cover - shape change
        log.debug("service table: %s", exc)
        return {}
    finally:
        _advapi32.CloseServiceHandle(manager)


def working_sets():
    """[(pid, name, working_set_bytes), ...] -- snapshot() without the
    CPU column, for callers that only want memory."""
    rows = snapshot()
    if rows is None:
        return None
    return [(pid, name, ws) for pid, name, ws, _ in rows]
