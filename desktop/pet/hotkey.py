from __future__ import annotations
import ctypes
from ctypes import wintypes
from collections.abc import Callable
from PySide6.QtCore import QAbstractNativeEventFilter, QTimer
from PySide6.QtWidgets import QApplication


class GlobalHotkey(QAbstractNativeEventFilter):
    """Register one Windows hotkey; no keyboard recording or polling."""
    ID = 0xA1E

    def __init__(self, callback: Callable[[], None]) -> None:
        super().__init__()
        self.callback = callback
        self.registered = bool(ctypes.windll.user32.RegisterHotKey(None, self.ID, 0x0002 | 0x4000, 0x20))
        if self.registered:
            QApplication.instance().installNativeEventFilter(self)

    def nativeEventFilter(self, event_type: bytes, message: int) -> tuple[bool, int]:
        msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
        if msg.message == 0x0312 and msg.wParam == self.ID:
            QTimer.singleShot(0, self.callback)
            return True, 0
        return False, 0

    def close(self) -> None:
        if self.registered:
            ctypes.windll.user32.UnregisterHotKey(None, self.ID)
            QApplication.instance().removeNativeEventFilter(self)
            self.registered = False
