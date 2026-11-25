"""Native Bionic desktop MCP, with plans approved in the Alex pet UI."""
from __future__ import annotations
import asyncio
from contextlib import AsyncExitStack
import json
import os
import threading
from pathlib import Path
from urllib.parse import urlparse
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from pet.config import load_config
from pet.desktop_guard import DesktopGuard
from pet.apps import (requested_app, requested_system_app, requested_shortcut,
                      requested_app_path, open_registered_app, requested_web, open_web)
from pet.minecraft import launch_minecraft, wants_minecraft_game
from pet.files import find_paths, search_roots, open_path
from pet.app_actions import AppActions, parse_action
from pet.device_actions import parse_device_action
from pet.external_mcp import ExternalMcpManager

BACKEND_TOOLS = ('App', 'Snapshot', 'Click', 'Type', 'Scroll', 'Shortcut', 'Move', 'FileSystem', 'PowerShell')


def special_tools() -> list[types.Tool]:
    return [types.Tool(name='CloseLocal', description='Actually close ONE browser tab or ONE app window for a direct request. Pass the exact original Vietnamese command unchanged: "đóng tab Chrome", "đóng Notepad", "đóng ứng dụng hiện tại". Normal close only, never kill processes or discard save prompts. A tab request must never close the browser window: keep the last tab open. Only an explicit app/window close may close the whole window. No UI Plan or shell needed for this narrow tool. If the target is ambiguous, ask using its message. Do not retry or call another tool after an uncertain result; never claim success unless verified.',
        inputSchema={'type':'object','properties':{'command':{'type':'string','minLength':1,'maxLength':300}},
                     'required':['command'],'additionalProperties':False}),
        types.Tool(name='DeviceControl', description='Actually adjust laptop volume or screen brightness for a direct user request, including text typed in Bionic. Pass the original Vietnamese command unchanged, e.g. "âm lượng 40 phần trăm", "giảm 40 phần trăm âm lượng cho tôi", "độ sáng 70%", "tắt tiếng". Supports increase/decrease/set/read/mute/unmute and verifies the result. No UI Plan or shell is needed for this narrow control. Report only its verified result; never merely suggest taskbar/settings.',
        inputSchema={'type': 'object', 'properties': {
            'command': {'type': 'string', 'description': 'Exact current user command about laptop volume or brightness',
                        'minLength': 1, 'maxLength': 300}},
            'required': ['command'], 'additionalProperties': False}),
        types.Tool(name='MusicControl', description='Search and auto-play music on Spotify or YouTube, or pause/stop/resume/skip currently playing music. Pass the exact original Vietnamese command unchanged, e.g. "tìm kiếm nhạc Lạc Trôi", "phát bài Thiên Lý Ơi trên YouTube", "dừng nhạc đang chạy", "mở nhạc", "chuyển bài tiếp theo". No UI Plan or shell is needed for this narrow tool. Report only its verified result.',
        inputSchema={'type': 'object', 'properties': {
            'command': {'type': 'string', 'description': 'Exact current user command about searching, playing, or stopping music',
                        'minLength': 1, 'maxLength': 300}},
            'required': ['command'], 'additionalProperties': False}),
        types.Tool(name='OpenLocal', description='For a direct user request to open one app, file or folder, ACTUALLY open it now. If an app name is not installed but matches a configured or known website, open that website in the default browser instead of suggesting installation. Never edit files. If multiple file matches, ask which one. Minecraft opens TLauncher and presses Enter the game for the selected version; TLauncher alone opens only the launcher.',
        inputSchema={'type': 'object', 'properties': {
            'name': {'type': 'string'}, 'kind': {'type': 'string',
                'enum': ['app', 'file', 'folder']}},
            'required': ['name', 'kind'], 'additionalProperties': False}),
        types.Tool(name='OpenWeb', description='For a direct user request to open a website or a URL they supplied, open it in the default browser now. Accept an exact http(s) URL, a configured site name, or a known website name. Do not search the web or claim that Browser Settings must be changed. Report only whether the browser accepted the address, not whether the page finished loading.',
        inputSchema={'type': 'object', 'properties': {
            'target': {'type': 'string', 'description': 'Exact URL or website name from the user request'}},
            'required': ['target'], 'additionalProperties': False}),
        types.Tool(name='FindLocal', description='Read-only: find an installed Windows app, configured website, local file, or folder by its name. Use for questions about where something is. If a requested app is not installed but a website of the same name exists, return its URL and call OpenWeb to fulfill an open request. For direct open requests prefer OpenLocal.',
        inputSchema={'type': 'object', 'properties': {
            'name': {'type': 'string'}, 'kind': {'type': 'string',
                'enum': ['app', 'file', 'folder']}},
            'required': ['name', 'kind'], 'additionalProperties': False}),
        types.Tool(name='Plan', description='Call before multi-step computer UI actions. Set goal to the exact current user request, without adding instructions. A direct request to open one app, file or folder uses OpenLocal. Alex checks the scope automatically during the active turn; do not ask the user to approve it again. Supply specific absolute paths only when needed. Stop if denied.',
        inputSchema={'type': 'object', 'properties': {
            'goal': {'type': 'string'}, 'steps': {'type': 'array', 'items': {'type': 'string'}},
            'apps': {'type': 'array', 'items': {'type': 'string'}},
            'paths': {'type': 'array', 'items': {'type': 'string'}, 'default': []}},
            'required': ['goal', 'steps', 'apps'], 'additionalProperties': False}),
        types.Tool(name='Finish', description='End the approved plan after verifying the requested result. Quote exact evidence from the most recent Snapshot or read-only FileSystem result. A successful click/type alone is not task completion.',
            inputSchema={'type': 'object', 'properties': {'evidence': {'type': 'string'}}, 'required': ['evidence'], 'additionalProperties': False}),
        types.Tool(name='Cancel', description='Stop the plan and revoke further actions. Use on denial or when unable to finish.',
            inputSchema={'type': 'object', 'properties': {}, 'additionalProperties': False})]


