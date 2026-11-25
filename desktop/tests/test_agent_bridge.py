import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from pet.agent_bridge import AgentBridgeError, AgentDesktopBridge, unique_ref_for_point


class FakeRunner:
    def __init__(self):
        self.calls = []
        self.response = None
    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        if 'start' in cmd:
            data = {'ok': True, 'data': {'session_id': 'run-test-1'}}
        elif 'snapshot' in cmd:
            data = self.response or {'ok': True, 'data': {'window': {'id': 'w-123'},
                'complete': True, 'tree': {'children': [{'ref_id': '@sabc:e1'}]}}}
        else:
            data = self.response or {'ok': True, 'data': {'disposition': {'delivery': 'delivered_unverified'}}}
        return SimpleNamespace(stdout=json.dumps(data), returncode=0)


class AgentBridgeTests(unittest.TestCase):
    def setUp(self):
        self.runner = FakeRunner()
        self.bridge = AgentDesktopBridge(Path('agent.exe'), 'w-123', lambda: True,
                                         lambda *_: True, lambda _: None, run=self.runner)
        self.addCleanup(self.bridge.close)

    def test_action_is_scoped_to_complete_snapshot_and_invalidated_after(self):
        self.bridge.snapshot()
        self.bridge.act('click', '@sabc:e1')
        with self.assertRaises(AgentBridgeError):
            self.bridge.act('click', '@sabc:e1')

    def test_sensitive_text_is_passed_on_stdin_not_command_line(self):
        self.bridge.snapshot()
        self.bridge.act('type', '@sabc:e1', text='hello')
        cmd, kw = self.runner.calls[-1]
        self.assertNotIn('hello', cmd)
        self.assertEqual(kw['input'], 'hello')
        self.assertIn('--headed', cmd)

    def test_focus_is_authorized_as_typing_and_invalidates_reference(self):
        self.bridge.snapshot()
        self.bridge.authorize = lambda op, ref, text: op == 'type' and text == 'hello'
        with self.assertRaises(AgentBridgeError):
            self.bridge.focus_for_type('@sabc:e1', 'other')
        self.bridge.focus_for_type('@sabc:e1', 'hello')
        self.assertIn('focus', self.runner.calls[-1][0])
        with self.assertRaises(AgentBridgeError):
            self.bridge.act('type', '@sabc:e1', text='hello')

    def test_control_characters_never_turn_typing_into_other_actions(self):
        for value in ('hello\n', 'hello\tworld', 'hello\x00'):
            self.bridge.snapshot()
            with self.assertRaises(AgentBridgeError):
                self.bridge.act('type','@sabc:e1',text=value)
        self.assertFalse(any('type' in call[0] for call in self.runner.calls))

    def test_incomplete_snapshot_cannot_authorize_action(self):
        self.runner.response = {'ok': True, 'data': {'window': {'id': 'w-123'},
                               'complete': False, 'tree': {'ref_id': '@sabc:e1'}}}
        with self.assertRaises(AgentBridgeError): self.bridge.snapshot()
        with self.assertRaises(AgentBridgeError): self.bridge.act('click', '@sabc:e1')

    def test_deep_snapshot_is_explicit_and_bounded(self):
        self.bridge.snapshot(max_depth=30)
        cmd,_=self.runner.calls[-1]
        self.assertEqual(cmd[cmd.index('--max-depth')+1], '30')
        with self.assertRaises(AgentBridgeError): self.bridge.snapshot(max_depth=100)

    def test_action_failure_never_retries_automatically(self):
        self.bridge.snapshot()
        self.runner.response = {'ok': False, 'error': {'code': 'TIMEOUT'}}
        self.bridge.act('click', '@sabc:e1')
        with self.assertRaises(AgentBridgeError): self.bridge.act('click', '@sabc:e1')
        self.assertEqual(sum('click' in call[0] for call in self.runner.calls), 1)

    def test_changed_window_and_unapproved_action_are_refused(self):
        self.bridge.snapshot()
        self.bridge.identity_ok = lambda: False
        with self.assertRaises(AgentBridgeError): self.bridge.act('click', '@sabc:e1')
        self.bridge.identity_ok = lambda: True
        self.bridge.authorize = lambda *_: False
        with self.assertRaises(AgentBridgeError): self.bridge.act('click', '@sabc:e1')

    def test_only_an_exact_guarded_target_can_be_mapped(self):
        n = {'ref_id':'@sabc:e1', 'name':'Tìm kiếm', 'role':'button','available_actions':['Click'],
             'bounds':{'x':90,'y':110,'width':40,'height':30}}
        line='├── (100,120) button "Tìm kiếm" [action: click]'
        self.assertEqual(unique_ref_for_point({'tree':n},[100,120],line,'click'), '@sabc:e1')
        for node in ({**n, 'name':'Xóa'}, {**n, 'bounds':{'x':200,'y':200,'width':10,'height':10}}):
            with self.assertRaises(AgentBridgeError):
                unique_ref_for_point({'tree':node},[100,120],line,'click')
        with self.assertRaises(AgentBridgeError):
            unique_ref_for_point({'tree':dict(n,identity_unproven=True)},[100,120],line,'click')
        with self.assertRaises(AgentBridgeError):
            unique_ref_for_point({'tree':{'children':[n,dict(n,ref_id='@sabc:e2')]}},[100,120],line,'click')

    def test_edit_is_not_confused_with_overlapping_combo_box(self):
        bounds={'x':90,'y':110,'width':40,'height':30}
        combo={'ref_id':'@sabc:e1','name':'Tìm kiếm','role':'combobox',
               'available_actions':['Click'],'bounds':bounds}
        edit={'ref_id':'@sabc:e2','name':'Tìm kiếm','role':'textfield',
              'available_actions':['Click'],'bounds':bounds}
        line='├── (100,120) edit "Tìm kiếm" [action: fill]'
        self.assertEqual(unique_ref_for_point({'tree':{'children':[combo,edit]}},[100,120],line,'click'),'@sabc:e2')

    def test_type_ref_must_be_an_editable_role(self):
        node={'ref_id':'@sabc:e1','name':'Nội dung','role':'button',
              'available_actions':['SetFocus'], 'bounds':{'x':90,'y':110,'width':40,'height':30}}
        line='├── (100,120) edit "Nội dung" [action: fill]'
        with self.assertRaises(AgentBridgeError):
            unique_ref_for_point({'tree':node},[100,120],line,'type')
        node['role']='textfield'
        self.assertEqual(unique_ref_for_point({'tree':node},[100,120],line,'type'),'@sabc:e1')
