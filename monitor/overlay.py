"""The floating card: an always-on-top panel wearing ia-usage's skin.

Structure mirrors the original's, and for the same reasons (see the WPF
comments it was ported from): a translucent top-level whose only job is
to hold a 6px gutter, and inside it the real card, which paints its own
16px radius and carries the drop shadow. Qt ignores a
QGraphicsDropShadowEffect on a top-level window and clips a QSS
border-radius to the widget rect, so both have to be done this way round.

Chrome sits over the top-right corner exactly as in ia-usage, but at 0.35
opacity until the pointer is on the card: a tray popup that dies when you
look away can afford invisible controls, a window that never closes
itself cannot.
"""

from __future__ import annotations

import logging
import os

from PySide6.QtCore import (QEasingCurve, QPoint, QPropertyAnimation, QRect,
                            QRectF, Qt, QTimer, Signal)
from PySide6.QtGui import (QAction, QActionGroup, QColor, QFontDatabase,
                           QFontMetrics, QGuiApplication, QPainter,
                           QPainterPath, QPen)
from PySide6.QtWidgets import (QApplication, QGraphicsOpacityEffect,
                               QHBoxLayout, QLabel, QMenu, QSizePolicy,
                               QToolButton, QToolTip, QVBoxLayout, QWidget)

from . import metrics as M
from .meter import (CASCADE_STEP_MS, MeterRow, SectionHeader, flat_gradient,
                    ramp_colors)

log = logging.getLogger("gpu_monitor.overlay")

GUTTER = 6            # shadow room; ia-usage's ChromeReserve
CARD_RADIUS = 16.0
PAD = 20              # card padding, full layout
PAD_COMPACT = 12
HEADER_GAP = 12       # below a section header
HEADER_GAP_COMPACT = 6
BLOCK_GAP = 18        # between service blocks
BLOCK_GAP_COMPACT = 8
ROW_GAP = 14          # between meter rows
ROW_GAP_COMPACT = 6

# Below this share of the card sitting on working desktop, it counts as
# lost rather than merely parked off an edge, and is nudged back. Low
# enough that a deliberately half-hidden card is left alone.
MIN_VISIBLE = 0.34

CHROME_REST_OPACITY = 0.35
CHROME_FADE_MS = 120

# ia-usage's popup shadow: blur 10, straight down by 2, black at 22%.
SHADOW_BLUR = GUTTER
SHADOW_OFFSET_Y = 2
SHADOW_ALPHA = 56

# Segoe MDL2 Assets codepoints. E711/E713 are the two ia-usage itself
# uses; the pin and collapse pairs are the closest stock equivalents of
# its emoji pin and its Material Symbols collapse/expand pair.
GLYPH_CLOSE = ""
GLYPH_SETTINGS = ""
GLYPH_PIN = ""
GLYPH_UNPIN = ""
GLYPH_COMPACT = ""
GLYPH_EXPAND = ""


# "keep above": an arrow to a top bar (Segoe MDL2 U+E898). Distinct from
# the pin the Lock button uses, so the two window toggles do not read as
# the same idea.
GLYPH_TOP = ""

# Re-asserting topmost each tick is how "always on top" beats *other*
# topmost windows: Qt's WindowStaysOnTopHint is applied once, so a window
# raised to topmost later still lands above it. SetWindowPos with
# HWND_TOPMOST and SWP_NOACTIVATE returns the card to the top without
# stealing focus. Nothing beats an exclusive-fullscreen game, which
# bypasses the compositor entirely, and that is left alone.
if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32
    _user32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    _user32.SetWindowPos.restype = wintypes.BOOL
    _HWND_TOPMOST = -1
    _HWND_NOTOPMOST = -2
    _SWP_KEEP = 0x0001 | 0x0002 | 0x0010   # NOSIZE | NOMOVE | NOACTIVATE
    _VK_LBUTTON = 0x01


def _repolish(root):
    """Re-evaluate QSS for a subtree after a property on an ancestor changed.

    The compact rules are descendant selectors hanging off
    `QWidget#Card[compact="true"]`, so flipping that property on the card
    alone leaves every label with the font it was polished with. Measured
    before this existed: rows stayed 49px instead of 51 coming out of
    compact, because their labels were still 10px.
    """
    for widget in [root] + root.findChildren(QWidget):
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.updateGeometry()


def _resize(spacer, height):
    """changeSize resets a spacer's size policy to its defaults unless
    both are passed, and QLayout.addSpacing's spacers are Minimum/Fixed."""
    spacer.changeSize(0, height, QSizePolicy.Minimum, QSizePolicy.Fixed)


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


