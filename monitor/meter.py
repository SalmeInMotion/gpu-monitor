"""The ia-usage meter: a 9px pill bar, its row, and the section header.

Everything here is painted rather than styled, for the reasons the design
spec found the hard way: QProgressBar + QSS cannot give a gradient whose
axis is the *fill* rect (not the track), and its rounded caps differ
between styles. Geometry is verbatim from ia-usage — 9px tall, radius
height/2, track rgba(128,128,128,38), gradient across the fill.

Two deliberate divergences from the original, both because a quota popup
and a live hardware monitor are not the same thing:

* **Colour is per metric.** In ia-usage every bar means "how much of your
  allowance is gone", so red at 85% is a warning. A GPU at 95% is not in
  trouble, it is working — painting that red teaches you to ignore red.
  Load metrics use the accent instead, and the red band is kept for the
  metrics where filling up really is bad (VRAM, RAM, temperature).
* **Motion runs once.** The original cascades every bar 0 -> value on
  every render because it renders on demand. This renders every second,
  so the cascade plays on the first sample only; after that a value
  change is a 150ms tween.
"""

from __future__ import annotations

from PySide6.QtCore import (QEasingCurve, QRectF, Qt, QTimer,
                            QVariantAnimation, Signal)
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

BAR_HEIGHT = 9
BAR_HEIGHT_COMPACT = 7

# ia-usage's own bands, on the percentage *consumed*.
RAMP = (
    (60.0, "#72d08f", "#3f9e63"),
    (85.0, "#f3c36a", "#d99420"),
    (float("inf"), "#ee8484", "#ce3d3d"),
)

TRACK = QColor(128, 128, 128, 38)          # #26808080, identical in both themes
TRACK_NO_DATA = QColor(128, 128, 128, 19)  # half alpha: "no signal", not "zero"

# Below this the fill is a sliver nobody can see; an idle GPU would look
# broken rather than idle. Only applied when there is a real reading.
MIN_FILL_PX = 3.0

CASCADE_MS = 500     # first fill, per ia-usage
CASCADE_STEP_MS = 80  # stagger between bars
TWEEN_MS = 150       # every later change
# Below this much movement a tween is invisible and just burns repaints.
TWEEN_EPSILON = 0.01

# Past this much pointer travel a press on a bar was a drag of the
# card, not a click on the bar.
DRAG_SLOP = 4


def flat_gradient(accent_hex):
    """ia-usage's own override for a user-picked accent: each channel
    +40 for the left end, the accent itself on the right."""
    base = QColor(accent_hex)
    lighter = QColor(min(255, base.red() + 40),
                     min(255, base.green() + 40),
                     min(255, base.blue() + 40))
    return lighter.name(), base.name()


def ramp_colors(fraction):
    pct = max(0.0, min(1.0, fraction)) * 100.0
    for limit, start, end in RAMP:
        if pct < limit:
            return start, end
    return RAMP[-1][1], RAMP[-1][2]


