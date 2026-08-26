"""The panel behind a click on the VRAM or RAM bar.

Answers one question — "what is holding this memory, and can I get it
back" — so it is a list sorted by size, grouped per executable, with
everything under 512 MB left out, and a button that ends what you pick.

Wears the card's own skin (same tokens, same painted rounded rect and
hand-drawn shadow) rather than a system window, because it belongs to the
card that opened it.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout,
                               QHeaderView, QLabel, QMessageBox,
                               QPushButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from . import breakdown as bd
from .chrome import ChromeButton, GLYPH_CLOSE, chrome_qss

log = logging.getLogger("gpu_monitor.processes")

GUTTER = 6              # room for the shadow, as on the card
RADIUS = 14.0           # ia-usage's secondary surfaces (toast, tray menu)
SHADOW_ALPHA = 71       # 0.28, the dialog weight rather than the popup's
SHADOW_OFFSET_Y = 2
PAD = 16

PANEL_WIDTH = 340
MAX_ROWS_SHOWN = 9      # past this the list scrolls instead of growing
ROW_HEIGHT = 22         # kept in step with the QSS below

REFRESH_MS = 2000       # slower than the card: this walks the process table

# The same words the rows carry. "Video memory"/"System memory"
# read as near-synonyms at a glance, which is exactly the mix-up
# this panel must not invite.
TITLES = {bd.KIND_GPU: "VRAM", bd.KIND_RAM: "RAM"}


class ProcessPanel(QWidget):
    """A list of memory hogs, and a way to end them."""

    refresh_requested = Signal(str)     # kind

    def __init__(self, theme, settings, parent=None):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool
                         | Qt.WindowStaysOnTopHint)
        self.theme = theme
        self.settings = settings
        # Where the panel sits relative to the card, so it can travel with
        # it. Ivan dragged the card to another monitor and the panel stayed
        # behind on the first one.
        self._offset = QPoint(0, 0)
        self._card_pos = None
        self._following = False
        self._muted = "#909093"
        self._clearing = False
        self.kind = bd.KIND_RAM
        self._entries = []

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setWindowTitle("GPU Monitor - processes")
        self.setFixedWidth(PANEL_WIDTH + 2 * GUTTER)

        shell = QVBoxLayout(self)
        shell.setContentsMargins(GUTTER, GUTTER, GUTTER, GUTTER)
        self.card = QWidget(self)
        self.card.setObjectName("PanelCard")
        shell.addWidget(self.card)

        body = QVBoxLayout(self.card)
        body.setContentsMargins(PAD, PAD, PAD, PAD)
        body.setSpacing(0)

        head = QHBoxLayout()
        head.setSpacing(6)
        self.title = QLabel(objectName="PanelTitle")
        self.total = QLabel(objectName="PanelTotal")
        self.total.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.btn_close = ChromeButton(GLYPH_CLOSE, "Close", self.card)
        self.btn_close.clicked.connect(self.close)
        head.addWidget(self.title, 1)
        head.addWidget(self.total, 0)
        head.addSpacing(2)
        head.addWidget(self.btn_close, 0)
        body.addLayout(head)
        body.addSpacing(10)

        self.list = QTreeWidget(self.card)
        self.list.setObjectName("PanelList")
        self.list.setColumnCount(2)
        self.list.setHeaderHidden(True)
        self.list.setRootIsDecorated(False)
        self.list.setUniformRowHeights(True)
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setFocusPolicy(Qt.StrongFocus)
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        header = self.list.header()
        header.setStretchLastSection(False)
        # Fixed percentages clipped "12 GB" to "12 GE" the moment a
        # scrollbar appeared. Let the size column ask for its own width
        # and give the rest to the name.
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.list.itemSelectionChanged.connect(self._sync_button)
        body.addWidget(self.list, 1)

        body.addSpacing(10)
        foot = QHBoxLayout()
        foot.setSpacing(8)
        self.hint = QLabel(objectName="PanelHint")
        self.hint.setWordWrap(True)
        self.btn_end = QPushButton("End process", objectName="PanelDanger")
        self.btn_end.setCursor(Qt.PointingHandCursor)
        self.btn_end.setEnabled(False)
        self.btn_end.clicked.connect(self._end_selected)
        foot.addWidget(self.hint, 1)
        foot.addWidget(self.btn_end, 0)
        body.addLayout(foot)

        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self._ask)
        self.theme.changed.connect(self.apply_theme)
        self.apply_theme()

    # --- opening and closing ----------------------------------------------

    def open_for(self, kind, anchor_rect):
        """Show the panel for one kind, beside the card that owns it."""
        if self.isVisible() and self.kind == kind:
            self.close()
            return
        self.kind = kind
        self.title.setText(TITLES.get(kind, "Memory"))
        self.total.setText("")
        self.list.clear()
        self._set_hint("Reading...")
        self._place(anchor_rect)
        self.show()
        self.raise_()
        self._ask()
        self._timer.start()

    def closeEvent(self, event):  # noqa: N802 - Qt naming
        self._timer.stop()
        super().closeEvent(event)

    def keyPressEvent(self, event):  # noqa: N802 - Qt naming
        if event.key() == Qt.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def follow(self, card_rect):
        """Keep station on the card. Called whenever the card moves."""
        self._card_pos = card_rect.topLeft()
        if not self.isVisible():
            return
        self._following = True
        try:
            self.move(self._clamped(self._card_pos + self._offset))
        finally:
            self._following = False

    def moveEvent(self, event):  # noqa: N802 - Qt naming
        super().moveEvent(event)
        # Any move that was not follow()'s own is the user dragging the
        # panel, which re-sets where it rides from then on.
        if not self._following and self._card_pos is not None:
            self._offset = self.pos() - self._card_pos

    def mousePressEvent(self, event):  # noqa: N802 - Qt naming
        """The panel is frameless, so its own background is the handle.
        Without this there was no way to move it at all."""
        if event.button() == Qt.LeftButton:
            handle = self.windowHandle()
            if handle is not None:
                handle.startSystemMove()
                return
        super().mousePressEvent(event)

    def _clamped(self, point):
        from PySide6.QtGui import QGuiApplication
        rect = QRect(point, self.size())
        screen = (QGuiApplication.screenAt(rect.center())
                  or QGuiApplication.screenAt(point)
                  or QGuiApplication.primaryScreen())
        area = screen.availableGeometry()
        x = max(area.left(), min(point.x(), area.right() - self.width()))
        y = max(area.top(), min(point.y(), area.bottom() - self.height()))
        return QPoint(x, y)

    def _place(self, anchor):
        """To the right of the card if it fits, otherwise to its left, and
        never off the screen the card is on."""
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.screenAt(anchor.center())
        area = (screen or QGuiApplication.primaryScreen()).availableGeometry()
        height = self.sizeHint().height()
        x = anchor.right() + 4
        if x + self.width() > area.right():
            x = anchor.left() - self.width() - 4
        x = max(area.left(), min(x, area.right() - self.width()))
        y = max(area.top(), min(anchor.top(), area.bottom() - height))
        self._card_pos = anchor.topLeft()
        self._offset = QPoint(x, y) - self._card_pos
        self._following = True
        try:
            self.move(x, y)
        finally:
            self._following = False

    # --- data --------------------------------------------------------------

    def _ask(self):
        self.refresh_requested.emit(self.kind)

    def set_entries(self, kind, entries):
        """Called with whatever the sampler thread came back with."""
        if kind != self.kind or not self.isVisible():
            return
        keep = {i.text(0) for i in self.list.selectedItems()}
        self._entries = entries
        self.list.clear()
        for entry in entries:
            item = QTreeWidgetItem([entry.name, bd.fmt_bytes(entry.bytes)])
            item.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
            if len(entry.pids) > 1:
                item.setToolTip(0, f"{len(entry.pids)} processes")
            if entry.protected:
                # Listed, because it is genuinely using the memory, but
                # not selectable: ending any of these takes Windows with
                # it. ItemIsEnabled without ItemIsSelectable is the
                # combination that still paints normally.
                item.setFlags(Qt.ItemIsEnabled)
                item.setToolTip(0, "Windows needs this one")
                # A QSS :disabled rule would not fire: the item is enabled,
                # just not selectable. Paint the difference directly.
                muted = QBrush(QColor(self._muted))
                item.setForeground(0, muted)
                item.setForeground(1, muted)
            self.list.addTopLevelItem(item)
            if entry.name in keep and not entry.protected:
                item.setSelected(True)

        total = sum(e.bytes for e in entries)
        self.total.setText(bd.fmt_bytes(total) if entries else "")
        if entries:
            self._set_hint("Nothing under 512 MB is listed.")
        else:
            self._set_hint("Nothing is using more than 512 MB.")
        self._resize_list()
        self._sync_button()

    def _set_hint(self, text):
        self.hint.setText(text)

    def _resize_list(self):
        rows = max(1, min(len(self._entries), MAX_ROWS_SHOWN))
        row_h = self.list.sizeHintForRow(0) if self._entries else ROW_HEIGHT
        # Frame included, or the last visible row comes out sliced in half.
        self.list.setFixedHeight(rows * max(ROW_HEIGHT, row_h)
                                 + 2 * self.list.frameWidth() + 4)
        self.adjustSize()

    # --- ending things -----------------------------------------------------

    def _selected_entries(self):
        names = {i.text(0) for i in self.list.selectedItems()}
        return [e for e in self._entries
                if e.name in names and not e.protected]

    def _drop_protected_selection(self):
        """Un-highlight any protected row that got selected from code.

        ItemIsSelectable only stops the *user*: setSelected() ignores it,
        leaving a row that looks armed while selectedItems() -- and so the
        button -- excludes it. Clearing it has to wait a turn of the event
        loop: done inside itemSelectionChanged, Qt is still mid-update and
        simply re-applies the selection afterwards.
        """
        self._clearing = True
        try:
            for i in range(self.list.topLevelItemCount()):
                item = self.list.topLevelItem(i)
                if item.isSelected() and not (
                        item.flags() & Qt.ItemIsSelectable):
                    item.setSelected(False)
        finally:
            self._clearing = False
        self._sync_button()

    def _sync_button(self):
        if not self._clearing:
            QTimer.singleShot(0, self._drop_protected_selection)

        chosen = self._selected_entries()
        self.btn_end.setEnabled(bool(chosen))
        if len(chosen) > 1:
            self.btn_end.setText(f"End {len(chosen)} apps")
        else:
            self.btn_end.setText("End process")

    def _end_selected(self):
        chosen = self._selected_entries()
        if not chosen:
            return
        pids = [pid for entry in chosen for pid in entry.pids]
        lines = "\n".join(
            f"  {e.name} - {bd.fmt_bytes(e.bytes)}"
            + (f" ({len(e.pids)} processes)" if len(e.pids) > 1 else "")
            for e in chosen)
        # Deliberately a confirmation, where Task Manager has none: this
        # list groups, so one row can be fifty processes, and there is no
        # undo for the unsaved work inside them.
        box = QMessageBox(self)
        box.setWindowTitle("End process")
        box.setIcon(QMessageBox.Warning)
        box.setText(f"End {len(pids)} process(es)? Unsaved work is lost.")
        box.setInformativeText(lines)
        box.setStandardButtons(QMessageBox.Cancel | QMessageBox.Yes)
        box.setDefaultButton(QMessageBox.Cancel)
        if box.exec() != QMessageBox.Yes:
            return

        ended, failed, skipped = bd.terminate(pids)
        log.info("ended %s, failed %s, skipped %s", ended, failed, skipped)
        if failed:
            self._set_hint(f"Ended {ended}; {failed} refused "
                           "(they need admin rights).")
        else:
            self._set_hint(f"Ended {ended}.")
        QTimer.singleShot(400, self._ask)

    # --- looks -------------------------------------------------------------

    def apply_theme(self):
        tokens = self.theme.tokens or {}
        if not tokens:
            return
        fill = QColor(tokens["SURFACE"])
        # Same alpha the card paints itself with, so the two surfaces read
        # as one thing rather than a solid panel stuck to a see-through card.
        fill.setAlpha(max(0, min(255, round(
            int(self.settings.get("opacity", 100)) / 100.0 * 255))))
        self._fill = fill
        self._muted = tokens["TEXT_45"]
        self.setStyleSheet(self._qss(tokens))
        self.update()

    def _qss(self, t):
        return f"""
