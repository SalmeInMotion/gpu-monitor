"""Preferences: the template's Appearance card plus this app's own two.

Extends the shared SettingsDialog rather than replacing it, so palette,
theme mode and accent behave exactly as in every other of Ivan's tools —
including the live preview and the Cancel that puts everything back. The
two extra cards follow the same contract: mutate settings, tell the
overlay, and let the base class restore on reject.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QPushButton, QSlider,
                               QVBoxLayout)

from app_template import SettingsDialog

from . import autostart
from . import metrics as M

# Poll rates offered. Faster than 500ms buys nothing: nvidia-smi itself
# averages over a longer window than that.
INTERVALS = ((500, "0.5s"), (1000, "1s"), (2000, "2s"), (5000, "5s"))


class PreferencesDialog(SettingsDialog):
    """Emits `changed` whenever something the overlay draws was touched."""

    changed = Signal()

    def __init__(self, settings, theme, parent=None):
        super().__init__(settings, theme, parent)
        self.setWindowTitle("GPU Monitor - Preferences")
        self.setMinimumWidth(520)
        self._insert(self._metrics_card())
        self._insert(self._overlay_card())
        self._insert(self._startup_card())

    def _insert(self, card):
        # the base class already appended the Cancel/Save row last
        self.body.insertWidget(self.body.count() - 1, card)

    # --- metrics ----------------------------------------------------------

    def _metrics_card(self):
        card = QFrame(objectName="Card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 14, 18, 16)
        lay.setSpacing(8)
        lay.addWidget(QLabel("METRICS", objectName="Kicker"))

        show = self.settings.get("show", {}) or {}
        self._metric_boxes = {}
        for group in M.GROUP_ORDER:
            lay.addWidget(QLabel(M.GROUP_LABELS[group], objectName="FieldLabel"))
            # A single row of six clipped "Core c…" labels; three columns
            # fit the longest label at this dialog width.
            grid = QGridLayout()
            grid.setHorizontalSpacing(14)
            grid.setVerticalSpacing(2)
            for i, metric in enumerate(M.metrics_in(group)):
                box = QCheckBox(metric.label)
                box.setObjectName(f"chk_{metric.key}")
                box.setChecked(bool(show.get(metric.key, metric.default)))
                box.toggled.connect(
                    lambda on, k=metric.key: self._set_metric(k, on))
                self._metric_boxes[metric.key] = box
                grid.addWidget(box, i // 3, i % 3)
            for column in range(3):
                grid.setColumnStretch(column, 1)
            lay.addLayout(grid)

        lay.addSpacing(4)
        hint = QLabel(
            "Capacity meters (VRAM, RAM, temperature) turn amber past 60% and "
            "red past 85%. Load meters (GPU, CPU, power, fan, clock) use the "
            "accent colour instead - a GPU at 95% is working, not failing.",
            objectName="Muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        return card

    def _set_metric(self, key, on):
        show = dict(self.settings.get("show", {}) or {})
        show[key] = bool(on)
        self.settings["show"] = show
        self.changed.emit()

    # --- overlay ----------------------------------------------------------

    def _overlay_card(self):
        card = QFrame(objectName="Card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 14, 18, 16)
        lay.setSpacing(8)
        lay.addWidget(QLabel("OVERLAY", objectName="Kicker"))

        self._opacity_label = QLabel(objectName="FieldLabel")
        lay.addWidget(self._opacity_label)
        self._opacity = self._slider(30, 100,
                                     int(self.settings.get("opacity", 100)),
                                     self._set_opacity, "sldOpacity")
        lay.addWidget(self._opacity)

        self._width_label = QLabel(objectName="FieldLabel")
        lay.addWidget(self._width_label)
        self._width = self._slider(220, 560,
                                   int(self.settings.get("width", 300)),
                                   self._set_width, "sldWidth")
        lay.addWidget(self._width)

        lay.addSpacing(4)
        lay.addWidget(QLabel("Refresh", objectName="FieldLabel"))
        seg = QHBoxLayout()
        seg.setSpacing(6)
        self._interval_group = QButtonGroup(self)
        current = int(self.settings.get("interval_ms", 1000))
        for ms, label in INTERVALS:
            b = QPushButton(label, objectName="SegBtn")
            b.setCheckable(True)
            # The template pins inputs to 36px but deliberately not
            # buttons, so a segmented button has to ask for its own height
            # or it clips its own text.
            b.setMinimumHeight(34)
            b.setCursor(Qt.PointingHandCursor)
            b.setChecked(ms == current)
            b.clicked.connect(lambda _=False, v=ms: self._set_interval(v))
            self._interval_group.addButton(b)
            seg.addWidget(b)
        seg.addStretch(1)
        lay.addLayout(seg)

        lay.addSpacing(6)
        self._chk_aot = self._check("Always on top", "always_on_top", True, lay)
        self._chk_locked = self._check("Lock position", "locked", False, lay)
        self._chk_compact = self._check("Compact layout", "compact", False, lay)
        self._chk_compact.toggled.connect(lambda _: self._sync_labels())
        self._chk_centre = self._check(
            "Open centred on the main screen", "centre_on_start", False, lay)
        self._chk_centre.setToolTip(
            "Also when it is already running: launching GPU Monitor again "
            "brings the card back to the middle of the main screen.")
        self._chk_anim = self._check("Animate meter changes", "animations",
                                     True, lay)
        self._chk_threshold = self._check(
            "Threshold colours on capacity meters", "threshold_colors",
            True, lay)

        self._sync_labels()
        return card

    # --- startup ----------------------------------------------------------

    def _startup_card(self):
        card = QFrame(objectName="Card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 14, 18, 16)
        lay.setSpacing(8)
        lay.addWidget(QLabel("STARTUP", objectName="Kicker"))

        # Windows is asked, not settings.json: the entry can be removed
        # from Task Manager or regedit behind the app's back, and a
        # mirrored copy would then sit here claiming the opposite.
        self._autostart_wanted = autostart.is_enabled()
        self._chk_autostart = QCheckBox("Start GPU Monitor when Windows starts")
        self._chk_autostart.setObjectName("chk_autostart")
        self._chk_autostart.setChecked(self._autostart_wanted)
        self._chk_autostart.setToolTip(autostart.launch_command())
        self._chk_autostart.toggled.connect(self._set_autostart)
        lay.addWidget(self._chk_autostart)

        self._autostart_hint = QLabel(objectName="Muted")
        self._autostart_hint.setWordWrap(True)
        lay.addWidget(self._autostart_hint)
        self._sync_autostart_hint()
        return card

    def _set_autostart(self, on):
        """Remembered, not applied — see _apply_autostart for why."""
        self._autostart_wanted = bool(on)
        self._sync_autostart_hint()

    def _sync_autostart_hint(self):
        if self._autostart_wanted and autostart.is_blocked():
            text = ("Windows currently has this entry switched off under "
                    "Task Manager > Startup apps. Saving switches it back on.")
        elif self._autostart_wanted and autostart.is_stale():
            text = ("The registered command points at an interpreter that has "
                    "since moved, so it would not start. Save to repair it.")
        else:
            text = ("Registered for your user only, so it never asks for "
                    "administrator rights. Applied when you press Save.")
        self._autostart_hint.setText(text)

    def _apply_autostart(self):
        """The one setting the base class's Cancel cannot undo.

        Everything else in this dialog lives in the settings dict, which
        reject() restores wholesale. This lives in the Windows registry,
        so it is written on Save instead of on toggle — which keeps the
        same promise (Cancel changes nothing) by the only road available.
        """
        wanted = self._autostart_wanted
        if wanted == autostart.is_enabled():
            # Already in the wanted state — but a ticked box still lies
            # while the command is stale or Windows has it disabled, and
            # re-writing the entry is what fixes both.
            if not (wanted and (autostart.is_stale()
                                or autostart.is_blocked())):
                return
        autostart.set_enabled(wanted)

    def _save(self):
        self._apply_autostart()
        super()._save()

    def _slider(self, lo, hi, value, on_change, name):
        s = QSlider(Qt.Horizontal)
        s.setObjectName(name)
        s.setRange(lo, hi)
        s.setValue(max(lo, min(hi, value)))
        s.valueChanged.connect(on_change)
        return s

    def _check(self, text, key, default, lay):
        box = QCheckBox(text)
        box.setObjectName(f"chk_{key}")
        box.setChecked(bool(self.settings.get(key, default)))
        box.toggled.connect(lambda on, k=key: self._set_flag(k, on))
        lay.addWidget(box)
        return box

    def _sync_labels(self):
        self._opacity_label.setText(f"Opacity - {self._opacity.value()}%")
        # The compact card is pinned to ia-usage's own narrow column, so
        # the slider genuinely does nothing there. Saying so beats letting
        # it look broken while it still stores the value it appears to set.
        if bool(self.settings.get("compact", False)):
            self._width_label.setText("Width - fixed while compact")
            self._width.setEnabled(False)
        else:
            self._width_label.setText(f"Width - {self._width.value()} px")
            self._width.setEnabled(True)

    def _set_opacity(self, value):
        self.settings["opacity"] = int(value)
        self._sync_labels()
        self.changed.emit()

    def _set_width(self, value):
        self.settings["width"] = int(value)
        self._sync_labels()
        self.changed.emit()

    def _set_interval(self, ms):
        self.settings["interval_ms"] = int(ms)
        self.changed.emit()

    def _set_flag(self, key, on):
        self.settings[key] = bool(on)
        self.changed.emit()

    # --- base-class hooks --------------------------------------------------

    # Keys the overlay owns and writes on its own while this dialog is
    # open. SettingsDialog.reject() restores the whole dict as it was when
    # the dialog opened, so without this, dragging the card and then
    # pressing Cancel would revert its position too.
    NOT_OURS = ("pos",)

    def reject(self):
        keep = {k: self.settings.get(k) for k in self.NOT_OURS
                if k in self.settings}
        super().reject()
        self.settings.data.update(keep)
        # the base class put the whole dict back; the overlay still has to
        # be told to re-read it
        self.changed.emit()