class RowLabel(QLabel):
    """A metric's name, and for VRAM and RAM a way in.

    Double-click, not single, and on the word rather than the bar: Ivan
    asked for both, so that opening the breakdown is a deliberate act on
    a named counter and there is no way to end up looking at the wrong
    one. The word is also exactly as wide as its text (see MeterRow), so
    the target is what it looks like.

    Holding the press is what makes this coexist with the whole card
    being a drag handle: let it through and the window's system move
    starts on the first press, and the second click never arrives.
    """

    activated = Signal()
    drag_requested = Signal()

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self._interactive = False
        self._press_at = None

    def set_interactive(self, on, tip=""):
        self._interactive = bool(on)
        if on:
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip(tip)
        else:
            self.unsetCursor()
            self.setToolTip("")

    def mousePressEvent(self, event):  # noqa: N802 - Qt naming
        if self._interactive and event.button() == Qt.LeftButton:
            self._press_at = event.globalPosition().toPoint()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802 - Qt naming
        if self._press_at is None:
            super().mouseMoveEvent(event)
            return
        if (event.globalPosition().toPoint()
                - self._press_at).manhattanLength() > DRAG_SLOP:
            self._press_at = None
            self.drag_requested.emit()

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt naming
        if self._press_at is not None:
            self._press_at = None
            event.accept()      # a single click does nothing on purpose
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):  # noqa: N802 - Qt naming
        if self._interactive and event.button() == Qt.LeftButton:
            self._press_at = None
            self.activated.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class Meter(QWidget):
    """The bar itself. `set_value(None)` is the no-data state."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = None      # target 0..1, or None
        self._drawn = 0.0       # what is actually painted, chased by the tween
        self._colors = (RAMP[0][1], RAMP[0][2])
        self._seeded = False    # has this meter ever shown a real value?

        # One animation for the life of the widget, re-targeted on every
        # change. Allocating a QVariantAnimation per tween instead leaks
        # it: parented to the meter, it outlives its own run and nothing
        # ever frees it — measured at ~73 MB and 21600 objects per hour
        # with six meters moving every second, on a card that is meant to
        # stay open for days.
        self._anim = QVariantAnimation(self)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_frame)
        # the cascade's stagger is a delayed *start*, not a delayed value
        self._delay = QTimer(self)
        self._delay.setSingleShot(True)
        self._delay.timeout.connect(self._anim.start)


        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.set_compact(False)

    def set_compact(self, compact):
        self.setFixedHeight(BAR_HEIGHT_COMPACT if compact else BAR_HEIGHT)

    def set_value(self, fraction, colors, animate=True, delay_ms=0):
        """colors is a (start_hex, end_hex) pair chosen by the caller, so
        the hue is picked from the *target* value and never shifts
        mid-animation the way it would if paint chose it from _drawn."""
        self._colors = colors
        if fraction is None:
            self._stop()
            self._value = None
            self._drawn = 0.0
            # Losing the sensor resets the cascade, so the bar fills in
            # again when the reading comes back rather than snapping.
            self._seeded = False
            self.update()
            return

        fraction = max(0.0, min(1.0, fraction))
        previous = self._value
        self._value = fraction
        first = not self._seeded
        self._seeded = True

        if not animate:
            self._stop()
            self._drawn = fraction
            self.update()
            return

        if not first and abs(fraction - (previous or 0.0)) < TWEEN_EPSILON:
            # Nothing worth animating; keep the painted value in step
            # anyway so slow drift cannot accumulate an offset.
            self._stop()
            self._drawn = fraction
            self.update()
            return

        self._animate(fraction,
                      CASCADE_MS if first else TWEEN_MS,
                      delay_ms if first else 0)

    def _animate(self, target, duration, delay_ms):
        self._stop()
        self._anim.setStartValue(float(self._drawn))
        self._anim.setEndValue(float(target))
        self._anim.setDuration(duration)
        if delay_ms:
            self._delay.start(delay_ms)
        else:
            self._anim.start()

    def _on_frame(self, value):
        self._drawn = float(value)
        self.update()

    def _stop(self):
        # Both, and in this order: a pending cascade start left armed
        # would fire later and re-run the animation toward a target that
        # has since been replaced.
        self._delay.stop()
        self._anim.stop()

    def paintEvent(self, event):  # noqa: N802 - Qt naming
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)

        h = float(self.height())
        r = h / 2.0
        p.setBrush(TRACK if self._value is not None else TRACK_NO_DATA)
        p.drawRoundedRect(QRectF(0.0, 0.0, float(self.width()), h), r, r)

        if self._value is None:
            p.end()
            return

        w = self._drawn * self.width()
        if w <= 0.0 and self._value <= 0.0:
            # A real zero still deserves a visible sliver: on a live meter
            # an empty track is indistinguishable from a dead sensor.
            w = MIN_FILL_PX
        elif 0.0 < w < MIN_FILL_PX:
            w = MIN_FILL_PX
        if w <= 0.0:
            p.end()
            return

        # Absolute, fill-derived coordinates: WPF's (0,0)->(1,0) is
        # relative to the fill's bounding box, and Qt's ObjectBoundingMode
        # would measure the whole widget instead.
        grad = QLinearGradient(0.0, 0.0, w, 0.0)
        grad.setColorAt(0.0, QColor(self._colors[0]))
        grad.setColorAt(1.0, QColor(self._colors[1]))
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(QRectF(0.0, 0.0, w, h), r, r)
        p.end()


class MeterRow(QWidget):
    """Label + value on one line, bar under it, optional caption under
    that. Margins are ia-usage's: bar 6 below the labels, caption 5 below
    the bar, 14 between rows (applied by the parent layout)."""

    def __init__(self, metric, parent=None):
        super().__init__(parent)
        # NOT self.metric: QPaintDevice already has a virtual metric()
        # that Qt calls internally, and shadowing it with a non-callable
        # breaks every paint the widget is involved in.
        self.spec = metric
        self._compact = False

        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(0)

        line = QHBoxLayout()
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(6)
        self.label = RowLabel(metric.label)
        self.label.setProperty("role", "label")
        self.value = QLabel("--")
        self.value.setProperty("role", "value")
        self.value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        # No stretch on the label: it has to be as wide as the word,
        # or double-clicking blank space to its right would open the
        # panel too and the target would not be what it looks like.
        line.addWidget(self.label, 0)
        line.addStretch(1)
        line.addWidget(self.value, 0)
        self._line = line
        self._lay.addLayout(line)

        self.meter = Meter(self)
        self._lay.addSpacing(6)
        self._lay.addWidget(self.meter)

        self.caption = QLabel("")
        self.caption.setProperty("role", "caption")
        self._lay.addSpacing(5)
        self._lay.addWidget(self.caption)
        self._caption_shown = True
        self._set_caption_visible(False)

    def set_compact(self, compact):
        """Compact drops the caption and tightens the gaps. ia-usage does
        this with a 0.75 LayoutTransform over the whole tree, which Qt has
        no clean equivalent for — same numbers, applied directly."""
        self._compact = compact
        self.meter.set_compact(compact)
        self._set_caption_visible(not compact and bool(self.caption.text()))
        # spacer items: [line][6][meter][5][caption]. changeSize resets
        # the size policy to its defaults unless both are passed, and
        # addSpacing's spacers are Minimum/Fixed.
        self._lay.itemAt(1).spacerItem().changeSize(
            0, 4 if compact else 6, QSizePolicy.Minimum, QSizePolicy.Fixed)
        self._lay.invalidate()
        # invalidate() only marks this layout dirty; without this the
        # parent keeps handing out the previous sizeHint and the window
        # stays one layout pass too tall.
        self.updateGeometry()

    def _set_caption_visible(self, visible):
        """The 5px gap above the caption belongs to the caption.

        Hiding the label alone leaves that spacer behind, so a row with no
        caption — Fan always, GPU usage on a board that reports no clock,
        CPU where psutil has no cpu_freq — sits with 5px more air under
        its bar than every other row.
        """
        if visible == self._caption_shown:
            return
        self._caption_shown = visible
        self.caption.setVisible(visible)
        self._lay.itemAt(3).spacerItem().changeSize(
            0, 5 if visible else 0, QSizePolicy.Minimum, QSizePolicy.Fixed)
        self._lay.invalidate()
        self.updateGeometry()

    def update_from(self, sample, colors, animate, delay_ms):
        self.value.setText(self.spec.value(sample))
        caption = self.spec.caption(sample)
        self.caption.setText(caption)
        self._set_caption_visible(not self._compact and bool(caption))
        self.meter.set_value(self.spec.fraction(sample), colors,
                             animate=animate, delay_ms=delay_ms)


class SectionHeader(QWidget):
    """Icon + name, the way ia-usage puts a service logo over its bars.

    The marks are painted, not glyphs: Segoe MDL2 has nothing that reads
    as "graphics card", and a painted mark recolours with the theme for
    free — the same reason ia-usage draws its stats icon as three
    rectangles instead of an emoji.
    """

    GPU = "gpu"
    SYSTEM = "system"

    def __init__(self, kind, text, parent=None):
        super().__init__(parent)
        self.kind = kind
        self._compact = False
        self._full = text
        self._limit = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.mark = _SectionMark(kind, self)
        self.label = QLabel(text)
        self.label.setProperty("role", "section")
        lay.addWidget(self.mark, 0)
        lay.addWidget(self.label, 1)

    def set_text(self, text):
        self._full = text
        self._apply_elide()

    def set_elide_width(self, limit):
        """Width this header may use, or None for all of it.

        The chrome buttons float over the top-right corner, so the header
        under them has to stop short: "RTX A6000 Ada Generation" would
        otherwise run straight under the close button, and in compact mode
        even a "RTX 4070 Ti SUPER" overlaps.
        """
        self._limit = limit
        self._apply_elide()

    def _apply_elide(self):
        self.label.setText(self._full)
        if not self._limit or self._limit <= 0:
            return
        # Measured by shrinking, not with QFontMetrics: the label's font
        # comes from the stylesheet, and font() does not reliably carry
        # it before the widget is polished — eliding against those metrics
        # produced a "RTX A600…" that still rendered 11px wider than the
        # space it was told to fit in.
        text = self._full
        while len(text) > 1 and self.sizeHint().width() > self._limit:
            text = text[:-1]
            self.label.setText(text + "…")

    def set_compact(self, compact):
        self._compact = compact
        self.mark.set_size(10.5 if compact else 18)
        self.layout().setSpacing(6 if compact else 8)
        self._apply_elide()
        self.updateGeometry()

    def set_ink(self, color_hex):
        self.mark.set_ink(color_hex)


class _SectionMark(QWidget):
    """18x18 (10.5 compact) vector mark tinted with the primary text
    colour, matching ia-usage's `text.primary`-tinted service icons."""

    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind = kind
        self._ink = QColor("#1a1a1a")
        self.set_size(18)

    def set_size(self, size):
        self._size = float(size)
        self.setFixedSize(int(round(size)), int(round(size)))

    def set_ink(self, color_hex):
        self._ink = QColor(color_hex)
        self.update()

    def paintEvent(self, event):  # noqa: N802 - Qt naming
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        s = min(self.width(), self.height())
        u = s / 18.0  # everything below is authored on an 18px grid

        # Stroked, not filled: a solid silhouette turns to mush at the
        # 10.5px compact size, and an outline is also what the MDL2
        # glyphs beside it look like. Nothing is punched out with a Clear
        # composition mode — inside a translucent window that would cut a
        # hole straight through the card to the desktop.
        pen = QPen(self._ink)
        pen.setWidthF(max(1.0, 1.4 * u))
        pen.setJoinStyle(Qt.RoundJoin)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        inset = pen.widthF() / 2.0

        if self.kind == SectionHeader.GPU:
            # a graphics card seen flat: a board with a fan and a bracket
            p.drawRoundedRect(
                QRectF(1.0 * u + inset, 4.0 * u + inset,
                       16.0 * u - 2 * inset, 9.5 * u - 2 * inset),
                1.6 * u, 1.6 * u)
            p.drawEllipse(QRectF(5.0 * u, 6.4 * u, 5.0 * u, 5.0 * u))
            p.setPen(Qt.NoPen)
            p.setBrush(self._ink)
            p.drawRect(QRectF(3.0 * u, 13.5 * u, 1.8 * u, 2.6 * u))
            p.drawRect(QRectF(13.2 * u, 13.5 * u, 1.8 * u, 2.6 * u))
        else:
            # a processor: square die with pins on all four sides
            p.drawRoundedRect(
                QRectF(4.0 * u + inset, 4.0 * u + inset,
                       10.0 * u - 2 * inset, 10.0 * u - 2 * inset),
                1.6 * u, 1.6 * u)
            p.setPen(Qt.NoPen)
            p.setBrush(self._ink)
            for offset in (5.6, 8.2, 10.8):
                p.drawRect(QRectF(offset * u, 1.4 * u, 1.6 * u, 2.6 * u))
                p.drawRect(QRectF(offset * u, 14.0 * u, 1.6 * u, 2.6 * u))
                p.drawRect(QRectF(1.4 * u, offset * u, 2.6 * u, 1.6 * u))
                p.drawRect(QRectF(14.0 * u, offset * u, 2.6 * u, 1.6 * u))
        p.end()
