"""Theme engine: chrome QSS built from tokens, applied app-wide live.

One code path serves startup and the Settings live preview, mirroring
ia-usage's ThemeHelper. "System" resolves against the Windows registry
and re-applies automatically when Windows switches modes.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QObject, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication

from . import presets
from . import tokens as T

_current_tokens = None  # last-applied token set, for runtime-painted widgets


class _ThemeBus(QObject):
    """Process-wide "theme applied" signal. Chrome that lives outside any
    single ThemeManager — a window's native DWM border colour, say — can
    subscribe here instead of every consumer wiring up the manager's own
    `changed` by hand. Emitted right after each apply()."""

    changed = Signal()


BUS = _ThemeBus()


def current_tokens():
    if _current_tokens is None:
        return T.build_tokens(True, "#FF6600")
    return _current_tokens


def preset_key(settings):
    key = settings.get("preset", presets.DEFAULT_PRESET)
    return key if key in presets.PRESETS else presets.DEFAULT_PRESET


def is_system_dark():
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            value, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
            return value == 0
    except OSError:
        return False


# --- runtime-painted icons (no binary assets to drift from the theme) -------

# Bump when the SHAPE of any painted icon changes (stroke width, dot
# diameter, chevron angle). The cache key is the colour, so without a
# revision every machine that already rendered that colour would keep
# the old drawing forever.
ICON_REV = 1


def _icon_dir(app_name):
    d = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / app_name / "icons"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _pen(p, color, width):
    pen = QPen(QColor(color))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)


def check_icon_path(app_name, color):
    png = _icon_dir(app_name) / f"check_r{ICON_REV}_{color.lstrip('#')}.png"
    if not png.exists():
        pm = QPixmap(34, 34)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        _pen(p, color, 5)
        p.drawLine(9, 17, 15, 23)
        p.drawLine(15, 23, 25, 11)
        p.end()
        pm.save(str(png))
    return png.as_posix()


def radio_dot_icon_path(app_name, color):
    """Filled dot for a checked radio. A thick QSS border renders as a
    squircle, so the circle is painted instead."""
    png = _icon_dir(app_name) / f"dot_r{ICON_REV}_{color.lstrip('#')}.png"
    if not png.exists():
        pm = QPixmap(34, 34)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color))
        p.drawEllipse(8, 8, 18, 18)
        p.end()
        pm.save(str(png))
    return png.as_posix()


def chevron_icon_path(app_name, color):
    png = _icon_dir(app_name) / f"chevron_r{ICON_REV}_{color.lstrip('#')}.png"
    if not png.exists():
        pm = QPixmap(24, 24)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        _pen(p, color, 2.4)
        p.drawLine(6, 10, 12, 16)
        p.drawLine(12, 16, 18, 10)
        p.end()
        pm.save(str(png))
    return png.as_posix()


# --- chrome ------------------------------------------------------------------

def chrome_qss(t, check_png, chevron_png, radio_png):
    """The shared chrome: window, title bar, labels, inputs, buttons,
    menus, scrollbars, dialogs. Apps restate any selector to override."""
    return f"""
* {{
    font-family: {t['FONT_STACK']};
    font-size: 13px;
    color: {t['TEXT']};
}}

/* The window is opaque now, so DWM draws the border + shadow, rounds the
   corners AND clips the whole window to that shape (Windows 11) — which is
   what keeps the close button's red hover fill from painting a hard square
   past the rounded corner. Border colour and radius are set natively in
   window.py; nothing to round or outline in the sheet. */
QWidget#Root {{
    background-color: {t['BG']};
}}

/* --- title bar -------------------------------------------------------- */

QWidget#TitleBar {{
    background-color: {t['BG']};
}}
QLabel#TitleText {{
    font-size: 14px;
    font-weight: 500;
    color: {t['TEXT']};
}}
QPushButton#WinBtn, QPushButton#CloseBtn {{
    background: transparent;
    border: none;
    border-radius: 0px;
}}
QPushButton#WinBtn:hover {{
    background-color: {t['SURFACE_HOVER']};
}}
QPushButton#CloseBtn:hover {{
    background-color: {t['CLOSE_HOVER']};
}}
QPushButton#CloseBtn:pressed {{
    background-color: {t['CLOSE_PRESSED']};
}}

