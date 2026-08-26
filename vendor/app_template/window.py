"""Frameless window chrome that Windows still treats as a real window.

Instead of Qt.FramelessWindowHint (which makes a borderless popup the shell
refuses to snap), the frame is removed *natively*: WM_NCCALCSIZE reports the
whole window as client area, so there is no title bar or border to see, yet
the window keeps WS_THICKFRAME | WS_CAPTION | WS_MAXIMIZEBOX. That is what
makes it behave like Explorer — drag-to-edge snap with the layout hints,
Win+Arrow, Snap Layouts, and the native minimise/maximise animations.

Because it is a normal opaque window, DWM (Windows 11) draws the drop
shadow and a 1px border, rounds the corners, and — crucially — *clips* the
window to that rounded shape, so the close button's red hover fill can no
longer paint a hard square past the corner. The border colour follows the
theme (DWMWA_BORDER_COLOR), refreshed from the theme BUS.

Resizing is native (WM_NCHITTEST reports the edges); dragging is the native
caption (the title bar reports HTCAPTION), so the compositor owns move and
snap. The behaviour lives in _NativeChrome, a mixin shared by the window
and the settings dialog. Ported from houdini-launcher, reworked for snap.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QPoint, QRect, QRectF, Qt
from PySide6.QtGui import (QColor, QCursor, QGuiApplication, QIcon, QPainter,
                           QPen)
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from . import theme

_IS_WIN = sys.platform == "win32"

# width of the invisible edge strip that starts a native resize
_RESIZE_BORDER = 8

# geometry-restore safety: minimum visible title-bar strip on a live screen
_TITLE_BAR_H = 44
_MIN_GRAB_W = 120
_MIN_GRAB_H = 12


# --- Win32 plumbing (all native behaviour lives behind this guard) -----------

if _IS_WIN:
    import ctypes
    from ctypes import wintypes

    WM_NCCALCSIZE = 0x0083
    WM_NCHITTEST = 0x0084

    GWL_STYLE = -16
    WS_MAXIMIZEBOX = 0x00010000
    WS_MINIMIZEBOX = 0x00020000
    WS_THICKFRAME = 0x00040000
    WS_CAPTION = 0x00C00000
    WS_SYSMENU = 0x00080000

    HTCLIENT = 1
    HTCAPTION = 2
    HTLEFT = 10
    HTRIGHT = 11
    HTTOP = 12
    HTTOPLEFT = 13
    HTTOPRIGHT = 14
    HTBOTTOM = 15
    HTBOTTOMLEFT = 16
    HTBOTTOMRIGHT = 17

    SWP_NOSIZE = 0x0001
    SWP_NOMOVE = 0x0002
    SWP_NOZORDER = 0x0004
    SWP_NOACTIVATE = 0x0010
    SWP_FRAMECHANGED = 0x0020

    SM_CXSIZEFRAME = 32
    SM_CXPADDEDBORDER = 92

    # DWM (Windows 11): round + clip the window, colour its 1px border
    DWMWA_WINDOW_CORNER_PREFERENCE = 33
    DWMWCP_ROUND = 2
    DWMWA_BORDER_COLOR = 34

    ABM_GETSTATE = 0x00000004
    ABM_GETTASKBARPOS = 0x00000005
    ABS_AUTOHIDE = 0x00000001
    ABE_LEFT, ABE_TOP, ABE_RIGHT, ABE_BOTTOM = 0, 1, 2, 3

    class NCCALCSIZE_PARAMS(ctypes.Structure):
        _fields_ = [("rgrc", wintypes.RECT * 3), ("lppos", ctypes.c_void_p)]

    class APPBARDATA(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
                    ("uCallbackMessage", wintypes.UINT), ("uEdge", wintypes.UINT),
                    ("rc", wintypes.RECT), ("lParam", wintypes.LPARAM)]

    def _colorref(hex_color):
        """#rrggbb -> Win32 COLORREF (0x00bbggrr)."""
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return (b << 16) | (g << 8) | r

    def _frame_thickness(hwnd):
        """The sizing-frame width Windows expects, DPI-aware. When maximized
        a frameless window would otherwise spill this much past the work
        area (over the taskbar), so WM_NCCALCSIZE adds it back."""
        try:
            user32 = ctypes.windll.user32
            if (hasattr(user32, "GetDpiForWindow")
                    and hasattr(user32, "GetSystemMetricsForDpi")):
                dpi = user32.GetDpiForWindow(hwnd) or 96
                return (user32.GetSystemMetricsForDpi(SM_CXSIZEFRAME, dpi)
                        + user32.GetSystemMetricsForDpi(SM_CXPADDEDBORDER, dpi))
            return (user32.GetSystemMetrics(SM_CXSIZEFRAME)
                    + user32.GetSystemMetrics(SM_CXPADDEDBORDER))
        except Exception:
            return 8

    def _autohide_edge():
        """Screen edge of an auto-hide taskbar, or None. A maximized window
        that covers the last pixel stops the bar from popping, so that edge
        is left 1px short."""
        try:
            shell32 = ctypes.windll.shell32
            data = APPBARDATA()
            data.cbSize = ctypes.sizeof(APPBARDATA)
            state = shell32.SHAppBarMessage(ABM_GETSTATE, ctypes.byref(data))
            if not (state & ABS_AUTOHIDE):
                return None
            pos = APPBARDATA()
            pos.cbSize = ctypes.sizeof(APPBARDATA)
            if shell32.SHAppBarMessage(ABM_GETTASKBARPOS, ctypes.byref(pos)):
                return pos.uEdge
            return ABE_BOTTOM
        except Exception:
            return None


