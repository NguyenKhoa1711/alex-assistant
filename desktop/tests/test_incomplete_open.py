import json
import threading
import time
import unittest
from unittest.mock import MagicMock, patch
import numpy as np
from pet.apps import incomplete_open_kind
from pet.audio import Utterance
from pet.config import load_config
from pet.controller import Controller
from pet.audio_jobs import AudioJob as MobileJob

class IncompleteOpenTests(unittest.TestCase):

    def engine(self):
        cfg = load_config()
        cfg['privacy']['save_transcripts'] = False
        cfg['learning']['enabled'] = False
        engine = Controller(cfg)
        engine.chat = engine.gemini_chat = MagicMock()
        engine.chat.check_ready.side_effect = AssertionError('Bionic must not be contacted')
        engine.chat.stream.side_effect = AssertionError('Bionic must not be contacted')
        engine.speaker = MagicMock()
        return engine

    def test_incomplete_variants(self):
        for value in ('Mở ứng dụng', 'Mở phần mềm', 'mở app', 'Mở ứng dụng dụng.', 'Bạn hãy mở ứng dụng cho tôi nhé.', 'Hãy mở phần mềm mềm cho mình', 'Mở', 'Mở app app cho tôi', 'Mở cho tôi ứng dụng'):
            with self.subTest(value=value):
                self.assertEqual(incomplete_open_kind(value), 'app')
        for value in ('Mở thư mục', 'Mở thư mục mục cho tôi.', 'Bạn mở thư mục giúp mình nhé'):
            self.assertEqual(incomplete_open_kind(value), 'folder')

    def test_complete_negative_and_conversational_requests_are_not_intercepted(self):
        for value in ('Mở KiCad cho tôi', 'Mở ứng dụng Dụng', 'Mở thư mục HỌC TẬP', 'Mở phần mềm quản lý', 'Đừng mở ứng dụng', 'Không mở app', 'Mở ứng dụng rồi xóa dữ liệu', 'Mở ứng dụng và đóng nó', 'Làm sao để mở ứng dụng?', 'Tôi đang mở app', 'Mở thư mục "mục"', 'Mở app\ncho tôi'):
            if value == 'Mở ứng dụng Dụng':
                self.assertEqual(incomplete_open_kind(value), 'app')
            else:
                with self.subTest(value=value):
                    self.assertIsNone(incomplete_open_kind(value))

    def test_truncated_command_never_contacts_bionic_or_launches(self):
        engine = self.engine()
        engine.pending_app = {'name': 'KiCad'}
        engine.pending_app_at = time.monotonic()
        engine.awaiting_contact = True
        with patch('pet.controller.requested_system_app', side_effect=AssertionError('No lookup')), patch('pet.controller.open_registered_app', side_effect=AssertionError('No launch')), patch('pet.controller.find_paths', side_effect=AssertionError('No search')), self.assertLogs(level='INFO') as logs:
            answer = engine._answer('Mở ứng dụng dụng.', Utterance(np.zeros(100), time.monotonic()), 0.1)
        self.assertIn('Bạn muốn mở ứng dụng nào', answer)
        engine.chat.check_ready.assert_not_called()
        engine.chat.stream.assert_not_called()
        engine.speaker.speak.assert_called_once()
        self.assertIsNone(engine.pending_app)
        self.assertFalse(engine.awaiting_contact)
        record = json.loads(next((line.split('VOICE_TRACE ', 1)[1] for line in logs.output if 'VOICE_TRACE ' in line)))
        self.assertEqual(record['reason'], 'missing_target')
        self.assertNotIn('text', record)
        self.assertNotIn('Mở ứng dụng dụng', '\n'.join(logs.output))

    def test_phone_clarification_renders_on_phone_without_bionic(self):
        engine = self.engine()
        engine.speaker.render_pcm.return_value = (24000, b'\x00\x00' * 10)
        job = MobileJob(np.zeros(100, dtype=np.float32))
        answer = engine._answer('Mở thư mục', Utterance(job.samples, time.monotonic()), 0.1, job)
        self.assertIn('thư mục nào', answer)
        self.assertEqual(job.sample_rate, 24000)
        self.assertEqual(len(job.audio), 20)
        engine.speaker.speak.assert_not_called()
        engine.chat.stream.assert_not_called()

    def test_cancelled_or_failed_tts_does_not_fall_back_to_llm(self):
        for cancelled in (True, False):
            engine = self.engine()
            if cancelled:
                engine.cancelled.set()
            else:
                engine.speaker.speak.side_effect = RuntimeError('No output device')
            with patch('pet.controller.logging.exception'):
                self.assertIn('ứng dụng nào', engine._answer('Mở app', Utterance(np.zeros(100), time.monotonic()), 0.1))
            engine.chat.stream.assert_not_called()
if __name__ == '__main__':
    unittest.main()
