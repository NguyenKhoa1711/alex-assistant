"""Exercise the actual proxy handler with synthetic windows/backend only."""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
import unittest
import desktop_mcp
from mcp import types


class SnapshotRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_snapshot_handler_does_not_require_agent_input_or_undefined_names(self):
        # The handler is nested in main's process/session setup. Load that
        # unchanged handler with fake dependencies, not real desktop sessions.
        tree=ast.parse(Path(desktop_mcp.__file__).read_text(encoding='utf-8'))
        handlers=[n for n in ast.walk(tree) if isinstance(n,ast.AsyncFunctionDef) and n.name=='call_tool']
        self.assertEqual(len(handlers),1)
        handler=handlers[0]
        handler.decorator_list=[]
        mod=ast.fix_missing_locations(ast.Module(body=[handler],type_ignores=[]))
        events=[]
        window=SimpleNamespace(executable='chrome.exe')
        guard=SimpleNamespace(failed=False,
            before=lambda name,args:(events.append(('before',name)) or (args,window)),
            after=lambda name,args,win,text,error:events.append(('after',name,error)))
        class Backend:
            async def call_tool(self,name,args):
                events.append(('backend',name))
                return types.CallToolResult(content=[types.TextContent(type='text',text='UI Tree:\nwindow "Synthetic"')])
        namespace={**vars(desktop_mcp),'serial':asyncio.Lock(),'cfg':{'computer':{'use_agent_desktop':True}},
            'guard':guard,'backend':Backend(),'backend_tools':{'Snapshot'},
            'ext_mgr':SimpleNamespace(handles_tool=lambda name:False)}
        exec(compile(mod,str(desktop_mcp.__file__),'exec'),namespace)
        reply=await asyncio.wait_for(namespace['call_tool']('Snapshot',{'use_vision':False,'use_ui_tree':True,'use_annotation':False}),timeout=3)
        self.assertFalse(reply.isError,reply.structuredContent)
        self.assertEqual(events,[('before','Snapshot'),('backend','Snapshot'),('after','Snapshot',False)])
        # Prove this test catches the production regression rather than just
        # exercising a mock's happy path.
        del namespace['Path']
        broken=await asyncio.wait_for(namespace['call_tool']('Snapshot',{}),timeout=3)
        self.assertTrue(broken.isError)
        self.assertEqual(broken.structuredContent['alex_error_type'],'NameError')

if __name__=='__main__': unittest.main()
