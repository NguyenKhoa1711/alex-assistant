import os
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
from PySide6.QtCore import QCoreApplication
from PySide6.QtNetwork import QLocalSocket
from pet.app_ipc import request_show, server_name


class AppIPCTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_activation_only_same_user_pipe(self):
        with tempfile.TemporaryDirectory(prefix='alex-ipc-test-') as folder:
            root = Path(folder)
            script = ("from pathlib import Path\n"
                      "from PySide6.QtCore import QCoreApplication,QTimer\n"
                      "from pet.app_ipc import AppActivation\n"
                      "import sys\n"
                      "app=QCoreApplication([])\n"
                      "root=Path(sys.argv[1])\n"
                      "def show():\n"
                      " p=root/'called'; p.write_text(p.read_text()+'x' if p.exists() else 'x')\n"
                      "server=AppActivation(root,show)\n"
                      "(root/'ready').touch()\n"
                      "QTimer.singleShot(12000,app.quit)\n"
                      "app.exec()\n")
            proc = subprocess.Popen([sys.executable, '-c', script, str(root)],
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            try:
                import time
                deadline = time.monotonic() + 10
                while not (root/'ready').exists() and time.monotonic() < deadline:
                    time.sleep(.05)
                if not (root/'ready').exists():
                    proc.terminate()
                    output = proc.communicate(timeout=5)[0]
                    self.fail('IPC fixture did not start: ' + output.decode('utf-8', errors='replace'))
                self.assertTrue(request_show(root))
                self.assertEqual((root/'called').read_text(), 'x')
                socket = QLocalSocket()
                socket.connectToServer(server_name(root))
                self.assertTrue(socket.waitForConnected(700))
                socket.write(b'run arbitrary command\n')
                socket.waitForBytesWritten(700)
                socket.waitForReadyRead(700)
                socket.abort()
                self.assertEqual((root/'called').read_text(), 'x')
                self.assertTrue(request_show(root))
                self.assertEqual((root/'called').read_text(), 'xx')
            finally:
                proc.terminate()
                proc.communicate(timeout=5)


if __name__ == '__main__':
    unittest.main()
