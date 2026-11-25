import threading
import unittest
from unittest.mock import MagicMock, patch
from pet.agent_bridge import AgentDesktopBridge, AgentBridgeError
from pet.desktop_guard import Window
from pet.messaging_driver import ZaloUiDriver


def snapshot(ref='@s1:e1', *, value_action=False, x=10, duplicate=False):
    node={'role':'group','native_id':{'kind':'uia','value':'richInput'},'ref_id':ref,
          'bounds':{'x':x,'y':20,'width':100,'height':30},
          'available_actions':['SetFocus']+(['SetValue'] if value_action else [])}
    return {'complete':True,'tree':{'children':[node,dict(node)] if duplicate else [node]}}


class ZaloObservationFocusTests(unittest.TestCase):
    def test_focus_then_reresolve_exact_same_field_without_typing(self):
        driver=ZaloUiDriver();driver.hwnd=123
        bridge=MagicMock();bridge.snapshot.side_effect=[snapshot(),snapshot('@s1:e2',value_action=True)]
        bridge.is_focused.return_value=True
        def focus(ref):
            self.assertEqual(driver._authorized_focus_ref,ref)
            return {'ok':True,'data':{'disposition':{'delivery':'delivered_verified'}}}
        bridge.focus_for_observation.side_effect=focus
        with patch('pet.messaging_driver.window_point_is_usable',return_value=True):
            found=driver._locate_rich_input(bridge)
        self.assertEqual(found.ref,'@s1:e2')
        self.assertEqual(driver._authorized_focus_ref,'')
        bridge.act.assert_not_called()
        bridge.press_key.assert_not_called()

    def test_unverified_delivery_needs_independent_focus_evidence(self):
        for actual_focus in (True,False):
            with self.subTest(actual_focus=actual_focus):
                driver=ZaloUiDriver();driver.hwnd=123
                bridge=MagicMock();bridge.snapshot.side_effect=[snapshot(),snapshot('@s1:e2',value_action=True)]
                bridge.focus_for_observation.return_value={'ok':True,'data':{'disposition':{'delivery':'delivered_unverified'}}}
                bridge.is_focused.return_value=actual_focus
                with patch('pet.messaging_driver.window_point_is_usable',return_value=True):
                    result=driver._locate_rich_input(bridge)
                self.assertEqual(result is not None,actual_focus)
                bridge.focus_for_observation.assert_called_once()

    def test_ambiguous_changed_or_unverified_fields_are_rejected(self):
        for initial,after,delivery in (
            (snapshot(duplicate=True),None,'delivered_verified'),
            (snapshot(),snapshot('@s1:e2',value_action=True,x=11),'delivered_verified'),
            (snapshot(),None,'not_delivered'),
        ):
            with self.subTest(delivery=delivery,duplicate=after is None):
                driver=ZaloUiDriver();driver.hwnd=123
                bridge=MagicMock();bridge.snapshot.side_effect=[initial]+([after] if after else [])
                bridge.focus_for_observation.return_value={'ok':True,'data':{'disposition':{'delivery':delivery}}}
                with patch('pet.messaging_driver.window_point_is_usable',return_value=True):
                    self.assertIsNone(driver._locate_rich_input(bridge))
                bridge.act.assert_not_called()
                bridge.press_key.assert_not_called()

    def test_existing_bridge_does_not_reclaim_focus_after_window_change(self):
        driver=ZaloUiDriver();driver.hwnd=123;driver.bridge=MagicMock()
        driver.window=Window(123,10,'Zalo.exe','Zalo')
        with patch('pet.messaging_driver.current_window',return_value=Window(456,11,'other.exe','Other')), \
             patch('pet.messaging_driver.focus_window') as focus:
            with self.assertRaises(RuntimeError):driver._ensure_bridge()
        focus.assert_not_called()

    def test_bridge_focus_requires_explicit_read_authorization(self):
        bridge=AgentDesktopBridge.__new__(AgentDesktopBridge)
        bridge.action_uncertain=False;bridge.refs={'@s1:e1'}
        bridge.identity_ok=lambda:True;bridge.authorize=lambda op,ref,value:False
        bridge._call=MagicMock()
        with self.assertRaises(AgentBridgeError):bridge.focus_for_observation('@s1:e1')
        bridge._call.assert_not_called()
        bridge.authorize=lambda op,ref,value:(op,ref,value)==('focus_read','@s1:e1','')
        bridge.focus_for_observation('@s1:e1')
        bridge._call.assert_called_once_with(['--headed','focus','@s1:e1'],action=True)
