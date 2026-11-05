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
from PySide6.QtCore import QAbstractNativeEventFilter, QLockFile, QTimer, Qt
from PySide6.QtGui import QFontDatabase, QFont
from PySide6.QtWidgets import QApplication, QMessageBox
from pet.config import ROOT, load_config
from pet.controller import Controller
from pet.window import PetWindow
from pet.mobile import MobileBridge
from pet.remote_standby import start_remote_wait, stop_remote_wait, notify_resume


class PowerResumeFilter(QAbstractNativeEventFilter):
    def nativeEventFilter(self, event_type, message):
        if sys.platform == 'win32':
            import ctypes
            from ctypes import wintypes
            native = wintypes.MSG.from_address(int(message))
            if native.message == 0x0218 and native.wParam in (7, 18):
                notify_resume()
        return False, 0


def ensure_server(base_url: str) -> bool:
    try:
        from pet.llm import ensure_local_server
        return ensure_local_server(base_url)
    except Exception:
        logging.exception('Could not start local server')
        return False


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
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Alex.Desktop')
    show_app = '--app' in sys.argv
    show_pairing = '--pair' in sys.argv
    show_muted = '--show-muted' in sys.argv or show_app
    (ROOT / 'logs').mkdir(exist_ok=True)
    handler = RotatingFileHandler(ROOT / 'logs/pet.log', maxBytes=1_000_000, backupCount=2, encoding='utf-8')
    logging.basicConfig(level=logging.INFO, handlers=[handler], format='%(asctime)s %(levelname)s %(message)s')
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('faster_whisper').setLevel(logging.WARNING)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication([arg for arg in sys.argv if arg not in {'--pair', '--show-muted', '--app'}])
    font_path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/segoeui.ttf'
    if font_path.exists():
        QFontDatabase.addApplicationFont(str(font_path))
        app.setFont(QFont('Segoe UI', 10))
    app.setQuitOnLastWindowClosed(False)
    power_events = PowerResumeFilter()
    app.installNativeEventFilter(power_events)
    lock = QLockFile(str(ROOT / 'pet.lock'))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        if show_app:
            from pet.app_ipc import request_show
            if request_show(ROOT):
                return 0
        QMessageBox.information(None, 'Alex', 'Alex đang chạy. Tìm pet hoặc biểu tượng Alex ở khay hệ thống.')
        return 0
    bridge = None
    try:
        cfg = load_config()
        if cfg.get('gemini', {}).get('offline_fallback', False) or 'gemini' not in cfg:
            threading.Thread(
                target=ensure_server,
                args=(cfg.get('llm', {}).get('base_url', 'http://127.0.0.1:1234'),),
                name='Alex-LLM-Server',
                daemon=True,
            ).start()
        engine = Controller(cfg)
        if show_muted:
            engine.paused.set()
        if cfg.get('mobile', {}).get('enabled', False):
            try:
                mobile_cfg = cfg['mobile']
                bridge = MobileBridge(engine.mobile_jobs, mobile_cfg.get('port', 8768),
                                      mobile_cfg.get('bind_host', 'auto'),
                                      mobile_cfg.get('allowed_client_ip'),
                                      remote_proxy_port=mobile_cfg.get('remote_proxy_port', 8769))
                bridge.start()
            except Exception:
                logging.exception('Phone bridge could not start')
                bridge = None
        window = PetWindow(cfg, engine, bridge)
        from pet.app_ipc import AppActivation
        activation = AppActivation(ROOT, window.show_desktop_app, window)
        try:
            start_remote_wait(bool(bridge and cfg.get('power', {}).get('remote_wait_on_ac', False)))
        except OSError:
            logging.exception('Remote waiting on AC could not start')
        engine.start()
        if show_muted or not cfg['pet'].get('start_hidden', False):
            window.show()
        if show_app:
            QTimer.singleShot(0, window.show_desktop_app)
        if show_pairing:
            logging.info('Opening phone pairing dialog on request')
            QTimer.singleShot(500, window.show_phone_pairing)
        return app.exec()
    except Exception as exc:
        logging.exception('Application failed')
        QMessageBox.critical(None, 'Alex', str(exc))
        return 1
    finally:
        stop_remote_wait()
        if bridge:
            bridge.close()
        lock.unlock()


if __name__ == '__main__':
    raise SystemExit(main())
