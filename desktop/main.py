from __future__ import annotations
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading

os.environ.update(HF_HUB_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1', DO_NOT_TRACK='1')
from PySide6.QtCore import QLockFile, QTimer, Qt
from PySide6.QtGui import QFontDatabase, QFont
from PySide6.QtWidgets import QApplication, QMessageBox
from pet.config import ROOT, load_config
from pet.controller import Controller
from pet.window import PetWindow
from pet.mobile import MobileBridge


def ensure_server(base_url: str) -> None:
    from urllib.parse import urlparse
    url = urlparse(base_url)
    try:
        with socket.create_connection((url.hostname, url.port or 80), timeout=1):
            return
    except OSError:
        cli = Path.home() / '.lmstudio/bin/lms.exe'
        if cli.exists():
            try:
                subprocess.run([str(cli), 'server', 'start', '--port', str(url.port or 80)],
                               creationflags=subprocess.CREATE_NO_WINDOW, timeout=60,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                logging.exception('Could not start local server')


def attach_default_desktop() -> None:
    try:
        import ctypes
        user = ctypes.WinDLL('user32')
        hDesk = user.OpenDesktopW('Default', 0, False, 0x1ff)
        if hDesk:
            user.SetThreadDesktop(hDesk)
    except Exception:
        pass


def main() -> int:
    attach_default_desktop()
    show_pairing = '--pair' in sys.argv
    show_muted = '--show-muted' in sys.argv
    (ROOT / 'logs').mkdir(exist_ok=True)
    handler = RotatingFileHandler(ROOT / 'logs/pet.log', maxBytes=1_000_000, backupCount=2, encoding='utf-8')
    logging.basicConfig(level=logging.INFO, handlers=[handler], format='%(asctime)s %(levelname)s %(message)s')
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('faster_whisper').setLevel(logging.WARNING)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication([arg for arg in sys.argv if arg not in {'--pair', '--show-muted'}])
    font_path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/segoeui.ttf'
    if font_path.exists():
        QFontDatabase.addApplicationFont(str(font_path))
        app.setFont(QFont('Segoe UI', 10))
    app.setQuitOnLastWindowClosed(False)
    lock = QLockFile(str(ROOT / 'pet.lock'))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, 'Alex', 'Alex đang chạy. Tìm pet hoặc biểu tượng Alex ở khay hệ thống.')
        return 0
    bridge = None
    try:
        cfg = load_config()
        engine = Controller(cfg)
        if show_muted:
            engine.paused.set()
        if cfg.get('mobile', {}).get('enabled', False):
            try:
                mobile_cfg = cfg['mobile']
                bridge = MobileBridge(engine.mobile_jobs, mobile_cfg.get('port', 8768),
                                      mobile_cfg.get('bind_host', 'auto'),
                                      mobile_cfg.get('allowed_client_ip'))
                bridge.start()
            except Exception:
                logging.exception('Phone bridge could not start')
                bridge = None
        window = PetWindow(cfg, engine, bridge)
        if show_muted or not cfg['pet'].get('start_hidden', False):
            window.show()
        engine.start()
        if show_pairing:
            logging.info('Opening phone pairing dialog on request')
            QTimer.singleShot(500, window.show_phone_pairing)
        return app.exec()
    except Exception as exc:
        logging.exception('Application failed')
        QMessageBox.critical(None, 'Alex', str(exc))
        return 1
    finally:
        if bridge:
            bridge.close()
        lock.unlock()


if __name__ == '__main__':
    raise SystemExit(main())
