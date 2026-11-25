from contextlib import AsyncExitStack
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from mcp import types

from pet.desktop_guard import DesktopGuard
from pet.external_mcp import ExternalMcpManager, _is_local_http_url, _trigger_n8n_webhook
from pet.gemma import _filter_tools_for_local_context


class ExternalMcpTests(unittest.IsolatedAsyncioTestCase):
    def test_n8n_security_guards_reject_remote_and_unlisted_webhooks(self):
        self.assertTrue(_is_local_http_url('http://127.0.0.1:5678/webhook'))
        self.assertTrue(_is_local_http_url('http://localhost:5678/webhook'))
        self.assertFalse(_is_local_http_url('https://evil.example.com/webhook'))

        cfg = {
            'computer': {
                'n8n_mcp': {
                    'enabled': True,
                    'webhook_base': 'https://evil.example.com/webhook',
                    'allowed_webhooks': ['gmail-summary'],
                }
            }
        }
        res = _trigger_n8n_webhook('gmail-summary', {}, cfg)
        self.assertFalse(res['ok'])
        self.assertIn('cục bộ', res['message'])

        cfg['computer']['n8n_mcp']['webhook_base'] = 'http://127.0.0.1:5678/webhook'
        res2 = _trigger_n8n_webhook('../secret', {}, cfg)
        self.assertFalse(res2['ok'])
        res3 = _trigger_n8n_webhook('other-hook', {}, cfg)
        self.assertFalse(res3['ok'])
        self.assertIn('allowed_webhooks', res3['message'])

        cfg['computer']['n8n_mcp']['allowed_webhooks'] = []
        res4 = _trigger_n8n_webhook('gmail-summary', {}, cfg)
        self.assertFalse(res4['ok'])
        self.assertIn('allowed_webhooks', res4['message'])

    async def test_n8n_trigger_requires_approved_plan(self):
        mgr = ExternalMcpManager({'computer': {'n8n_mcp': {'enabled': False, 'allowed_webhooks': ['gmail-summary']}}})
        guard = DesktopGuard()
        with self.assertRaises(ValueError):
            await mgr.call_tool('N8nTrigger', {'webhook': 'gmail-summary', 'payload': {}}, guard)

        # Model the real DesktopGuard: Plan grants a token and every step
        # must revalidate it; a synthetic .approved flag is not sufficient.
        guard.grant = 'test-grant'
        guard.approve = MagicMock(return_value={'allowed': True})
        res = await mgr.call_tool('N8nTrigger', {'webhook': 'gmail-summary', 'payload': {}}, guard)
        self.assertTrue(res.isError)
        self.assertEqual(guard.steps, 1)
        guard.approve.assert_called_once_with('check', 'test-grant')

    async def test_n8n_refuses_revoked_grant_even_if_fake_approved_flag_is_set(self):
        mgr = ExternalMcpManager({'computer': {'n8n_mcp': {'enabled': False}}})
        guard = DesktopGuard(approve=MagicMock(return_value={'allowed': False}))
        guard.grant = 'revoked'
        guard.approved = True
        with self.assertRaises(ValueError):
            await mgr.call_tool('N8nTrigger', {'webhook': 'example'}, guard)
        self.assertEqual(guard.steps, 0)

    async def test_n8n_valid_grant_calls_only_authorized_workflow_once(self):
        mgr = ExternalMcpManager({'computer': {'n8n_mcp': {'enabled': True}}})
        guard = DesktopGuard(approve=MagicMock(return_value={'allowed': True}))
        guard.grant = 'active'
        with patch('pet.external_mcp._trigger_n8n_webhook', return_value={'ok': True}) as trigger:
            result = await mgr.call_tool('N8nTrigger', {'webhook': 'example', 'payload': {}}, guard)
        self.assertFalse(result.isError)
        trigger.assert_called_once()
        self.assertEqual(guard.steps, 1)

    async def test_n8n_respects_step_limit(self):
        mgr = ExternalMcpManager({'computer': {'n8n_mcp': {'enabled': True}}})
        guard = DesktopGuard(approve=MagicMock(return_value={'allowed': True}))
        guard.grant = 'active'
        guard.steps = guard.limit
        with patch('pet.external_mcp._trigger_n8n_webhook') as trigger:
            with self.assertRaises(ValueError):
                await mgr.call_tool('N8nTrigger', {'webhook': 'example'}, guard)
        trigger.assert_not_called()

    def test_local_gemma_tool_filter_omits_bulky_external_schemas(self):
        schemas = [
            {'type': 'function', 'function': {'name': 'Plan'}},
            {'type': 'function', 'function': {'name': 'Snapshot'}},
            {'type': 'function', 'function': {'name': 'AgentDesktop_click'}},
            {'type': 'function', 'function': {'name': 'Playwright_browser_navigate'}},
            {'type': 'function', 'function': {'name': 'BrowserCdpStatus'}},
            {'type': 'function', 'function': {'name': 'N8nStatus'}},
            {'type': 'function', 'function': {'name': 'N8nTrigger'}},
        ]
        filtered = _filter_tools_for_local_context(schemas, n8n_enabled=False)
        names = [s['function']['name'] for s in filtered]
        self.assertEqual(names, ['Plan', 'Snapshot'])

        filtered_n8n = _filter_tools_for_local_context(schemas, n8n_enabled=True)
        names_n8n = [s['function']['name'] for s in filtered_n8n]
        self.assertEqual(names_n8n, ['Plan', 'Snapshot', 'N8nStatus', 'N8nTrigger'])

    async def test_mutating_external_tools_require_approved_plan(self):
        mgr = ExternalMcpManager({'computer': {}})
        session = MagicMock()
        session.call_tool = AsyncMock(
            return_value=types.CallToolResult(content=[types.TextContent(type='text', text='ok')])
        )
        mgr._sessions['AgentDesktop'] = session
        mgr._tool_map['AgentDesktop_snapshot'] = (
            'AgentDesktop', 'snapshot', types.Tool(name='AgentDesktop_snapshot', inputSchema={'type': 'object'})
        )
        mgr._tool_map['AgentDesktop_click'] = (
            'AgentDesktop', 'click', types.Tool(name='AgentDesktop_click', inputSchema={'type': 'object'})
        )

        guard = DesktopGuard()
        snap_res = await mgr.call_tool('AgentDesktop_snapshot', {}, guard)
        self.assertFalse(snap_res.isError)
        with self.assertRaises(ValueError):
            await mgr.call_tool('AgentDesktop_click', {'ref': '@s1'}, guard)

        guard.approved = True
        click_res = await mgr.call_tool('AgentDesktop_click', {'ref': '@s1'}, guard)
        self.assertFalse(click_res.isError)
        self.assertEqual(guard.steps, 1)

    async def test_agent_desktop_mcp_connects_if_binary_present(self):
        mgr = ExternalMcpManager({
            'computer': {
                'agent_desktop_mcp': {'enabled': True, 'args': ['mcp', '--headed']},
                'playwright_mcp': {'enabled': False},
            }
        })
        async with AsyncExitStack() as stack:
            await mgr.start_all(stack)
            tool_names = [t.name for t in mgr.list_tools()]
            self.assertIn('BrowserCdpStatus', tool_names)
            self.assertIn('N8nStatus', tool_names)
            self.assertIn('N8nTrigger', tool_names)
            if 'AgentDesktop' in mgr._sessions:
                self.assertTrue(any(n.startswith('AgentDesktop_') for n in tool_names))
                status = await mgr.call_tool('N8nStatus', {}, DesktopGuard())
                payload = json.loads(status.content[0].text)
                self.assertIn('reachable', payload)


if __name__ == '__main__':
    unittest.main()
