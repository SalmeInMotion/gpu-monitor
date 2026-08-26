"""App bootstrap: QApplication + settings + theme + logging + Supervisor.

    from app_template import create_app, FramelessWindow

    ctx = create_app("MyTool", brand_accent="#FF6600")
    win = FramelessWindow("MyTool", persist=(ctx.settings, "window"))
    ...
    win.show()
    raise SystemExit(ctx.app.exec())
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys

from PySide6.QtWidgets import QApplication

from .settings import Settings
from .theme import ThemeManager

SUPERVISOR_BRIDGE_DIR = r"C:\IA\Tools\Claude\Supervisor\bridge"


def _default_app_id(app_name):
    """A dotted AppUserModelID from the app name (no spaces, 128 max)."""
    return ("SalmeInMotion." + "-".join(app_name.split() or ["App"]))[:128]


def _set_app_user_model_id(app_id):
    """Claim a taskbar identity of our own.

    Windows reads the taskbar button's icon - and what it groups with - from
    the process AppUserModelID, NOT from the window icon alone. A Python
    process inherits the interpreter's, which is why every tool launched
    through pythonw.exe showed the Python logo however good its own icon was.
    Must run before the first window exists, so create_app does it first.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except (OSError, AttributeError) as exc:      # shell32 refused; not fatal
        logging.getLogger("app_template").warning(
            "AppUserModelID not set: %s", exc)


class AppContext:
    def __init__(self, app, settings, theme, name):
        self.app = app
        self.settings = settings
        self.theme = theme
        self.name = name


def _setup_logging(app_name):
    log_dir = os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
        app_name, "logs")
    os.makedirs(log_dir, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, "app.log"), maxBytes=1_000_000, backupCount=3,
        encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    root.addHandler(logging.StreamHandler(sys.stderr))


def create_app(name, brand_accent="#FF6600", brand_accent_dark=None,
               extra_qss="", argv=None, app_id=None, icon=None):
    """Create the QApplication with the whole template wired up.

    app_id: explicit AppUserModelID; defaults to one derived from `name`.
    icon:   a QIcon, or a CALLABLE returning one, applied app-wide so every
            window, the Alt+Tab entry and the taskbar button use it. The
            callable form exists because an icon painted at runtime needs a
            live QApplication to build its pixmaps - so the app cannot hand us
            a finished QIcon before this call.
    """
    _set_app_user_model_id(app_id or _default_app_id(name))
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(name)
    app.setStyle("Fusion")  # predictable base for a fully-styled UI
    if icon is not None:
        app.setWindowIcon(icon() if callable(icon) else icon)

    _setup_logging(name)
    settings = Settings(name)
    theme = ThemeManager(name, settings, brand_accent, brand_accent_dark,
                         extra_qss)
    theme.apply()

    if settings.get("hover_glow", True):
        from .effects import install_hover_reveal
        install_hover_reveal(app)

    # Supervisor bridge: lets Claude inspect/drive the app while developing.
    try:
        sys.path.insert(0, SUPERVISOR_BRIDGE_DIR)
        from supervisor_bridge import attach
        attach(name)
    except Exception as exc:
        logging.getLogger("app_template").warning(
            "supervisor bridge not attached: %s", exc)

    return AppContext(app, settings, theme, name)
