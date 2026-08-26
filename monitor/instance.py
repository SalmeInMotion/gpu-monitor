"""One card, not a stack of them: a single-instance guard.

Launching GPU Monitor while it is already running should not open a second
identical card — it should surface the one already there. The first instance
opens a named local server (a Windows named pipe under the hood); every later
launch finds that server, pokes it so the running card raises itself to the
front, and exits before building any window.

QLocalServer is used rather than a bare mutex because it is both halves of
what this needs in one mechanism sitting on Qt's own event loop: the "is one
already running?" test *and* the channel to tell that one to surface.
"""

from __future__ import annotations

import getpass
import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

log = logging.getLogger("gpu_monitor.instance")

# Local IPC on a pipe that either answers at once or is simply not there;
# nothing here is worth blocking startup on for longer than a breath.
_TIMEOUT_MS = 300


def _key(app_name):
    """A pipe name unique to this app and this Windows user, so two people
    signed into the same machine each keep their own single card."""
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    slug = "".join(c if c.isalnum() else "_" for c in app_name)
    return f"{slug}.singleton.{user}"


class SingleInstance(QObject):
    """Primary-instance guard. ``activated`` fires when a later launch pokes
    us, so the owner can surface its window."""

    activated = Signal()

    def __init__(self, app_name, parent=None):
        super().__init__(parent)
        self._key = _key(app_name)
        self._server = None

    def is_primary(self):
        """True when we now own the server and should build the UI; False
        after handing off to a running instance, meaning the caller exits."""
        if self._poke_existing():
            return False
        # Nobody answered — clear any pipe a crashed run left behind (a no-op
        # when there is none), then claim it.
        QLocalServer.removeServer(self._key)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_poke)
        if self._server.listen(self._key):
            return True
        # Lost a launch-time race with another starting instance: let it be
        # the primary and surface it instead.
        if self._poke_existing():
            return False
        # Neither owns nor can reach a peer — proceed anyway; one window is a
        # better failure than none.
        log.warning("single-instance server unavailable: %s",
                    self._server.errorString())
        return True

    def _poke_existing(self):
        """Connect to a running instance and nudge it. True if one answered.

        The nudge is any connection at all — the payload is not read on the
        far side — but a byte is sent and flushed so the channel could carry
        a command later without changing the protocol.
        """
        socket = QLocalSocket()
        socket.connectToServer(self._key)
        if not socket.waitForConnected(_TIMEOUT_MS):
            return False
        socket.write(b"raise")
        socket.flush()
        socket.waitForBytesWritten(_TIMEOUT_MS)
        socket.disconnectFromServer()
        if socket.state() != QLocalSocket.LocalSocketState.UnconnectedState:
            socket.waitForDisconnected(_TIMEOUT_MS)
        return True

    def _on_poke(self):
        conn = self._server.nextPendingConnection()
        if conn is not None:
            conn.disconnected.connect(conn.deleteLater)
        self.activated.emit()
