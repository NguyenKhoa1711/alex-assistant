"""Same-user named pipe used only to show the existing Alex window."""
from __future__ import annotations
import hashlib
from pathlib import Path
from PySide6.QtCore import QObject, QTimer, QCoreApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket


def server_name(root: Path) -> str:
    identity = str(root.resolve()).casefold() + str(Path.home()).casefold()
    return 'AlexDesktop-' + hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]


def request_show(root: Path) -> bool:
    app = QCoreApplication.instance() or QCoreApplication([])
    socket = QLocalSocket()
    socket.connectToServer(server_name(root))
    if not socket.waitForConnected(700):
        return False
    socket.write(b'show\n')
    socket.waitForBytesWritten(700)
    if not socket.waitForReadyRead(1500):
        socket.abort()
        return False
    ok = bytes(socket.readAll()).strip() == b'ok'
    socket.disconnectFromServer()
    return ok


class AppActivation(QObject):
    def __init__(self, root: Path, show, parent=None):
        super().__init__(parent)
        self.show = show
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._accept)
        if not self.server.listen(server_name(root)):
            raise RuntimeError('Không tạo được kênh mở cửa sổ Alex: ' + self.server.errorString())

    def _accept(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            socket.setReadBufferSize(32)
            socket.readyRead.connect(lambda s=socket: self._read(s))
            socket.disconnected.connect(socket.deleteLater)
            timer = QTimer(socket)
            timer.setSingleShot(True)
            timer.timeout.connect(socket.abort)
            timer.start(2000)
            self._read(socket)

    def _read(self, socket):
        if not socket.canReadLine():
            return
        if bytes(socket.readLine(32)) != b'show\n':
            socket.abort()
            return
        # This pipe cannot submit chat, shell commands or machine actions.
        self.show()
        socket.write(b'ok\n')
        socket.disconnectFromServer()