QWidget#PanelCard {{ background: transparent; }}
QLabel {{ background: transparent; font-family: "Segoe UI"; }}
QLabel#PanelTitle {{ font-size: 14px; font-weight: 500; color: {t['TEXT']}; }}
QLabel#PanelTotal {{ font-size: 12px; color: {t['TEXT_55']}; }}
QLabel#PanelHint  {{ font-size: 11px; color: {t['TEXT_55']}; }}

QTreeWidget#PanelList {{
    background: transparent;
    border: none;
    outline: none;
    font-family: "Segoe UI";
    font-size: 12px;
    color: {t['TEXT']};
}}
QTreeWidget#PanelList::item {{
    height: 22px;
    border-radius: 4px;
    padding: 0px 4px;
}}
QTreeWidget#PanelList::item:hover {{ background: rgba(128, 128, 128, 20); }}
QTreeWidget#PanelList::item:selected {{
    background: {t['ACCENT']};
    color: {t['ON_ACCENT']};
}}
/* A protected row is listed but cannot be picked; say so in the colour. */
QTreeWidget#PanelList::item:disabled {{ color: {t['TEXT_45']}; }}

QPushButton#PanelDanger {{
    background: transparent;
    border: 1px solid {t['DIVIDER']};
    border-radius: 6px;
    padding: 5px 12px;
    font-size: 12px;
    color: {t['TEXT']};
}}
QPushButton#PanelDanger:hover {{
    border-color: {t['ERROR']};
    color: {t['ERROR']};
}}
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px 0px 2px 0px;
}}
QScrollBar::handle:vertical {{
    background: {t['SCROLL_HANDLE']};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: {t['SCROLL_HANDLE_HOVER']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

QPushButton#PanelDanger:disabled {{
    color: {t['TEXT_45']};
    border-color: {t['DIVIDER']};
}}
""" + chrome_qss(t)

    def paintEvent(self, event):  # noqa: N802 - Qt naming
        """Card fill plus the shadow outside it, the same way the overlay
        does it — and for the same reason: a QGraphicsDropShadowEffect
        would sit behind the whole silhouette and show through."""
        card = QRectF(self.card.geometry())
        if card.isEmpty():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        hole = QPainterPath()
        hole.addRoundedRect(card, RADIUS, RADIUS)
        whole = QPainterPath()
        whole.addRect(QRectF(self.rect()))
        p.setClipPath(whole.subtracted(hole))
        p.setBrush(Qt.NoBrush)
        for step in range(GUTTER):
            fade = (1.0 - step / float(GUTTER)) ** 2
            pen = QPen(QColor(0, 0, 0, max(1, round(SHADOW_ALPHA * fade))))
            pen.setWidthF(1.6)
            p.setPen(pen)
            p.drawRoundedRect(
                card.adjusted(-step, -step + SHADOW_OFFSET_Y,
                              step, step + SHADOW_OFFSET_Y),
                RADIUS + step, RADIUS + step)

        p.setClipping(False)
        p.setPen(Qt.NoPen)
        p.setBrush(getattr(self, "_fill", QColor("#fafafa")))
        p.drawRoundedRect(card, RADIUS, RADIUS)
        p.end()