class Card(QWidget):
    """Paints the sheet everything else sits on."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._fill = QColor("#fafafa")

    def set_fill(self, color_hex, alpha):
        c = QColor(color_hex)
        c.setAlpha(alpha)
        self._fill = c
        self.update()

    def paintEvent(self, event):  # noqa: N802 - Qt naming
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(self._fill)
        p.drawRoundedRect(QRectF(self.rect()), CARD_RADIUS, CARD_RADIUS)
        p.end()


class Overlay(QWidget):
    """The window. Owns the rows, the chrome and the settings it mirrors."""

    prefs_requested = Signal()
    # Qt.Tool windows do not reliably carry WA_QuitOnClose, so the app is
    # told to exit explicitly rather than relying on quitOnLastWindowClosed.
    closed = Signal()

    def __init__(self, settings, theme, parent=None):
        flags = Qt.FramelessWindowHint | Qt.Tool  # Tool == not in the taskbar
        if bool(settings.get("always_on_top", True)):
            flags |= Qt.WindowStaysOnTopHint
        super().__init__(parent, flags)
        self.settings = settings
        self.theme = theme
        self._rows = {}
        self._headers = {}
        self._errors = {}
        self._blocks = {}
        self._first_fill = True
        self._got_sample = False
        # metric keys that have produced a reading at least once: a
        # machine with no temperature sensor should not show a
        # permanent "--" row for it
        self._sensed = set()
        self._sample = {}
        self._gpu_name = None
        self._shown_groups = []
        self._user_moved = False
        self._centre_pending = False
        self._last_fit_height = -1

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setWindowTitle("GPU Monitor")

        shell = QVBoxLayout(self)
        shell.setContentsMargins(GUTTER, GUTTER, GUTTER, GUTTER)
        shell.setSpacing(0)
        self.card = Card(self)
        shell.addWidget(self.card)

        # The shadow is painted here, in the window, rather than with a
        # QGraphicsDropShadowEffect on the card: that effect renders the
        # shadow behind the card's whole silhouette, so once the Opacity
        # setting makes the card fill translucent, what shows through is
        # the shadow rather than the desktop — a grey film over the whole
        # card that gets worse the more transparent it is asked to be.

        self.body = QVBoxLayout(self.card)
        self.body.setContentsMargins(PAD, PAD, PAD, PAD)
        self.body.setSpacing(0)

        self._build_chrome()
        self._build_blocks()

        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.setInterval(0)
        self._fit_timer.timeout.connect(self._fit)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(600)
        self._save_timer.timeout.connect(self._persist_position)

        self.card.installEventFilter(self)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)

        self.theme.changed.connect(self.apply_theme)
        self.apply_theme()
        self.reload_layout()
        self._restore_position()

    # --- construction -----------------------------------------------------

    def _build_chrome(self):
        self.chrome = QWidget(self.card)
        lay = QHBoxLayout(self.chrome)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.btn_top = ChromeButton(GLYPH_TOP, "Always on top",
                                    self.chrome, checkable=True)
        self.btn_lock = ChromeButton(GLYPH_UNPIN, "Lock position",
                                     self.chrome, checkable=True)
        self.btn_compact = ChromeButton(GLYPH_COMPACT, "Compact layout",
                                        self.chrome, checkable=True)
        self.btn_prefs = ChromeButton(GLYPH_SETTINGS, "Preferences", self.chrome)
        self.btn_close = ChromeButton(GLYPH_CLOSE, "Quit", self.chrome)
        for b in (self.btn_top, self.btn_lock, self.btn_compact,
                  self.btn_prefs, self.btn_close):
            lay.addWidget(b)

        self.btn_top.toggled.connect(self._on_aot_toggled)
        self.btn_lock.toggled.connect(self._on_lock_toggled)
        self.btn_compact.toggled.connect(self._on_compact_toggled)
        self.btn_prefs.clicked.connect(self.prefs_requested)
        self.btn_close.clicked.connect(self.close)

        self._chrome_fx = QGraphicsOpacityEffect(self.chrome)
        self._chrome_fx.setOpacity(CHROME_REST_OPACITY)
        self.chrome.setGraphicsEffect(self._chrome_fx)
        self._chrome_anim = QPropertyAnimation(self._chrome_fx, b"opacity", self)
        self._chrome_anim.setDuration(CHROME_FADE_MS)
        self._chrome_anim.setEasingCurve(QEasingCurve.OutCubic)

    def _build_blocks(self):
        """One block per group: header, rows, and the error line that
        replaces the rows when the whole group has no data."""
        for group in M.GROUP_ORDER:
            block = QWidget(self.card)
            lay = QVBoxLayout(block)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(0)

            kind = (SectionHeader.GPU if group == M.GROUP_GPU
                    else SectionHeader.SYSTEM)
            header = SectionHeader(kind, M.GROUP_LABELS[group], block)
            lay.addWidget(header)
            lay.addSpacing(HEADER_GAP)

            error = QLabel("no GPU readings available"
                           if group == M.GROUP_GPU
                           else "psutil not installed", block)
            error.setProperty("role", "error")
            error.setWordWrap(True)
            error.setVisible(False)
            lay.addWidget(error)

            for metric in M.metrics_in(group):
                row = MeterRow(metric, block)
                lay.addWidget(row)
                lay.addSpacing(ROW_GAP)
                self._rows[metric.key] = row

            self._headers[group] = header
            self._errors[group] = error
            self._blocks[group] = block
            self.body.addWidget(block)
            self.body.addSpacing(BLOCK_GAP)

        self.body.addStretch(0)

    # --- settings-driven layout -------------------------------------------

    def _compact(self):
        return bool(self.settings.get("compact", False))

    def reload_layout(self):
        """Re-read every setting that changes what the card looks like."""
        compact = self._compact()

        pad = PAD_COMPACT if compact else PAD
        self.body.setContentsMargins(pad, pad, pad, pad)
        self.card.setProperty("compact", "true" if compact else "false")
        _repolish(self.card)

        for group in M.GROUP_ORDER:
            self._headers[group].set_compact(compact)
            for metric in M.metrics_in(group):
                self._rows[metric.key].set_compact(compact)

        self.btn_compact.blockSignals(True)
        self.btn_compact.setChecked(compact)
        self.btn_compact.set_glyph(GLYPH_EXPAND if compact else GLYPH_COMPACT)
        self.btn_compact.blockSignals(False)
        self.btn_lock.blockSignals(True)
        locked = bool(self.settings.get("locked", False))
        self.btn_lock.setChecked(locked)
        self.btn_lock.set_glyph(GLYPH_PIN if locked else GLYPH_UNPIN)
        self.btn_lock.blockSignals(False)
        self.btn_top.blockSignals(True)
        self.btn_top.setChecked(bool(self.settings.get("always_on_top", True)))
        self.btn_top.blockSignals(False)

        width = int(self.settings.get("width", 300))
        if compact:
            width = min(width, 214)
        self.setFixedWidth(width + 2 * GUTTER)
        self._render(self._sample, animate=False)

    def _enabled_metrics(self, group):
        show = self.settings.get("show", {}) or {}
        return [m for m in M.metrics_in(group)
                if bool(show.get(m.key, m.default))]

    def _has_sensor(self, metric):
        """Whether this machine can read this metric at all.

        On an AMD or Intel GPU the Windows counters give utilisation and
        video memory but no temperature, power, fan or clock — those come
        only from nvidia-smi. Showing four rows permanently reading "--"
        would say "broken" when the honest answer is "not measurable
        here", so a metric that has never once produced a reading is left
        out entirely. A metric that *has* read before and drops out keeps
        its row and shows "--", because that really is a dropout.
        """
        if not self._got_sample:
            return True
        return metric.key in self._sensed

    def _sync_visibility(self, sample):
        """Which rows exist right now, from both the user's choice and
        whether the sensor answered at all. Returns them in paint order.

        Every gap is a spacer that belongs to the thing above it, so a
        hidden row takes its own gap with it and the card never grows a
        blank stripe where a metric used to be.
        """
        compact = self._compact()
        row_gap = ROW_GAP_COMPACT if compact else ROW_GAP
        header_gap = HEADER_GAP_COMPACT if compact else HEADER_GAP
        block_gap = BLOCK_GAP_COMPACT if compact else BLOCK_GAP
        visible_metrics = []
        shown = []

        for group in M.GROUP_ORDER:
            enabled = self._enabled_metrics(group)
            # Before the first sample lands, "no data" is not a failure —
            # show the rows reading "--" rather than flashing an error
            # message for the fraction of a second it takes to poll.
            missing = (self._got_sample and bool(enabled)
                       and not any(m.available(sample) for m in enabled))
            self._errors[group].setVisible(missing)
            block_lay = self._blocks[group].layout()
            trailing = None
            for metric in M.metrics_in(group):
                row = self._rows[metric.key]
                visible = (metric in enabled and not missing
                           and self._has_sensor(metric))
                row.setVisible(visible)
                spacer = block_lay.itemAt(
                    block_lay.indexOf(row) + 1).spacerItem()
                _resize(spacer, row_gap if visible else 0)
                if visible:
                    visible_metrics.append(metric)
                    trailing = spacer
            # the last row's gap would be padding on top of padding
            if trailing is not None:
                _resize(trailing, 0)
            _resize(block_lay.itemAt(1).spacerItem(),
                    header_gap if enabled else 0)
            block_lay.invalidate()
            self._blocks[group].updateGeometry()
            self._blocks[group].setVisible(bool(enabled))
            if enabled:
                shown.append(group)

        # `shown` is built from the settings, not from isVisible(): a
        # widget inside a window that has not been shown yet reports False
        # no matter what setVisible() was just told, so reading it back
        # here made the very first layout drop the gap between the two
        # blocks and the card jumped 18px taller on the first sample.
        for i, group in enumerate(M.GROUP_ORDER):
            spacer = self.body.itemAt(i * 2 + 1).spacerItem()
            last = bool(shown) and group == shown[-1]
            _resize(spacer, 0 if (group not in shown or last) else block_gap)
        self._shown_groups = shown
        self.body.invalidate()
        # the card owns `body`; without this its sizeHint keeps the gap it
        # had before, which showed up as an 18px-short card for one pass
        # after leaving compact mode
        self.card.updateGeometry()
        return visible_metrics

    def _relayout(self):
        """Ask for a re-fit; the resize itself waits for Qt to catch up.

        Hiding a row posts a LayoutRequest instead of recomputing on the
        spot, so a sizeHint() read in the same call is a whole
        configuration stale — measured: switching every metric off but
        VRAM still reported the previous four-row height. Calling
        activate() by hand on each nested layout does not help either,
        because each one is re-invalidated by the child under it. A 0ms
        timer lets the event loop deliver those requests first, and
        coalesces the several _relayout calls one refresh makes.

        Never resize the card directly: it belongs to the shell layout,
        and adjustSize() on it collapses it to its content hint — the
        meters are Expanding, so that hint is far narrower than the card.
        """
        self._fit_timer.start()

    def _fit(self):
        self.resize(self.width(), self.sizeHint().height())
        self._place_chrome()
        if self._centre_pending:
            # The card reaches its real height in stages: 374 at the first
            # fit, 494 once the first readings land. Centring on either of
            # the early ones leaves it visibly low — measured 60px — so
            # keep re-centring until two fits agree on the height.
            self.centre_on_main(remember=False)
            if self.height() == self._last_fit_height:
                self._centre_pending = False
            self._last_fit_height = self.height()

    def _place_chrome(self):
        self.chrome.adjustSize()
        # ia-usage anchors its chrome at (top 8, right 8) of the card
        x = self.card.width() - self.chrome.width() - 8
        self.chrome.move(max(0, x), 8)
        self.chrome.raise_()
        self._elide_top_header()

    def _elide_top_header(self):
        """Only the header the chrome actually sits over is constrained;
        the rest of the card is below the buttons and gets full width."""
        pad = PAD_COMPACT if self._compact() else PAD
        budget = self.card.width() - 2 * pad - self.chrome.width() - 8
        top = self._shown_groups[0] if self._shown_groups else None
        for group in M.GROUP_ORDER:
            self._headers[group].set_elide_width(
                budget if group == top else None)

    # --- theme ------------------------------------------------------------

    def apply_theme(self):
        t = self.theme.tokens or {}
        if not t:
            return
        alpha = max(0, min(255, round(
            int(self.settings.get("opacity", 100)) / 100.0 * 255)))
        self.card.set_fill(t["SURFACE"], alpha)
        for header in self._headers.values():
            header.set_ink(t["TEXT"])
        self.setStyleSheet(self._qss(t))
        self._refresh_colors()

    def _qss(self, t):
        icon = icon_font_family()
        return f"""
