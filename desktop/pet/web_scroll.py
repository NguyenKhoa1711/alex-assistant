"""Continuous slow web auto-scrolling controlled by voice commands."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import os
from pathlib import Path
import re
import sys
import threading
import time
from typing import Literal

from .app_actions import ActionResult, folded
from .apps import app_windows

ScrollCommand = Literal['start_down', 'start_up', 'stop']

BROWSER_PROCESSES = (
    'chrome.exe',
    'msedge.exe',
    'firefox.exe',
    'brave.exe',
    'opera.exe',
    'vivaldi.exe',
    'browser.exe',
)

_SHELL_CLASSES = {'Progman', 'WorkerW', 'Shell_TrayWnd', 'Shell_SecondaryTrayWnd', '#32770'}
_MOUSEEVENTF_WHEEL = 0x0800
_SW_RESTORE = 9


class _Point(ctypes.Structure):
    _fields_ = [('x', wintypes.LONG), ('y', wintypes.LONG)]


class _Rect(ctypes.Structure):
    _fields_ = [
        ('left', wintypes.LONG),
        ('top', wintypes.LONG),
        ('right', wintypes.LONG),
        ('bottom', wintypes.LONG),
    ]


def _clean_key(text: str) -> str:
    key = ' '.join(re.sub(r'[^a-z0-9 ]+', ' ', folded(text)).split())
    prefixes = (
        'alex oi ', 'alex ', 'a lech oi ', 'a lech ', 'ban oi ',
        'vang ', 'da ', 'u ', 'uh ', 'a ', 'o ', 'oi ', 'nay ', 'e ', 'oke ', 'ok ', 'duoc roi ',
        'ban ', 'hay ', 'vui long ', 'lam on ', 'giup toi ', 'giup minh ',
        'cho toi ', 'cho minh ', 'toi muon ', 'minh muon ',
    )
    suffixes = (
        ' tren may tinh', ' tren me tinh', ' tren laptop', ' tren pc',
        ' tren trinh duyet', ' trong trinh duyet',
        ' cho toi', ' cho minh', ' giup toi', ' giup minh',
        ' di', ' nhe', ' nha', ' ngay', ' luon', ' voi',
    )
    for _ in range(5):
        prefix = next((p for p in prefixes if key.startswith(p)), None)
        if prefix is None:
            break
        key = key[len(prefix):].strip()
    for _ in range(5):
        suffix = next((s for s in suffixes if key.endswith(s)), None)
        if suffix is None:
            break
        key = key[:-len(suffix)].strip()
    return key


def parse_web_scroll_request(text: str, *, active: bool = False) -> ScrollCommand | None:
    """Parse voice commands to start or stop slow web auto-scrolling."""
    raw_folded = folded(text)
    if not raw_folded:
        return None
    # Reject compound commands chaining unrelated actions.
    if re.search(r'\b(?:va|roi|sau do|xong)\s+(?:mo|dong|tat|ngung|dung|phat|tim|thu nho|phong to|tang|giam)\b', raw_folded):
        return None
    key = _clean_key(text)
    if not key:
        return None

    web_word = r'(?:web|quep|quet|ghep|guep|wep|trang web|trang|trinh duyet)'
    scroll_verb = r'(?:luot|luoc|nuot|luat|luc|look|loop|loot|load|log)'
    scroll_target = r'(?:' + web_word + r'|tiktok|tik tok|facebook|fb|youtube|you tube|du tup|video|bai|tin|tiep)'
    slow_tail = r'(?: (?:tu tu|cham|cham cham|hoi cham|nhe|nhe nhang|lien tuc|tiep|nhanh|binh thuong))?'

    # Explicit stop scrolling commands (always recognized even when active=False).
    stop_explicit = re.fullmatch(
        r'(?:'
        r'(?:thoi )?(?:dung|tam dung|ngung|thoi|tat|huy|khong) '
        r'(?:tu(?: dong)? )?(?:' + scroll_verb + r'|cuon|keo)'
        r'(?: ' + scroll_target + r'| xuong| len)?'
        r'(?: (?:nua|lai|di|ngay|luon|nhe|nha|voi))*'
        r'|(?:thoi )?(?:khong|dung|thoi khong) (?:tu(?: dong)? )?(?:' + scroll_verb + r'|cuon|keo)'
        r'(?: ' + scroll_target + r'| xuong| len)?'
        r'(?: (?:nua|lai|di|ngay|luon|nhe|nha|voi))*'
        r')',
        key,
    )
    if stop_explicit:
        return 'stop'

    short_stop = re.fullmatch(
        r'(?:dung|dung lai|tam dung|ngung|ngung lai|thoi|dung di|ngung di|thoi di|'
        r'dung luot|ngung luot|tat luot|stop)(?: (?:nua|lai|di|ngay|luon|nhe|nha|voi))*',
        key,
    )
    stop_with_scroll_context = (
        re.search(r'\b(?:dung|tam dung|ngung|thoi|tat|huy|stop)\b', key)
        and re.search(r'\b(?:' + scroll_verb + r'|cuon|keo|' + scroll_target + r')\b', key)
    )
    if active and (short_stop or stop_with_scroll_context):
        return 'stop'

    # Guard against negations ("đừng lướt web", "không lướt web").
    if re.search(r'\b(?:dung|khong|khoan)\b', key):
        return None

    start_down = re.fullmatch(
        r'(?:bat dau |tiep tuc )?(?:tu(?: dong)? )?'
        r'(?:'
        + scroll_verb + r' ' + scroll_target + r'(?: xuong)?'
        r'|(?:luot|luoc|nuot) (?:xuong|tiep)'
        r'|(?:cuon|keo) (?:trang |' + scroll_target + r' )?(?:xuong|tiep)'
        r')' + slow_tail,
        key,
    )
    if start_down:
        return 'start_down'

    start_up = re.fullmatch(
        r'(?:bat dau |tiep tuc )?(?:tu(?: dong)? )?'
        r'(?:'
        + scroll_verb + r' ' + web_word + r' len'
        r'|(?:' + scroll_verb + r'|cuon|keo) (?:trang |' + web_word + r' )?len'
        r')' + slow_tail,
        key,
    )
    if start_up:
        return 'start_up'

    return None


class WebScroller:
    """Background worker that gently scrolls the active browser/web window."""

    def __init__(self, step_wheel: int = 16, interval_seconds: float = 0.26) -> None:
        self.step_wheel = step_wheel
        self.interval_seconds = interval_seconds
        self._lock = threading.Lock()
        self._generation = 0
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._target_hwnd: int = 0
        self._direction: Literal['down', 'up'] = 'down'

    def is_active(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive() and not self._stop_event.is_set()

    def _find_scroll_target(self) -> int:
        if sys.platform != 'win32':
            return 1
        from .window_actions import Windows
        api = Windows()
        fg = api.foreground()
        fg_id = api.identity(fg) if fg else None
        my_pid = os.getpid()

        def is_browser_identity(identity: tuple | None) -> bool:
            if not identity:
                return False
            _hwnd, pid, exe_path, cls = identity
            if pid == my_pid or cls in _SHELL_CLASSES:
                return False
            exe_name = Path(exe_path).name.casefold()
            if exe_name == 'browser.exe' and 'coccoc' not in exe_path.casefold():
                return False
            return exe_name in BROWSER_PROCESSES

        if is_browser_identity(fg_id) and api.visible(fg):
            return fg

        for hwnd in app_windows({'processes': list(BROWSER_PROCESSES)}):
            identity = api.identity(hwnd)
            if is_browser_identity(identity) and api.visible(hwnd) and api.enabled(hwnd):
                return int(hwnd)

        # Fallback to current foreground window if it is a normal user window (not Pet/Bionic/shell).
        if fg_id and fg_id[1] != my_pid and fg_id[3] not in _SHELL_CLASSES:
            exe_name = Path(fg_id[2]).name.casefold()
            if 'bionic' not in exe_name and api.visible(fg):
                return fg
        return 0

    def _focus_and_position_cursor(self, hwnd: int, *, initial: bool = False) -> None:
        if sys.platform != 'win32' or not hwnd:
            return
        user = ctypes.WinDLL('user32', use_last_error=True)
        user.IsIconic.argtypes = [wintypes.HWND]
        user.IsIconic.restype = wintypes.BOOL
        user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user.ShowWindow.restype = wintypes.BOOL
        user.SetForegroundWindow.argtypes = [wintypes.HWND]
        user.SetForegroundWindow.restype = wintypes.BOOL
        user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(_Rect)]
        user.GetWindowRect.restype = wintypes.BOOL
        user.GetCursorPos.argtypes = [ctypes.POINTER(_Point)]
        user.GetCursorPos.restype = wintypes.BOOL
        user.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        user.SetCursorPos.restype = wintypes.BOOL
        user.WindowFromPoint.argtypes = [_Point]
        user.WindowFromPoint.restype = wintypes.HWND
        user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

        if initial:
            if user.IsIconic(hwnd):
                user.ShowWindow(hwnd, _SW_RESTORE)
            user.SetForegroundWindow(hwnd)

        rect = _Rect()
        if not user.GetWindowRect(hwnd, ctypes.byref(rect)):
            return
        pt = _Point()
        if not user.GetCursorPos(ctypes.byref(pt)):
            return
        under_hwnd = user.WindowFromPoint(pt)
        under_pid = wintypes.DWORD()
        if under_hwnd:
            user.GetWindowThreadProcessId(under_hwnd, ctypes.byref(under_pid))
        inside = (rect.left + 40 <= pt.x <= rect.right - 40
                  and rect.top + 120 <= pt.y <= rect.bottom - 40)
        if under_pid.value == os.getpid() or (initial and not inside):
            cx = (rect.left + rect.right) // 2
            cy = rect.top + int((rect.bottom - rect.top) * 0.55)
            user.SetCursorPos(cx, cy)

    def _send_wheel_tick(self, hwnd: int, direction: Literal['down', 'up']) -> bool:
        if sys.platform != 'win32':
            return True
        user = ctypes.WinDLL('user32', use_last_error=True)
        user.IsWindow.argtypes = [wintypes.HWND]
        user.IsWindow.restype = wintypes.BOOL
        user.IsWindowVisible.argtypes = [wintypes.HWND]
        user.IsWindowVisible.restype = wintypes.BOOL
        if hwnd and (not user.IsWindow(hwnd) or not user.IsWindowVisible(hwnd)):
            return False
        self._focus_and_position_cursor(hwnd, initial=False)
        delta = -self.step_wheel if direction == 'down' else self.step_wheel
        user.mouse_event.argtypes = (
            wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
            wintypes.DWORD, ctypes.c_size_t,
        )
        user.mouse_event(_MOUSEEVENTF_WHEEL, 0, 0, wintypes.DWORD(delta & 0xFFFFFFFF), 0)
        return True

    def _loop(self, hwnd: int, direction: Literal['down', 'up'], stop_event: threading.Event) -> None:
        logging.info('WEB_SCROLL started: hwnd=%s direction=%s', hwnd, direction)
        try:
            while not stop_event.is_set():
                if not self._send_wheel_tick(hwnd, direction):
                    logging.info('WEB_SCROLL target window closed or hidden; stopping')
                    break
                if stop_event.wait(self.interval_seconds):
                    break
        except Exception:
            logging.exception('WEB_SCROLL loop error')
        finally:
            stop_event.set()
            logging.info('WEB_SCROLL stopped')

    def start(self, direction: Literal['down', 'up'] = 'down') -> ActionResult:
        started = time.monotonic()
        with self._lock:
            if (self._thread is not None and self._thread.is_alive()
                    and not self._stop_event.is_set() and self._direction == direction):
                return ActionResult('Chế độ này vẫn đang chạy.', verified=True,
                                    seconds=time.monotonic() - started)
            generation = self._generation
        target = self._find_scroll_target()
        with self._lock:
            if generation != self._generation:
                return ActionResult('Đã dừng.', verified=True, seconds=time.monotonic() - started)
            if not target:
                return ActionResult(
                    'Mình chưa thấy trình duyệt nào đang mở để lướt web. Bạn mở trang web trước nhé.',
                    verified=False, seconds=time.monotonic() - started)
            previous_thread = self._thread
            self._stop_event.set()
            self._generation += 1
            stop_event = threading.Event()
            self._stop_event = stop_event
            self._target_hwnd = target
            self._direction = direction
            self._focus_and_position_cursor(target, initial=True)
            self._thread = threading.Thread(
                target=self._loop, args=(target, direction, stop_event),
                name='Alex-web-scroller', daemon=True)
            self._thread.start()
        if previous_thread is not None and previous_thread is not threading.current_thread():
            previous_thread.join(timeout=0.5)
        return ActionResult('Đã bật chế độ tự động.', verified=True,
                            seconds=time.monotonic() - started)

    def stop(self) -> ActionResult:
        started = time.monotonic()
        with self._lock:
            self._generation += 1
            was_active = self._thread is not None and self._thread.is_alive() and not self._stop_event.is_set()
            self._stop_event.set()
            thread = self._thread
            self._thread = None
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=0.5)
        if was_active:
            return ActionResult('Đã dừng.', verified=True, seconds=time.monotonic() - started)
        return ActionResult('Đã dừng rồi.', verified=True, seconds=time.monotonic() - started)
