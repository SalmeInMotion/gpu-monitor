"""Settings dialog — Appearance card with theme mode and accent swatches.

Live preview: every change applies app-wide immediately (the same code
path as startup, like ia-usage). Cancel restores the state the dialog
opened with; Save persists to disk.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QDialog,
                               QFrame, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from . import presets
from . import theme as theme_mod
from . import tokens as T
from .window import TitleBar, _NativeChrome


class Swatch(QPushButton):
    """A round accent color sample; the checked one wears a ring."""

    def __init__(self, color_hex, tooltip="", parent=None):
        super().__init__(parent)
        self.color_hex = color_hex
        self.setCheckable(True)
        self.setFixedSize(30, 30)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tooltip or color_hex)
        self.setObjectName("Swatch")
        self.setStyleSheet("background: transparent; border: none;")

    def paintEvent(self, event):  # noqa: N802 - Qt naming
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self.color_hex))
        p.drawEllipse(int(cx - 10), int(cy - 10), 20, 20)
        if self.isChecked():
            pen = QPen(QColor(theme_mod.current_tokens()["TEXT"]))
            pen.setWidthF(2.0)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(int(cx - 13), int(cy - 13), 26, 26)
        p.end()


class PresetChip(QPushButton):
    """A palette shown as a miniature of itself: its own ground, a card,
    its accent and its text, so it can be judged before being applied."""

    def __init__(self, key, dark=True, accent=None, parent=None):
        super().__init__(parent)
        self.key = key
        data = presets.preset(key)
        # the mode the app is showing right now, not the system's
        self.pal = data["dark" if dark else "light"]
        # `accent` overrides the preset's own for the house preset, where
        # "Original" means the *app's* brand colour: without it the chip
        # promises Houdini orange in an app whose brand is navy, and
        # clicking it repaints everything navy instead.
        self.accent = accent or presets.brand_accent(key, dark)
        self.title = data["name"]
        self.setCheckable(True)
        self.setFixedSize(104, 62)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(presets.BLURBS.get(key, self.title))
        self.setObjectName("PresetChip")
        self.setProperty("noReveal", True)  # the chip is a swatch, not a button
        self.setStyleSheet("background: transparent; border: none;")

    def refresh(self, dark, accent=None):
        data = presets.preset(self.key)
        self.pal = data["dark"] if dark else data["light"]
        self.accent = accent or presets.brand_accent(self.key, dark)
        self.update()

    def paintEvent(self, event):  # noqa: N802 - Qt naming
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        radius = 7.0

        body = QPainterPath()
        body.addRoundedRect(r, radius, radius)
        p.fillPath(body, QColor(self.pal["BG"]))

        # a card floating on the ground, as in the real UI
        card = QRectF(r.x() + 7, r.y() + 8, r.width() - 14, 20)
        card_path = QPainterPath()
        card_path.addRoundedRect(card, 4, 4)
        p.fillPath(card_path, QColor(self.pal["SURFACE"]))

        # accent dot + two text bars, the three things the eye checks
        p.setBrush(QColor(self.accent))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(card.x() + 5, card.y() + 6, 8, 8))
        p.setBrush(QColor(self.pal["TEXT"]))
        p.drawRoundedRect(QRectF(card.x() + 18, card.y() + 7, 30, 3), 1.5, 1.5)
        p.setBrush(QColor(self.pal["TEXT_55"]))
        p.drawRoundedRect(QRectF(card.x() + 18, card.y() + 13, 20, 3), 1.5, 1.5)

        p.setPen(QColor(self.pal["TEXT"]))
        font = p.font()
        font.setPointSizeF(8.0)
        p.setFont(font)
        p.drawText(QRectF(r.x(), r.bottom() - 20, r.width(), 18),
                   Qt.AlignHCenter | Qt.AlignVCenter, self.title)

        ring = QColor(theme_mod.current_tokens()["ACCENT"]) if self.isChecked() \
            else QColor(self.pal["DIVIDER"])
        pen = QPen(ring)
        pen.setWidthF(2.0 if self.isChecked() else 1.0)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(body)
        p.end()


class SettingsDialog(_NativeChrome, QDialog):
    """Frameless settings dialog. Extend by adding cards to self.body."""

    def __init__(self, settings, theme, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.theme = theme
        self._entry_state = dict(settings.data)

        # opaque + native frameless (see window._NativeChrome): DWM rounds,
        # clips and borders it, matching the main window and keeping the
        # close button's hover fill inside the rounded corner
        self.setWindowFlags(Qt.Dialog)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(480)
        self._resizable = False

        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        root = QWidget(objectName="Root")
        shell.addWidget(root)
        root_lay = QVBoxLayout(root)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)

        self.title_bar = TitleBar("Settings", buttons=("close",), parent=root)
        self.title_bar.btn_close.clicked.connect(self.reject)
        root_lay.addWidget(self.title_bar)

        body_host = QWidget(root)
        self.body = QVBoxLayout(body_host)
        self.body.setContentsMargins(20, 8, 20, 20)
        self.body.setSpacing(12)
        root_lay.addWidget(body_host, 1)

        self.body.addWidget(self._appearance_card())

        # With Theme=System, Windows can flip mode while this dialog is
        # open: the chrome restyles itself but the chips and the Original
        # swatch are painted by hand and would keep the old mode's colours.
        self.theme.changed.connect(self._refresh_previews)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_save = QPushButton("Save", objectName="Primary")
        btn_save.clicked.connect(self._save)
        buttons.addWidget(btn_cancel)
        buttons.addWidget(btn_save)
        self.body.addLayout(buttons)

        self._init_native()

    # --- appearance card --------------------------------------------------

    def _house_accent(self, key):
        """What "Original" would resolve to for this preset's chip.

        Only the house preset needs one: there Original is the app's own
        brand colour, which the preset table knows nothing about. Every
        other chip returns None and falls back to its preset's accent.
        """
        if key != presets.DEFAULT_PRESET:
            return None
        if self.theme.is_dark() and self.theme.brand_accent_dark:
            return self.theme.brand_accent_dark
        return self.theme.brand_accent

    def _appearance_card(self):
        card = QFrame(objectName="Card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 14, 18, 16)
        lay.setSpacing(8)

        title = QLabel("APPEARANCE", objectName="Kicker")
        lay.addWidget(title)

        lay.addWidget(QLabel("Palette", objectName="FieldLabel"))
        chips = QHBoxLayout()
        chips.setSpacing(6)
        self._preset_group = QButtonGroup(self)
        self._chips = []
        current_preset = theme_mod.preset_key(self.settings)
        for key in presets.PRESETS:
            chip = PresetChip(key, dark=self.theme.is_dark(),
                              accent=self._house_accent(key))
            chip.setChecked(key == current_preset)
            chip.clicked.connect(lambda _=False, k=key: self._set_preset(k))
            self._preset_group.addButton(chip)
            self._chips.append(chip)
            chips.addWidget(chip)
        chips.addStretch(1)
        lay.addLayout(chips)

        lay.addSpacing(4)
        lay.addWidget(QLabel("Theme", objectName="FieldLabel"))
        seg = QHBoxLayout()
        seg.setSpacing(6)
        self._theme_group = QButtonGroup(self)
        for label, value in (("System", "system"), ("Light", "light"),
                             ("Dark", "dark")):
            b = QPushButton(label, objectName="SegBtn")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setChecked(self.settings.get("theme", "system") == value)
            b.clicked.connect(lambda _=False, v=value: self._set_theme(v))
            self._theme_group.addButton(b)
            seg.addWidget(b)
        seg.addStretch(1)
        lay.addLayout(seg)

        lay.addSpacing(4)
        lay.addWidget(QLabel("Accent color", objectName="FieldLabel"))
        row = QHBoxLayout()
        row.setSpacing(4)
        self._swatch_group = QButtonGroup(self)
        current = self.settings.get("accent", T.ORIGINAL_ACCENT)

        original = Swatch(self.theme.original_accent_hex(), "Original")
        original.accent_value = T.ORIGINAL_ACCENT
        original.setChecked(current == T.ORIGINAL_ACCENT)
        self._original_swatch = original
        self._wire_swatch(original, row)

        for hex_color in T.ACCENT_SWATCHES:
            s = Swatch(hex_color)
            s.accent_value = hex_color
            s.setChecked(current == hex_color)
            self._wire_swatch(s, row)
        row.addStretch(1)
        lay.addLayout(row)

        lay.addSpacing(6)
        self._glow = QCheckBox("Button hover glow", objectName="chkGlow")
        self._glow.setChecked(bool(self.settings.get("hover_glow", True)))
        self._glow.toggled.connect(self._set_glow)
        lay.addWidget(self._glow)
        return card

    def _set_glow(self, on):
        from .effects import install_hover_reveal, remove_hover_reveal
        self.settings["hover_glow"] = bool(on)
        app = QApplication.instance()
        if on:
            install_hover_reveal(app)
        else:
            remove_hover_reveal(app)

    def _wire_swatch(self, swatch, row):
        self._swatch_group.addButton(swatch)
        swatch.clicked.connect(
            lambda _=False, s=swatch: self._set_accent(s.accent_value))
        row.addWidget(swatch)

    # --- live preview + persistence ---------------------------------------

    def _set_preset(self, key):
        self.settings["preset"] = key
        self.theme.apply()
        self._refresh_previews()

    def _set_theme(self, value):
        self.settings["theme"] = value
        self.theme.apply()
        self._refresh_previews()

    def _set_accent(self, value):
        self.settings["accent"] = value
        self.theme.apply()
        self._refresh_previews()

    def _refresh_previews(self):
        """Chips mirror the live theme mode, and the Original swatch has to
        follow the preset it now stands for."""
        dark = self.theme.is_dark()
        for chip in self._chips:
            chip.refresh(dark, self._house_accent(chip.key))
        original = getattr(self, "_original_swatch", None)
        if original is not None:
            original.color_hex = self.theme.original_accent_hex()
            original.update()

    def _save(self):
        self.settings.save()
        self.accept()

    def reject(self):
        self.settings.data.clear()
        self.settings.data.update(self._entry_state)
        self.theme.apply()
        # the glow is a live app-wide filter, so it has to be put back too
        self._set_glow(bool(self.settings.get("hover_glow", True)))
        super().reject()