/* --- labels ----------------------------------------------------------- */

QLabel#H4 {{
    font-size: 20px;
    font-weight: 500;
    color: {t['TEXT']};
}}
QLabel#Muted {{
    font-size: 13px;
    color: {t['TEXT_55']};
}}
QLabel#Kicker {{
    font-size: 10px;
    font-weight: 600;
    color: {t['ACCENT']};
}}
QLabel#Warning {{
    font-size: 12px;
    color: {t['ACCENT_300']};
}}
QLabel#FieldLabel {{
    font-size: 12px;
    color: {t['TEXT_55']};
}}
QLabel#Ok {{
    color: {t['OK']};
}}
QLabel#Error {{
    color: {t['ERROR']};
}}

/* --- cards ------------------------------------------------------------ */

QFrame#Card {{
    background-color: {t['SURFACE']};
    border-radius: {t['RADIUS_MD']}px;
}}

/* --- inputs ----------------------------------------------------------- */

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox {{
    min-height: 36px;
    padding: 6px 10px;
    font-size: 14px;
    color: {t['TEXT']};
    background-color: {t['SURFACE']};
    border: 1px solid {t['DIVIDER']};
    border-radius: {t['RADIUS_MD']}px;
    selection-background-color: {t['ACCENT']};
    selection-color: {t['ON_ACCENT']};
}}
QPlainTextEdit, QTextEdit {{
    font-size: 13px;
}}

/* log / code panel: monospaced, darker ground, meant to scroll both ways */
QPlainTextEdit#Code, QTextEdit#Code {{
    font-family: {t['MONO_STACK']};
    font-size: 12px;
    color: {t['CODE_TEXT']};
    background-color: {t['CODE_BG']};
    border: 1px solid {t['DIVIDER']};
    border-radius: {t['RADIUS_MD']}px;
    padding: 10px;
}}
QPlainTextEdit#Code:focus, QTextEdit#Code:focus {{
    border-color: {t['ACCENT']};
}}
QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover,
QSpinBox:hover, QDoubleSpinBox:hover {{
    border-color: {t['TEXT_45']};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {t['ACCENT']};
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    width: 0px;
    border: none;
}}

/* --- buttons ---------------------------------------------------------- */

QPushButton {{
    background-color: {t['SURFACE']};
    border: 1px solid {t['DIVIDER']};
    border-radius: {t['RADIUS_MD']}px;
    padding: 7px 18px;
}}
QPushButton:hover {{
    border-color: {t['ACCENT']};
    color: {t['ACCENT']};
}}
QPushButton:pressed {{
    background-color: {t['SURFACE_HOVER']};
}}
QPushButton:disabled {{
    color: {t['TEXT_45']};
    border-color: {t['DIVIDER']};
}}

QPushButton#Primary {{
    background-color: {t['ACCENT']};
    border: none;
    color: {t['ON_ACCENT']};
    font-weight: 500;
    padding: 8px 22px;
}}
QPushButton#Primary:hover {{
    background-color: {t['ACCENT_600']};
    color: {t['ON_ACCENT']};
}}
QPushButton#Primary:pressed {{
    background-color: {t['ACCENT_700']};
}}
QPushButton#Primary:disabled {{
    background-color: {t['SURFACE']};
    color: {t['TEXT_45']};
}}

QPushButton#Ghost {{
    color: {t['ACCENT']};
    background: transparent;
    border: 1.5px solid {t['ACCENT']};
    font-weight: 500;
}}
QPushButton#Ghost:hover {{
    background-color: {t['ACCENT_900']};
    color: {t['ACCENT']};
}}
QPushButton#Ghost:pressed {{
    background-color: {t['ACCENT_800']};
}}

QPushButton#Link {{
    background: transparent;
    border: none;
    color: {t['TEXT_70']};
    font-size: 13px;
    padding: 3px 2px;
    text-align: left;
}}
QPushButton#Link:hover {{
    color: {t['ACCENT']};
}}

QPushButton#SegBtn {{
    background: transparent;
    border: 1px solid {t['DIVIDER']};
    border-radius: {t['RADIUS_MD']}px;
    padding: 6px 16px;
    color: {t['TEXT_55']};
}}
QPushButton#SegBtn:hover {{
    color: {t['TEXT']};
}}
QPushButton#SegBtn:checked {{
    background-color: {t['SURFACE_HOVER']};
    border-color: {t['ACCENT']};
    color: {t['ACCENT']};
    font-weight: 500;
}}

