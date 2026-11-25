import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from mcp import types
from pet.external_mcp import ExternalMcpManager


class AgentMcpGuardNamesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mgr = ExternalMcpManager({'computer': {}})
        self.session = SimpleNamespace(call_tool=AsyncMock(
            return_value=types.CallToolResult(content=[types.TextContent(type='text', text='ok')])
        ))
        self.mgr._sessions['AgentDesktop'] = self.session
        self.mgr._sessions['Playwright'] = self.session
        for prefix, names in {
            'AgentDesktop': ('desktop_version', 'desktop_snapshot', 'desktop_list_windows',
                             'desktop_click', 'desktop_type', 'desktop_set_value', 'desktop_press'),
            'Playwright': ('browser_snapshot', 'browser_click', 'desktop_snapshot'),
        }.items():
            for original in names:
                name = f'{prefix}_{original}'
                self.mgr._tool_map[name] = (prefix, original, types.Tool(name=name, inputSchema={'type':'object'}))

    async def test_real_agent_readonly_names_do_not_need_mutation_approval(self):
        guard = SimpleNamespace(approved=False, steps=0, limit=10)
        for tool in ('AgentDesktop_desktop_version', 'AgentDesktop_desktop_snapshot',
                     'AgentDesktop_desktop_list_windows', 'Playwright_browser_snapshot'):
            with self.subTest(tool=tool):
                result = await self.mgr.call_tool(tool, {}, guard)
                self.assertFalse(result.isError)
        self.assertEqual(guard.steps, 0)

    async def test_mutating_or_unknown_names_remain_blocked(self):
        guard = SimpleNamespace(approved=False, steps=0, limit=10)
        for tool in ('AgentDesktop_desktop_click', 'AgentDesktop_desktop_type',
                     'AgentDesktop_desktop_set_value', 'AgentDesktop_desktop_press',
                     'Playwright_browser_click', 'Playwright_desktop_snapshot'):
            with self.subTest(tool=tool), self.assertRaises(ValueError):
                await self.mgr.call_tool(tool, {}, guard)
        self.session.call_tool.assert_not_awaited()

    async def test_approved_mutation_counts_one_step(self):
        guard = SimpleNamespace(approved=True, steps=0, limit=1)
        await self.mgr.call_tool('AgentDesktop_desktop_click', {}, guard)
        self.assertEqual(guard.steps, 1)
        with self.assertRaises(ValueError):
            await self.mgr.call_tool('AgentDesktop_desktop_click', {}, guard)


if __name__ == '__main__':
    unittest.main()
