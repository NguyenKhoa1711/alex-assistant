import unittest
from unittest.mock import MagicMock, patch
from pet.desktop_guard import Window
from pet.messaging_driver import MessengerUiDriver


def node(role,name,ref):
    return {'role':role,'name':name,'ref_id':ref,'bounds':{'x':10,'y':50,'width':200,'height':20}}


class BrowserOriginBindingTests(unittest.TestCase):
    def test_page_cannot_spoof_browser_controls(self):
        doc={'role':'document','children':[{'role':'toolbar','children':[
            node('textfield','Address and search bar','@s1:e1'),
            node('button','View site information','@s1:e2')]}]}
        self.assertEqual(MessengerUiDriver._find_address_bar_ref({'tree':doc}), '')
        self.assertEqual(MessengerUiDriver._find_site_info_ref({'tree':doc}), '')

    def test_unique_browser_toolbar_controls_are_found(self):
        tree={'role':'window','children':[{'role':'toolbar','children':[
            node('textfield','Address and search bar','@s1:e1'),
            node('button','View site information','@s1:e2')]}]}
        self.assertEqual(MessengerUiDriver._find_address_bar_ref({'tree':tree}), '@s1:e1')
        self.assertEqual(MessengerUiDriver._find_site_info_ref({'tree':tree}), '@s1:e2')

    def test_focused_or_unknown_address_is_not_a_committed_page(self):
        snap={'tree':{'role':'window','children':[{'role':'toolbar','children':[
            node('textfield','Address and search bar','@s1:e1')]}]}}
        for outcome in (True,None):
            with self.subTest(outcome=outcome):
                driver=MessengerUiDriver();driver.hwnd=123
                bridge=MagicMock();driver.bridge=bridge
                bridge.get_value.return_value={'ok':True,'data':{'value':'https://messenger.com/'}}
                with patch.object(driver,'_address_focused_state',return_value=outcome):
                    with self.assertRaises(RuntimeError):driver._verify_browser_address_and_security(snap)
                bridge.act.assert_not_called()

    def test_user_window_change_does_not_steal_focus(self):
        driver=MessengerUiDriver();driver.hwnd=123
        snap={'tree':{'role':'window','children':[{'role':'toolbar','children':[
            node('textfield','Address and search bar','@s1:e1'),
            node('button','View site information','@s1:e2')]}]}}
        bridge=MagicMock();driver.bridge=bridge
        bridge.get_value.return_value={'ok':True,'data':{'value':'messenger.com/'}}
        bridge.act.return_value={'ok':True}
        browser=Window(123,456,'chrome.exe','Messenger')
        other=Window(777,888,'other.exe','Other')
        with patch.object(driver,'_address_focused_state',return_value=False), \
             patch.object(driver,'_read_security_popup_is_https',return_value=False), \
             patch('pet.messaging_driver.current_window',side_effect=[browser,other,other]), \
             patch('pet.messaging_driver.focus_window') as focus:
            with self.assertRaises(RuntimeError):driver._verify_browser_address_and_security(snap)
        focus.assert_not_called()

    def test_unreadable_focus_state_is_not_mistaken_for_unfocused(self):
        driver=MessengerUiDriver();bridge=MagicMock();driver.bridge=bridge
        bridge.refs={'@s1:e1'};bridge.identity_ok.return_value=True
        for reply in ({'ok':False}, {'ok':True,'data':{}},
                      {'ok':True,'data':{'applicable':False,'result':False}}):
            with self.subTest(reply=reply):
                bridge._call.return_value=reply
                self.assertIsNone(driver._address_focused_state('@s1:e1'))
        bridge._call.return_value={'ok':True,'data':{'applicable':True,'result':False}}
        self.assertIs(driver._address_focused_state('@s1:e1'),False)