/* --- checks and radios ------------------------------------------------ */

QCheckBox {{
    spacing: 8px;
    /* 28, not 24, for the same reason as the radio below: the indicator's
       BORDER box is 17 + 2*ceil(1.5) = 21px, and a 24px row left 1.5px of
       slack - which a fractional display scale (1.25, 1.5) rounds away,
       clipping the top row of the box's border clean off. Seen for real on a
       125% vertical monitor in Capture-o-matic. 28 leaves 3.5px a side, more
       than any rounding can eat. */
    min-height: 28px;
    color: {t['TEXT']};
}}
QCheckBox::indicator {{
    width: 17px;
    height: 17px;
    border-radius: 4px;
    border: 1.5px solid {t['DIVIDER']};
    background: transparent;
}}
QCheckBox::indicator:hover {{
    border-color: {t['ACCENT_400']};
}}
QCheckBox::indicator:checked {{
    background-color: {t['ACCENT']};
    border-color: {t['ACCENT']};
    image: url("{check_png}");
}}

QRadioButton {{
    spacing: 8px;
    /* The indicator's border box is 18 + 2*ceil(1.5) = 22px. A 24px row left
       ONE pixel of slack a side, which fractional display scaling rounds
       away - the same clip the checkbox above was showing. 28px settles it. */
    min-height: 28px;
    color: {t['TEXT']};
}}
QRadioButton::indicator {{
    width: 18px;
    height: 18px;
    /* QSS width/height are the CONTENT box while border-radius applies to
       the BORDER box: 18 + 2*ceil(1.5) = 22, so a true circle needs 11.
       At 9 the ring kept a flat 4px chord across the top and bottom. */
    border-radius: 11px;
    border: 1.5px solid {t['DIVIDER']};
    background: transparent;
}}
QRadioButton::indicator:hover {{
    border-color: {t['ACCENT_400']};
}}
QRadioButton::indicator:checked {{
    border: 1.5px solid {t['ACCENT']};
    image: url("{radio_png}");
}}

/* --- combo ------------------------------------------------------------ */

QComboBox {{
    min-height: 36px;
    padding: 6px 30px 6px 10px;
    font-size: 14px;
    background-color: {t['SURFACE']};
    border: 1px solid {t['DIVIDER']};
    border-radius: {t['RADIUS_MD']}px;
}}
QComboBox:hover {{
    border-color: {t['TEXT_45']};
}}
QComboBox:focus {{
    border-color: {t['ACCENT']};
}}
QComboBox::drop-down {{
    border: none;
    width: 28px;
}}
QComboBox::down-arrow {{
    image: url("{chevron_png}");
    width: 12px;
    height: 12px;
}}
QComboBox QAbstractItemView {{
    background-color: {t['SURFACE']};
    border: 1px solid {t['DIVIDER']};
    border-radius: {t['RADIUS_MD']}px;
    padding: 4px;
    outline: none;
    selection-background-color: {t['SURFACE_HOVER']};
    selection-color: {t['ACCENT']};
}}

/* --- slider / progress ------------------------------------------------ */

QSlider::groove:horizontal {{
    height: 4px;
    background: {t['DIVIDER']};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {t['ACCENT']};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    width: 16px;
    height: 16px;
    margin: -6px 0;
    background: {t['ACCENT']};
    border-radius: 8px;
}}
QSlider::handle:horizontal:hover {{
    background: {t['ACCENT_400']};
}}

QProgressBar {{
    background-color: {t['SURFACE']};
    border: none;
    border-radius: 3px;
    max-height: 6px;
}}
QProgressBar::chunk {{
    background-color: {t['ACCENT']};
    border-radius: 3px;
}}

/* --- rules ------------------------------------------------------------ */

QFrame#Rule, QFrame#FooterRule {{
    background-color: {t['DIVIDER']};
    max-height: 1px;
    min-height: 1px;
    border: none;
}}

/* --- scroll ----------------------------------------------------------- */

