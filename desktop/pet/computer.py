from __future__ import annotations
import asyncio
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
import json
import logging
import os
from pathlib import Path
import re
import threading
import time
from typing import Callable
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from .wake import normalized

TOOLS = ('App', 'Snapshot', 'Click', 'Type', 'Scroll', 'Shortcut', 'FileSystem')


@dataclass
class Decision:
    done: threading.Event = field(default_factory=threading.Event)
    allowed: bool = False


def foreground() -> tuple[int, str]:
    import ctypes
    user = ctypes.windll.user32
    user.GetForegroundWindow.restype = ctypes.c_void_p
    hwnd = user.GetForegroundWindow()
    buf = ctypes.create_unicode_buffer(1024)
    user.GetWindowTextW(ctypes.c_void_p(hwnd), buf, len(buf))
    return int(hwnd or 0), buf.value


def confirmation_reason(name: str, args: dict, snapshot: str = '', window: str = '') -> str | None:
    """Guard concrete destructive operations; UI content remains untrusted data."""
    if name == 'FileSystem':
        mode = args.get('mode')
        path = Path(str(args.get('path', ''))).expanduser()
        if not path.is_absolute() or str(path).startswith('\\\\'):
            raise ValueError('Dùng đường dẫn tuyệt đối trên máy, không dùng đường dẫn mạng.')
        if args.get('destination'):
            destination = Path(args['destination']).expanduser()
            if not destination.is_absolute() or str(destination).startswith('\\\\'):
                raise ValueError('Đường dẫn đích phải là đường dẫn tuyệt đối trên máy.')
        if path.resolve() == Path(path.anchor):
            if mode in {'delete', 'move', 'write'}:
                raise ValueError('Không thao tác thay đổi ở gốc ổ đĩa.')
        if mode in {'delete', 'move'} or (mode == 'write' and path.exists()):
            return f'Thao tác file: {mode}\n{path}\nĐích: {args.get("destination", "")}\n' + str(args.get('content', ''))[:1600]
        if args.get('overwrite') in (True, 'true'):
            return f'Ghi đè đích: {args.get("destination", path)}'
        if mode == 'write' and path.suffix.lower() in {'.exe', '.bat', '.cmd', '.ps1', '.vbs', '.reg', '.lnk'}:
            return f'Tạo file có thể thực thi: {path}\n{str(args.get("content", ""))[:1600]}'
    if name == 'App' and args.get('mode') == 'launch_executable':
        executable = Path(str(args.get('executable', '')))
        if executable.name.lower() not in {'notepad.exe', 'calc.exe', 'explorer.exe', 'mspaint.exe'} or args.get('args'):
            return 'Chạy chương trình:\n' + json.dumps(args, ensure_ascii=False)
    if name in {'Click', 'Type', 'Shortcut'}:
        context = normalized(window)
        if any(t in context for t in ('powershell', 'terminal', 'command prompt', 'cmd exe', 'registry', 'run')):
            return f'Thao tác trong cửa sổ lệnh: {window}\n' + json.dumps(args, ensure_ascii=False)
    if name == 'Shortcut':
        keys = str(args.get('shortcut', '')).lower().replace(' ', '')
        safe = {'ctrl+c', 'ctrl+v', 'ctrl+a', 'ctrl+f', 'ctrl+s', 'ctrl+z', 'ctrl+y',
                'ctrl+home', 'ctrl+end', 'home', 'end', 'tab', 'shift+tab', 'esc',
                'alt+tab', 'win+e', 'win+d', 'up', 'down', 'left', 'right', 'pageup', 'pagedown'}
        if keys not in safe:
            return f'Nhấn phím {keys} trong {window}.'
    if name == 'Type' and args.get('press_enter') in (True, 'true'):
        return f'Nhập và gửi trong {window}:\n{args.get("text", "")}'
    if name == 'Type' and args.get('clear') in (True, 'true'):
        return f'Thay nội dung đang có trong {window} bằng:\n{args.get("text", "")}'
    if name == 'Click':
        if args.get('label') is None:
            return f'Bấm tọa độ chưa có nhãn trong {window}: {args.get("loc")}'
        label = str(args['label'])
        lines = [line for line in snapshot.splitlines() if re.search(rf'(?<!\d){re.escape(label)}(?!\d)', line)]
        if not lines:
            raise ValueError('Không tìm thấy nhãn trong ảnh chụp giao diện gần nhất. Gọi Snapshot lại.')
        text = normalized(' '.join(lines))
        if any(re.search(rf'\b{word}\b', text) for word in
               ('delete', 'remove', 'xoa', 'send', 'gui', 'submit', 'publish', 'dang', 'buy', 'mua', 'pay', 'install', 'uninstall', 'format', 'reset', 'confirm', 'xac nhan')):
            return 'Bấm nút:\n' + '\n'.join(lines)[:1200]
    return None


