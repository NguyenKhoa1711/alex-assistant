from __future__ import annotations
import threading
import time
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
import numpy as np
from pet.audio import Utterance
from pet.config import load_config
from pet.controller import Controller
from pet.mobile import MobileJob


class ControllerTests(unittest.TestCase):
    def make_engine(self) -> Controller:
        engine = Controller(load_config())
        engine.chat = MagicMock()
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
            self.assertIn('công cụ tệp/Git của Bionic', question)
            self.assertIn('MCP Windows Desktop Plan chỉ dành cho thao tác giao diện', question)
            self.assertIn('AGENTS.md', question)
            self.assertLess(len(question), 350)
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


if __name__ == '__main__':
    unittest.main()
