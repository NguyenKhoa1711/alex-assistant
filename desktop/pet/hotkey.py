from __future__ import annotations
import ctypes
from ctypes import wintypes
from collections.abc import Callable
from PySide6.QtCore import QAbstractNativeEventFilter, QTimer
from PySide6.QtWidgets import QApplication


class GlobalHotkey(QAbstractNativeEventFilter):
    """Register Windows hotkeys; no keyboard recording or polling."""
    ID = 0xA1E

    def __init__(self, callback: Callable[[], None]) -> None:
        super().__init__()
        self._callbacks: dict[int, Callable[[], None]] = {}
        self.callback = callback
        self.registered = self.register_extra(self.ID, 0x0002 | 0x4000, 0x20, callback)
        if self.registered:
            QApplication.instance().installNativeEventFilter(self)

    def register_extra(self, hotkey_id: int, modifiers: int, vk: int, callback: Callable[[], None]) -> bool:
        ok = bool(ctypes.windll.user32.RegisterHotKey(None, hotkey_id, modifiers, vk))
        if ok:
            self._callbacks[hotkey_id] = callback
            if not getattr(self, '_filter_installed', False):
                QApplication.instance().installNativeEventFilter(self)
                self._filter_installed = True
        return ok

    def nativeEventFilter(self, event_type: bytes, message: int) -> tuple[bool, int]:
        msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
        if msg.message == 0x0312 and msg.wParam in self._callbacks:
            cb = self._callbacks[msg.wParam]
            QTimer.singleShot(0, cb)
            return True, 0
        return False, 0

    def close(self) -> None:
        if self._callbacks:
            for hk_id in list(self._callbacks):
                ctypes.windll.user32.UnregisterHotKey(None, hk_id)
            self._callbacks.clear()
            QApplication.instance().removeNativeEventFilter(self)
            self.registered = False
