"""Hover reveal — a spotlight of light that follows the cursor across a
button, plus a rim highlight on the edge nearest the cursor.

Qt style sheets can only switch between static states, so the glow is a
transparent child overlay painted with an additive radial gradient. It is
click-through (WA_TransparentForMouseEvents) and follows the button's
geometry, so it composes with whatever QSS the button already has.

Enable app-wide with install_hover_reveal(app); a widget can opt out with
    widget.setProperty("noReveal", True)
"""

from __future__ import annotations

from PySide6.QtCore import (QEasingCurve, QEvent, QObject, QPoint, QPointF,
                            QRectF, Qt, QVariantAnimation)
from PySide6.QtGui import (QBrush, QColor, QPainter, QPainterPath, QPen,
                           QRadialGradient)
from PySide6.QtWidgets import QAbstractButton, QWidget

from . import theme as theme_mod
from . import tokens as T

# object names whose hover is already a statement of its own
_EXCLUDED = {"WinBtn", "CloseBtn", "Swatch"}

_FADE_IN_MS = 130
_FADE_OUT_MS = 240


class _RevealOverlay(QWidget):
    """Transparent sheet over one button that paints the glow."""

    def __init__(self, host):
        super().__init__(host)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setFocusPolicy(Qt.NoFocus)
        self._host = host
        self._cursor = QPointF(host.width() / 2, host.height() / 2)
        self._strength = 0.0

        self._anim = QVariantAnimation(self)
        self._anim.setEasingCurve(QEasingCurve.InOutQuad)
        self._anim.valueChanged.connect(self._on_strength)
        self.setGeometry(host.rect())

    def _on_strength(self, value):
        self._strength = float(value)
        self.update()

    def fade(self, target):
        self._anim.stop()
        self._anim.setStartValue(self._strength)
        self._anim.setEndValue(float(target))
        self._anim.setDuration(_FADE_IN_MS if target else _FADE_OUT_MS)
        self._anim.start()

    def move_light(self, pos):
        self._cursor = QPointF(pos)
        if self._strength > 0.0:
            self.update()

    # --- painting ---------------------------------------------------------

    def _palette(self):
        """Glow color, peak alpha, rim alpha and blend mode for this
        button's actual background.

        Additive light only works on a ground with headroom left: on a
        light theme the buttons sit on near-white, where adding light
        changes nothing at all. There the glow is painted as a tint
        instead, which reads as the same "lit from the cursor" effect.
        """
        t = theme_mod.current_tokens()
        plus = QPainter.CompositionMode_Plus
        over = QPainter.CompositionMode_SourceOver
        if self._host.objectName() == "Primary":
            # solid accent fill: white light reads on it in either theme
            return QColor("#ffffff"), 0.16, 0.40, plus
        if T.luminance(t["BG"]) < 0.2:
            return QColor(t["ACCENT"]), 0.15, 0.55, plus
        return QColor(t["ACCENT"]), 0.16, 0.55, over

    def paintEvent(self, event):  # noqa: N802 - Qt naming
        if self._strength <= 0.002:
            return
        t = theme_mod.current_tokens()
        color, peak, rim_peak, blend = self._palette()
        rect = QRectF(self.rect())
        radius = float(t["RADIUS_MD"])

        path = QPainterPath()
        path.addRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setClipPath(path)

        # spotlight: additive so it reads as light rather than as paint.
        # Tied to height so a wide button gets a travelling pool of light
        # rather than an evenly-lit slab.
        reach = max(36.0, min(self.height() * 1.6, 120.0))
        grad = QRadialGradient(self._cursor, reach)
        center = QColor(color)
        center.setAlphaF(peak * self._strength)
        edge = QColor(color)
        edge.setAlphaF(0.0)
        grad.setColorAt(0.0, center)
        grad.setColorAt(1.0, edge)
        p.setCompositionMode(blend)
        p.fillPath(path, QBrush(grad))

        # rim: the edge nearest the cursor catches the light
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        p.setClipping(False)
        rim_grad = QRadialGradient(self._cursor, reach * 0.9)
        rim = QColor(color)
        rim.setAlphaF(rim_peak * self._strength)
        rim_grad.setColorAt(0.0, rim)
        rim_grad.setColorAt(1.0, edge)
        pen = QPen(QBrush(rim_grad), 1.3)
        p.setPen(pen)
        p.drawPath(path)
        p.end()


class HoverReveal(QObject):
    """Application event filter that gives every button the reveal glow."""

    _WATCHED = {QEvent.Type.Enter, QEvent.Type.Leave, QEvent.Type.MouseMove,
                QEvent.Type.Resize, QEvent.Type.EnabledChange}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._overlays = {}  # id(button) -> _RevealOverlay

    def _wants_reveal(self, obj):
        return (isinstance(obj, QAbstractButton)
                and obj.isEnabled()
                and obj.objectName() not in _EXCLUDED
                and not obj.property("noReveal"))

    def _overlay_for(self, button):
        overlay = self._overlays.get(id(button))
        if overlay is None or overlay.parent() is not button:
            overlay = _RevealOverlay(button)
            self._overlays[id(button)] = overlay
            button.destroyed.connect(
                lambda _=None, key=id(button): self._overlays.pop(key, None))
            button.setMouseTracking(True)
            overlay.show()
        return overlay

    def eventFilter(self, obj, event):  # noqa: N802 - Qt naming
        etype = event.type()
        if etype not in self._WATCHED or not self._wants_reveal(obj):
            return False

        if etype == QEvent.Type.Enter:
            overlay = self._overlay_for(obj)
            overlay.setGeometry(obj.rect())
            overlay.raise_()
            pos = event.position().toPoint() if hasattr(event, "position") \
                else obj.mapFromGlobal(obj.cursor().pos())
            overlay.move_light(pos)
            overlay.fade(1.0)
        elif etype == QEvent.Type.Leave:
            overlay = self._overlays.get(id(obj))
            if overlay is not None:
                overlay.fade(0.0)
        elif etype == QEvent.Type.MouseMove:
            overlay = self._overlays.get(id(obj))
            if overlay is not None:
                overlay.move_light(event.position().toPoint())
        elif etype == QEvent.Type.Resize:
            overlay = self._overlays.get(id(obj))
            if overlay is not None:
                overlay.setGeometry(obj.rect())
        elif etype == QEvent.Type.EnabledChange:
            overlay = self._overlays.get(id(obj))
            if overlay is not None and not obj.isEnabled():
                overlay.fade(0.0)
        return False  # never consume: the button still behaves normally


_installed = None


def install_hover_reveal(app):
    """Install (idempotent) and return the app-wide reveal filter."""
    global _installed
    if _installed is None:
        _installed = HoverReveal(app)
        app.installEventFilter(_installed)
    return _installed


def remove_hover_reveal(app):
    global _installed
    if _installed is not None:
        app.removeEventFilter(_installed)
        for overlay in list(_installed._overlays.values()):
            overlay.hide()
            overlay.deleteLater()
        _installed._overlays.clear()
        _installed = None