class WindowButton(QPushButton):
    """Minimise / maximise / close, drawn at paint time with theme colors."""

    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setObjectName("CloseBtn" if kind == "close" else "WinBtn")
        self.setFixedSize(44, 44)
        self.setCursor(Qt.ArrowCursor)
        self.setFocusPolicy(Qt.NoFocus)

    def paintEvent(self, event):  # noqa: N802 - Qt naming
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(theme.current_tokens()["TEXT"]))
        pen.setWidthF(1.1)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        cx, cy, r = self.width() / 2, self.height() / 2, 5
        if self.kind == "minimise":
            p.drawLine(int(cx - r), int(cy), int(cx + r), int(cy))
        elif self.kind == "maximise":
            p.drawRect(QRectF(cx - r, cy - r, r * 2, r * 2))
        else:
            p.drawLine(int(cx - r), int(cy - r), int(cx + r), int(cy + r))
            p.drawLine(int(cx + r), int(cy - r), int(cx - r), int(cy + r))
        p.end()


class TitleBar(QWidget):
    """App mark, title, and window buttons. On Windows the strip is reported
    as HTCAPTION so the compositor drives dragging + snap; the Qt handlers
    below are the fallback for any non-Windows host."""

    def __init__(self, title, icon=None, buttons=("min", "max", "close"),
                 parent=None):
        super().__init__(parent)
        self.setObjectName("TitleBar")
        self.setFixedHeight(_TITLE_BAR_H)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 0, 0)
        lay.setSpacing(0)

        if icon is not None and not icon.isNull():
            mark = QLabel()
            mark.setPixmap(icon.pixmap(20, 20))
            mark.setFixedSize(20, 20)
            lay.addWidget(mark)
            lay.addSpacing(10)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("TitleText")
        lay.addWidget(self.title_label)
        lay.addStretch(1)

        self.btn_min = WindowButton("minimise") if "min" in buttons else None
        self.btn_max = WindowButton("maximise") if "max" in buttons else None
        self.btn_close = WindowButton("close") if "close" in buttons else None
        for b in (self.btn_min, self.btn_max, self.btn_close):
            if b is not None:
                lay.addWidget(b)

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None:
                handle.startSystemMove()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton and self.btn_max is not None:
            self.btn_max.click()
        super().mouseDoubleClickEvent(event)


