import os
import threading
import time
import unittest
from unittest.mock import MagicMock, patch
import numpy as np
from pet.app_actions import Action, ActionResult, AppActions, parse_action
from pet.audio import Utterance
from pet.config import load_config
from pet.controller import Controller
from pet.window_state import change_window_state


class ParsingTests(unittest.TestCase):
    def test_vietnamese_commands(self):
        for text, operation in {
            'Phóng to cửa sổ hiện tại': 'maximize',
            'Alex ơi hãy phóng to cửa sổ này cho tôi': 'maximize',
            'Bạn phóng to phần mềm hiện tại lên': 'maximize',
            'Mở rộng cửa sổ đang dùng': 'maximize',
            'Thu nhỏ cửa sổ hiện tại': 'minimize',
            'Bạn hãy thu nhỏ ứng dụng này giúp mình nhé': 'minimize',
            'Thu nhỏ cửa sổ xuống thanh tác vụ': 'minimize',
            'Ẩn xuống cửa sổ này': 'minimize',
            'Khôi phục cửa sổ': 'restore',
            'Đưa cửa sổ hiện tại về kích thước bình thường': 'restore',
            'Thu nhỏ cửa sổ này về kích thước ban đầu': 'restore',
        }.items():
            self.assertEqual(parse_action(text), Action('Window', operation), text)

    def test_short_commands_and_real_browser_request(self):
        for text, action in {
            'Phóng to': Action('Window', 'maximize'),
            'Thu nhỏ': Action('Window', 'minimize'),
            'Thu nhỏ cho tôi': Action('Window', 'minimize'),
            'Alex ơi, phóng to cửa sổ này giúp tôi với': Action('Window', 'maximize'),
            'Bạn có thể thu nhỏ cửa sổ hiện tại cho tôi được không?': Action('Window', 'minimize'),
            'Thu nhỏ trang web hiện tại cho tôi.': Action('Window', 'minimize', 'browser'),
            'Hãy phóng to trang web hiện tại cho tôi.': Action('Window', 'maximize', 'browser'),
            'Phóng to trình duyệt đang xem': Action('Window', 'maximize', 'browser'),
            'Phòng tác của sự hiện đại cho tôi.': Action('Window', 'maximize'),
        }.items():
            self.assertEqual(parse_action(text), action, text)

    def test_conversation_negations_and_other_targets_do_not_resize(self):
        for text in ['Đừng phóng to cửa sổ', 'Không thu nhỏ cửa sổ hiện tại',
                     'Cách phóng to cửa sổ', 'Tôi đang thu nhỏ cửa sổ',
                     'Phóng to tất cả cửa sổ', 'Phóng to cửa sổ rồi đóng Chrome',
                     'Phóng to cửa sổ và thu nhỏ ứng dụng', 'Phóng to chữ',
                     'Thu nhỏ tab', 'Phóng to ảnh này', 'Thu nhỏ cửa sổ 50 phần trăm',
                     'Phóng to trang web 120%', 'Thu nhỏ chữ trên trang web',
                     'Không thu nhỏ', 'Cách thu nhỏ', 'Phóng to và thu nhỏ',
                     'Thu nhỏ rồi mở Chrome', 'Mình không muốn thu nhỏ',
                     'Phóng to ảnh trong trình duyệt',
                     'Không phòng tác của sự hiện đại cho tôi',
                     'Tôi nói phòng tác của sự hiện đại cho tôi',
                     'Phòng tác của sự hiện đại cho tôi rồi đóng ứng dụng']:
            self.assertIsNone(parse_action(text), text)
        self.assertEqual(parse_action('Đóng tab hiện tại'), Action('Tabs', 'close_current'))
        self.assertEqual(parse_action('Đóng phần mềm hiện tại'), Action('Window', 'close_current'))


