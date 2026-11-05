import time
import unittest
from unittest.mock import MagicMock, patch

from pet.config import load_config
from pet.controller import Controller


class RemoteWaitMenuTests(unittest.TestCase):
    def setUp(self):
        cfg = load_config()
        cfg['learning']['enabled'] = False
        cfg['power']['enabled'] = True
        cfg['power']['remote_wait_on_ac'] = True
        self.engine = Controller(cfg)
        self.engine.mic = MagicMock()
        self.engine.web_scroller = MagicMock()

    def test_clicks_queue_once_without_any_immediate_power_action(self):
        with patch.object(self.engine, 'isRunning', return_value=True), \
             patch('pet.controller.resolve_power_action', return_value='remote_wait'), \
             patch('pet.controller.execute_power') as power:
            self.engine.request_remote_wait()
            self.engine.request_remote_wait()
        self.assertEqual(self.engine._remote_wait_requests.qsize(), 1)
        power.assert_not_called()

    def test_paused_microphone_can_use_menu_and_action_is_consumed_once(self):
        self.engine.paused.set()
        self.engine._remote_wait_requests.put(time.monotonic())
        with patch('pet.controller._pc_unlocked', return_value=True), \
             patch('pet.controller.resolve_power_action', return_value='remote_wait'), \
             patch('pet.controller.execute_power') as power:
            self.assertTrue(self.engine._run_remote_wait_request())
            self.assertFalse(self.engine._run_remote_wait_request())
        power.assert_called_once_with('remote_wait')
        self.engine.mic.close.assert_called_once()
        self.assertTrue(self.engine.paused.is_set())
        self.assertTrue(self.engine._power_latched)

    def test_battery_change_never_falls_back_to_sleep(self):
        self.engine.paused.set()
        self.engine._remote_wait_requests.put(time.monotonic())
        with patch('pet.controller._pc_unlocked', return_value=True), \
             patch('pet.controller.resolve_power_action', return_value='sleep'), \
             patch('pet.controller.execute_power') as power:
            self.engine._run_remote_wait_request()
        power.assert_not_called()
        self.engine.mic.close.assert_not_called()
        self.assertTrue(self.engine.paused.is_set())

    def test_stale_or_already_locked_request_is_never_replayed(self):
        for issued, unlocked in ((time.monotonic()-10, True), (time.monotonic(), False)):
            self.engine._remote_wait_requests.put(issued)
            with patch('pet.controller._pc_unlocked', return_value=unlocked), \
                 patch('pet.controller.execute_power') as power:
                self.engine._run_remote_wait_request()
            power.assert_not_called()

    def test_busy_or_not_ready_does_not_queue_for_later(self):
        with patch.object(self.engine, 'isRunning', return_value=True):
            self.engine.busy.set()
            self.engine.request_remote_wait()
        self.assertTrue(self.engine._remote_wait_requests.empty())

    def test_failed_lock_restores_previously_active_microphone(self):
        self.engine.paused.clear()
        self.engine._remote_wait_requests.put(time.monotonic())
        with patch('pet.controller._pc_unlocked', return_value=True), \
             patch('pet.controller.resolve_power_action', return_value='remote_wait'), \
             patch('pet.controller.execute_power', side_effect=OSError('test failure')):
            self.engine._run_remote_wait_request()
        self.assertFalse(self.engine.paused.is_set())
        self.assertFalse(self.engine.busy.is_set())
        self.assertFalse(self.engine._power_latched)
        self.engine.mic.start.assert_called_once()
