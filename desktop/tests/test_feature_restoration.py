import time
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from pet.app_actions import Action, ActionResult
from pet.audio import Utterance
from pet.config import load_config
from pet.controller import Controller
from pet.llm import LocalChat
from pet.web_research import SearchResult
from pet.web_scroll import WebScroller, parse_web_scroll_request


class FeatureRestorationTests(unittest.TestCase):
    def make_engine(self):
        cfg = load_config()
        cfg['learning']['enabled'] = False
        cfg['computer']['enabled'] = True
        cfg['apps']['enabled'] = False
        cfg['files']['enabled'] = False
        cfg['bionic']['use_ui_bridge'] = False
        engine = Controller(cfg)
        engine.paused.clear()
        engine.local_chat = MagicMock(spec=LocalChat)
        engine.chat = engine.gemini_chat = MagicMock()
        engine.chat.computer_for_turn = False
        engine.chat.stream.return_value = iter(['Câu trả lời tại máy.'])
        engine.speaker = MagicMock()
        engine._desktop_speak = False
        engine.app_actions = MagicMock()
        engine.app_actions.execute.return_value = ActionResult('Đã thực hiện.', True)
        return engine

    def say(self, engine, text):
        return engine._answer(text, Utterance(np.zeros(0), time.monotonic()), 0)

    def test_explicit_research_uses_search_results_and_local_model(self):
        engine = self.make_engine()
        results = [SearchResult('Tài liệu mẫu', 'Python là ngôn ngữ lập trình.', 'https://example.org')]
        with patch('pet.controller.search_web', return_value=results) as search:
            self.assertEqual(self.say(engine, 'Giải thích Python là gì?'), 'Câu trả lời tại máy.')
        search.assert_called_once()
        self.assertIn('Python là ngôn ngữ lập trình.', engine.chat.stream.call_args.args[0])

    def test_coding_request_reaches_file_tools(self):
        engine = self.make_engine()
        self.say(engine, 'Sửa mã nguồn Python trong dự án')
        engine.chat.stream.assert_called_once()
        self.assertTrue(engine.chat.computer_for_turn)
        self.assertIn('Dùng công cụ Alex được cấp', engine.chat.stream.call_args.args[0])

    def test_regular_chat_stays_local(self):
        engine = self.make_engine()
        self.assertEqual(self.say(engine, 'Bạn khỏe không?'), 'Câu trả lời tại máy.')
        engine.chat.stream.assert_called_once()
        self.assertFalse(engine.chat.computer_for_turn)

    def test_disabled_computer_tools_stay_disabled(self):
        engine = self.make_engine()
        engine.computer_enabled = False
        self.say(engine, 'Sửa mã nguồn Python')
        self.assertFalse(engine.chat.computer_for_turn)

    def test_music_does_not_require_language_model(self):
        engine = self.make_engine()
        engine.chat.check_ready.side_effect = RuntimeError('model offline')
        self.assertEqual(self.say(engine, 'Mở nhạc Lạc Trôi trên YouTube'), 'Đã thực hiện.')
        engine.app_actions.execute.assert_called_once_with(
            Action('YouTube', 'song', 'Lạc Trôi'), engine.cancelled)
        engine.chat.check_ready.assert_not_called()
        engine.chat.stream.assert_not_called()

    def test_repeated_sleep_never_rearms_itself_after_long_idle(self):
        engine = self.make_engine()
        with patch('pet.controller.execute_power') as power, \
             patch('pet.controller.resolve_power_action', side_effect=lambda value: value):
            self.say(engine, 'Tắt máy')
            engine.paused.clear()
            engine._last_sleep_at = time.monotonic() - 600
            for _ in range(3):
                self.assertEqual(self.say(engine, 'Tắt máy'), '')
            power.assert_called_once_with('sleep')

    def test_source_alias_for_youtube_scroll_is_retained(self):
        self.assertEqual(parse_web_scroll_request('Lướt du túp'), 'start_down')

    def test_configured_gentle_step_is_not_accelerated_for_short_video_titles(self):
        scroller = WebScroller(step_wheel=16, interval_seconds=.26)
        user = MagicMock()
        with patch('pet.web_scroll.ctypes.WinDLL', return_value=user), \
             patch.object(scroller, '_focus_and_position_cursor'), \
             patch.object(scroller, '_window_title', return_value='tiktok - chrome', create=True):
            self.assertTrue(scroller._send_wheel_tick(123, 'down'))
        self.assertEqual(user.mouse_event.call_args.args[3].value, (-16) & 0xFFFFFFFF)


if __name__ == '__main__':
    unittest.main()