QScrollArea {{
    background: transparent;
    border: none;
}}
QScrollArea > QWidget > QWidget {{
    background: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0px;
}}
QScrollBar::handle:vertical {{
    background: {t['SCROLL_HANDLE']};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {t['SCROLL_HANDLE_HOVER']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 0px;
}}
QScrollBar::handle:horizontal {{
    background: {t['SCROLL_HANDLE']};
    border-radius: 5px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {t['SCROLL_HANDLE_HOVER']};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

/* where the two bars meet, Fusion would paint a grey square */
QAbstractScrollArea::corner {{
    background: transparent;
    border: none;
}}

/* --- menus, tooltips, dialogs ----------------------------------------- */

QMenu {{
    background-color: {t['SURFACE']};
    border: 1px solid {t['DIVIDER']};
    border-radius: {t['RADIUS_MD']}px;
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 22px 7px 14px;
    border-radius: {t['RADIUS_SM']}px;
}}
QMenu::item:selected {{
    background-color: {t['SURFACE_HOVER']};
    color: {t['ACCENT']};
}}
QMenu::separator {{
    height: 1px;
    background: {t['DIVIDER']};
    margin: 5px 8px;
}}
QToolTip {{
    background-color: {t['SURFACE']};
    border: 1px solid {t['DIVIDER']};
    border-radius: {t['RADIUS_MD']}px;
    padding: 6px 8px;
    color: {t['TEXT']};
}}
QDialog, QMessageBox, QInputDialog {{
    background-color: {t['BG']};
}}
"""


class ThemeManager(QObject):
    """Owns preset + theme + accent resolution and applies the QSS
    app-wide, emitting `changed` so custom-painted widgets can refresh.

    brand_accent is the app's "Original" color; brand_accent_dark is an
    optional dark-theme variant for brands that vanish on dark ground
    (ia-usage's navy needed one; Houdini orange doesn't).
    """

    changed = Signal()

    def __init__(self, app_name, settings, brand_accent="#FF6600",
                 brand_accent_dark=None, extra_qss=""):
        super().__init__()
        self.app_name = app_name
        self.settings = settings
        self.brand_accent = brand_accent
        self.brand_accent_dark = brand_accent_dark
        self.extra_qss = extra_qss
        self.tokens = None
        app = QApplication.instance()
        hints = app.styleHints() if app else None
        if hints is not None and hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(self._on_system_scheme_changed)

    def is_dark(self):
        mode = self.settings.get("theme", "system")
        if mode == "light":
            return False
        if mode == "dark":
            return True
        return is_system_dark()

    def preset(self):
        return preset_key(self.settings)

    def original_accent_hex(self):
        """What the "Original" sentinel resolves to right now — the app's
        own brand colour on the house preset, the preset's own designed
        accent on any other one, in either case with the dark-mode
        sibling when the brand has one.

        Kept separate from accent_hex() because the Settings dialog has to
        paint the Original swatch even while a custom accent is selected.
        """
        key = self.preset()
        if key != presets.DEFAULT_PRESET:
            return presets.brand_accent(key, self.is_dark())
        if self.is_dark() and self.brand_accent_dark:
            return self.brand_accent_dark
        return self.brand_accent

    def accent_hex(self):
        accent = self.settings.get("accent", T.ORIGINAL_ACCENT)
        if accent != T.ORIGINAL_ACCENT:
            return accent
        return self.original_accent_hex()

    def apply(self):
        global _current_tokens
        t = T.build_tokens(self.is_dark(), self.accent_hex(), self.preset())
        self.tokens = t
        _current_tokens = t
        check = check_icon_path(self.app_name, t["ON_ACCENT"])
        chevron = chevron_icon_path(self.app_name, t["TEXT_55"])
        radio = radio_dot_icon_path(self.app_name, t["ACCENT"])
        qss = chrome_qss(t, check, chevron, radio)
        # extra_qss may be a string or a callable(tokens)->str; a callable
        # lets an app's own widget styles track the live theme instead of
        # freezing at the colours captured when create_app ran
        extra = self.extra_qss(t) if callable(self.extra_qss) else self.extra_qss
        if extra:
            qss = qss + "\n" + extra
        QApplication.instance().setStyleSheet(qss)
        self.changed.emit()
        BUS.changed.emit()

    def _on_system_scheme_changed(self, *_):
        if self.settings.get("theme", "system") == "system":
            self.apply()
