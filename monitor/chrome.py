"""The little circular icon buttons, and the glyphs they wear.

Lives apart from overlay.py so the process panel can use the same button
without importing the overlay that imports it. Nothing here knows about
the card or the panel; it is the ia-usage chrome recipe and nothing else:
a 26px transparent circle that only fills in on hover.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QToolButton

# Segoe MDL2 Assets codepoints. E711/E713 are the two ia-usage itself
# uses; the pin and collapse pairs are the closest stock equivalents of
# its emoji pin and its Material Symbols collapse/expand pair.
GLYPH_CLOSE = ""
GLYPH_SETTINGS = ""
GLYPH_PIN = ""
GLYPH_UNPIN = ""
GLYPH_COMPACT = ""
GLYPH_EXPAND = ""
# The panel's own Refresh (U+E72C). It has one because the list no longer
# re-sorts itself under the pointer -- see ProcessPanel.
GLYPH_REFRESH = ""
# "keep above": an arrow to a top bar (U+E898). Distinct from the pin the
# Lock button uses, so the two window toggles do not read as the same idea.
GLYPH_TOP = ""


def icon_font_family():
    """Win11 ships Segoe Fluent Icons and keeps Segoe MDL2 Assets for
    compatibility; the codepoints used here exist in both."""
    families = QFontDatabase.families()
    for name in ("Segoe MDL2 Assets", "Segoe Fluent Icons"):
        if name in families:
            return name
    return "Segoe UI Symbol"


class ChromeButton(QToolButton):
    """26px circle, transparent until hovered — ia-usage's chrome recipe."""

    def __init__(self, glyph, tooltip, parent=None, checkable=False):
        super().__init__(parent)
        self.setObjectName("Chrome")
        self.setProperty("noReveal", True)  # the template's glow is not this look
        self.setFixedSize(26, 26)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setCheckable(checkable)
        self.setToolTip(tooltip)
        self.set_glyph(glyph)

    def set_glyph(self, glyph):
        self.setText(glyph)


def chrome_qss(t):
    """The button's styling, from a token set. Shared so the card and the
    panel cannot drift apart on it."""
    return f"""
QToolButton#Chrome {{
    border: none;
    border-radius: 13px;
    background: transparent;
    color: {t['TEXT_55']};
    font-family: "{icon_font_family()}";
    font-size: 11px;
}}
QToolButton#Chrome:hover   {{ background: rgba(128, 128, 128, 20); }}
QToolButton#Chrome:pressed {{ background: rgba(128, 128, 128, 34); }}
QToolButton#Chrome:checked {{ color: {t['TEXT']}; }}
"""
