"""A normal, one-shot window Close request, with unsaved-data prompts preserved."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import os
import threading
import time
from .app_actions import ActionResult, folded
from .apps import (requested_app, requested_system_app, requested_shortcut,
                   requested_app_path, requested_web, app_windows, _safe_shortcut_target)


class Windows:
    def __init__(self):
        self.user=ctypes.WinDLL('user32',use_last_error=True)
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        self.user.GetForegroundWindow.restype=wintypes.HWND
        self.user.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
        self.user.GetClassNameW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
        self.user.PostMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
        self.user.PostMessageW.restype=wintypes.BOOL
        for name in ('IsWindow','IsWindowVisible','IsWindowEnabled'):
            getattr(self.user,name).argtypes=[wintypes.HWND]
            getattr(self.user,name).restype=wintypes.BOOL
        self.kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        self.kernel.OpenProcess.restype=wintypes.HANDLE
        self.kernel.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
        self.kernel.CloseHandle.argtypes=[wintypes.HANDLE]

    def foreground(self): return int(self.user.GetForegroundWindow() or 0)

    def identity(self, hwnd):
        if not self.user.IsWindow(hwnd): return None
        pid=wintypes.DWORD(); self.user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        cls=ctypes.create_unicode_buffer(256); self.user.GetClassNameW(hwnd,cls,len(cls))
        handle=self.kernel.OpenProcess(0x1000,False,pid.value)
        if not handle: return None
        try:
            size=wintypes.DWORD(32768); path=ctypes.create_unicode_buffer(size.value)
            if not self.kernel.QueryFullProcessImageNameW(handle,0,path,ctypes.byref(size)): return None
            return (int(hwnd),pid.value,path.value.casefold(),cls.value)
        finally: self.kernel.CloseHandle(handle)

    def visible(self, hwnd): return bool(self.user.IsWindow(hwnd) and self.user.IsWindowVisible(hwnd))
    def enabled(self, hwnd): return bool(self.user.IsWindowEnabled(hwnd))
    def post_close(self, hwnd): return bool(self.user.PostMessageW(hwnd,0x0010,0,0))

    def topmost_user_window(self) -> int:
        my_pid = os.getpid()
        found: list[int] = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        @callback_type
        def visit(hwnd: int, _: int) -> bool:
            if not self.visible(hwnd) or not self.enabled(hwnd):
                return True
            title = ctypes.create_unicode_buffer(512)
            self.user.GetWindowTextW(hwnd, title, len(title))
            if not title.value.strip():
                return True
            ident = self.identity(hwnd)
            if not ident:
                return True
            _, pid, exe_path, cls = ident
            if pid == my_pid or cls in {
                'Progman', 'WorkerW', 'Shell_TrayWnd', 'Shell_SecondaryTrayWnd',
                '#32770', 'IME', 'MSCTFIME UI', 'tooltips_class32',
                'Windows.UI.Core.CoreWindow',
            }:
                return True
            exe_name = exe_path.rsplit('\\', 1)[-1]
            if exe_name in {'bionic.exe', 'applicationframehost.exe', 'searchhost.exe', 'startmenuexperiencehost.exe', 'shellexperiencehost.exe', 'textinputhost.exe'}:
                return True
            found.append(int(hwnd))
            return False

        self.user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
        self.user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user.EnumWindows(visit, 0)
        return found[0] if found else 0


_BROWSER_PROCESSES = ['chrome.exe', 'msedge.exe', 'firefox.exe', 'brave.exe', 'opera.exe', 'vivaldi.exe', 'browser.exe']


def resolve_close_entry(name, cfg):
    key = folded(name).strip(' .!?')
    if key in {'trinh duyet', 'trang web', 'website', 'web', 'cua so web', 'trang'}:
        return {'name': 'trình duyệt', 'processes': list(_BROWSER_PROCESSES)}
    command='Mở '+name
    entry=(requested_app(command,cfg.get('apps',{}).get('entries',[])) or
           requested_system_app(command) or requested_shortcut(command) or requested_app_path(command))
    if not entry:
        web_hit = requested_web(command, cfg.get('web', {}).get('sites', []))
        if web_hit:
            return {'name': web_hit[1], 'processes': list(_BROWSER_PROCESSES)}
        return None
    entry=dict(entry)
    # Minecraft is launched through TLauncher, but closing them is not equivalent.
    if entry['name']=='TLauncher' and folded(name) not in {'tlauncher','tlaucher','t launcher'}:
        return None
    if entry.get('shortcut_path') and not entry.get('processes'):
        from pathlib import Path
        target=_safe_shortcut_target(Path(entry['shortcut_path']))
        if not target: return None
        entry['processes']=[target[0]]
        if target[1]: entry.update(browser_app=True,title_contains=entry['name'])
    return entry


def close_app_window(name: str, cfg: dict, cancelled: threading.Event,
                     windows=None) -> ActionResult:
    started=time.monotonic()
    api=windows or Windows()
    def result(message, verified=False):
        return ActionResult(message,verified,time.monotonic()-started)
    if cancelled.is_set(): return result('Đã dừng theo yêu cầu của bạn.')
    foreground=api.foreground()
    used_fallback_window=False
    label='ứng dụng'
    if name:
        entry=resolve_close_entry(name,cfg)
        if entry is None:
            return result('Chưa xác định được phần mềm cần đóng. Bạn đưa nó lên trước rồi nói “Đóng ứng dụng này” nhé.')
        label=entry['name']
        handles=app_windows(entry)
        if foreground in handles: hwnd=foreground
        elif len(handles)==1 or label=='trình duyệt': hwnd=handles[0]
        elif not handles: return result(f'Mình chưa thấy cửa sổ {label} đang mở.')
        else: return result(f'Có nhiều cửa sổ {label} đang mở. Bạn chọn cửa sổ cần đóng trước nhé.')
    else:
        hwnd=foreground
        ident_fg=api.identity(hwnd)
        if (not ident_fg or ident_fg[1]==os.getpid() or ident_fg[3] in {
                'Progman','WorkerW','Shell_TrayWnd','Shell_SecondaryTrayWnd','#32770'}) and hasattr(api, 'topmost_user_window'):
            fallback=api.topmost_user_window()
            if fallback:
                hwnd=fallback
                used_fallback_window=True
    identity=api.identity(hwnd)
    if not identity or identity[1]==os.getpid() or identity[3] in {
            'Progman','WorkerW','Shell_TrayWnd','Shell_SecondaryTrayWnd','#32770'}:
        return result('Bạn đưa cửa sổ phần mềm cần đóng lên trước rồi nói lại nhé.')
    if not api.visible(hwnd) or not api.enabled(hwnd):
        return result('Cửa sổ chưa sẵn sàng hoặc đang có hộp thoại. Bạn xử lý trên màn hình trước nhé.')
    if cancelled.is_set(): return result('Đã dừng theo yêu cầu của bạn.')
    if api.identity(hwnd)!=identity or (not name and not used_fallback_window and api.foreground()!=foreground):
        return result('Cửa sổ đã thay đổi; mình chưa đóng gì.')
    if not api.post_close(hwnd):
        return result('Windows chưa cho đóng cửa sổ này; mình chưa đóng được.')
    # WM_CLOSE respects the app's save/discard prompt; never use TerminateProcess.
    for _ in range(20):
        if not api.visible(hwnd) or api.identity(hwnd)!=identity:
            return result(f'Mình đã đóng cửa sổ {label}.',True)
        if cancelled.wait(.1): break
    return result('Chưa xác nhận cửa sổ đã đóng. Nếu ứng dụng hỏi lưu dữ liệu, bạn chọn trên màn hình nhé.')