class ExecutionTests(unittest.TestCase):
    def api(self):
        api = MagicMock()
        api.foreground.return_value = 10
        api.identity.return_value = (10, os.getpid() + 10000, 'C:/example.exe', 'AppWindow')
        api.visible.return_value = api.enabled.return_value = api.supports.return_value = True
        api.show.return_value = True
        return api

    def test_actions_once_and_verified_on_same_window(self):
        for operation in ('maximize', 'minimize', 'restore'):
            api = self.api()
            api.state.side_effect = ['restore' if operation != 'restore' else 'maximize', operation]
            result = change_window_state(operation, threading.Event(), api)
            self.assertTrue(result.verified)
            api.show.assert_called_once_with(10, operation)
            api.post_close.assert_not_called()

    def test_focus_change_before_dispatch_does_not_touch_next_window(self):
        api = self.api(); api.foreground.side_effect = [10, 20]
        self.assertFalse(change_window_state('minimize', threading.Event(), api).verified)
        api.show.assert_not_called()

    def test_identity_change_is_rejected(self):
        api = self.api(); api.identity.side_effect = [api.identity.return_value, None]
        self.assertFalse(change_window_state('maximize', threading.Event(), api).verified)
        api.show.assert_not_called()

    def test_protected_or_disabled_windows_are_not_touched(self):
        for cls in ('Progman', 'WorkerW', 'Shell_TrayWnd', '#32770'):
            api = self.api(); api.identity.return_value = (10, 12345, 'C:/x.exe', cls)
            self.assertFalse(change_window_state('minimize', threading.Event(), api).verified)
            api.show.assert_not_called()
        for field in ('visible', 'enabled', 'supports'):
            api = self.api(); getattr(api, field).return_value = False
            self.assertFalse(change_window_state('maximize', threading.Event(), api).verified)
            api.show.assert_not_called()

    def test_cancel_and_idempotence(self):
        api = self.api(); cancel = threading.Event(); cancel.set()
        self.assertFalse(change_window_state('maximize', cancel, api).verified)
        api.foreground.assert_not_called()
        cancel.clear(); api.state.return_value = 'maximize'
        self.assertTrue(change_window_state('maximize', cancel, api).verified)
        api.show.assert_not_called()

    def test_no_false_success_or_retry(self):
        api = self.api(); api.state.return_value = 'restore'
        cancel = MagicMock(); cancel.is_set.return_value = cancel.wait.return_value = False
        self.assertFalse(change_window_state('maximize', cancel, api).verified)
        api.show.assert_called_once()
        api = self.api(); api.state.return_value = 'restore'; api.show.return_value = False
        self.assertFalse(change_window_state('maximize', threading.Event(), api).verified)

    def test_no_worker_or_global_shortcuts(self):
        cancel = threading.Event()
        with patch('pet.window_state.change_window_state', return_value=ActionResult('OK', True)) as change, \
                patch('pet.app_actions.subprocess.Popen') as worker:
            self.assertTrue(AppActions({}).execute(Action('Window', 'maximize'), cancel).verified)
            change.assert_called_once_with('maximize', cancel)
            worker.assert_not_called()

    def test_browser_request_never_changes_an_unrelated_foreground_app(self):
        api = self.api()
        self.assertFalse(change_window_state('minimize', threading.Event(), api, browser_only=True).verified)
        api.show.assert_not_called()
        api.identity.return_value = (10, os.getpid() + 10000, 'C:/Chrome/chrome.exe', 'Chrome_WidgetWin_1')
        api.state.side_effect = ['restore', 'minimize']
        self.assertTrue(change_window_state('minimize', threading.Event(), api, browser_only=True).verified)
        api.show.assert_called_once_with(10, 'minimize')
        with patch('pet.window_state.change_window_state', return_value=ActionResult('OK', True)) as change:
            event = threading.Event()
            AppActions({}).execute(parse_action('Thu nhỏ trang web hiện tại cho tôi.'), event)
            change.assert_called_once_with('minimize', event, browser_only=True)


class RouterTests(unittest.TestCase):
    def engine(self):
        cfg = load_config(); cfg['learning']['enabled'] = False
        cfg['privacy']['save_transcripts'] = False
        engine = Controller(cfg)
        engine.chat = engine.gemini_chat = MagicMock(); engine.app_actions = MagicMock()
        engine._speak_action_result = MagicMock()
        engine.app_actions.execute.return_value = ActionResult('Đã chỉnh.', True)
        return engine

    def test_local_and_duplicate_minimize_not_sent_to_next_window(self):
        engine = self.engine()
        for _ in range(2):
            with self.assertLogs(level='INFO') as logs:
                engine._answer('Thu nhỏ cửa sổ hiện tại', Utterance(np.zeros(100), time.monotonic()), .1)
            self.assertNotIn('"text"', '\n'.join(logs.output))
        engine.app_actions.execute.assert_called_once()
        engine.chat.check_ready.assert_not_called(); engine.chat.stream.assert_not_called()

    def test_disabled_and_different_followup(self):
        engine = self.engine(); utterance = Utterance(np.zeros(100), time.monotonic())
        engine.cfg['actions']['enabled'] = False
        engine._answer('Phóng to cửa sổ', utterance, .1)
        engine.app_actions.execute.assert_not_called()
        engine.cfg['actions']['enabled'] = True
        engine._answer('Phóng to cửa sổ', utterance, .1)
        engine._answer('Khôi phục cửa sổ', utterance, .1)
        self.assertEqual(engine.app_actions.execute.call_count, 2)

    def test_window_command_clears_unfinished_open_question(self):
        engine = self.engine()
        engine.opening_contexts['desktop'].remember('app', awaiting=True)
        engine._answer('Phóng to cửa sổ hiện tại', Utterance(np.zeros(100), time.monotonic()), .1)
        self.assertEqual(engine.app_actions.execute.call_args.args[0], Action('Window', 'maximize'))
        engine.chat.stream.assert_not_called()

    def test_real_spoken_browser_request_is_local(self):
        engine = self.engine()
        engine._answer('Thu nhỏ trang web hiện tại cho tôi.', Utterance(np.zeros(100), time.monotonic()), .1)
        self.assertEqual(engine.app_actions.execute.call_args.args[0], Action('Window', 'minimize', 'browser'))
        engine.chat.check_ready.assert_not_called(); engine.chat.stream.assert_not_called()

    def test_user_confirmed_stt_correction_bypasses_bionic(self):
        engine = self.engine()
        engine._answer('Phòng tác của sự hiện đại cho tôi.', Utterance(np.zeros(100), time.monotonic()), .1)
        self.assertEqual(engine.app_actions.execute.call_args.args[0], Action('Window', 'maximize'))
        engine.chat.check_ready.assert_not_called(); engine.chat.stream.assert_not_called()


if __name__ == '__main__':
    unittest.main()
