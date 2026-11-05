from __future__ import annotations
from datetime import datetime
import threading
import time
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
import numpy as np
from pet.audio import Utterance
from pet.config import load_config
from pet.controller import Controller, format_laptop_clock
from pet.mobile import MobileJob


class ControllerTests(unittest.TestCase):
    def test_desktop_text_can_stream_without_synthesizing_voice(self) -> None:
        engine = self.make_engine()
        engine._desktop_speak = False
        engine.chat.stream.return_value = iter(['Chào ', 'bạn.'])
        answer = engine._answer('Xin chào', Utterance(np.zeros(0), time.monotonic()), 0)
        self.assertEqual(answer, 'Chào bạn.')
        engine.speaker.speak.assert_not_called()
        engine.speaker.render_pcm.assert_not_called()

    def test_desktop_silent_action_reports_result_without_voice(self) -> None:
        engine = self.make_engine()
        engine._desktop_speak = False
        self.assertTrue(engine._speak_action_result('Đã kiểm tra.',
            Utterance(np.zeros(0), time.monotonic()), 0, None))
        engine.speaker.speak.assert_not_called()
        engine.speaker.render_pcm.assert_not_called()

    def make_engine(self) -> Controller:
        engine = Controller(load_config())
        engine.chat = engine.gemini_chat = MagicMock()
        engine.chat.first_token_seconds = .1
        engine.speaker = MagicMock()
        return engine

    def test_audio_starts_before_model_finishes(self) -> None:
        engine = self.make_engine()
        played = threading.Event()
        def stream(question: str, cancelled: threading.Event):
            yield 'Mình là Alex. '
            self.assertTrue(played.wait(2), 'Playback waited for full response')
            yield 'Chào bạn.'
        def speak(text: str, cancelled: threading.Event, on_play):
            self.assertNotIn('Alex', text)
            on_play(.02)
            played.set()
        engine.chat.stream.side_effect = stream
        engine.speaker.speak.side_effect = speak
        engine._answer('Xin chào', Utterance(np.zeros(100), time.monotonic()), .1)
        self.assertEqual(engine.speaker.speak.call_count, 2)

    def test_regular_chat_does_not_send_computer_instructions(self) -> None:
        engine = self.make_engine()
        engine.computer_enabled = True
        engine.chat.stream.return_value = iter(['Mình khỏe, cảm ơn bạn.'])
        engine._answer('Bạn khỏe không?', Utterance(np.zeros(100), time.monotonic()), .1)
        prompt = engine.chat.stream.call_args.args[0]
        self.assertNotIn('MCP Windows Desktop', prompt)
        self.assertNotIn('công cụ tệp/Git', prompt)
        self.assertLess(len(prompt), 120)

    def test_player_failure_cancels_generation(self) -> None:
        engine = self.make_engine()
        def stream(question: str, cancelled: threading.Event):
            yield 'Xin chào.'
            self.assertTrue(cancelled.wait(2))
        engine.chat.stream.side_effect = stream
        engine.speaker.speak.side_effect = RuntimeError('Output device unavailable')
        with self.assertRaisesRegex(RuntimeError, 'Output device'):
            engine._answer('Xin chào', Utterance(np.zeros(100), time.monotonic()), .1)
        self.assertTrue(engine.failed.is_set())

    def test_model_error_exits_player(self) -> None:
        engine = self.make_engine()
        engine.chat.stream.side_effect = RuntimeError('Model offline')
        with self.assertRaisesRegex(RuntimeError, 'Model offline'):
            engine._answer('Xin chào', Utterance(np.zeros(100), time.monotonic()), .1)
        self.assertTrue(engine.failed.is_set())
        self.assertTrue(engine.cancelled.is_set())

    def test_phone_answer_routes_selected_voice_audio_to_phone(self) -> None:
        engine = self.make_engine()
        engine.chat.stream.return_value = iter(['Chào bạn.'])
        engine.speaker.render_pcm.return_value = (48000, b'\x01\x00' * 100)
        job = MobileJob(np.zeros(1600, dtype=np.float32))
        answer = engine._answer('Xin chào', Utterance(job.samples, time.monotonic()), .1, job)
        self.assertEqual(answer, 'Chào bạn.')
        self.assertEqual(job.sample_rate, 48000)
        self.assertEqual(job.audio, b'\x01\x00' * 100)
        engine.speaker.speak.assert_not_called()

    def test_voice_coding_uses_project_file_tools(self) -> None:
        engine = self.make_engine()
        engine.computer_enabled = True
        def stream(question: str, cancelled: threading.Event):
            self.assertIn('Sửa mã nguồn Python', question)
            self.assertIn('Dùng công cụ Alex được cấp', question)
            self.assertIn('lập kế hoạch', question)
            yield 'Mình sẽ kiểm tra dự án.'
        engine.chat.stream.side_effect = stream
        engine._answer('Sửa mã nguồn Python', Utterance(np.zeros(100), time.monotonic()), .1)

    def test_folder_request_opens_explorer_before_chat_reply(self) -> None:
        engine = self.make_engine()
        engine.chat.stream.return_value = iter([])
        folder = Path('D:/HỌC TẬP')
        with patch('pet.controller.find_paths', return_value=[folder]), \
             patch('pet.controller.open_path', return_value=True) as opened, \
             patch.object(engine, '_speak_action_result', return_value=True):
            engine._answer('Mở thư mục HỌC TẬP',
                           Utterance(np.zeros(100), time.monotonic()), .1)
        opened.assert_called_once_with(folder)
        prompt = engine.chat.stream.call_args.args[0]
        self.assertIn('Kết quả pet đã kiểm tra', prompt)
        self.assertIn('File Explorer', prompt)

    def test_project_request_allows_on_demand_web_research(self) -> None:
        engine = self.make_engine()
        def stream(question: str, cancelled: threading.Event):
            self.assertIn('người dùng đã yêu cầu tra cứu hoặc làm project', question)
            self.assertIn('ưu tiên tài liệu chính thức', question)
            yield 'Mình sẽ làm project.'
        engine.chat.stream.side_effect = stream
        engine._answer('Hãy làm project học từ vựng', Utterance(np.zeros(100), time.monotonic()), .1)

    def test_clock_queries_read_laptop_clock_instead_of_bangkok_timezone(self) -> None:
        sample_now = datetime(2026, 10, 24, 15, 4, 0)
        for phrase in ('Bây giờ là mấy giờ rồi?', 'Mấy giờ rồi?', 'Xem giờ trên laptop cho tôi'):
            text = format_laptop_clock(phrase, now=sample_now)
            self.assertIsNotNone(text)
            self.assertIn('15 giờ 04 phút', text)
            self.assertIn('thứ Bảy ngày 24 tháng 10 năm 2026', text)
            self.assertNotIn('Bangkok', text)
        date_text = format_laptop_clock('Hôm nay là thứ mấy?', now=sample_now)
        self.assertIsNotNone(date_text)
        self.assertIn('thứ Bảy', date_text)
        self.assertIsNone(format_laptop_clock('Bây giờ ở Tokyo là mấy giờ?', now=sample_now))

        engine = self.make_engine()
        answer = engine._answer('Bây giờ là mấy giờ rồi?',
                                Utterance(np.zeros(100), time.monotonic()), .1)
        self.assertIn('Theo đồng hồ trên laptop', answer)
        self.assertNotIn('Bangkok', answer)
        engine.chat.stream.assert_not_called()

    def test_compound_voice_commands_execute_both_tasks(self) -> None:
        from pet.apps import LaunchResult
        from pet.app_actions import ActionResult
        for phrase in (
            'Vâng, hãy mở TikTok và loop web cho tôi đi.',
            'Bạn hãy mở TikTok và Look Web cho tôi đi.',
            'Mở TikTok cho tôi lướt web cho tôi đi.',
            'Mở TikTok và lướt web cho tôi.',
        ):
            with self.subTest(phrase=phrase):
                engine = self.make_engine()
                with patch('pet.controller.open_web',
                           return_value=LaunchResult('TikTok', True, True, 0.1, 'web')) as web_mock, \
                     patch.object(engine.web_scroller, '_find_scroll_target', return_value=12345), \
                     patch.object(engine.web_scroller, 'start',
                                  return_value=ActionResult('Đã bật chế độ tự động.', True, 0.05)) as scroll_mock:
                    reply = engine._answer(phrase, Utterance(np.zeros(100), time.monotonic()), .1)
                web_mock.assert_called_once_with('https://www.tiktok.com', 'TikTok')
                scroll_mock.assert_called_once_with('down')
                self.assertIn('TikTok', reply)
                self.assertIn('Đã bật chế độ tự động.', reply)
                engine.chat.stream.assert_not_called()

    def test_active_web_scroll_stops_after_compound_open_and_scroll(self) -> None:
        from pet.apps import LaunchResult

        for phrase in ('Dừng', 'Thôi', 'Dừng lướt web đi', 'Ngừng lướt TikTok lại đi'):
            with self.subTest(phrase=phrase):
                engine = self.make_engine()
                scroller = engine.web_scroller
                try:
                    with patch('pet.controller.open_web',
                               return_value=LaunchResult('TikTok', True, True, 0.1, 'web')), \
                         patch.object(scroller, '_find_scroll_target', return_value=12345), \
                         patch.object(scroller, '_focus_and_position_cursor'), \
                         patch.object(scroller, '_send_wheel_tick', return_value=True):
                        engine._answer('Mở TikTok và lướt web cho tôi',
                                       Utterance(np.zeros(100), time.monotonic()), .1)
                        self.assertTrue(scroller.is_active())

                        reply = engine._answer(phrase,
                                               Utterance(np.zeros(100), time.monotonic()), .1)

                    self.assertEqual(reply, 'Đã dừng.')
                    self.assertFalse(scroller.is_active())
                    engine.chat.stream.assert_not_called()
                finally:
                    scroller.stop()

    def test_interrupt_stops_active_web_scroll(self) -> None:
        engine = self.make_engine()
        scroller = engine.web_scroller
        with patch.object(scroller, '_find_scroll_target', return_value=12345), \
             patch.object(scroller, '_focus_and_position_cursor'), \
             patch.object(scroller, '_send_wheel_tick', return_value=True), \
             patch.object(engine.local_chat, 'cancel'), \
             patch.object(engine.gemini_chat, 'cancel'):
            scroller.start()
            self.assertTrue(scroller.is_active())

            engine.interrupt()

        self.assertFalse(scroller.is_active())


if __name__ == '__main__':
    unittest.main()
