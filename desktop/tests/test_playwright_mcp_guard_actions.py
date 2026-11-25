import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from mcp import types
from pet.external_mcp import ExternalMcpManager


class PlaywrightMcpGuardActionsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mgr = ExternalMcpManager({'computer': {}})
        self.session = SimpleNamespace(call_tool=AsyncMock(
            return_value=types.CallToolResult(content=[types.TextContent(type='text', text='ok')])
        ))
        self.mgr._sessions['Playwright'] = self.session
        for original in ('browser_tabs', 'browser_snapshot', 'browser_console_messages', 'browser_network_requests'):
            name = f'Playwright_{original}'
            self.mgr._tool_map[name] = ('Playwright', original, types.Tool(name=name, inputSchema={'type':'object'}))

    async def test_list_and_observations_without_file_are_read_only(self):
        guard = SimpleNamespace(approved=False, steps=0, limit=10)
        for name, args in (('browser_tabs',{'action':'list'}), ('browser_snapshot',{}),
                           ('browser_console_messages',{'level':'info'}),
                           ('browser_network_requests',{'static':False})):
            with self.subTest(name=name):
                self.assertFalse((await self.mgr.call_tool('Playwright_'+name,args,guard)).isError)
        self.assertEqual(guard.steps,0)

    async def test_tab_mutations_and_file_writes_require_approval(self):
        guard = SimpleNamespace(approved=False, steps=0, limit=10)
        cases = [('browser_tabs', {'action': action}) for action in ('new','close','select')]
        cases += [('browser_tabs', {})]
        cases += [(name, {'filename':'fixture.txt'}) for name in
                  ('browser_snapshot','browser_console_messages','browser_network_requests')]
        for name,args in cases:
            with self.subTest(name=name,args=args), self.assertRaises(ValueError):
                await self.mgr.call_tool('Playwright_'+name,args,guard)
        self.session.call_tool.assert_not_awaited()

    async def test_approved_tab_close_is_counted_and_step_limit_enforced(self):
        guard = SimpleNamespace(approved=True, steps=0, limit=1)
        await self.mgr.call_tool('Playwright_browser_tabs',{'action':'close'},guard)
        self.assertEqual(guard.steps,1)
        with self.assertRaises(ValueError):
            await self.mgr.call_tool('Playwright_browser_tabs',{'action':'new'},guard)


if __name__ == '__main__':
    unittest.main()