class _NativeChrome:
    """Mixin that turns a plain *opaque* top-level QWidget/QDialog into a
    frameless, DWM-rounded window Windows still treats natively (snap,
    Win+Arrow, native animations, clipped corners).

    The host must, before calling ``self._init_native()``:
      * create ``self.title_bar`` (a TitleBar),
      * set ``self._resizable`` (bool),
    and must NOT set Qt.FramelessWindowHint or WA_TranslucentBackground.

    All of it is a no-op off Windows and under the offscreen platform, so
    the offscreen smoke tests never touch Win32.
    """

    def _init_native(self):
        self._hwnd = None
        if not _IS_WIN:
            return
        app = QApplication.instance()
        if app is not None and app.platformName() == "offscreen":
            return
        try:
            self._hwnd = int(self.winId())
        except Exception:
            self._hwnd = None
            return
        self._apply_native_styles()
        self._apply_dwm()
        theme.BUS.changed.connect(self._apply_border_color)

    def _apply_native_styles(self):
        if not self._hwnd:
            return
        try:
            user32 = ctypes.windll.user32
            style = user32.GetWindowLongW(self._hwnd, GWL_STYLE)
            style |= WS_CAPTION | WS_MINIMIZEBOX | WS_SYSMENU
            if getattr(self, "_resizable", False):
                style |= WS_THICKFRAME | WS_MAXIMIZEBOX
            user32.SetWindowLongW(self._hwnd, GWL_STYLE, style)
            # force a frame recalculation so WM_NCCALCSIZE runs before show
            user32.SetWindowPos(
                self._hwnd, 0, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE
                | SWP_FRAMECHANGED)
        except Exception:
            pass

    def _apply_dwm(self):
        if not self._hwnd:
            return
        try:
            pref = ctypes.c_int(DWMWCP_ROUND)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                self._hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(pref), ctypes.sizeof(pref))
        except Exception:
            pass  # pre-Win11: square corners, harmless
        self._apply_border_color()

    def _apply_border_color(self):
        """Colour the DWM border from the theme's WINDOW_BORDER token, so it
        tracks the app's palette rather than the system's. Called on every
        theme change via the BUS."""
        if not _IS_WIN or not getattr(self, "_hwnd", None):
            return
        try:
            c = wintypes.DWORD(_colorref(theme.current_tokens()["WINDOW_BORDER"]))
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                self._hwnd, DWMWA_BORDER_COLOR, ctypes.byref(c), ctypes.sizeof(c))
        except Exception:
            pass  # pre-Win11: no custom border, harmless

    def showEvent(self, event):  # noqa: N802
        # re-assert DWM once the window is actually mapped (some attributes
        # only stick then); cheap and idempotent
        if _IS_WIN and getattr(self, "_hwnd", None):
            self._apply_dwm()
        super().showEvent(event)

    def nativeEvent(self, eventType, message):  # noqa: N802
        if _IS_WIN and getattr(self, "_hwnd", None) \
                and eventType == b"windows_generic_MSG":
            try:
                msg = wintypes.MSG.from_address(int(message))
            except Exception:
                return super().nativeEvent(eventType, message)
            if msg.hWnd == self._hwnd:
                if msg.message == WM_NCCALCSIZE and msg.wParam:
                    # keep client == whole window (no frame); only special-
                    # case maximized so it doesn't swallow the taskbar
                    self._nc_calc_size(msg)
                    return True, 0
                if msg.message == WM_NCHITTEST:
                    return True, self._hit_test()
        return super().nativeEvent(eventType, message)

    def _nc_calc_size(self, msg):
        if not self.isMaximized():
            return
        try:
            params = NCCALCSIZE_PARAMS.from_address(msg.lParam)
            th = _frame_thickness(self._hwnd)
            params.rgrc[0].left += th
            params.rgrc[0].top += th
            params.rgrc[0].right -= th
            params.rgrc[0].bottom -= th
            edge = _autohide_edge()
            if edge == ABE_TOP:
                params.rgrc[0].top += 1
            elif edge == ABE_BOTTOM:
                params.rgrc[0].bottom -= 1
            elif edge == ABE_LEFT:
                params.rgrc[0].left += 1
            elif edge == ABE_RIGHT:
                params.rgrc[0].right -= 1
        except Exception:
            pass

    def _hit_test(self):
        local = self.mapFromGlobal(QCursor.pos())
        x, y = local.x(), local.y()
        w, h = self.width(), self.height()
        b = _RESIZE_BORDER
        if getattr(self, "_resizable", False) \
                and not self.isMaximized() and not self.isFullScreen():
            left, right = x < b, x >= w - b
            top, bottom = y < b, y >= h - b
            if top and left:
                return HTTOPLEFT
            if top and right:
                return HTTOPRIGHT
            if bottom and left:
                return HTBOTTOMLEFT
            if bottom and right:
                return HTBOTTOMRIGHT
            if top:
                return HTTOP
            if bottom:
                return HTBOTTOM
            if left:
                return HTLEFT
            if right:
                return HTRIGHT
        # the title bar drags (and snaps) as a native caption, except over
        # the window buttons, which must stay client so Qt gets the click
        if self._in_titlebar(local) and not self._over_button(local):
            return HTCAPTION
        return HTCLIENT

    def _in_titlebar(self, local):
        tb = self.title_bar
        tl = tb.mapTo(self, QPoint(0, 0))
        return QRect(tl, tb.size()).contains(local)

    def _over_button(self, local):
        for btn in (self.title_bar.btn_min, self.title_bar.btn_max,
                    self.title_bar.btn_close):
            if btn is None:
                continue
            tl = btn.mapTo(self, QPoint(0, 0))
            if QRect(tl, btn.size()).contains(local):
                return True
        return False