class Computer:
    def __init__(self, cfg: dict, notify: Callable[[str], None], confirm: Callable[[str, Decision], None]) -> None:
        self.cfg, self.notify, self.confirm = cfg, notify, confirm
        self.ready = threading.Event()
        self.closed = threading.Event()
        self.error: Exception | None = None
        self.schemas: list[dict] = []
        self.snapshot_text = ''
        self.snapshot_window: tuple[int, str] | None = None
        self.thread = threading.Thread(target=self._thread, name='Alex-Windows-MCP', daemon=True)
        self.thread.start()

    def _thread(self) -> None:
        try:
            asyncio.run(self._serve())
        except Exception as exc:
            self.error = exc
            logging.exception('Windows MCP stopped')
        finally:
            self.ready.set()

    async def _serve(self) -> None:
        self.loop = asyncio.get_running_loop()
        params = StdioServerParameters(command=self.cfg['command'],
            args=['serve', '--transport', 'stdio', '--tools', ','.join(TOOLS)],
            env={**os.environ, 'ANONYMIZED_TELEMETRY': 'false', 'PYTHONIOENCODING': 'utf-8'})
        # stderr must exist even under pythonw; don't persist screen/file content.
        with open(os.devnull, 'w') as err:
            async with stdio_client(params, errlog=err) as (read, write):
                async with ClientSession(read, write) as session:
                    self.session = session
                    await session.initialize()
                    listed = await session.list_tools()
                    self.schemas = [{'type': 'function', 'function': {'name': t.name,
                        'description': t.description or t.name, 'parameters': t.inputSchema}}
                        for t in listed.tools if t.name in TOOLS]
                    self.ready.set()
                    while not self.closed.is_set():
                        await asyncio.sleep(.1)

    def tools(self, cancelled: threading.Event) -> list[dict]:
        deadline = time.monotonic() + 30
        while not self.ready.wait(.1):
            if cancelled.is_set() or time.monotonic() > deadline:
                raise RuntimeError('Chưa kết nối được công cụ Windows.')
        if self.error:
            raise RuntimeError('Công cụ Windows chưa sẵn sàng.') from self.error
        return self.schemas

    def close(self) -> None:
        self.closed.set()
        self.thread.join(timeout=5)

    def call(self, name: str, args: dict, cancelled: threading.Event) -> str:
        if name not in TOOLS:
            return json.dumps({'error': 'Công cụ không được cấp quyền.'}, ensure_ascii=False)
        if cancelled.is_set():
            return '{"error":"Đã dừng theo yêu cầu người dùng."}'
        try:
            current = foreground()
            if name in {'Click', 'Type', 'Scroll', 'Shortcut'}:
                if self.snapshot_window is None or current != self.snapshot_window:
                    raise ValueError('Cửa sổ đã thay đổi. Gọi Snapshot để xem lại trước khi thao tác.')
            if name == 'Snapshot':
                args = {**args, 'use_vision': False, 'use_annotation': False, 'use_ui_tree': True}
            reason = confirmation_reason(name, args, self.snapshot_text, current[1])
            if reason:
                decision = Decision()
                self.confirm(reason, decision)
                deadline = time.monotonic() + 90
                while not decision.done.wait(.1):
                    if cancelled.is_set() or time.monotonic() > deadline:
                        decision.done.set()
                        return '{"error":"Thao tác chưa được người dùng xác nhận; không thực hiện."}'
                if not decision.allowed:
                    return '{"error":"Người dùng hủy thao tác; không thực hiện, không thử cách khác."}'
                # Restore only the exact window reviewed before sending input.
                if name in {'Click', 'Type', 'Shortcut'} and foreground() != current:
                    import ctypes
                    handle = ctypes.c_void_p(current[0])
                    if ctypes.windll.user32.IsWindow(handle):
                        ctypes.windll.user32.SetForegroundWindow(handle)
                        time.sleep(.15)
                    if foreground() != current:
                        raise ValueError('Cần đưa cửa sổ đích lên lại và Snapshot trước khi thao tác.')
            if cancelled.is_set():
                return '{"error":"Đã dừng."}'
            self.notify(f'Đang thao tác: {name}')
            started = time.monotonic()
            future = asyncio.run_coroutine_threadsafe(self.session.call_tool(name, args), self.loop)
            while True:
                try:
                    result = future.result(timeout=.1)
                    break
                except FutureTimeout:
                    if cancelled.is_set() or time.monotonic() - started > self.cfg.get('timeout_seconds', 45):
                        future.cancel()
                        raise RuntimeError('Đã dừng chờ công cụ. Thao tác đang chạy có thể đã hoàn tất; kiểm tra lại trước khi thử.')
            text = '\n'.join(item.text for item in result.content if item.type == 'text')
            if name == 'Snapshot' and not result.isError:
                self.snapshot_text = text
                self.snapshot_window = foreground()
            elif name in {'App', 'Click', 'Type', 'Shortcut'}:
                self.snapshot_window = None
            logging.info('TOOL %s error=%s duration=%.2fs', name, result.isError, time.monotonic() - started)
            return json.dumps({'is_error': bool(result.isError), 'result': text[:16000]}, ensure_ascii=False)
        except Exception as exc:
            logging.warning('Tool %s failed: %s', name, type(exc).__name__)
            return json.dumps({'is_error': True, 'error': str(exc)}, ensure_ascii=False)
