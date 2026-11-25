import unittest
from unittest.mock import MagicMock, patch

from pet.agent_bridge import AgentBridgeError, AgentDesktopBridge
from pet.messaging_driver import ZaloUiDriver, _zalo_search_node


def snapshot(ref='@s1:e1', x=10, duplicate=False):
    field = {'native_id': {'kind': 'uia', 'value': 'contact-search-input'},
             'ref_id': ref, 'available_actions': ['SetValue'],
             'bounds': {'x': x, 'y': 10, 'width': 200, 'height': 30}}
    return {'tree': {'children': [field, dict(field)] if duplicate else [field]}}


class SearchBridgeTests(unittest.TestCase):
    def test_requires_exact_authorization_and_current_reference(self):
        bridge = object.__new__(AgentDesktopBridge)
        bridge.action_uncertain = False
        bridge.refs = {'@s1:e1'}
        bridge.identity_ok = lambda: True
        bridge.authorize = lambda op, ref, text: (op, ref, text) == ('search', '@s1:e1', 'Truyền File')
        bridge._call = MagicMock(return_value={'ok': True})
        for ref, text in (('@s1:e2', 'Truyền File'), ('@s1:e1', 'khác')):
            with self.assertRaises(AgentBridgeError):
                bridge.set_value_for_search(ref, text)
        bridge._call.assert_not_called()
        bridge.set_value_for_search('@s1:e1', 'Truyền File')
        bridge._call.assert_called_once_with(['set-value', '@s1:e1', '--stdin'], text='Truyền File', action=True)

    def test_locator_refuses_duplicates(self):
        self.assertIsNone(_zalo_search_node(snapshot(duplicate=True)))

    def test_driver_resolves_again_and_verifies_value(self):
        driver = ZaloUiDriver()
        bridge = MagicMock()
        bridge.snapshot.side_effect = [snapshot(), snapshot('@s1:e2'), snapshot('@s1:e3')]
        bridge.get_value.return_value = {'ok': True, 'data': {'value': 'Truyền File'}}
        def set_value(ref, value):
            self.assertEqual(driver._authorized_search, (ref, value))
            return {'ok': True}
        bridge.set_value_for_search.side_effect = set_value
        area = MagicMock()
        area.IsOffscreen = False
        area.AutomationId = ''
        area.ControlTypeName = 'PaneControl'
        area.GetChildren.return_value = []
        with patch.object(driver, '_ensure_bridge', return_value=bridge), \
             patch('app_action_worker.Ui'), patch('app_action_worker.zalo_find', return_value=area), \
             patch('pet.messaging_driver.time.sleep'):
            candidates, complete = driver.search_contacts('Truyền File')
        self.assertEqual((candidates, complete), ([], True))
        self.assertIsNone(driver._authorized_search)
        bridge.set_value_for_search.assert_called_once()
        bridge.press_key.assert_not_called()

    def test_changed_target_or_incorrect_value_stops(self):
        for after, value in ((snapshot('@s1:e2', x=11), 'Truyền File'),
                             (snapshot('@s1:e2'), 'khác')):
            driver = ZaloUiDriver()
            bridge = MagicMock()
            bridge.snapshot.side_effect = [snapshot(), after]
            bridge.set_value_for_search.return_value = {'ok': True}
            bridge.get_value.return_value = {'ok': True, 'data': {'value': value}}
            with patch.object(driver, '_ensure_bridge', return_value=bridge), patch('app_action_worker.Ui'):
                self.assertEqual(driver.search_contacts('Truyền File'), ([], False))
            bridge.set_value_for_search.assert_called_once()
            bridge.press_key.assert_not_called()


if __name__ == '__main__':
    unittest.main()
