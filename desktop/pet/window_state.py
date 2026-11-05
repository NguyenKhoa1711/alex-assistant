"""Explicit current-window sizing; never send global keyboard shortcuts."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import re
import threading
import time
from .app_actions import Action, ActionResult, folded
from .window_actions import Windows

OPERATIONS = frozenset({'maximize', 'minimize', 'restore'})


def parse_window_state(question: str) -> Action | None:
    if not isinstance(question, str) or len(question) > 300 or '\n' in question:
        return None
    text = folded(question).strip(' .!?')
    text = re.sub(r'^(alex oi|alex|ban oi)[,!:]+\s*', r'\1 ', text)
    prefix = r'(?:(?:alex oi|alex|ban oi|ban|hay|lam on|vui long|ban co the|ban giup toi|ban giup minh|nho ban|toi muon|minh muon|giup toi|giup minh) ){0,3}'
    target = r'(?:cai )?(?:cua so|ung dung|phan mem|app|trang web|trinh duyet)(?: (?:hien tai|nay|dang dung|dang mo|dang su dung|dang xem))?'
    suffix = r'(?: (?:giup|cho) (?:toi|minh))?(?: (?:di|nhe|nha|voi|len|xuong|lai)){0,2}(?: (?:duoc khong|duoc ko))?'
    patterns = (
        # User-confirmed mic correction (2026-10-23), scoped to the whole
        # window command, never a global replacement in conversational text.
        ('maximize', r'phong tac cua su hien dai'),
        ('restore', r'(?:khoi phuc|phuc hoi) ' + target),
        ('restore', r'(?:dua|tra|thu nho) ' + target + r' (?:ve|lai) kich thuoc (?:binh thuong|ban dau)'),
        ('maximize', r'(?:phong to|mo rong|toi da hoa) ' + target),
        ('minimize', r'(?:thu nho|an xuong|toi thieu hoa) ' + target + r'(?: xuong (?:thanh tac vu|taskbar))?'),
        ('maximize', r'phong to'),
        ('minimize', r'thu nho'),
    )
    for operation, pattern in patterns:
        if re.fullmatch(prefix + pattern + suffix, text):
            browser = bool(re.search(r'\b(?:trang web|trinh duyet)\b', text))
            return Action('Window', operation, 'browser' if browser else '')
    return None


class WindowStateAPI(Windows):
    def __init__(self):
        super().__init__()
        for name in ('IsIconic', 'IsZoomed'):
            getattr(self.user, name).argtypes = [wintypes.HWND]
            getattr(self.user, name).restype = wintypes.BOOL
        self.user.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user.ShowWindowAsync.restype = wintypes.BOOL
        self.user.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user.GetWindowLongW.restype = wintypes.LONG

    def state(self, hwnd):
        if self.user.IsIconic(hwnd):
            return 'minimize'
        return 'maximize' if self.user.IsZoomed(hwnd) else 'restore'

    def supports(self, hwnd, operation):
        style = self.user.GetWindowLongW(hwnd, -16)
        return operation == 'restore' or bool(style & (0x10000 if operation == 'maximize' else 0x20000))

    def show(self, hwnd, operation):
        return bool(self.user.ShowWindowAsync(hwnd, {'maximize': 3, 'minimize': 6, 'restore': 9}[operation]))


def change_window_state(operation: str, cancelled: threading.Event, windows=None,
                        *, browser_only=False) -> ActionResult:
    started = time.monotonic()
    def result(message, verified=False):
        return ActionResult(message, verified, time.monotonic() - started)
    if operation not in OPERATIONS:
        return result('Chưa rõ cách điều chỉnh cửa sổ.')
    if cancelled.is_set():
        return result('Đã dừng theo yêu cầu của bạn.')
    api = windows or WindowStateAPI()
    hwnd = api.foreground()
    identity = api.identity(hwnd)
    if not identity or identity[1] == os.getpid() or identity[3] in {
            'Progman', 'WorkerW', 'Shell_TrayWnd', 'Shell_SecondaryTrayWnd', '#32770'}:
        return result('Bạn chọn cửa sổ ứng dụng cần chỉnh rồi nói lại nhé.')
    if browser_only:
        executable = Path(identity[2]).name.casefold()
        is_browser = executable in {'chrome.exe', 'msedge.exe', 'firefox.exe',
                                    'brave.exe', 'opera.exe', 'vivaldi.exe'}
        is_browser |= executable == 'browser.exe' and 'coccoc' in identity[2].casefold()
        if not is_browser:
            return result('Bạn chọn cửa sổ trình duyệt đang xem rồi nói lại nhé. Mình chưa chỉnh cửa sổ khác.')
    if not api.visible(hwnd) or not api.enabled(hwnd):
        return result('Cửa sổ đang có hộp thoại hoặc chưa sẵn sàng. Bạn xử lý trên màn hình trước nhé.')
    if not api.supports(hwnd, operation):
        return result('Cửa sổ này không hỗ trợ thao tác đó.')
    if cancelled.is_set():
        return result('Đã dừng theo yêu cầu của bạn.')
    if api.identity(hwnd) != identity or api.foreground() != hwnd:
        return result('Cửa sổ đã thay đổi; mình chưa chỉnh gì.')
    descriptions = {'maximize': 'phóng to cửa sổ', 'minimize': 'thu nhỏ cửa sổ xuống thanh tác vụ',
                    'restore': 'đưa cửa sổ về kích thước bình thường'}
    if api.state(hwnd) == operation:
        return result('Cửa sổ đã ở trạng thái bạn yêu cầu rồi.', True)
    if not api.show(hwnd, operation):
        return result('Windows chưa cho điều chỉnh cửa sổ này.')
    # Minimize changes focus. Check the original identity, not the next window.
    for _ in range(20):
        if api.identity(hwnd) != identity or not api.visible(hwnd):
            return result('Cửa sổ đã thay đổi; mình chưa xác nhận được kết quả.')
        if api.state(hwnd) == operation:
            return result('Mình đã ' + descriptions[operation] + '.', True)
        if cancelled.wait(.05):
            return result('Đã gửi lệnh rồi dừng chờ; bạn kiểm tra cửa sổ nhé.')
    return result('Đã gửi lệnh nhưng chưa xác nhận cửa sổ đổi trạng thái. Bạn kiểm tra trên màn hình nhé.')
