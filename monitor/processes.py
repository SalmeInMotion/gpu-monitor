"""The panel behind a click on the VRAM or RAM bar.

Answers one question — "what is holding this memory, and can I get it
back" — so it is a list sorted by size, grouped per executable, with
everything under the kind's threshold left out, and a button that ends
what you pick.

Wears the card's own skin (same tokens, same painted rounded rect and
hand-drawn shadow) rather than a system window, because it belongs to the
card that opened it.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout,
                               QHeaderView, QLabel, QMenu, QMessageBox,
                               QPlainTextEdit, QPushButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from . import breakdown as bd
from . import metrics as M
from .chrome import (ChromeButton, GLYPH_CLOSE, GLYPH_REFRESH,
                     chrome_qss)

log = logging.getLogger("gpu_monitor.processes")

GUTTER = 6              # room for the shadow, as on the card
RADIUS = 14.0           # ia-usage's secondary surfaces (toast, tray menu)
SHADOW_ALPHA = 71       # 0.28, the dialog weight rather than the popup's
SHADOW_OFFSET_Y = 2
PAD = 16

PANEL_WIDTH = 340
MAX_ROWS_SHOWN = 9      # past this the list scrolls instead of growing
ROW_HEIGHT = 22         # kept in step with the QSS below

# There is no auto-refresh, on purpose. Ivan, watching rows re-sort
# themselves while he tried to click one: "para que la lista no cambie de
# posicion, pongamos un boton de refresh". Opening the panel reads once;
# after that the list holds still until Refresh is pressed.

# Between two stacked panels, measured between what you can *see*. Each
# window carries a GUTTER of transparent shadow room on every side, so
# the windows themselves overlap by 2*GUTTER - STACK_GAP for the painted
# cards to sit this far apart.
STACK_GAP = 8

# Straight from the metric table, so the panel is always titled with the
# exact word that was double-clicked. "Video memory"/"System memory" read
# as near-synonyms at a glance, which is the mix-up this must not invite.
TITLES = {m.key: m.label for m in M.METRICS if m.breakdown}

# A command line can run to two thousand characters -- Edge's renderers do
# -- and a tooltip that tall covers the panel it belongs to.
TIP_CHARS = 420


def _elide(text, limit=TIP_CHARS):
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


def paint_card(widget, card_widget):
    """Card fill plus the shadow outside it, the same way the overlay does
    it — and for the same reason: a QGraphicsDropShadowEffect would sit
    behind the whole silhouette and show through.

    Shared, so the details window cannot drift away from the panel it
    belongs to."""
    card = QRectF(card_widget.geometry())
    if card.isEmpty():
        return
    p = QPainter(widget)
    p.setRenderHint(QPainter.Antialiasing, True)

    hole = QPainterPath()
    hole.addRoundedRect(card, RADIUS, RADIUS)
    whole = QPainterPath()
    whole.addRect(QRectF(widget.rect()))
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
    p.setBrush(getattr(widget, "_fill", QColor("#fafafa")))
    p.drawRoundedRect(card, RADIUS, RADIUS)
    p.end()


class DetailsWindow(QWidget):
    """Everything knowable about one row, on a right-click.

    Ivan's own suggestion, and the right shape for it: a row is one line
    and some of these answers are a 400-character command line. It is
    **not** modal and not part of the panel stack -- a window that has to
    be answered is exactly what trapped him once already.
    """

    WIDTH = 560
    MAX_HEIGHT = 460

    def __init__(self, theme, settings, title, body, parent=None):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool
                         | Qt.WindowStaysOnTopHint)
        self.theme = theme
        self.settings = settings
        self._fill = QColor("#fafafa")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setWindowTitle(f"GPU Monitor - {title}")
        self.setFixedWidth(self.WIDTH + 2 * GUTTER)

        shell = QVBoxLayout(self)
        shell.setContentsMargins(GUTTER, GUTTER, GUTTER, GUTTER)
        self.card = QWidget(self)
        self.card.setObjectName("PanelCard")
        shell.addWidget(self.card)

        body_box = QVBoxLayout(self.card)
        body_box.setContentsMargins(PAD, PAD, PAD, PAD)
        body_box.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(6)
        self.title = QLabel(title, objectName="PanelTitle")
        self.btn_close = ChromeButton(GLYPH_CLOSE, "Close", self.card)
        self.btn_close.clicked.connect(self.close)
        head.addWidget(self.title, 1)
        head.addWidget(self.btn_close, 0)
        body_box.addLayout(head)

        self.text = QPlainTextEdit(body, self.card)
        self.text.setObjectName("DetailsText")
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.NoWrap)
        # Selectable on purpose: a command line is something you paste
        # somewhere else, and there is nowhere else to get it from.
        self.text.setTextInteractionFlags(Qt.TextSelectableByMouse
                                          | Qt.TextSelectableByKeyboard)
        body_box.addWidget(self.text, 1)

        self.theme.changed.connect(self.apply_theme)
        self.apply_theme()
        self._fit(body)

    def _fit(self, body):
        rows = body.count("\n") + 1
        metrics = self.text.fontMetrics()
        wanted = rows * (metrics.lineSpacing() + 1) + 16
        self.text.setFixedHeight(max(80, min(self.MAX_HEIGHT, wanted)))
        self.adjustSize()

    def apply_theme(self):
        tokens = self.theme.tokens or {}
        if not tokens:
            return
        fill = QColor(tokens["SURFACE"])
        fill.setAlpha(max(0, min(255, round(
            int(self.settings.get("opacity", 100)) / 100.0 * 255))))
        self._fill = fill
        self.setStyleSheet(f"""
