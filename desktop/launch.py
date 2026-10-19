from __future__ import annotations
import ctypes
import logging
import subprocess
from PySide6.QtCore import QLockFile
from pet.config import ROOT, load_config
from pet.launcher import open_bionic

def attach_default_desktop() -> None:
    try:
        user = ctypes.WinDLL('user32')
        hDesk = user.OpenDesktopW('Default', 0, False, 0x1ff)
        if hDesk:
            user.SetThreadDesktop(hDesk)
    except Exception:
        pass


if __name__ == '__main__':
    (ROOT / 'logs').mkdir(exist_ok=True)
    logging.basicConfig(filename=ROOT / 'logs/launcher.log', encoding='utf-8', level=logging.INFO)
    try:
        attach_default_desktop()
        lock = QLockFile(str(ROOT / 'pet.lock'))
        lock.setStaleLockTime(0)
        if lock.tryLock(100):
            lock.unlock()
            subprocess.Popen([str(ROOT / '.venv/Scripts/pythonw.exe'), str(ROOT / 'main.py')],
                             cwd=ROOT)
        try:
            open_bionic(load_config()['bionic']['bridge_port'], show=False)
        except Exception:
            logging.exception('Bionic did not open; Alex pet remains available')
    except Exception as exc:
        logging.exception('Launcher failed')
        ctypes.windll.user32.MessageBoxW(None, str(exc), 'Alex - Bionic', 0x10)
