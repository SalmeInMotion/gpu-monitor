"""GPU Monitor - a floating always-on-top card for GPU, VRAM, CPU and RAM.

Wears the look of Ivan's own ia-usage (github.com/ivanram/ia-usage), which
meters something else entirely but has exactly the right shape for this:
a borderless sheet of label/value rows over pill meters. Built on the
shared Windows app template, so palette, theme mode and accent are the
same controls as in every other tool here.

    python gpu_monitor.py          (or GPU_Monitor.bat, which uses pythonw)
"""

from __future__ import annotations

import json
import logging
import os
import sys


# Puts the project and app_template on sys.path; see monitor/template.py
# for why the shared copy beats the bundled one.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from monitor.template import ensure_on_path  # noqa: E402

ensure_on_path()

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QIcon

# Must run before the QApplication exists. The default rounding policy
# snaps 125%/150% displays to whole integers, which lands the 9px meter
# and its 4.5px caps off the pixel grid on Ivan's 4K screens.
QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
    Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

from app_template import create_app  # noqa: E402 - must follow the DPI call

from monitor import metrics as M  # noqa: E402
from monitor.instance import SingleInstance  # noqa: E402
from monitor.overlay import Overlay  # noqa: E402
from monitor.prefs import PreferencesDialog  # noqa: E402
from monitor.sampler import Sampler  # noqa: E402

APP_NAME = "GPU Monitor"
# Explicit Application User Model ID; see claim_shell_identity().
APP_ID = "IvanSalmeron.GPUMonitor"

# ia-usage's own brand navy, and the lighter sibling it swaps to on dark
# because the navy disappears there.
BRAND_ACCENT = "#2E4372"
BRAND_ACCENT_DARK = "#7C97E0"

LEGACY_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "vram_monitor_config.json")
ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "ico", "GPU_Monitor.ico")

APP_DEFAULTS = {
    "show": dict(M.DEFAULT_SHOW),
    "opacity": 100,        # percent; drives the card fill's alpha
    "width": 300,          # content width, ia-usage's own column is 288
    "locked": False,
    "compact": False,
    "always_on_top": True,  # re-asserted each tick, see overlay._set_topmost
    "centre_on_start": True,   # open in the middle of Windows' main screen
    "animations": True,
    "threshold_colors": True,
    "interval_ms": 1000,
}

log = logging.getLogger("gpu_monitor")


def apply_defaults(settings):
    """Fill in this app's keys without touching anything already chosen.

    On a genuinely first run the palette starts on `iausage` and the
    template's hover glow is off: the glow is a nice affordance in a full
    app window and pure noise on a 300px always-on-top card.
    """
    first_run = not os.path.exists(settings.path)
    for key, value in APP_DEFAULTS.items():
        settings.data.setdefault(key, value)
    # a metric added in a later version must appear for existing users too
    show = dict(M.DEFAULT_SHOW)
    show.update(settings.get("show") or {})
    settings["show"] = show
    if first_run:
        settings["preset"] = "iausage"
        settings["hover_glow"] = False
    return first_run


def migrate_legacy(settings):
    """Carry over vram_monitor_config.json from the tkinter version.

    Runs once; the flag is what stops a later edit of the old file from
    overwriting choices made since.
    """
    if settings.get("legacy_imported"):
        return
    settings["legacy_imported"] = True
    try:
        with open(LEGACY_CONFIG, "r", encoding="utf-8-sig") as f:
            old = json.load(f)
    except (OSError, ValueError):
        return
    if not isinstance(old, dict):
        return

    show = dict(settings.get("show") or {})
    for key, value in (old.get("show") or {}).items():
        if key in M.BY_KEY:
            show[key] = bool(value)
    settings["show"] = show
    if isinstance(old.get("x"), int) and isinstance(old.get("y"), int):
        settings["pos"] = [old["x"], old["y"]]
    if isinstance(old.get("opacity"), (int, float)):
        # the old file stored a 0..1 alpha, this one stores a percent
        settings["opacity"] = max(30, min(100, round(old["opacity"] * 100)))
    settings["locked"] = bool(old.get("locked", False))
    log.info("imported settings from %s", LEGACY_CONFIG)


def claim_shell_identity():
    """Stop Windows filing this app under the Python interpreter.

    The shell groups windows, and picks the taskbar / Alt-Tab icon, by
    Application User Model ID — which for a script defaults to the
    interpreter's. Left alone, GPU Monitor is "pythonw.exe" and wears the
    Python logo however many times Qt is handed an icon of our own.

    Must run before the first window exists, hence before create_app.
    """
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (OSError, AttributeError) as exc:      # pre-Win7, or no shell32
        log.debug("could not claim an app id: %s", exc)


def main():
    claim_shell_identity()
    ctx = create_app(APP_NAME, brand_accent=BRAND_ACCENT,
                     brand_accent_dark=BRAND_ACCENT_DARK)
    if os.path.exists(ICON_PATH):
        # Qt's half of the same story: what the Preferences dialog and the
        # Alt-Tab entry actually paint.
        ctx.app.setWindowIcon(QIcon(ICON_PATH))

    # One card only. If GPU Monitor is already running, poke it so it
    # surfaces itself and bow out before building a second window. Parented
    # to the app so the server keeps listening for the whole session.
    guard = SingleInstance(APP_NAME, ctx.app)
    if not guard.is_primary():
        log.info("already running; surfaced the existing card and exiting")
        return 0

    apply_defaults(ctx.settings)
    migrate_legacy(ctx.settings)
    ctx.settings.save()

    # create_app resolved the palette and installed the hover glow from
    # whatever was on disk, which on a first run is the template's own
    # defaults — apply_defaults has only just written this app's. Without
    # re-resolving both here the entire first session runs on Nocturne
    # with the glow on, while settings.json already says otherwise, and
    # it only looks right after a restart.
    ctx.theme.apply()
    if not ctx.settings.get("hover_glow", True):
        from app_template.effects import remove_hover_reveal
        remove_hover_reveal(ctx.app)

    overlay = Overlay(ctx.settings, ctx.theme)
    guard.activated.connect(overlay.raise_to_front)
    sampler = Sampler(int(ctx.settings.get("interval_ms", 1000)))
    sampler.sampled.connect(overlay.on_sample)
    # Clicking a memory bar asks for a per-process breakdown; the walk
    # happens on the sampler thread and comes back the same way.
    overlay.breakdown_requested.connect(sampler.request_breakdown)
    sampler.breakdown.connect(overlay.set_breakdown)

    def open_prefs():
        dialog = PreferencesDialog(ctx.settings, ctx.theme, overlay)
        dialog.changed.connect(lambda: apply_live(overlay, sampler,
                                                  ctx.settings))
        # the card is topmost; the dialog is not, so drop the card below it
        # for the duration or it covers its own Preferences window
        overlay.suspend_topmost()
        dialog.exec()
        apply_live(overlay, sampler, ctx.settings)
        # exec() only hides it; parented to the overlay it would otherwise
        # stay alive, so every open would add a dead dialog tree under a
        # window that never closes.
        dialog.deleteLater()

    overlay.prefs_requested.connect(open_prefs)
    overlay.closed.connect(ctx.app.quit)

    overlay.show()
    sampler.start()
    code = ctx.app.exec()
    sampler.stop()
    return code


def apply_live(overlay, sampler, settings):
    """One path for every settings change, from the dialog or the menu."""
    overlay.apply_theme()
    overlay.reload_layout()
    overlay.apply_always_on_top()
    sampler.set_interval(int(settings.get("interval_ms", 1000)))


if __name__ == "__main__":
    raise SystemExit(main())
