import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np
from pet.dialogue import OpeningContext, natural_open
from pet.apps import LaunchResult
from pet.audio import Utterance
from pet.config import load_config
from pet.controller import Controller


class DialogueTests(unittest.TestCase):
    def test_natural_open_preserves_destination(self):
        for text, expected in [
            ('Alex ơi, bạn giúp mình mở KiCad nhé', 'mở KiCad'),
            ('Mình muốn mở thư mục HỌC TẬP nha', 'mở thư mục HỌC TẬP'),
            ('Bạn có thể mở Zalo được không?', 'mở Zalo'),
            ('Alex ơi, mở https://example.org/MyPage nhé', 'mở https://example.org/MyPage'),
        ]:
            self.assertEqual(natural_open(text), expected)

    def test_do_not_reinterpret_negations_questions_or_conversation(self):
        for text in ('Đừng mở Zalo', 'Mình không muốn mở Zalo', 'Làm sao mở Zalo?',
                     'Nếu mở Zalo thì sao?', 'Mình muốn hỏi bạn chuyện này',
                     'Alex ơi, tắt máy', 'mở\nZalo'):
            self.assertEqual(natural_open(text), text)

    def test_missing_target_followup_and_correction(self):
        c = OpeningContext()
        c.remember('folder', awaiting=True)
        self.assertEqual(c.resolve('HỌC TẬP'), ('Mở thư mục HỌC TẬP', False))
        c.remember('app')
        self.assertEqual(c.resolve('Không, ý mình là KiCad'), ('Mở KiCad', False))
        c.remember('app', awaiting=True)
        self.assertEqual(c.resolve('Mở Zalo'), ('Mở Zalo', False))

    def test_expires_and_does_not_reuse_after_topic_change(self):
        now = [100.0]
        c = OpeningContext(clock=lambda: now[0])
        c.remember('app', awaiting=True)
        now[0] += 46
        self.assertEqual(c.resolve('KiCad'), ('KiCad', False))
        c.remember('app', awaiting=True)
        self.assertEqual(c.resolve('Cảm ơn'), ('Cảm ơn', False))
        self.assertEqual(c.resolve('KiCad'), ('KiCad', False))

    def test_cancel_and_other_actions_are_not_names(self):
        for text in ('tắt máy', 'giảm âm lượng', 'xóa file', 'gửi tin nhắn', 'không biết', 'Tôi đang ăn cơm'):
            c = OpeningContext()
            c.remember('app', awaiting=True)
            self.assertEqual(c.resolve(text), (text, False))
        c.remember('app', awaiting=True)
        self.assertEqual(c.resolve('Thôi không cần'), ('Thôi không cần', True))

    def engine(self):
        cfg = load_config()
        cfg['learning']['enabled'] = False
        cfg['apps']['enabled'] = True
        cfg['apps']['entries'] = [{'name': 'KiCad', 'path': 'unused.exe'}]
        cfg['files']['enabled'] = True
        e = Controller(cfg)
        e.chat = e.gemini_chat = MagicMock()
        e.chat.stream.return_value = iter([])
        e.speaker = MagicMock()
        e._speak_action_result = MagicMock(return_value=True)
        return e

    def test_controller_missing_name_then_short_answer_launches(self):
        e = self.engine()
        utterance = Utterance(np.zeros(100), time.monotonic())
        e._answer('Mở ứng dụng', utterance, .1)
        e.chat.stream.assert_not_called()
        with patch('pet.controller.open_registered_app', return_value=LaunchResult('KiCad', True, True, .1)) as opened:
            e._answer('KiCad', utterance, .1)
        self.assertEqual(opened.call_args.args[0]['name'], 'KiCad')

    def test_controller_correction_after_open_and_negative_request(self):
        e = self.engine()
        e.cfg['apps']['entries'].append({'name': 'Zalo', 'path': 'unused2.exe'})
        utterance = Utterance(np.zeros(100), time.monotonic())
        with patch('pet.controller.open_registered_app', return_value=LaunchResult('OK', True, True, .1)) as opened:
            e._answer('Bạn có thể mở Zalo được không?', utterance, .1)
            e._answer('Không, ý mình là KiCad', utterance, .1)
        self.assertEqual([c.args[0]['name'] for c in opened.call_args_list], ['Zalo', 'KiCad'])
        self.assertFalse(e.cfg['privacy']['save_transcripts'])

    def test_controller_followup_folder_and_separate_channels(self):
        e = self.engine()
        utterance = Utterance(np.zeros(100), time.monotonic())
        e._answer('Mở thư mục', utterance, .1)
        self.assertEqual(e.opening_contexts['mobile'].resolve('HỌC TẬP'), ('HỌC TẬP', False))
        with patch('pet.controller.find_paths', return_value=[Path('D:/HỌC TẬP')]), \
             patch('pet.controller.open_path', return_value=True) as opened:
            e._answer('HỌC TẬP', utterance, .1)
        opened.assert_called_once_with(Path('D:/HỌC TẬP'))


if __name__ == '__main__':
    unittest.main()
