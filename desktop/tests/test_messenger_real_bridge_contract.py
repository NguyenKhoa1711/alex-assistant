"""Origin preflight must use snapshot depths supported by the real bridge."""
import unittest
from unittest.mock import MagicMock, patch
from pet.desktop_guard import Window
from pet.messaging_driver import MessengerUiDriver


class MessengerBridgeContractTests(unittest.TestCase):
    def test_preflight_reobserves_at_supported_depth_after_security_popup(self):
        driver=MessengerUiDriver();driver.hwnd=123
        snap={'complete':True,'tree':{'role':'window','children':[{'role':'toolbar','children':[
            {'role':'textfield','name':'Address and search bar','ref_id':'@s1:e1',
             'bounds':{'y':50}},
            {'role':'button','name':'View site information','ref_id':'@s1:e2',
             'bounds':{'y':50}},
        ]}]}}
        bridge=MagicMock()
        bridge.get_value.return_value={'ok':True,'data':{'value':'messenger.com/t/123'}}
        bridge.act.return_value={'ok':True}
        def snapshot(*,max_depth=10):
            if max_depth not in (10,30):raise ValueError('unsupported depth')
            return snap
        bridge.snapshot.side_effect=snapshot
        driver.bridge=bridge
        window=Window(123,456,'chrome.exe','Messenger')
        with patch('pet.messaging_driver.current_window',return_value=window), \
             patch('pet.messaging_driver.focus_window',return_value=True), \
             patch.object(driver,'_read_security_popup_is_https',return_value=True), \
             patch.object(driver,'_address_focused_state',return_value=False):
            driver._verify_messenger_surface(snap)
        bridge.snapshot.assert_called_once_with(max_depth=30)


if __name__ == '__main__': unittest.main()
