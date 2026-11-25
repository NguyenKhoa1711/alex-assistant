"""Optional external MCP & local n8n bridges for Alex Desktop MCP."""
from __future__ import annotations

from contextlib import AsyncExitStack
import json
import os
import re
import shutil
import socket
import urllib.error
import urllib.request
from urllib.parse import urlparse

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

from pet.screen_context import _binary

_READONLY_SUFFIXES = frozenset({
    'snapshot', 'find', 'get', 'is', 'list_windows', 'list_apps',
    'list_displays', 'list_surfaces', 'status', 'version', 'skills',
    'screenshot', 'clipboard_get', 'browser_snapshot', 'browser_tabs',
    'browser_console_messages', 'browser_network_requests',
})


class _NoWebhookRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a local webhook response to a different address."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def tcp_port_open(host: str, port: int, timeout: float = 0.25) -> bool:
    """Quickly check whether a local TCP service (e.g. Chrome CDP or n8n) is listening."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _endpoint_host_port(endpoint: str, default_port: int) -> tuple[str, int] | None:
    if not isinstance(endpoint, str) or '://' not in endpoint:
        return None
    parsed = urlparse(endpoint.strip())
    if not parsed.hostname:
        return None
    return parsed.hostname, parsed.port or default_port


def _is_local_http_url(url: str) -> bool:
    try:
        parsed = urlparse((url or '').strip())
        return (
            parsed.scheme in ('http', 'https')
            and (parsed.hostname or '').casefold() in ('127.0.0.1', 'localhost')
            and parsed.username is None
            and parsed.password is None
        )
    except ValueError:
        return False


def _n8n_status(cfg: dict) -> dict:
    n8n_cfg = cfg.get('computer', {}).get('n8n_mcp', {}) or {}
    base = str(n8n_cfg.get('webhook_base') or 'http://127.0.0.1:5678/webhook').strip()
    hp = _endpoint_host_port(base, 5678)
    reachable = bool(hp and tcp_port_open(hp[0], hp[1]))
    return {
        'enabled': bool(n8n_cfg.get('enabled', False)),
        'reachable': reachable,
        'webhook_base': base if _is_local_http_url(base) else '',
        'allowed_webhooks': list(n8n_cfg.get('allowed_webhooks') or []),
    }


def _trigger_n8n_webhook(webhook: str, payload: dict, cfg: dict) -> dict:
    n8n_cfg = cfg.get('computer', {}).get('n8n_mcp', {}) or {}
    if not n8n_cfg.get('enabled', False):
        return {'ok': False, 'message': 'Local n8n chưa được bật trong config.yaml (computer.n8n_mcp.enabled=true).'}
    base = str(n8n_cfg.get('webhook_base') or 'http://127.0.0.1:5678/webhook').strip().rstrip('/')
    if not _is_local_http_url(base):
        return {'ok': False, 'message': 'Chỉ cho phép kết nối n8n cục bộ (127.0.0.1 / localhost).'}
    slug = str(webhook or '').strip().lstrip('/')
    if not slug or '..' in slug or not re.fullmatch(r'[A-Za-z0-9_/-]{1,120}', slug):
        return {'ok': False, 'message': 'Tên webhook n8n không hợp lệ.'}
    allowed = [str(w).strip().lstrip('/') for w in (n8n_cfg.get('allowed_webhooks') or []) if str(w).strip()]
    if not allowed:
        return {'ok': False, 'message': 'Chưa cấu hình webhook được phép trong computer.n8n_mcp.allowed_webhooks.'}
    if slug not in allowed:
        return {'ok': False, 'message': f'Webhook "{slug}" chưa nằm trong computer.n8n_mcp.allowed_webhooks.'}
    hp = _endpoint_host_port(base, 5678)
    if not hp or not tcp_port_open(hp[0], hp[1]):
        return {'ok': False, 'message': f'Local n8n chưa chạy tại {base}.'}
    url = f'{base}/{slug}'
    body = json.dumps(payload if isinstance(payload, dict) else {}).encode('utf-8')
    req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json'}, method='POST')
    try:
        # Local-only applies to the actual request destination as well as its
        # initial URL. Do not let environment proxies or redirects bypass it.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoWebhookRedirect())
        with opener.open(req, timeout=12) as resp:
            raw = resp.read(8192).decode('utf-8', errors='replace')
            return {'ok': 200 <= resp.status < 300, 'status': resp.status, 'response': raw}
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {'ok': False, 'message': f'Gọi local n8n thất bại: {exc}'}


class ExternalMcpManager:
    """Connects optional AgentDesktop MCP, Playwright CDP MCP, and local n8n helpers."""

    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self._sessions: dict[str, ClientSession] = {}
        self._tool_map: dict[str, tuple[str, str, types.Tool]] = {}

    async def start_all(self, stack: AsyncExitStack) -> None:
        comp = self.cfg.get('computer', {}) or {}
        base_env = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'ANONYMIZED_TELEMETRY': 'false', 'DO_NOT_TRACK': '1'}

        # 1. agent-desktop mcp (Windows native UIA automation)
        ad_cfg = comp.get('agent_desktop_mcp', {}) or {}
        if ad_cfg.get('enabled', True):
            cmd = str(ad_cfg.get('command') or _binary() or '').strip()
            args = list(ad_cfg.get('args') or ['mcp', '--headed'])
            if cmd and os.path.exists(cmd):
                await self._connect_stdio(stack, 'AgentDesktop', cmd, args, base_env)

        # 2. Microsoft Playwright MCP (Chrome CDP) — connect only if CDP endpoint is listening
        pw_cfg = comp.get('playwright_mcp', {}) or {}
        if pw_cfg.get('enabled', True):
            endpoint = str(pw_cfg.get('cdp_endpoint') or 'http://127.0.0.1:9222').strip()
            hp = _endpoint_host_port(endpoint, 9222)
            npx = shutil.which(str(pw_cfg.get('command') or 'npx'))
            if npx and hp and tcp_port_open(hp[0], hp[1]):
                args = list(pw_cfg.get('args') or ['-y', '@playwright/mcp@latest', '--cdp-endpoint', endpoint])
                await self._connect_stdio(stack, 'Playwright', npx, args, base_env)

    async def _connect_stdio(
        self, stack: AsyncExitStack, prefix: str, command: str, args: list[str], env: dict[str, str]
    ) -> None:
        try:
            params = StdioServerParameters(command=command, args=args, env=env)
            errlog = stack.enter_context(open(os.devnull, 'w'))
            read, write = await stack.enter_async_context(stdio_client(params, errlog=errlog))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            listed = await session.list_tools()
            self._sessions[prefix] = session
            for tool in listed.tools:
                ext_name = f'{prefix}_{tool.name}'
                prefixed_tool = types.Tool(
                    name=ext_name,
                    description=f'[{prefix} MCP] {tool.description or tool.name}',
                    inputSchema=tool.inputSchema,
                )
                self._tool_map[ext_name] = (prefix, tool.name, prefixed_tool)
        except Exception:
            # Optional external MCPs must never crash Alex desktop startup.
            self._sessions.pop(prefix, None)

    def helper_tools(self) -> list[types.Tool]:
        return [
            types.Tool(
                name='BrowserCdpStatus',
                description='Check whether Chrome Remote Debugging (CDP) is open for Playwright MCP.',
                inputSchema={'type': 'object', 'properties': {}, 'additionalProperties': False},
            ),
            types.Tool(
                name='N8nStatus',
                description='Check whether local n8n workflow engine is configured and reachable.',
                inputSchema={'type': 'object', 'properties': {}, 'additionalProperties': False},
            ),
            types.Tool(
                name='N8nTrigger',
                description='Trigger an allowed local n8n webhook workflow (e.g. Gmail, Calendar, reminders).',
                inputSchema={
                    'type': 'object',
                    'properties': {
                        'webhook': {'type': 'string', 'description': 'Webhook path slug under local n8n /webhook/'},
                        'payload': {'type': 'object', 'description': 'JSON payload for the n8n workflow', 'default': {}},
                    },
                    'required': ['webhook'],
                    'additionalProperties': False,
                },
            ),
        ]

    def list_tools(self) -> list[types.Tool]:
        return self.helper_tools() + [entry[2] for entry in self._tool_map.values()]

    def handles_tool(self, name: str) -> bool:
        return name in ('BrowserCdpStatus', 'N8nStatus', 'N8nTrigger') or name in self._tool_map

    async def call_tool(self, name: str, arguments: dict, guard) -> types.CallToolResult:
        if name == 'BrowserCdpStatus':
            pw_cfg = self.cfg.get('computer', {}).get('playwright_mcp', {}) or {}
            endpoint = str(pw_cfg.get('cdp_endpoint') or 'http://127.0.0.1:9222').strip()
            hp = _endpoint_host_port(endpoint, 9222)
            reachable = bool(hp and tcp_port_open(hp[0], hp[1]))
            data = {
                'connected': 'Playwright' in self._sessions,
                'cdp_reachable': reachable,
                'cdp_endpoint': endpoint,
                'hint': '' if reachable else 'Mở Chrome với cờ --remote-debugging-port=9222 rồi khởi động lại Alex để dùng Playwright MCP.',
            }
            return types.CallToolResult(content=[types.TextContent(type='text', text=json.dumps(data, ensure_ascii=False))])

        if name == 'N8nStatus':
            return types.CallToolResult(
                content=[types.TextContent(type='text', text=json.dumps(_n8n_status(self.cfg), ensure_ascii=False))]
            )

        if name == 'N8nTrigger':
            # DesktopGuard stores an actual revocable grant, not an
            # ``approved`` attribute. Verify the existing grant on every use.
            self._require_n8n_plan_step(guard)
            res = _trigger_n8n_webhook(arguments.get('webhook', ''), arguments.get('payload') or {}, self.cfg)
            return types.CallToolResult(
                content=[types.TextContent(type='text', text=json.dumps(res, ensure_ascii=False))],
                isError=not res.get('ok'),
            )

        prefix, orig_name, _ = self._tool_map[name]
        normalized = orig_name.replace('-', '_').casefold()
        # The actual agent-desktop MCP exposes desktop_snapshot,
        # desktop_version, etc.; the whitelist uses their operation names.
        # Only strip the prefix for the known AgentDesktop server.
        if prefix == 'AgentDesktop' and normalized.startswith('desktop_'):
            normalized = normalized[len('desktop_'):]
        readonly = normalized in _READONLY_SUFFIXES
        if prefix == 'Playwright' and normalized == 'browser_tabs':
            # This tool also opens, selects and closes tabs.
            readonly = isinstance(arguments, dict) and arguments.get('action') == 'list'
        if prefix == 'Playwright' and normalized in (
                'browser_snapshot', 'browser_console_messages', 'browser_network_requests'):
            # These observation tools can optionally write output to a file.
            readonly = isinstance(arguments, dict) and 'filename' not in arguments
        if not readonly:
            self._require_approved_step(guard)
        session = self._sessions[prefix]
        return await session.call_tool(orig_name, arguments or {})

    @staticmethod
    def _require_n8n_plan_step(guard) -> None:
        check = getattr(guard, '_check', None)
        if not callable(check):
            raise ValueError('Cần kế hoạch hợp lệ trước khi chạy workflow.')
        check()
        guard.steps += 1

    @staticmethod
    def _require_approved_step(guard) -> None:
        if not getattr(guard, 'approved', False):
            raise ValueError('Cần gọi Plan được duyệt trước khi thực hiện thao tác thay đổi giao diện.')
        if getattr(guard, 'steps', 0) >= getattr(guard, 'limit', 40):
            raise ValueError('Đã đạt giới hạn bước thao tác trong kế hoạch hiện tại.')
        guard.steps = getattr(guard, 'steps', 0) + 1