def result_text(result: types.CallToolResult) -> str:
    """FastMCP wraps Snapshot's text as a one-item JSON array."""
    parts = []
    for item in result.content:
        if not isinstance(item, types.TextContent):
            continue
        value = item.text
        try:
            decoded = json.loads(value)
            if isinstance(decoded, list) and len(decoded) == 1 and isinstance(decoded[0], str):
                value = decoded[0]
        except ValueError:
            pass
        parts.append(value)
    return '\n'.join(parts)


def resolve_app(name: str, cfg: dict) -> dict | None:
    question = 'Mở ' + name
    return (requested_app(question, cfg.get('apps', {}).get('entries', [])) or
            requested_system_app(question) or requested_shortcut(question) or
            requested_app_path(question))


def resolve_path(name: str, kind: str, cfg: dict) -> list:
    return find_paths(name, kind, search_roots(cfg.get('files', {}).get('search_roots', [])),
                      seconds=float(cfg.get('files', {}).get('search_seconds', 3)))


def resolve_web(target: str, cfg: dict) -> tuple[str, str] | None:
    target = target.strip()
    if not target or len(target) > 2000 or any(char in target for char in '\r\n\t'):
        return None
    if '://' in target:
        if any(char.isspace() for char in target):
            return None
        try:
            url = urlparse(target)
        except ValueError:
            return None
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password:
            return None
        return target, url.hostname
    return requested_web('Mở ' + target, cfg.get('web', {}).get('sites', []))


