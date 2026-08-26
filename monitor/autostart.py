"""Start with Windows: the HKCU Run entry, and the truth about it.

The registry is the single source of truth here, never a mirror of it in
settings.json. A copy would drift the moment the entry is removed from
Task Manager, msconfig or regedit — and it would drift silently, leaving
the checkbox claiming something Windows disagrees with.

Per-user (HKCU), so no elevation is ever needed, and the same shape the
rest of Ivan's tools use:

    "<pythonw.exe>" "C:\\IA\\Tools\\Apps\\GPU_Monitor\\gpu_monitor.py"
"""

from __future__ import annotations

import logging
import os
import sys

log = logging.getLogger("gpu_monitor.autostart")

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
# Where Task Manager's Startup tab records what the user switched off. It
# survives the Run value being rewritten, so an entry disabled there stays
# disabled no matter how many times we re-add ourselves.
APPROVED_KEY = (r"Software\Microsoft\Windows\CurrentVersion\Explorer"
                r"\StartupApproved\Run")
# Every function below resolves the value name at call time rather than
# binding it as a default argument, so the test suite can point the whole
# module at a scratch name and never touch the real startup entry.
VALUE_NAME = "GPU Monitor"

APP_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "gpu_monitor.py")

if os.name == "nt":
    import winreg


def launch_command():
    """The command Windows should run at logon.

    Two deliberate choices. **pythonw**, so no console window flashes on
    the desktop at every logon — `sys.executable` is already pythonw when
    launched from GPU_Monitor.bat, but a run started from a console is
    python.exe and would register the wrong one. And the **resolved**
    interpreter rather than a bare `pythonw` on PATH: at logon the PATH
    shim can resolve to a Windows Store stub, and a full path cannot.

    The .bat is deliberately not used: it pip-installs on a cold start,
    which is the last thing wanted while Windows is still logging in.
    """
    exe = sys.executable or "pythonw.exe"
    if os.path.basename(exe).lower() == "python.exe":
        windowless = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.exists(windowless):
            exe = windowless
    return f'"{exe}" "{APP_SCRIPT}"'


def registered_command(name=None):
    """What is registered right now, or None when nothing is."""
    if os.name != "nt":
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, name or VALUE_NAME)
            return value
    except OSError:
        return None


def is_enabled(name=None):
    return registered_command(name) is not None


def is_stale(name=None):
    """Registered, but pointing somewhere else than this copy would.

    Happens after a Python upgrade moves the interpreter: the entry
    survives, the path it names does not, and the app silently stops
    appearing at logon. Re-saving rewrites it.
    """
    current = registered_command(name)
    return current is not None and current != launch_command()


def is_blocked(name=None):
    """True when Windows itself has the entry switched off.

    Task Manager stores a flag per value name whose low bit means
    "disabled" (2 = enabled, 3 = disabled, 6/7 the same pair with a
    timestamp). Undocumented, so it is only ever *read* to warn with —
    the one write is the deletion in set_enabled, which merely puts the
    name back to its default of enabled.
    """
    if os.name != "nt":
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APPROVED_KEY) as key:
            blob, _ = winreg.QueryValueEx(key, name or VALUE_NAME)
    except OSError:
        return False
    return bool(blob) and bool(blob[0] & 1)


def _clear_block(name):
    """Drop Task Manager's disable flag, so ticking the box actually takes.

    Without this, re-adding the Run value after the user once disabled
    GPU Monitor in Task Manager looks like it worked and changes nothing:
    the flag outlives the value. Deleting the flag restores the default,
    which is enabled.
    """
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APPROVED_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, name)
        log.info("cleared the Task Manager disable flag for %s", name)
    except OSError:
        pass       # not disabled, or the key does not exist yet


def set_enabled(on, name=None):
    """Add or remove the Run entry. Returns whether it now matches `on`.

    Enabling always rewrites the command, so this doubles as the repair
    for a stale path.
    """
    if os.name != "nt":
        return False
    name = name or VALUE_NAME
    try:
        if on:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ,
                                  launch_command())
            if is_blocked(name):
                _clear_block(name)
            log.info("autostart enabled: %s", launch_command())
        else:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, name)
            log.info("autostart disabled")
    except FileNotFoundError:
        pass       # already absent; disabling something gone is a success
    except OSError as exc:
        log.warning("could not %s autostart: %s",
                    "enable" if on else "disable", exc)
        return False
    return is_enabled(name) == bool(on)