QWidget#PanelCard {{ background: transparent; }}
QLabel#PanelTitle {{ font-size: 14px; font-weight: 500;
                     color: {tokens['TEXT']}; background: transparent; }}
QPlainTextEdit#DetailsText {{
    background: transparent;
    border: none;
    color: {tokens['TEXT_70']};
    font-family: {tokens['MONO_STACK']};
    font-size: 11px;
    selection-background-color: {tokens['ACCENT']};
    selection-color: {tokens['ON_ACCENT']};
}}
QScrollBar:vertical, QScrollBar:horizontal {{
    background: transparent; width: 8px; height: 8px; margin: 0;
}}
QScrollBar::handle {{ background: {tokens['SCROLL_HANDLE']};
                      border-radius: 4px; }}
QScrollBar::handle:hover {{ background: {tokens['SCROLL_HANDLE_HOVER']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
""" + chrome_qss(tokens))
        self.update()

    def paintEvent(self, event):  # noqa: N802 - Qt naming
        paint_card(self, self.card)

    def mousePressEvent(self, event):  # noqa: N802 - Qt naming
        if event.button() == Qt.LeftButton:
            handle = self.windowHandle()
            if handle is not None:
                handle.startSystemMove()

    def keyPressEvent(self, event):  # noqa: N802 - Qt naming
        if event.key() == Qt.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)


class ProcessPanel(QWidget):
    """A list of what is using one meter, and a way to end it.

    One panel is one kind for its whole life. Several can be open at once
    (Shift + double-click stacks them), so the kind cannot be a mutable
    property of a single shared window any more.
    """

    refresh_requested = Signal(str)     # kind
    closed = Signal(str)                # kind, so the overlay can forget it
    # Height changes when the rows arrive, and again on every refresh that
    # adds or drops one. Whoever stacks these has to hear about it.
    resized = Signal(str)

    def __init__(self, theme, settings, kind, parent=None):
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
        self._details = None
        self.kind = kind
        self._entries = []
        # In the stack the overlay lays out, until the user drags it out.
        self.stacked = True

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
        self.btn_refresh = ChromeButton(GLYPH_REFRESH, "Refresh", self.card)
        self.btn_refresh.clicked.connect(self._ask)
        self.btn_close = ChromeButton(GLYPH_CLOSE, "Close", self.card)
        self.btn_close.clicked.connect(self.close)
        head.addWidget(self.title, 1)
        head.addWidget(self.total, 0)
        head.addSpacing(2)
        head.addWidget(self.btn_refresh, 0)
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
        # Ivan's own suggestion: a row is one line, and some of what is
        # knowable about it is a 400-character command line.
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._row_menu)
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

        self.title.setText(TITLES.get(kind, kind.upper()))
        self._set_hint("Reading...")

        self.theme.changed.connect(self.apply_theme)
        self.apply_theme()

    # --- opening and closing ----------------------------------------------

    def open_at(self):
        """Show it. The overlay has already put it where it belongs."""
        self.show()
        self.raise_()
        self._ask()

    def place_at(self, point, card_pos):
        """Go exactly here. Positioning belongs to the overlay: a panel
        that worked out its own slot had to read the previous panel's
        frameGeometry() back, and right after a move() that is still the
        old rect on Windows -- so every pass computed a different layout
        and the stack oscillated forever at 100% CPU."""
        self._card_pos = card_pos
        self._offset = point - card_pos
        self._move_to(point)

    def set_topmost(self, on):
        """Leave or rejoin the always-on-top band. Changing the flag
        recreates the native window, so it is only touched when it really
        differs."""
        want = bool(on)
        if bool(self.windowFlags() & Qt.WindowStaysOnTopHint) == want:
            return
        visible = self.isVisible()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, want)
        if visible:
            self.show()

    def resizeEvent(self, event):  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        if self.stacked:
            self.resized.emit(self.kind)

    def closeEvent(self, event):  # noqa: N802 - Qt naming
        if self._details is not None:
            # It belongs to this panel; a details window outliving the
            # list it came from is an orphan nobody can trace back.
            self._details.close()
            self._details = None
        super().closeEvent(event)
        self.closed.emit(self.kind)

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
        # Only a free panel tracks an offset; a stacked one is positioned
        # by the overlay. Leaving the stack happens in mousePressEvent,
        # not here: show() also emits a moveEvent, and reading that as a
        # drag took every panel out of the stack the instant it opened.
        if not self._following and not self.stacked                 and self._card_pos is not None:
            self._offset = self.pos() - self._card_pos

    def mousePressEvent(self, event):  # noqa: N802 - Qt naming
        """The panel is frameless, so its own background is the handle.
        Without this there was no way to move it at all."""
        if event.button() == Qt.LeftButton:
            handle = self.windowHandle()
            if handle is not None:
                # Dragging it by hand is what takes it out of the stack:
                # the one gesture that can move a panel, and unambiguous,
                # where guessing from moveEvent is not.
                self.stacked = False
                self._card_pos = self._card_pos or self.pos()
                handle.startSystemMove()
                return
        super().mousePressEvent(event)

    def _move_to(self, point):
        """Move without it reading as a hand-drag -- and not at all when
        it is already there. The no-op matters: a move that changes
        nothing can still make Qt resize the window on a DPI boundary,
        and that resize asks for another lay-out."""
        if self.pos() == point:
            return
        self._following = True
        try:
            self.move(point)
        finally:
            self._following = False

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
        """The free-floating fallback: beside the card. Only used for a
        panel that is not in the stack."""
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
        self._move_to(QPoint(x, y))

    # --- data --------------------------------------------------------------

    def _ask(self):
        self.refresh_requested.emit(self.kind)

    def set_entries(self, kind, entries):
        """Called with whatever the sampler thread came back with."""
        if kind != self.kind or not self.isVisible():
            return
        keep = {i.text(0) for i in self.list.selectedItems()}
        # Rebuilding the list resets the scrollbar, which on a manual
        # refresh means the row you were reading jumps away from under the
        # pointer -- the whole complaint this button exists to answer.
        where = self.list.verticalScrollBar().value()
        self._entries = entries
        self.list.clear()
        for entry in entries:
            item = QTreeWidgetItem(
                [entry.name, bd.fmt_value(kind, entry.value)])
            item.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
            tip = _elide(entry.detail)
            if len(entry.pids) > 1:
                count = f"{len(entry.pids)} processes"
                tip = f"{tip}\n\n{count}" if tip else count
            if entry.protected:
                # Listed, because it is genuinely using the memory, but
                # not selectable: ending any of these takes Windows with
                # it. ItemIsEnabled without ItemIsSelectable is the
                # combination that still paints normally.
                item.setFlags(Qt.ItemIsEnabled)
                # Not instead of the detail: svchost is protected *and*
                # the one row whose hover matters most, since the services
                # inside it are the only thing that names it.
                tip = f"{tip}\n\nWindows needs this one" if tip \
                    else "Windows needs this one"
                # A QSS :disabled rule would not fire: the item is enabled,
                # just not selectable. Paint the difference directly.
                muted = QBrush(QColor(self._muted))
                item.setForeground(0, muted)
                item.setForeground(1, muted)
            if tip:
                item.setToolTip(0, tip)
            self.list.addTopLevelItem(item)
            if entry.name in keep and not entry.protected:
                item.setSelected(True)

        total = sum(e.value for e in entries)
        self.total.setText(bd.fmt_value(kind, total) if entries else "")
        limit = bd.fmt_threshold(kind)
        if entries:
            self._set_hint(f"Nothing under {limit} is listed.")
        else:
            self._set_hint(f"Nothing is using more than {limit}.")
        self._resize_list()
        self.list.verticalScrollBar().setValue(where)
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

    def _row_menu(self, point):
        """Right-click on a row: the long answer, for whoever wants it."""
        item = self.list.itemAt(point)
        if item is None:
            return
        entry = next((e for e in self._entries if e.name == item.text(0)), None)
        if entry is None:
            return
        menu = QMenu(self)
        menu.setStyleSheet(self._menu_qss(self.theme.tokens or {}))
        show = menu.addAction("Show details")
        chosen = menu.exec(self.list.viewport().mapToGlobal(point))
        if chosen is show:
            self.show_details(entry)

    def show_details(self, entry):
        """Open (or replace) the details window for one row.

        One at a time: a right-click that quietly piles up windows behind
        each other is how a monitor becomes the thing you have to tidy.
        """
        body = bd.details(entry, self.kind)
        if self._details is not None:
            self._details.close()
        self._details = DetailsWindow(self.theme, self.settings,
                                      entry.name, body)
        self._details.destroyed.connect(self._forget_details)
        here = self.frameGeometry()
        self._details.move(here.left(), here.bottom() + STACK_GAP)
        self._details.show()
        self._details.raise_()
        return self._details

    def _forget_details(self, *_):
        self._details = None

    def _menu_qss(self, t):
        if not t:
            return ""
        return f"""
QMenu {{ background: {t['SURFACE']}; color: {t['TEXT']};
         border: 1px solid {t['DIVIDER']}; border-radius: 8px;
         padding: 4px; font-family: "Segoe UI"; font-size: 12px; }}
QMenu::item {{ padding: 5px 14px; border-radius: 5px; }}
QMenu::item:selected {{ background: {t['ACCENT']}; color: {t['ON_ACCENT']}; }}
"""

    def _selected_entries(self):
        names = {i.text(0) for i in self.list.selectedItems()}
        return [e for e in self._entries
                if e.name in names and not e.protected]

    def _protected_selected(self):
        """Rows that are highlighted but must never be acted on.

        Walks the items rather than asking selectedItems(): the whole
        point is that Qt leaves isSelected() true on a row it refuses to
        put in that list, which is the mismatch this exists to clean up.
        """
        out = []
        for i in range(self.list.topLevelItemCount()):
            item = self.list.topLevelItem(i)
            if item.isSelected() and not (item.flags() & Qt.ItemIsSelectable):
                out.append(item)
        return out

    def _drop_protected_selection(self):
        """Un-highlight any protected row that got selected from code.

        ItemIsSelectable only stops the *user*: setSelected() ignores it,
        leaving a row that looks armed while selectedItems() -- and so the
        button -- excludes it. Clearing it has to wait a turn of the event
        loop: done inside itemSelectionChanged, Qt is still mid-update and
        simply re-applies the selection afterwards.
        """
        stuck = self._protected_selected()
        if not stuck:
            return
        self._clearing = True
        try:
            for item in stuck:
                item.setSelected(False)
        finally:
            self._clearing = False
        self._sync_button()

    def _sync_button(self):
        # Scheduled unconditionally, because during itemSelectionChanged
        # Qt has not yet marked the row as selected -- asking here whether
        # there is anything to clean always answers no, and the row stays
        # highlighted.
        #
        # What stops this pair looping is the early return in
        # _drop_protected_selection: it only calls back here when it
        # actually cleared something, so the chain is at most sync -> drop
        # -> sync -> drop(nothing) -> stop. Without that early return the
        # two scheduled each other through a 0ms timer forever: one core
        # burned per open panel, no Python event to show for it, and an
        # app too busy to answer its own Preferences dialog.
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
            f"  {e.name} - {bd.fmt_value(self.kind, e.value)}"
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
        paint_card(self, self.card)