QWidget#Card {{ background: transparent; }}
QLabel {{ background: transparent; font-family: "Segoe UI"; }}
QLabel[role="section"] {{ font-size: 14px; font-weight: 500; color: {t['TEXT']}; }}
QLabel[role="label"]   {{ font-size: 12px; color: {t['TEXT_55']}; }}
QLabel[role="value"]   {{ font-size: 12px; color: {t['TEXT']}; }}
QLabel[role="caption"] {{ font-size: 11px; color: {t['TEXT_55']}; }}
QLabel[role="error"]   {{ font-size: 13px; color: {t['ERROR']}; }}

QWidget#Card[compact="true"] QLabel[role="section"] {{ font-size: 12px; font-weight: 400; }}
QWidget#Card[compact="true"] QLabel[role="label"]   {{ font-size: 10px; }}
QWidget#Card[compact="true"] QLabel[role="value"]   {{ font-size: 10px; }}

QToolButton#Chrome {{
    border: none;
    border-radius: 13px;
    background: transparent;
    color: {t['TEXT_55']};
    font-family: "{icon}";
    font-size: 11px;
}}
QToolButton#Chrome:hover   {{ background: rgba(128, 128, 128, 20); }}
QToolButton#Chrome:pressed {{ background: rgba(128, 128, 128, 34); }}
QToolButton#Chrome:checked {{ color: {t['TEXT']}; }}
"""

    def _bar_colors(self, metric, fraction):
        """QUOTA metrics keep ia-usage's bands; LOAD metrics take the
        accent. Turning thresholds off makes every bar the accent, which
        is what ia-usage does the moment you pick a custom accent."""
        if (metric.ramp == M.RAMP_QUOTA
                and self.settings.get("threshold_colors", True)
                and fraction is not None):
            return ramp_colors(fraction)
        return flat_gradient(self.theme.accent_hex())

    def _refresh_colors(self):
        if self._sample:
            self._render(self._sample, animate=False)

    # --- data -------------------------------------------------------------

    def on_sample(self, sample):
        self._sample = sample
        self._got_sample = True
        for metric in M.METRICS:
            if metric.available(sample):
                self._sensed.add(metric.key)
        name = sample.get("gpu_name")
        if name and name != self._gpu_name:
            self._gpu_name = name
            self._headers[M.GROUP_GPU].set_text(name)
        self._render(sample, animate=bool(self.settings.get("animations", True)))
        # the one place guaranteed to run every tick — keeps the card above
        # any window that grabbed topmost since the last sample, without
        # ever climbing over our own tooltips, menu or dialog
        self._reassert_topmost()
        self._keep_in_view()

    def _render(self, sample, animate=True):
        visible = self._sync_visibility(sample)
        for index, metric in enumerate(visible):
            row = self._rows[metric.key]
            fraction = metric.fraction(sample)
            row.update_from(sample, self._bar_colors(metric, fraction),
                            animate,
                            delay_ms=CASCADE_STEP_MS * index
                            if self._first_fill else 0)
        if visible and sample:
            self._first_fill = False
        self._relayout()

    # --- interaction ------------------------------------------------------

    def eventFilter(self, obj, event):  # noqa: N802 - Qt naming
        if obj is self.card:
            if event.type() == event.Type.Enter:
                self._fade_chrome(1.0)
            elif event.type() == event.Type.Leave:
                self._fade_chrome(CHROME_REST_OPACITY)
        return super().eventFilter(obj, event)

    def _fade_chrome(self, target):
        self._chrome_anim.stop()
        self._chrome_anim.setStartValue(self._chrome_fx.opacity())
        self._chrome_anim.setEndValue(target)
        self._chrome_anim.start()

    def mousePressEvent(self, event):  # noqa: N802 - Qt naming
        if event.button() == Qt.LeftButton and not self.settings.get("locked"):
            handle = self.windowHandle()
            if handle is not None:
                # Hands the drag to the compositor, so snapping and
                # per-monitor DPI keep behaving natively.
                self._user_moved = True
                # Whatever the opening centre-up was still going to do, the
                # moment he grabs the card he outranks it. Without this a
                # late _fit — the first readings can land a second after
                # the window does — would snatch the card back to the
                # middle from wherever he had just dropped it.
                self._centre_pending = False
                handle.startSystemMove()
                return
        super().mousePressEvent(event)

    def paintEvent(self, event):  # noqa: N802 - Qt naming
        """The drop shadow, drawn only *outside* the card.

        Clipping the card's own rounded rect out of the painter means the
        card interior is never painted over, so its fill blends with the
        desktop and nothing else. Concentric strokes at falling alpha
        approximate the WPF blur (radius 10, offset 0/+2, 22%).
        """
        card = QRectF(self.card.geometry())
        if card.isEmpty():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        hole = QPainterPath()
        hole.addRoundedRect(card, CARD_RADIUS, CARD_RADIUS)
        whole = QPainterPath()
        whole.addRect(QRectF(self.rect()))
        p.setClipPath(whole.subtracted(hole))

        p.setBrush(Qt.NoBrush)
        for step in range(SHADOW_BLUR):
            fade = (1.0 - step / float(SHADOW_BLUR)) ** 2
            pen = QPen(QColor(0, 0, 0, max(1, round(SHADOW_ALPHA * fade))))
            pen.setWidthF(1.6)
            p.setPen(pen)
            ring = card.adjusted(-step, -step + SHADOW_OFFSET_Y,
                                 step, step + SHADOW_OFFSET_Y)
            p.drawRoundedRect(ring, CARD_RADIUS + step, CARD_RADIUS + step)
        p.end()

    def resizeEvent(self, event):  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._place_chrome()

    def moveEvent(self, event):  # noqa: N802 - Qt naming
        super().moveEvent(event)
        # Only a move the *pointer* is making counts. Windows re-homes
        # windows by itself whenever the display layout changes — a monitor
        # sleeping, a game switching resolution, an RDP session, a DPI
        # change — and `_user_moved` alone never turns off again, so one
        # early drag used to make every later shove by the desktop
        # permanent. That is how the card ended up saved at y=1617, under
        # the taskbar of the left screen, and stayed there.
        if self._user_moved and self._pointer_held():
            self._save_timer.start()

    def _pointer_held(self):
        """Is the left mouse button physically down right now?

        Read from the OS rather than from Qt: `startSystemMove` hands the
        drag to Windows, which runs its own modal loop, so Qt's cached
        button state cannot be relied on for the duration of the very
        gesture this has to recognise.
        """
        if os.name != "nt":
            return True          # no way to ask; assume the move was meant
        return bool(_user32.GetAsyncKeyState(_VK_LBUTTON) & 0x8000)

    def _persist_position(self):
        # Fires 600ms after the last move, so it records where the drag
        # finished, not where it passed through.
        if not self._user_moved:
            return
        pos = self.pos()
        self.settings["pos"] = [pos.x(), pos.y()]
        self.settings.save()

    def _visible_fraction(self, rect):
        """How much of the card lands on usable desktop, at its best screen.

        Measured against `availableGeometry`, unlike `_on_a_live_screen`:
        this one asks "can Ivan see and grab it", and the strip under the
        taskbar is exactly where a card goes to hide.
        """
        area = rect.width() * rect.height()
        if area <= 0:
            return 0.0
        best = 0
        for screen in QGuiApplication.screens():
            lap = screen.availableGeometry().intersected(rect)
            best = max(best, lap.width() * lap.height())
        return best / float(area)

    def _nudged_into_view(self, rect):
        """The shortest move that puts `rect` back on working desktop.

        Clamped inside the screen it already overlaps most, so a rescue
        never teleports the card to another monitor when it is merely
        hanging off an edge — and never to 60,60, which threw away which
        screen he had chosen.
        """
        screens = QGuiApplication.screens()
        if not screens:
            return rect.topLeft()

        def overlap(screen):
            lap = screen.availableGeometry().intersected(rect)
            return lap.width() * lap.height()

        def distance(screen):
            """Squared gap between the card's centre and a screen."""
            area = screen.availableGeometry()
            centre = rect.center()
            dx = max(area.x() - centre.x(), 0, centre.x() - area.right())
            dy = max(area.y() - centre.y(), 0, centre.y() - area.bottom())
            return dx * dx + dy * dy

        best = max(screens, key=overlap)
        if overlap(best) == 0:
            # It touches nothing, so "overlaps most" is a tie every screen
            # loses and max() just hands back the first one — which is how
            # a card lost 17px under the left monitor's taskbar came back
            # on the primary. Fall back to the nearest screen instead, so
            # a rescue returns it to the monitor it fell off.
            best = min(screens, key=distance)
        area = best.availableGeometry()
        x = max(area.x(), min(rect.x(), area.right() - rect.width() + 1))
        y = max(area.y(), min(rect.y(), area.bottom() - rect.height() + 1))
        return QPoint(x, y)

    def centre_on_main(self, remember=True):
        """Put the card in the middle of whatever Windows calls the main
        screen right now.

        Asked fresh every time, never cached: which monitors are attached
        and which one is primary both change under the app's feet, and the
        whole point of this is to land on the one Ivan is looking at.

        Qt answers in **logical** pixels, and so does `move()`, so the
        arithmetic is done there and the scaling takes care of itself: his
        main monitor is 3840x2160 running at 150%, which Qt reports as
        2560x1440 — halving the physical numbers by hand would put the
        card off the bottom right of the screen.

        Centred on `geometry()`, not the working area, so it lands on the
        true middle of the panel; a centred card is nowhere near the
        taskbar anyway.
        """
        screen = QGuiApplication.primaryScreen()
        if screen is None:                       # no desktop at all
            return
        area = screen.geometry()
        size = self.size() if self.isVisible() else self.sizeHint()
        home = QPoint(area.x() + (area.width() - size.width()) // 2,
                      area.y() + (area.height() - size.height()) // 2)
        self.move(home)
        log.info("centred on %s (%dx%d logical, %d screens attached) at %s",
                 screen.name(), area.width(), area.height(),
                 len(QGuiApplication.screens()), (home.x(), home.y()))
        if remember:
            # A menu-driven move is deliberate, but no pointer was held, so
            # moveEvent will not have armed the save. Write it here.
            self.settings["pos"] = [home.x(), home.y()]
            self.settings.save()

    def _centres_on_start(self):
        return bool(self.settings.get("centre_on_start", False))

    def _keep_in_view(self):
        """Rescue a card the desktop moved out from under.

        Runs every tick because there is no one signal to hang it on: the
        layout change can arrive as a screen added, removed, resized, or
        merely re-scaled, and the shove sometimes lands a frame later. The
        check is three rectangle intersections, and it stands down while
        the pointer is down so it can never fight a drag.
        """
        if self._pointer_held():
            return
        rect = self.geometry()
        if self._visible_fraction(rect) >= MIN_VISIBLE:
            return
        # Deliberately a nudge and never a re-centre, even when the card
        # opens centred: once the session is under way, where Ivan put it
        # is where it stays. Sliding it the shortest distance back onto
        # the desktop is the least this can do and still leave it
        # reachable; teleporting it to the middle of another monitor for
        # a passing display glitch is not.
        home = self._nudged_into_view(rect)
        log.info("card was %.0f%% visible at %s; nudged to %s",
                 self._visible_fraction(rect) * 100,
                 (rect.x(), rect.y()), (home.x(), home.y()))
        self.move(home)

    def _restore_position(self):
        if self._centres_on_start():
            # Placed now so the card never flashes at 60,60, and again on
            # the first _fit once the layout knows how big it really is.
            self._centre_pending = True
            self.centre_on_main(remember=False)
            return
        pos = self.settings.get("pos")
        if isinstance(pos, list) and len(pos) == 2:
            candidate = QPoint(int(pos[0]), int(pos[1]))
            if self._on_a_live_screen(candidate):
                probe = QRect(candidate, self.sizeHint())
                if self._visible_fraction(probe) < MIN_VISIBLE:
                    candidate = self._nudged_into_view(probe)
                self.move(candidate)
                return
        self.move(60, 60)

    def _on_a_live_screen(self, top_left):
        """A card with no title bar and no system menu cannot be dragged
        back from a monitor that is no longer plugged in."""
        # sizeHint, not frameGeometry: before the window is shown that is
        # still Qt's default 640x480, big enough to overlap a live screen
        # from a saved position that is nowhere near one.
        probe = QRect(top_left, self.size() if self.isVisible()
                      else self.sizeHint())
        for screen in QGuiApplication.screens():
            # geometry, not availableGeometry: the question is "is this
            # monitor still plugged in", not "does the taskbar sit here".
            # An always-on-top card parked over the taskbar draws above it
            # and is perfectly draggable, but availableGeometry excludes
            # that strip — measured: a card left at y=1617 on a screen
            # ending at 1649 was declared off-screen and yanked to 60,60
            # on the next launch, losing a position the user had chosen.
            if screen.geometry().intersects(probe):
                return True
        return False

    def _on_lock_toggled(self, checked):
        self.settings["locked"] = bool(checked)
        self.settings.save()
        self.btn_lock.set_glyph(GLYPH_PIN if checked else GLYPH_UNPIN)

    def _on_aot_toggled(self, checked):
        self.settings["always_on_top"] = bool(checked)
        self.settings.save()
        self.apply_always_on_top()

    def apply_always_on_top(self):
        """Sync the window's topmost state to the setting.

        Done purely with SetWindowPos, never by flipping the Qt flag while
        the window is live: setWindowFlag() re-creates the native handle,
        which forces a show() and a visible flash. Moving the OS topmost
        band re-orders the window with no re-create and no flicker.
        Qt.WindowStaysOnTopHint is set once at construction, for the
        initial z-order and for non-Windows, where _set_topmost is a no-op.
        """
        on = bool(self.settings.get("always_on_top", True))
        if on:
            self._reassert_topmost()   # goes through the own-UI guard
        else:
            self._set_topmost(False)
        self.btn_top.blockSignals(True)
        self.btn_top.setChecked(on)
        self.btn_top.blockSignals(False)

    def _reassert_topmost(self):
        """Put the card back on top — unless one of our own transient
        windows is showing.

        Re-raising every tick is what beats another app's topmost window,
        but it was also climbing over the card's own tooltips and context
        menu, which are topmost too and so were left drawn behind it. While
        any of ours is open we simply stop re-raising: those are already
        above the card and stay there, and no other app is going to seize
        the top in that instant. The Preferences dialog is *not* topmost,
        so it is pushed below the card explicitly (see suspend_topmost),
        and this guard then leaves it there.
        """
        if not self.settings.get("always_on_top", True):
            return
        app = QApplication.instance()
        if (QToolTip.isVisible()
                or app.activePopupWidget() is not None
                or app.activeModalWidget() is not None):
            return
        self._set_topmost(True)

    def suspend_topmost(self):
        """Drop the card out of the topmost band while a modal dialog of
        ours is open, so it cannot cover the dialog. apply_always_on_top()
        — called from apply_live once the dialog closes — restores it."""
        self._set_topmost(False)

    def raise_to_front(self):
        """Surface the card in front of everything — the answer to a second
        launch. There is only ever one card, so "open it again" means "show
        me the one I already have", wherever on screen it drifted to.

        The one-shot HWND_TOPMOST is what actually lifts it from the
        background: Windows blocks a background process from seizing the
        foreground, but not from re-ordering the topmost band, so this beats
        raise_()/activateWindow() alone. If the card is not pinned it is
        dropped back out of the band shortly after, so a stray launch never
        silently turns "always on top" on.
        """
        if self.isMinimized():
            self.showNormal()
        if not self.isVisible():
            self.show()
        # Where a second launch puts it. Launching an app you cannot find is
        # how Ivan asks "where is it?", so with the centring preference on
        # that re-launch is treated as an open and lands the card in the
        # middle of the main screen — the one place he is certain to look.
        # This is the one exception to "nothing moves the card until the
        # next launch": it *is* a launch, and he asked for it by name.
        #
        # With the preference off he has chosen a position, and a stray
        # double-click on the shortcut must not throw it away. Then this
        # only rescues a card that has genuinely drifted out of reach —
        # surfacing one hidden under the taskbar achieves nothing.
        if self._centres_on_start():
            self.centre_on_main(remember=False)
        elif not self._on_a_live_screen(self.pos()):
            self.move(60, 60)
        else:
            self._keep_in_view()
        self.raise_()
        self.activateWindow()
        self._set_topmost(True)
        if not self.settings.get("always_on_top", True):
            QTimer.singleShot(150, lambda: self._set_topmost(False))

    def _set_topmost(self, on):
        """Re-assert (or drop) the OS topmost band. A no-op off Windows,
        and harmless before the native window exists."""
        if os.name != "nt":
            return
        try:
            hwnd = int(self.winId())
        except (TypeError, ValueError, RuntimeError):
            return
        if not hwnd:
            return
        try:
            _user32.SetWindowPos(hwnd, _HWND_TOPMOST if on else _HWND_NOTOPMOST,
                                 0, 0, 0, 0, _SWP_KEEP)
        except OSError:
            pass

    def _on_compact_toggled(self, checked):
        self.settings["compact"] = bool(checked)
        self.settings.save()
        self.reload_layout()   # owns the property flip and the repolish

    def _show_menu(self, pos):
        menu = self.build_menu()
        # exec() returns when the menu closes but the QMenu stays parented
        # to the card; on a window that lives for days, every right-click
        # would leave a menu and its ~15 QActions behind.
        menu.setAttribute(Qt.WA_DeleteOnClose)
        menu.exec(self.mapToGlobal(pos))

    def build_menu(self):
        """The right-click menu the tkinter version had, kept so the old
        muscle memory still works without opening Preferences.

        Separate from _show_menu because exec() enters a modal loop: the
        menu cannot be inspected, or built under test, from the same call
        that opens it.
        """
        menu = QMenu(self)
        show = self.settings.get("show", {}) or {}
        for group in M.GROUP_ORDER:
            menu.addSection(M.GROUP_LABELS[group])
            for metric in M.metrics_in(group):
                action = QAction(metric.label, menu)
                action.setCheckable(True)
                action.setChecked(bool(show.get(metric.key, metric.default)))
                action.toggled.connect(
                    lambda on, k=metric.key: self._toggle_metric(k, on))
                menu.addAction(action)
        menu.addSeparator()

        opacity_menu = menu.addMenu("Opacity")
        group = QActionGroup(opacity_menu)
        current = int(self.settings.get("opacity", 100))
        for pct in (100, 90, 80, 70, 60, 50):
            action = QAction(f"{pct}%", opacity_menu)
            action.setCheckable(True)
            action.setChecked(pct == current)
            action.triggered.connect(lambda _=False, p=pct: self.set_opacity(p))
            group.addAction(action)
            opacity_menu.addAction(action)

        compact = QAction("Compact layout", menu)
        compact.setCheckable(True)
        compact.setChecked(self._compact())
        compact.toggled.connect(self.btn_compact.setChecked)
        menu.addAction(compact)

        on_top = QAction("Always on top", menu)
        on_top.setCheckable(True)
        on_top.setChecked(bool(self.settings.get("always_on_top", True)))
        on_top.toggled.connect(self.btn_top.setChecked)
        menu.addAction(on_top)

        locked = QAction("Lock position", menu)
        locked.setCheckable(True)
        locked.setChecked(bool(self.settings.get("locked", False)))
        locked.toggled.connect(self.btn_lock.setChecked)
        menu.addAction(locked)

        centre = QAction("Centre on main screen", menu)
        # triggered hands a `checked` bool to its slot, which would arrive
        # as centre_on_main(remember=False) and quietly not save.
        centre.triggered.connect(lambda _=False: self.centre_on_main())
        menu.addAction(centre)

        menu.addSeparator()
        prefs = QAction("Preferences…", menu)
        prefs.triggered.connect(self.prefs_requested)
        menu.addAction(prefs)
        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self.close)
        menu.addAction(quit_action)
        return menu

    def _toggle_metric(self, key, on):
        show = dict(self.settings.get("show", {}) or {})
        show[key] = bool(on)
        self.settings["show"] = show
        self.settings.save()
        self.reload_layout()

    def set_opacity(self, percent):
        self.settings["opacity"] = int(percent)
        self.settings.save()
        self.apply_theme()

    def closeEvent(self, event):  # noqa: N802 - Qt naming
        self._persist_position()
        super().closeEvent(event)
        self.closed.emit()
