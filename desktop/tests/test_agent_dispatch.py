import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pet.agent_bridge import AgentBridgeError
from pet.agent_dispatch import (dispatched_step_key, is_eligible, is_simple_type_request,
                                should_require_empty, run_agent_step)


class FakeBridge:
    def __init__(self, binary, window_id, identity_ok, authorize, make_private):
        self.identity_ok = identity_ok
        self.authorize = authorize
        self.act = Mock(return_value={'ok':True, 'data':{'disposition':{'delivery':'delivered_unverified'}}})
        self.focus_for_type = Mock(return_value={'ok':True, 'data':{'disposition':{'delivery':'delivered_verified'}}})
        FakeBridge.instance = self
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def snapshot(self):
        return {'tree':{'children':[{'name':'Nút thử','ref_id':'@sabc:e1',
                 'role':'button','available_actions':['Click'],
                 'bounds':{'x':90,'y':110,'width':40,'height':30}}]}}
    def get_value(self, ref): return {'ok':True, 'data':{'value':''}}


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.window = SimpleNamespace(hwnd=123, pid=456, executable='fixture.exe', title='fixture')
        self.guard = Mock()
        self.guard._target_line.return_value = '├── (100,120) button "Nút thử" [action: click]'

    def test_existing_backend_remains_for_clear_and_submit(self):
        self.assertTrue(is_eligible('Click', {}, True))
        self.assertTrue(is_eligible('Type', {'text':'hi'}, True))
        self.assertFalse(is_eligible('Type', {'clear':True}, True))
        self.assertFalse(is_eligible('Type', {'press_enter':True}, True))
        self.assertFalse(is_eligible('Click', {}, False))
        self.assertFalse(is_eligible('Scroll', {}, True))
        self.assertFalse(is_eligible('Click', {}, True, 'button "Gửi" [action: click]'))
        self.assertFalse(is_eligible('Click', {}, True, 'button "Delete" [action: click]'))
        self.assertTrue(is_eligible('Click', {}, True, 'button "Tìm kiếm" [action: click]'))
        self.assertFalse(is_eligible('Click', {'button':'right'}, True, 'button "Tìm kiếm" [action: click]'))
        self.assertFalse(is_eligible('Click', {'clicks':2}, True, 'button "Tìm kiếm" [action: click]'))

    def test_auto_ack_only_for_a_simple_type_request(self):
        self.assertTrue(is_simple_type_request('Nhập chữ xin chào vào ô văn bản cho tao'))
        self.assertTrue(is_simple_type_request('Nhập chữ alex bridge vào ô văn bản trên màn hình'))
        for text in ('Nhập chữ xin chào vào ô văn bản rồi gửi',
                     'Nhập chữ xin chào vào ô văn bản và nhấn Enter',
                     'Gửi tin nhắn cho An trên Zalo'):
            self.assertFalse(is_simple_type_request(text), text)

    def test_clear_is_never_silently_removed_for_send_or_non_type_tasks(self):
        args={'clear':True,'press_enter':False}
        self.assertTrue(should_require_empty('Type',args,True,'Nhập chữ hello vào ô văn bản'))
        self.assertFalse(should_require_empty('Type',args,True,'Nhập chữ hello vào ô văn bản rồi gửi'))
        self.assertFalse(should_require_empty('Type',{'clear':True,'press_enter':True},True,
                                              'Nhập chữ hello vào ô văn bản'))
        self.assertFalse(should_require_empty('Type',args,False,'Nhập chữ hello vào ô văn bản'))

    def test_step_replay_key_distinguishes_targets_and_text_without_storing_it(self):
        line='├── (1,2) edit "target" [action: fill]'
        first=dispatched_step_key('Type',self.window,{'loc':[1,2],'text':'secret'},line)
        self.assertEqual(first,dispatched_step_key('Type',self.window,{'loc':[1,2],'text':'secret'},line+' [focused]'))
        self.assertNotEqual(first,dispatched_step_key('Type',self.window,{'loc':[1,2],'text':'other'},line))
        self.assertNotIn('secret',repr(first))

    def test_one_guarded_action_returns_delivery_not_claimed_success(self):
        with patch('pet.agent_dispatch.current_window',return_value=self.window), \
             patch('pet.agent_dispatch._binary',return_value=Path('fixture.exe')):
            value=run_agent_step(self.guard,self.window,'Click',{'loc':[100,120]},bridge_type=FakeBridge)
        self.assertEqual(value['delivery'],'delivered_unverified')
        FakeBridge.instance.act.assert_called_once_with('click','@sabc:e1',text='')

    def test_missing_target_is_reobserved_at_greater_depth_before_one_click(self):
        class DeepFixture(FakeBridge):
            def __init__(self,*args):
                super().__init__(*args);self.depths=[]
            def snapshot(self, *, max_depth=10):
                self.depths.append(max_depth)
                return {'tree':{}} if max_depth==10 else super().snapshot()
        with patch('pet.agent_dispatch.current_window',return_value=self.window), \
             patch('pet.agent_dispatch._binary',return_value=Path('fixture.exe')):
            run_agent_step(self.guard,self.window,'Click',{'loc':[100,120]},bridge_type=DeepFixture)
        self.assertEqual(DeepFixture.instance.depths,[10,30])
        DeepFixture.instance.act.assert_called_once_with('click','@sabc:e1',text='')

    def test_ambiguous_target_is_not_retried_at_greater_depth(self):
        class AmbiguousFixture(FakeBridge):
            def __init__(self,*args):super().__init__(*args);self.depths=[]
            def snapshot(self, *, max_depth=10):
                self.depths.append(max_depth)
                item=super().snapshot()['tree']['children'][0]
                return {'tree':{'children':[item,dict(item,ref_id='@sabc:e2')]}}
        with patch('pet.agent_dispatch.current_window',return_value=self.window), \
             patch('pet.agent_dispatch._binary',return_value=Path('fixture.exe')):
            with self.assertRaises(AgentBridgeError):
                run_agent_step(self.guard,self.window,'Click',{'loc':[100,120]},bridge_type=AmbiguousFixture)
        self.assertEqual(AmbiguousFixture.instance.depths,[10])
        AmbiguousFixture.instance.act.assert_not_called()

    def test_changed_window_and_unsafe_type_are_rejected(self):
        with patch('pet.agent_dispatch.current_window',return_value=None):
            with self.assertRaises(AgentBridgeError):
                run_agent_step(self.guard,self.window,'Click',{'loc':[100,120]},bridge_type=FakeBridge)
        with patch('pet.agent_dispatch.current_window',return_value=self.window):
            with self.assertRaises(AgentBridgeError):
                run_agent_step(self.guard,self.window,'Type',{'loc':[100,120], 'text':'hello',
                               'press_enter':True},bridge_type=FakeBridge)

    def test_require_empty_never_overwrites_nonempty_field(self):
        self.guard._target_line.return_value = '├── (100,120) edit "Nút thử" [action: fill]'
        class ExistingDraft(FakeBridge):
            def snapshot(self):
                return {'tree':{'children':[{'name':'Nút thử','ref_id':'@sabc:e1','role':'textfield',
                    'available_actions':['SetFocus'],'bounds':{'x':90,'y':110,'width':40,'height':30}}]}}
            def get_value(self, ref): return {'ok':True,'data':{'value':'bản nháp cũ'}}
        with patch('pet.agent_dispatch.current_window',return_value=self.window), \
             patch('pet.agent_dispatch._binary',return_value=Path('fixture.exe')):
            with self.assertRaises(AgentBridgeError):
                run_agent_step(self.guard,self.window,'Type',{'loc':[100,120],'text':'hello'},
                               require_empty=True,bridge_type=ExistingDraft)
        ExistingDraft.instance.act.assert_not_called()

    def test_type_focuses_exact_field_and_stops_when_focus_not_verified(self):
        self.guard._target_line.return_value = '├── (100,120) edit "Nút thử" [action: fill]'
        class InputField(FakeBridge):
            def snapshot(self):
                return {'tree':{'children':[{'name':'Nút thử','ref_id':'@sabc:e1','role':'textfield',
                    'available_actions':['SetFocus'],'bounds':{'x':90,'y':110,'width':40,'height':30}}]}}
        with patch('pet.agent_dispatch.current_window',return_value=self.window), \
             patch('pet.agent_dispatch._binary',return_value=Path('fixture.exe')):
            run_agent_step(self.guard,self.window,'Type',{'loc':[100,120],'text':'hello'},bridge_type=InputField)
            InputField.instance.focus_for_type.assert_called_once_with('@sabc:e1','hello')
            InputField.instance.act.assert_called_once_with('type','@sabc:e1',text='hello')
            class UnverifiedFocus(InputField):
                def __init__(self,*args):
                    super().__init__(*args)
                    self.focus_for_type.return_value={'ok':True,'data':{'disposition':{'delivery':'delivered_unverified'}}}
            with self.assertRaises(AgentBridgeError):
                run_agent_step(self.guard,self.window,'Type',{'loc':[100,120],'text':'hello'},bridge_type=UnverifiedFocus)
            UnverifiedFocus.instance.act.assert_not_called()
