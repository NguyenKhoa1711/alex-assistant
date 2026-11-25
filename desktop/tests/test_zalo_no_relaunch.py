import unittest
from unittest.mock import MagicMock, patch
from app_action_worker import Ui
from pet.messaging_driver import ZaloUiDriver


class ZaloExistingWindowTests(unittest.TestCase):
    def test_bind_existing_window_without_launching(self):
        entry={'name':'Zalo'}
        with patch('app_action_worker.load_config', return_value={'apps':{'entries':[entry]}}), \
             patch('app_action_worker.app_windows',return_value=[42]), \
             patch('app_action_worker.open_registered_app') as launch, \
             patch('app_action_worker.enable_accessibility_hwnd') as enable, \
             patch('app_action_worker.auto.ControlFromHandle',return_value='root'):
            ui=Ui('Zalo',existing_hwnd=42)
        self.assertEqual((ui.hwnd,ui.root),(42,'root'))
        launch.assert_not_called()
        enable.assert_called_once_with(42)

    def test_rejects_missing_or_wrong_window_without_launching(self):
        entry={'name':'Zalo'}
        with patch('app_action_worker.load_config',return_value={'apps':{'entries':[entry]}}), \
             patch('app_action_worker.app_windows',return_value=[43]), \
             patch('app_action_worker.open_registered_app') as launch:
            with self.assertRaises(RuntimeError):Ui('Zalo',existing_hwnd=42)
        launch.assert_not_called()

    def test_current_conversation_binds_existing_handle(self):
        driver=ZaloUiDriver();driver.hwnd=42;driver._chosen_row_aid='friend-item-1'
        window=MagicMock(hwnd=42)
        fake_ui=MagicMock();fake_ui.root='root'
        with patch('pet.messaging_driver.current_window',return_value=window), \
             patch('app_action_worker.Ui',return_value=fake_ui) as ui, \
             patch('app_action_worker.zalo_find',return_value='header'), \
             patch('app_action_worker.texts',return_value=['Mẫu']):
            conversation=driver.current_conversation()
        ui.assert_called_once_with('Zalo',existing_hwnd=42)
        self.assertEqual(conversation.name,'Mẫu')
