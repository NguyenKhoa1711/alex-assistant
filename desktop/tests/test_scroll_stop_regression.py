"""Stop must win over queued scroll work; all OS input and speech are mocked."""
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from pet.audio import Utterance
from pet.config import load_config
from pet.controller import Controller, split_compound_commands
from pet.web_scroll import WebScroller


class ScrollStopRegressionTests(unittest.TestCase):
    def make_engine(self):
        engine = Controller(load_config())
        engine.paused.clear()
        engine.chat = engine.gemini_chat = MagicMock()
        engine.speaker = MagicMock()
        engine._desktop_speak = False
        return engine

    def test_negation_is_not_discarded_as_filler(self):
        for phrase in ('Thôi, lướt web', 'Không, lướt web', 'Khoan, lướt web'):
            with self.subTest(phrase=phrase):
                self.assertNotEqual(split_compound_commands(phrase), ['lướt web'])

    def test_stop_wins_over_conflicting_compound_restart(self):
        engine = self.make_engine()
        scroller = engine.web_scroller
        utterance = Utterance(np.zeros(100), time.monotonic())
        with patch.object(scroller, '_find_scroll_target', return_value=12345), \
             patch.object(scroller, '_focus_and_position_cursor'), \
             patch.object(scroller, '_send_wheel_tick', return_value=True), \
             patch('pet.controller.open_web') as open_web:
            self.addCleanup(scroller.stop)
            scroller.start()
            with patch.object(scroller, 'start', wraps=scroller.start) as start:
                reply = engine._answer('Dừng và mở TikTok rồi lướt web', utterance, .1)
                self.assertEqual(reply, 'Đã dừng.')
                self.assertFalse(scroller.is_active())
                start.assert_not_called()
            open_web.assert_not_called()
            engine.chat.stream.assert_not_called()

    def test_stop_clears_opening_context_and_stays_stopped_until_new_request(self):
        engine = self.make_engine()
        scroller = engine.web_scroller
        utterance = Utterance(np.zeros(100), time.monotonic())
        with patch.object(scroller, '_find_scroll_target', return_value=12345), \
             patch.object(scroller, '_focus_and_position_cursor'), \
             patch.object(scroller, '_send_wheel_tick', return_value=True) as tick:
            self.addCleanup(scroller.stop)
            scroller.start()
            engine.opening_contexts['desktop'].remember('app', awaiting=True)
            reply = engine._answer('Thôi', utterance, .1)
            self.assertEqual(reply, 'Đã dừng.')
            self.assertFalse(engine.opening_contexts['desktop'].awaiting)
            ticks = tick.call_count
            time.sleep(.35)
            self.assertEqual(tick.call_count, ticks)
            engine._answer('Tiếp tục lướt web', utterance, .1)
            self.assertTrue(scroller.is_active())
            engine.chat.stream.assert_not_called()

    def test_old_worker_cannot_restart_or_stop_replacement_worker(self):
        scroller = WebScroller(interval_seconds=.02)
        old_entered, release_old, new_entered = (threading.Event() for _ in range(3))
        old_calls = []

        def tick(hwnd, direction):
            if direction == 'down':
                old_calls.append(1)
                old_entered.set()
                release_old.wait(3)
            else:
                new_entered.set()
            return True

        with patch.object(scroller, '_find_scroll_target', return_value=12345), \
             patch.object(scroller, '_focus_and_position_cursor'), \
             patch.object(scroller, '_send_wheel_tick', side_effect=tick):
            try:
                scroller.start('down')
                self.assertTrue(old_entered.wait(1))
                old_thread = scroller._thread
                scroller.start('up')
                self.assertTrue(new_entered.wait(1))
                release_old.set()
                old_thread.join(1)
                self.assertFalse(old_thread.is_alive())
                self.assertEqual(len(old_calls), 1)
                self.assertTrue(scroller.is_active())
            finally:
                release_old.set()
                scroller.stop()

    def test_stop_cancels_start_waiting_for_browser(self):
        scroller = WebScroller()
        locating, release_target = threading.Event(), threading.Event()

        def find_target():
            locating.set()
            release_target.wait(3)
            return 12345

        with patch.object(scroller, '_find_scroll_target', side_effect=find_target), \
             patch.object(scroller, '_focus_and_position_cursor') as focus, \
             patch.object(scroller, '_send_wheel_tick', return_value=True) as tick:
            starter = threading.Thread(target=scroller.start)
            try:
                starter.start()
                self.assertTrue(locating.wait(1))
                scroller.stop()
                release_target.set()
                starter.join(1)
                self.assertFalse(starter.is_alive())
                self.assertFalse(scroller.is_active())
                focus.assert_not_called()
                tick.assert_not_called()
            finally:
                release_target.set()
                starter.join(1)
                scroller.stop()


if __name__ == '__main__':
    unittest.main()