def default_browser_app() -> str:
    """Read Windows' registered HTTPS handler; never alter the user's default."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice') as key:
            prog_id = str(winreg.QueryValueEx(key, 'ProgId')[0]).casefold()
    except OSError:
        return ''
    for prefix, app in (('chromehtml', 'Chrome'), ('msedgehtm', 'Microsoft Edge'),
                        ('firefoxurl', 'Firefox'), ('bravehtml', 'Brave'),
                        ('operastable', 'Opera')):
        if prog_id.startswith(prefix):
            return app
    return ''


def expand_web_plan_apps(apps: list[str], cfg: dict) -> list[str]:
    """A known web service is hosted by a browser, not a Windows process.

    Add only the actual registered browser when a planned service has a known
    website and no installed-app match. Other app/path/permission checks remain
    in DesktopGuard. Unknown URLs and unrelated running windows grant nothing.
    """
    result = list(apps)
    if any(resolve_web(app, cfg) and not resolve_app(app, cfg) for app in apps):
        browser = default_browser_app()
        if browser and browser.casefold() not in {app.casefold() for app in result}:
            result.append(browser)
    return result


def device_control(command: str, cfg: dict) -> dict:
    if not isinstance(command, str) or not 1 <= len(command.strip()) <= 300:
        raise ValueError('Cần một câu lệnh ngắn về âm lượng hoặc độ sáng.')
    action = parse_device_action(command)
    if action is None:
        raise ValueError('Chưa rõ mức cần chỉnh. Ví dụ: "âm lượng 40 phần trăm" hoặc "giảm độ sáng". Không gọi công cụ khác để đoán lệnh.')
    if not cfg.get('actions', {}).get('enabled', True):
        return {'verified': False, 'message': 'Thao tác máy tính đang tắt trong cấu hình.'}
    result = AppActions(cfg).execute(action, threading.Event())
    return {'device': action.app, 'operation': action.operation,
            'verified': result.verified, 'message': result.message}


def close_local(command: str, cfg: dict) -> dict:
    if not isinstance(command,str) or not 1<=len(command.strip())<=300:
        raise ValueError('Cần một câu lệnh đóng tab hoặc phần mềm cụ thể.')
    action=parse_action(command)
    if action is None or action.app not in ('Tabs','Window') or action.operation!='close_current':
        raise ValueError('Chưa rõ mục cần đóng. Ví dụ: “Đóng tab Chrome” hoặc “Đóng Notepad”. Không tự đoán hay đóng tất cả.')
    if not cfg.get('actions',{}).get('enabled',True):
        return {'verified':False,'message':'Thao tác ứng dụng đang tắt trong cấu hình.'}
    if action.app=='Window' and not action.query:
        from pathlib import Path
        from pet.desktop_guard import current_window
        # Typing in Bionic does not identify another app window. Do not silently
        # close the conversation or guess the window behind it.
        if Path(current_window().executable).name.casefold()=='bionic.exe':
            return {'verified':False,'message':'Bạn đang gõ trong Bionic. Bạn muốn đóng phần mềm nào? Ví dụ “Đóng Notepad”. Nếu dùng mic Alex, đưa cửa sổ cần đóng lên trước rồi nói “Đóng cửa sổ này”.'}
    result=AppActions(cfg).execute(action,threading.Event())
    return {'kind':'tab' if action.app=='Tabs' else 'window',
            'verified':result.verified,'message':result.message}


def music_control(command: str, cfg: dict) -> dict:
    if not isinstance(command, str) or not 1 <= len(command.strip()) <= 300:
        raise ValueError('Cần một câu lệnh tìm kiếm, phát hoặc dừng nhạc cụ thể.')
    action = parse_action(command)
    if action is None or action.app not in ('Spotify', 'YouTube') or action.operation not in ('play', 'pause', 'next', 'previous', 'song'):
        raise ValueError('Chưa rõ lệnh nhạc. Ví dụ: "tìm nhạc Lạc Trôi", "phát bài Thiên Lý Ơi trên YouTube", hoặc "dừng nhạc đang chạy".')
    if not cfg.get('actions', {}).get('enabled', True):
        return {'verified': False, 'message': 'Thao tác ứng dụng đang tắt trong cấu hình.'}
    result = AppActions(cfg).execute(action, threading.Event())
    return {'app': action.app, 'operation': action.operation, 'query': action.query,
            'verified': result.verified, 'message': result.message}


async def main() -> None:
    cfg = load_config()
    parameters = StdioServerParameters(command=cfg['computer']['command'],
        args=[*cfg['computer'].get('command_args', []), 'serve', '--transport', 'stdio', '--tools', ','.join(BACKEND_TOOLS)],
        env={**os.environ, 'PYTHONIOENCODING': 'utf-8', 'ANONYMIZED_TELEMETRY': 'false', 'DO_NOT_TRACK': '1'})
    guard = DesktopGuard()
    guard.limit = min(80, max(1, int(cfg['computer'].get('max_steps', 40))))
    server = Server('Alex Desktop')
    serial = asyncio.Lock()
    with open(os.devnull, 'w') as errors:
        async with AsyncExitStack() as stack:
            read, write = await stack.enter_async_context(stdio_client(parameters, errlog=errors))
            backend = await stack.enter_async_context(ClientSession(read, write))
            await backend.initialize()
            backend_tools = {t.name: t for t in (await backend.list_tools()).tools if t.name in BACKEND_TOOLS}
            ext_mgr = ExternalMcpManager(cfg)
            await ext_mgr.start_all(stack)
            @server.list_tools()
            async def list_tools() -> list[types.Tool]:
                return special_tools() + list(backend_tools.values()) + ext_mgr.list_tools()

            @server.call_tool()
            async def call_tool(name: str, arguments: dict) -> types.CallToolResult:
                async with serial:
                    try:
                        if name == 'CloseLocal':
                            value = await asyncio.to_thread(close_local, arguments['command'], cfg)
                            return types.CallToolResult(content=[types.TextContent(type='text',
                                text=json.dumps(value, ensure_ascii=False))], isError=not value['verified'])
                        if name == 'DeviceControl':
                            value = await asyncio.to_thread(device_control, arguments['command'], cfg)
                            return types.CallToolResult(content=[types.TextContent(type='text',
                                text=json.dumps(value, ensure_ascii=False))], isError=not value['verified'])
                        if name == 'MusicControl':
                            value = await asyncio.to_thread(music_control, arguments['command'], cfg)
                            return types.CallToolResult(content=[types.TextContent(type='text',
                                text=json.dumps(value, ensure_ascii=False))], isError=not value['verified'])
                        if name in ('FindLocal', 'OpenLocal'):
                            requested_name = str(arguments['name']).strip()
                            kind = arguments['kind']
                            if not requested_name or len(requested_name) > 150 or kind not in ('app', 'file', 'folder'):
                                raise ValueError('Cần tên ngắn và loại app/file/folder.')
                            if kind == 'app':
                                entry = await asyncio.to_thread(resolve_app, requested_name, cfg)
                                website = resolve_web(requested_name, cfg) if not entry else None
                                value = {'found': bool(entry or website),
                                         'name': entry['name'] if entry else website[1] if website else requested_name,
                                         'kind': 'app' if entry else 'website' if website else 'unknown'}
                                if entry:
                                    value.update({key: entry[key] for key in
                                        ('executable_path', 'app_id', 'shortcut_path', 'shortcut_name') if key in entry})
                                elif website:
                                    value['url'] = website[0]
                                    value['message'] = 'Đã tìm thấy web cùng tên. Dùng OpenWeb để mở địa chỉ này.'
                                if name == 'OpenLocal' and entry:
                                    play = (entry['name'] == 'TLauncher' and
                                            wants_minecraft_game('Mở ' + requested_name))
                                    opened = await asyncio.to_thread(
                                        launch_minecraft if play else open_registered_app,
                                        entry, threading.Event())
                                    value = {'found': True, 'name': opened.name,
                                             'opened': opened.verified, 'foreground': opened.foreground,
                                             'message': opened.message,
                                             'note': 'Đã bấm nút vào game; chưa xác nhận Minecraft vào menu.'
                                                     if opened.kind == 'minecraft_start' else ''}
                                elif name == 'OpenLocal' and website:
                                    opened = await asyncio.to_thread(open_web, *website)
                                    value = {'found': True, 'kind': 'website', 'url': website[0],
                                             'name': website[1], 'opened': opened.verified,
                                             'message': opened.message}
                            else:
                                paths = await asyncio.to_thread(resolve_path, requested_name, kind, cfg)
                                value = {'found': bool(paths), 'matches': [str(path) for path in paths],
                                         'truncated': len(paths) >= 6}
                                if name == 'OpenLocal' and len(paths) == 1:
                                    sent = await asyncio.to_thread(open_path, paths[0])
                                    value = {'found': True, 'name': paths[0].name,
                                             'path': str(paths[0]), 'sent_to_explorer': sent,
                                             'message': f'Đã gửi {paths[0].name} tới File Explorer.' if sent
                                                        else f'Chưa mở được {paths[0].name} trong File Explorer.'}
                                elif name == 'OpenLocal' and len(paths) > 1:
                                    value['message'] = 'Có nhiều mục cùng tên; cần tên thư mục chứa hoặc đường dẫn đầy đủ.'
                                elif name == 'OpenLocal':
                                    value['message'] = 'Chưa tìm thấy đường dẫn trong các thư mục đã cấu hình.'
                            return types.CallToolResult(content=[types.TextContent(type='text',
                                text=json.dumps(value, ensure_ascii=False))],
                                isError=(name == 'OpenLocal' and not (value.get('opened') or value.get('sent_to_explorer'))))
                        if name == 'OpenWeb':
                            website = resolve_web(str(arguments['target']), cfg)
                            if website is None:
                                raise ValueError('Chưa nhận được URL http(s) hoặc tên web đã biết. Hỏi người dùng địa chỉ chính xác.')
                            opened = await asyncio.to_thread(open_web, *website)
                            value = {'url': website[0], 'name': website[1],
                                     'accepted_by_browser': opened.verified,
                                     'message': opened.message}
                            return types.CallToolResult(content=[types.TextContent(type='text',
                                text=json.dumps(value, ensure_ascii=False))],
                                isError=not opened.verified)
                        if name == 'Plan':
                            planned_apps = await asyncio.to_thread(expand_web_plan_apps, arguments['apps'], cfg)
                            value = await asyncio.to_thread(guard.plan, arguments['goal'], arguments['steps'], planned_apps, arguments.get('paths', []))
                            guard._agent_goal = arguments['goal'] if value.get('approved') else ''
                            guard._agent_dispatched = set()
                            return types.CallToolResult(content=[types.TextContent(type='text', text=json.dumps(value, ensure_ascii=False))], isError=not value.get('approved'))
                        if name == 'Finish':
                            value = await asyncio.to_thread(guard.verified_finish, arguments['evidence'])
                            return types.CallToolResult(content=[types.TextContent(type='text', text=json.dumps(value, ensure_ascii=False))])
                        if name == 'Cancel':
                            await asyncio.to_thread(guard.finish)
                            return types.CallToolResult(content=[types.TextContent(type='text', text='Đã thu hồi kế hoạch. Không thực hiện thêm.')])
                        if ext_mgr.handles_tool(name):
                            return await ext_mgr.call_tool(name, arguments, guard)
                        if name not in backend_tools:
                            raise ValueError('Công cụ không được hỗ trợ.')
                        from pet.agent_dispatch import dispatched_step_key, is_eligible, should_require_empty
                        require_empty = should_require_empty(name, arguments, cfg['computer'].get('use_agent_desktop', False),
                                                             getattr(guard, '_agent_goal', ''))
                        incoming = {**arguments, 'clear': False} if require_empty else arguments
                        args, window = await asyncio.to_thread(guard.before, name, incoming)
                        if name in ('Click', 'Type', 'Scroll', 'Shortcut', 'Move'):
                            live = await backend.call_tool('Snapshot', {'use_vision': False, 'use_annotation': False, 'use_ui_tree': True})
                            live_text = result_text(live)
                            if live.isError:
                                raise ValueError('Chưa đọc lại được đích thao tác; dừng bước này.')
                            await asyncio.to_thread(guard.validate_live_target, name, args, live_text, window)
                        target_line = guard._target_line(args.get('loc')) if name in ('Click', 'Type') else ''
                        from pet.search_ui import search_input_query, run_search_input, augment_search_observation
                        search_query = search_input_query(getattr(guard,'_agent_goal',''),args,target_line) if name=='Type' else None
                        exe_stem = Path(getattr(window, 'executable', '') or '').stem.lower()
                        use_agent = bool(search_query and cfg['computer'].get('use_agent_desktop',False)) or is_eligible(name, args, cfg['computer'].get('use_agent_desktop', False), target_line, exe_stem)
                        if use_agent:
                            from pet.agent_dispatch import run_agent_step
                            try:
                                key = dispatched_step_key(name, window, args, target_line)
                                if key in getattr(guard, '_agent_dispatched', set()):
                                    raise ValueError('Thao tác này đã được chuyển một lần; không tự lặp lại.')
                                guard._agent_dispatched.add(key)
                                value = (await asyncio.to_thread(run_search_input,guard,window,args,search_query)
                                         if search_query else await asyncio.to_thread(run_agent_step, guard, window, name, args, require_empty=require_empty))
                            except Exception:
                                # Delivery may be unknown: revoke rather than replay through another backend.
                                await asyncio.to_thread(guard.finish)
                                phase = getattr(guard, '_agent_phase', 'preflight')
                                raise ValueError('Chưa xác định được kết quả agent-desktop; dừng, không tự thử lại. '
                                                 f'[agent_phase={phase}]')
                            text = json.dumps(value, ensure_ascii=False)
                            await asyncio.to_thread(guard.after, name, args, window, text, False)
                            return types.CallToolResult(content=[types.TextContent(type='text', text=text)],
                                                        structuredContent={'result': text})
                        result = await backend.call_tool(name, args)
                        text = result_text(result)
                        error = bool(result.isError) or text.lstrip().startswith('Error capturing desktop state:')
                        if name=='Snapshot' and not error:
                            text=await asyncio.to_thread(augment_search_observation,guard,window,text)
                        await asyncio.to_thread(guard.after, name, args, window, text, error)
                        metadata=dict(result.structuredContent or {})
                        if error:
                            metadata['alex_error_type']='BackendError'
                        content=[types.TextContent(type='text',text=text)] if name=='Snapshot' and not error else result.content
                        return types.CallToolResult(content=content, isError=error,
                                                    structuredContent=metadata or None)
                    except asyncio.CancelledError:
                        await asyncio.to_thread(guard.finish)
                        raise
                    except Exception as exc:
                        guard.failed = True
                        # A rejected step must not be retried through an unguarded tool.
                        message = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else 'Công cụ chưa hoàn tất; kiểm tra lại trạng thái trước khi thử tiếp.'
                        return types.CallToolResult(content=[types.TextContent(type='text', text=message)], isError=True,
                            structuredContent={'alex_error_type':type(exc).__name__})
            try:
                async with stdio_server() as (incoming, outgoing):
                    await server.run(incoming, outgoing, server.create_initialization_options())
            finally:
                await asyncio.to_thread(guard.finish)


if __name__ == '__main__':
    asyncio.run(main())