class FramelessWindow(_NativeChrome, QWidget):
    """Rounded frameless top-level with native Windows behaviour: Aero Snap,
    the drag-to-edge layout hints, Win+Arrow and Snap Layouts all work.

    It is a normal opaque window; the frame is removed natively (see the
    module docstring) rather than with Qt.FramelessWindowHint, and DWM owns
    the rounding, shadow and border.

    persist=(settings, "window") restores the geometry on creation and
    saves it back on close.
    """

    def __init__(self, title, icon=None, buttons=("min", "max", "close"),
                 resizable=True, persist=None, parent=None):
        super().__init__(parent)
        # No FramelessWindowHint and no translucency: a plain top-level
        # window is what the shell snaps and DWM rounds/clips.
        self.setWindowTitle(title)
        self._resizable = resizable
        self._persist = persist

        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)  # DWM owns the border + shadow

        self.root = QWidget(objectName="Root")
        shell.addWidget(self.root)

        root_lay = QVBoxLayout(self.root)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)

        self.title_bar = TitleBar(title, icon, buttons, self.root)
        root_lay.addWidget(self.title_bar)

        content = QWidget(self.root)
        content.setObjectName("Content")
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(22, 14, 22, 20)
        self.content_layout.setSpacing(10)
        root_lay.addWidget(content, 1)

        if self.title_bar.btn_min is not None:
            self.title_bar.btn_min.clicked.connect(self.showMinimized)
        if self.title_bar.btn_max is not None:
            self.title_bar.btn_max.clicked.connect(self._toggle_maximized)
        if self.title_bar.btn_close is not None:
            self.title_bar.btn_close.clicked.connect(self.close)

        if persist is not None:
            self._restore_geometry()

        self._init_native()

    # --- maximize handling ------------------------------------------------

    def _toggle_maximized(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def changeEvent(self, event):  # noqa: N802
        if event.type() == event.Type.WindowStateChange:
            maxed = self.isMaximized() or self.isFullScreen()
            # "maximized" would collide with QWidget's read-only meta
            # property of that name and setProperty() would be swallowed;
            # kept as a hook for apps that restyle in the maximized state
            val = "true" if maxed else "false"
            for w in (self.root, self.title_bar):
                w.setProperty("winMaximized", val)
                w.style().unpolish(w)
                w.style().polish(w)
        super().changeEvent(event)

    # --- geometry persistence --------------------------------------------

    def _restore_geometry(self):
        settings, key = self._persist
        geo = settings.get(key)
        if not (isinstance(geo, list) and len(geo) == 4
                and all(isinstance(v, int) for v in geo)):
            return
        x, y, w, h = geo
        if w >= 200 and h >= 150:
            # Only the title bar can drag a frameless window back, so the
            # saved rect is kept only if enough of that strip is reachable
            # on a currently-connected screen (taskbar area excluded).
            strip = QRect(x, y, w, _TITLE_BAR_H)
            for screen in QGuiApplication.screens():
                visible = strip.intersected(screen.availableGeometry())
                if (visible.width() >= _MIN_GRAB_W
                        and visible.height() >= _MIN_GRAB_H):
                    self.setGeometry(x, y, w, h)
                    return
        # unreachable (monitor unplugged) or nonsense rect: forget it so
        # the window opens at its default and persists a fresh rect
        settings.data.pop(key, None)

    def closeEvent(self, event):  # noqa: N802
        if self._persist is not None:
            settings, key = self._persist
            g = self.geometry()
            settings[key] = [g.x(), g.y(), g.width(), g.height()]
            settings.save()
        super().closeEvent(event)
