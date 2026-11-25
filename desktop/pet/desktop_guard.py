"""Bound a generic desktop tool sequence to one user-approved plan."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import json
from pathlib import Path
import re
import time
from typing import Callable
from .app_actions import folded
from .apps import focus_window
from .computer import confirmation_reason
from .permissions import ask_pet


@dataclass(frozen=True)
class Window:
    hwnd: int
    pid: int
    executable: str
    title: str


def current_window() -> Window:
    user = ctypes.WinDLL('user32'); kernel = ctypes.WinDLL('kernel32')
    user.GetForegroundWindow.restype = wintypes.HWND
    hwnd = user.GetForegroundWindow()
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    pid = wintypes.DWORD(); user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    title = ctypes.create_unicode_buffer(1024); user.GetWindowTextW(hwnd, title, len(title))
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    def executable(process_id: int) -> str:
        handle = kernel.OpenProcess(0x1000, False, process_id)
        if not handle:
            return ''
        try:
            path = ctypes.create_unicode_buffer(32768)
            length = wintypes.DWORD(len(path))
            return path.value if kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(length)) else ''
        finally:
            kernel.CloseHandle(handle)

    path = executable(pid.value)
    if Path(path).stem.lower() == 'applicationframehost':
        # Store apps put their UI in a CoreWindow child of ApplicationFrameHost.
        found: list[tuple[int, str]] = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

        @callback_type
        def child(window: int, _: int) -> bool:
            name = ctypes.create_unicode_buffer(128)
            user.GetClassNameW(window, name, len(name))
            if name.value == 'Windows.UI.Core.CoreWindow':
                child_pid = wintypes.DWORD()
                user.GetWindowThreadProcessId(window, ctypes.byref(child_pid))
                child_path = executable(child_pid.value)
                if child_path:
                    found.append((child_pid.value, child_path))
            return True

        user.EnumChildWindows.argtypes = [wintypes.HWND, callback_type, wintypes.LPARAM]
        user.EnumChildWindows(hwnd, child, 0)
        if len(found) == 1:
            return Window(int(hwnd or 0), found[0][0], found[0][1], title.value)
    return Window(int(hwnd or 0), pid.value, path, title.value)


def app_matches(app: str, window: Window) -> bool:
    requested = folded(app).removesuffix('.exe')
    executable = folded(Path(window.executable).stem)
    if requested == 'tlauncher' and executable == 'javaw' and 'tlauncher' in folded(window.title):
        return True
    aliases = {'file explorer': 'explorer', 'windows explorer': 'explorer',
               'calculator': 'calculatorapp', 'visual studio code': 'code',
               'paint': 'mspaint',
               'google chrome': 'chrome', 'microsoft edge': 'msedge', 'microsoft word': 'winword',
               'word': 'winword', 'microsoft excel': 'excel', 'microsoft powerpoint': 'powerpnt',
               'powerpoint': 'powerpnt'}
    expected = aliases.get(requested, requested)
    return bool(executable) and (expected == executable or
        re.sub(r'[^a-z0-9]', '', expected) == re.sub(r'[^a-z0-9]', '', executable))


class DesktopGuard:
    def __init__(self, approve: Callable[..., dict] = ask_pet,
                 foreground: Callable[[], Window] = current_window,
                 restore: Callable[[int], bool] = focus_window) -> None:
        self.approve, self.foreground, self.restore = approve, foreground, restore
        self.grant = ''
        self.apps: list[str] = []
        self.paths: list[Path] = []
        self.steps = 0
        self.limit = 40
        self.snapshot = ''
        self.snapshot_window: Window | None = None
        self.snapshot_at = 0.0
        self.last_observation = ''
        self.needs_verification = False
        self.failed = False
        self.bound_processes: set[tuple[int, str]] = set()
        self.agent_observations: dict[tuple[int, int], tuple[Window, str]] = {}

    def plan(self, goal: str, steps: list[str], apps: list[str], paths: list[str]) -> dict:
        self.finish()
        if not goal.strip() or not 1 <= len(steps) <= 12 or not (apps or paths) or len(apps) > 10:
            raise ValueError('Kế hoạch cần mục tiêu, 1–12 bước và tên ứng dụng hoặc đường dẫn cụ thể.')
        if any(not isinstance(x, str) or not x.strip() or len(x) > 600 or
               '\n' in x or '\r' in x for x in [goal, *steps, *apps, *paths]):
            raise ValueError('Kế hoạch phải ngắn, rõ và không có mục trống.')
        resolved: list[Path] = []
        for value in paths:
            path = Path(value).expanduser()
            if not path.is_absolute() or str(path).startswith('\\\\') or path.resolve() == Path(path.anchor):
                raise ValueError('Cấp phép đường dẫn cụ thể trên máy; không cấp cả gốc ổ đĩa hoặc ổ mạng.')
            resolved.append(path.resolve())
        description = ('KẾ HOẠCH THAO TÁC\n\n' + goal + '\n\n' +
            '\n'.join(f'{i + 1}. {step}' for i, step in enumerate(steps)) +
            '\n\nỨng dụng: ' + ', '.join(apps) + '\nĐường dẫn: ' + ', '.join(str(p) for p in resolved) +
            '\n\nAlex sẽ hỏi riêng trước khi gửi, xóa, mua, ghi đè hoặc chạy lệnh. Ctrl+Space/Ngắt sẽ thu hồi kế hoạch.')
        reply = self.approve('approve_plan', description=description)
        if not reply.get('allowed'):
            return {'approved': False, 'error': reply.get('error', 'Bạn đã hủy kế hoạch; dừng thao tác.')}
        self.grant = reply['grant']; self.apps = apps; self.paths = resolved
        self.steps = 0; self.failed = False; self.needs_verification = False
        return {'approved': True, 'max_steps': self.limit, 'apps': apps,
                'instruction': 'App để mở/chuyển ứng dụng; Snapshot rồi thao tác bằng loc=[x,y] lấy từ cây giao diện mới nhất. Snapshot sau thay đổi. Finish với bằng chứng đọc được.'}

    def finish(self) -> None:
        if self.grant:
            self.approve('finish', self.grant)
        self.grant = ''; self.snapshot = ''; self.snapshot_window = None
        self.bound_processes.clear(); self.last_observation = ''
        self.agent_observations.clear()

    def register_agent_observation(self, window: Window, identity: str, point: tuple[int, int]) -> None:
        """Bind a deep agent-desktop InputObservation identity to a verified Window and point."""
        if not identity or not isinstance(point, tuple) or len(point) != 2:
            raise ValueError('Quan sát agent-desktop không hợp lệ.')
        self.agent_observations[point] = (window, identity)

    def verify_agent_observation(self, window: Window, point: tuple[int, int],
                                 fresh_snapshot: dict, *, include_standard_roles: bool = False):
        """Re-verify a registered agent-desktop control against a fresh snapshot."""
        from .agent_input_observation import InputObservation, rematch
        bound = self.agent_observations.get(point)
        if not bound or bound[0] != window or self.foreground() != window:
            return None
        probe = InputObservation(bound[1], point, '@s0:e0')
        return rematch(probe, fresh_snapshot, include_standard_roles=include_standard_roles)

    def _check(self) -> None:
        if not self.grant or not self.approve('check', self.grant).get('allowed'):
            self.grant = ''
            raise ValueError('Chưa có kế hoạch được duyệt hoặc quyền đã thu hồi. Dừng và xin Plan mới.')
        if self.steps >= self.limit:
            self.finish()
            raise ValueError('Đã hết số bước được cấp; dừng và báo phần đã làm.')

    def _window_allowed(self, window: Window) -> bool:
        return (window.pid, window.executable) in self.bound_processes or any(app_matches(a, window) for a in self.apps)

    def _path_allowed(self, value: str) -> None:
        path = Path(value).expanduser().resolve()
        if not Path(value).is_absolute() or str(value).startswith('\\\\'):
            raise ValueError('Cần đường dẫn tuyệt đối trên máy.')
        if path.name == 'desktop-permissions.json':
            raise ValueError('Không đọc hoặc thay đổi kênh cấp phép của pet.')
        if not any(path == root or (root.is_dir() and root in path.parents) for root in self.paths):
            raise ValueError('Đường dẫn ngoài kế hoạch; cần duyệt kế hoạch có đúng đường dẫn trước.')

    def before(self, name: str, args: dict) -> tuple[dict, Window]:
        args = dict(args)
        for key in ('clear', 'press_enter', 'overwrite', 'recursive', 'append'):
            if isinstance(args.get(key), str):
                if args[key].lower() not in ('true', 'false'):
                    raise ValueError('Tham số bật/tắt phải là true hoặc false.')
                args[key] = args[key].lower() == 'true'
        if name == 'Snapshot':
            # Read-only observation can inform the plan. Never mutate from it without approval.
            return {**args, 'use_ui_tree': True}, self.foreground()
        self._check()
        current = self.foreground()
        reason = None
        if name == 'App':
            mode = args.get('mode', 'launch')
            if mode == 'launch_executable':
                executable = str(args.get('executable') or '')
                if (not Path(executable).is_absolute() or
                    not any(app_matches(a, Window(0, 0, executable, '')) for a in self.apps)):
                    raise ValueError('Chương trình chạy chưa thuộc ứng dụng đã duyệt trong kế hoạch.')
                reason = 'Chạy chương trình cụ thể:\n' + json.dumps(args, ensure_ascii=False, indent=2)
            else:
                target = folded(str(args.get('name', '')))
                if not target or target not in {folded(a) for a in self.apps}:
                    raise ValueError('Tên ứng dụng chưa nằm trong kế hoạch. Gọi Plan với đúng tên ứng dụng.')
        elif name == 'FileSystem':
            self._path_allowed(args['path'])
            if args.get('destination'):
                self._path_allowed(args['destination'])
            reason = confirmation_reason(name, args)
        elif name == 'PowerShell':
            reason = 'CHẠY LỆNH POWERSHELL\n\n' + str(args.get('command', '')) + '\n\nChỉ chấp nhận nếu đúng việc bạn yêu cầu.'
        elif name in ('Click', 'Type', 'Scroll', 'Shortcut', 'Move'):
            if not self._window_allowed(current):
                raise ValueError('Cửa sổ hiện tại không thuộc ứng dụng đã duyệt. Dùng App chuyển đúng ứng dụng hoặc duyệt lại Plan.')
            if self.snapshot_window != current or time.monotonic() - self.snapshot_at > 120:
                raise ValueError('Ảnh giao diện đã cũ hoặc cửa sổ đổi. Gọi Snapshot mới trước khi bấm/gõ.')
            if args.get('label') is not None:
                raise ValueError('Công cụ này dùng loc=[x,y] từ Snapshot mới nhất; nhãn số chưa được hỗ trợ an toàn.')
            target = self._target_line(args.get('loc')) if name in ('Click', 'Type', 'Scroll', 'Move') else ''
            reason = confirmation_reason(name, args, self.snapshot, current.title)
            if Path(current.executable).stem.lower() in ('powershell', 'pwsh', 'cmd', 'windowsterminal', 'wt'):
                reason = 'Thao tác trong cửa sổ lệnh:\n' + json.dumps(args, ensure_ascii=False)
            if name == 'Click' and target:
                reason = None
            if name == 'Click' and target and re.search(
                    r'\b(?:send|gui|submit|publish|dang|buy|mua|pay|thanh toan|delete|remove|xoa|'
                    r'run|execute|chay|thuc thi|install|cai dat|uninstall|go cai dat|'
                    r'dong y|cho phep|accept|allow|yes|ok|confirm|xac nhan)\b', folded(target)):
                reason = 'Xác nhận nút có thể gửi, xóa, mua hoặc chạy lệnh:\n' + target
            if name in ('Click', 'Type', 'Scroll', 'Move') and not target:
                reason = 'Thao tác vị trí chưa có nhãn trong ' + current.title + ':\n' + json.dumps(args, ensure_ascii=False)
            if name == 'Type' and any(c in str(args.get('text', '')) for c in '\r\n'):
                reason = 'Nhập nội dung có xuống dòng (có thể gửi trong ứng dụng chat):\n' + str(args['text'])
            if name == 'Shortcut' and str(args.get('shortcut', '')).lower().replace(' ', '') in ('ctrl+s', 'ctrl+v', 'ctrl+z', 'ctrl+y'):
                reason = 'Thao tác lưu/dán/thay đổi tài liệu trong ' + current.title + ': ' + str(args['shortcut'])
        else:
            raise ValueError('Công cụ chưa được cấp trong bộ điều khiển này.')
        if reason:
            message = reason + '\n\nCửa sổ hiện tại: ' + current.title
            if not self.approve('approve_action', self.grant, message).get('allowed'):
                self.finish()
                raise ValueError('Thao tác chưa khớp đủ chi tiết với yêu cầu hiện tại hoặc đã bị hủy. Đã dừng, không thử đường khác.')
            if name in ('Click', 'Type', 'Scroll', 'Shortcut', 'Move'):
                self.restore(current.hwnd)
                if self.foreground() != current:
                    raise ValueError('Cửa sổ thay đổi khi chờ cấp phép; chụp lại trước khi thao tác.')
        self._check()
        self.steps += 1
        return args, current

    def _target_line(self, location, snapshot: str | None = None) -> str:
        if not isinstance(location, list) or len(location) != 2 or not all(type(n) is int for n in location):
            return ''
        text = self.snapshot if snapshot is None else snapshot
        hits = []
        for line in text.splitlines():
            match = re.match(
                r'^[ │]*[├└]──\s+\((-?\d+),(-?\d+)\)\s+[\w /-]+\s+"[^"\r\n]*"\s+'
                r'(?:\[[^\]\r\n]+\]\s+)*\[action:', line)
            if match and [int(match[1]),int(match[2])] == location and line not in hits:
                hits.append(line)
        # Do not confuse a point mentioned inside a label with its location,
        # or choose between different controls sharing the same point.
        if len(hits)==1: return hits[0]
        # UIA can expose a control and its decorative Text child at the same
        # center. Never choose between two inputs/buttons or hide a sensitive
        # button behind the text decorating it.
        semantic=[line for line in hits if not re.search(r'\)\s+(?:text|static text|statictext)\s+"',line,re.I)]
        return semantic[0] if len(semantic)==1 else ''

    def validate_live_target(self, name: str, args: dict, text: str, window: Window) -> None:
        if window != self.snapshot_window or self.foreground() != window:
            raise ValueError('Cửa sổ đã đổi ngay trước thao tác; cần Snapshot lại.')
        location = args.get('loc')
        if name in ('Click', 'Type', 'Scroll', 'Move'):
            old = self._target_line(location)
            new = self._target_line(location, text)
        else:
            def elements(value: str) -> list[str]:
                return [line.strip() for line in value.splitlines() if '[action:' in line]
            old, new = elements(self.snapshot), elements(text)
        if not old or old != new:
            self.snapshot_window = None
            raise ValueError('Phần tử hoặc vị trí giao diện đã thay đổi. Gọi Snapshot mới, không dùng nhãn cũ.')
        self._check()

    def after(self, name: str, args: dict, before: Window, text: str, error: bool) -> None:
        self.failed = error
        if error:
            self.snapshot_window = None
            return
        if name == 'Snapshot':
            current = self.foreground()
            if current != before:
                raise ValueError('Cửa sổ đổi trong lúc đọc giao diện; Snapshot lại.')
            self.snapshot, self.snapshot_window, self.snapshot_at = text, current, time.monotonic()
            self.last_observation = text
            self.needs_verification = False
        elif name == 'FileSystem' and args.get('mode') in ('read', 'list', 'search', 'info'):
            self.last_observation = text; self.needs_verification = False
        else:
            self.snapshot_window = None; self.needs_verification = True
            if name == 'App':
                current = self.foreground()
                requested = folded(str(args.get('name') or ''))
                title = folded(current.title)
                result = folded(text)
                title_confirms_app = (requested and requested in {folded(a) for a in self.apps}
                    and re.search(r'\b' + re.escape(requested) + r'\b', title)
                    and requested in result and current != before)
                if any(app_matches(a, current) for a in self.apps) or title_confirms_app:
                    self.bound_processes.add((current.pid, current.executable))

    def verified_finish(self, evidence: str) -> dict:
        self._check()
        if self.failed or self.needs_verification or not evidence.strip() or evidence not in self.last_observation:
            raise ValueError('Chưa có bằng chứng mới. Đọc lại giao diện/file, trích đúng phần thể hiện kết quả rồi Finish.')
        self.finish()
        return {'finished': True, 'observed_evidence': evidence,
                'instruction': 'Báo đúng điều đã quan sát và phần chưa làm được; không mở rộng kết luận ngoài bằng chứng.'}
