from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from pet.audio import Utterance
from pet.config import load_config
from pet.controller import Controller
from pet.web_scroll import WebScroller, parse_web_scroll_request


class WebScrollTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = Controller(load_config())
        self.engine.paused.clear()
        self.engine.chat = self.engine.gemini_chat = MagicMock()
        self.engine.speaker = MagicMock()
        self.utterance = Utterance(np.zeros(100), time.monotonic())

    def test_parse_web_scroll_commands(self) -> None:
        for phrase in (
            'Lướt web',
            'Lướt web cho tôi',
            'Tự lướt web',
            'Tự động lướt web',
            'Kéo xuống từ từ',
            'Cuộn xuống chậm',
            'Lướt quép cho tôi',
            'Lướt tiếp',
            'Cuộn tiếp',
            'Lướt web nhanh',
            'Lướt web bình thường',
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(parse_web_scroll_request(phrase), 'start_down')

        for phrase in ('Lướt lên', 'Cuộn lên từ từ', 'Lướt web lên'):
            with self.subTest(phrase=phrase):
                self.assertEqual(parse_web_scroll_request(phrase), 'start_up')

        for phrase in ('Lướt', 'Tự lướt'):
            with self.subTest(phrase=phrase):
                self.assertIsNone(parse_web_scroll_request(phrase))

        for phrase in ('Đã bật chế độ tự động.', 'Chế độ này vẫn đang chạy.'):
            with self.subTest(phrase=phrase):
                self.assertIsNone(parse_web_scroll_request(phrase, active=True))

        for phrase in (
            'Dừng lướt web',
            'Ngừng lướt web',
            'Không lướt web nữa',
            'Thôi không lướt nữa',
            'Dừng cuộn',
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(parse_web_scroll_request(phrase, active=False), 'stop')

        # Bare "dừng" only stops scrolling when auto-scroll is active.
        self.assertIsNone(parse_web_scroll_request('Dừng', active=False))
        self.assertEqual(parse_web_scroll_request('Dừng', active=True), 'stop')
        self.assertEqual(parse_web_scroll_request('Dừng lại', active=True), 'stop')
        self.assertEqual(parse_web_scroll_request('Thôi', active=True), 'stop')

    def test_controller_starts_and_stops_auto_scroll_by_voice(self) -> None:
        scroller = WebScroller(step_wheel=28, interval_seconds=0.05)
        self.engine.web_scroller = scroller
        with patch.object(scroller, '_find_scroll_target', return_value=12345), \
             patch.object(scroller, '_focus_and_position_cursor'), \
             patch.object(scroller, '_send_wheel_tick', return_value=True) as tick:
            start_reply = self.engine._answer('Lướt web cho tôi', self.utterance, 0.1)
            self.assertEqual(start_reply, 'Đã bật chế độ tự động.')
            self.assertIsNone(parse_web_scroll_request(start_reply, active=True))
            self.assertTrue(scroller.is_active())
            time.sleep(0.12)
            self.assertGreaterEqual(tick.call_count, 1)

            running_thread = scroller._thread
            repeated_reply = self.engine._answer(
                'Lướt web cho tôi', self.utterance, 0.1)
            self.assertEqual(repeated_reply, 'Chế độ này vẫn đang chạy.')
            self.assertIs(scroller._thread, running_thread)
            self.assertIsNone(parse_web_scroll_request(repeated_reply, active=True))

            stop_reply = self.engine._answer('Dừng', self.utterance, 0.1)
            self.assertEqual(stop_reply, 'Đã dừng.')
            self.assertIsNone(parse_web_scroll_request(stop_reply, active=False))
            self.assertFalse(scroller.is_active())
            self.engine.chat.stream.assert_not_called()

    def test_repeated_same_direction_start_does_not_restart_scroller(self) -> None:
        scroller = WebScroller(step_wheel=28, interval_seconds=0.05)
        with patch.object(scroller, '_find_scroll_target', return_value=12345) as find_target, \
             patch.object(scroller, '_focus_and_position_cursor'), \
             patch.object(scroller, '_send_wheel_tick', return_value=True):
            first = scroller.start('down')
            first_thread = scroller._thread
            second = scroller.start('down')

            self.assertTrue(first.verified)
            self.assertEqual(second.message, 'Chế độ này vẫn đang chạy.')
            self.assertIs(scroller._thread, first_thread)
            find_target.assert_called_once_with()
        scroller.stop()


if __name__ == '__main__':
    unittest.main()
