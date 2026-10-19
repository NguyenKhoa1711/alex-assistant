import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch
import numpy as np
from pet.app_actions import Action, ActionResult, parse_action
from pet.audio import Utterance
from pet.config import load_config
from pet.controller import Controller
from pet.learning import LearningStore, Lesson, parse_lesson, resolve_target, web_requested


class LearningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cfg = load_config()
        self.path = Path(self.temp.name) / 'commands.sqlite'
        self.cfg['learning'] = {'enabled': True, 'path': str(self.path)}
        self.store = LearningStore(self.path, self.cfg['apps']['entries'])

    def engine(self):
        engine = Controller(self.cfg)
        engine.request_plan = MagicMock(return_value=True)
        engine.chat = MagicMock(); engine.speaker = MagicMock(); engine.app_actions = MagicMock()
        def stream(question, cancelled):
            if engine.chat.on_submitted:
                engine.chat.on_submitted()
            yield 'Kết quả trong Bionic.'
        engine.chat.stream.side_effect = stream
        return engine

    def answer(self, engine, text):
        engine._answer(text, Utterance(np.zeros(480), time.monotonic()), 0)

    def test_teaching_preserves_vietnamese_names(self):
        self.assertEqual(parse_lesson('Hãy nhớ khi tôi nói nhạc làm việc thì phát bài Lạc Trôi của Sơn Tùng.'),
                         Lesson('teach', 'nhạc làm việc', 'phát bài Lạc Trôi của Sơn Tùng'))
        self.assertEqual(parse_lesson('Không phải, ý tôi là mở Zalo.'), Lesson('correct', target='mở Zalo'))
        self.assertIsNone(parse_lesson('Đừng ghi nhớ khi tôi nói nhạc thì mở nhạc'))

    def test_survives_new_instance_and_matches_only_whole_phrase(self):
        self.store.put('Nhạc làm việc', Action('Spotify', 'play'))
        reopened = LearningStore(self.path, self.cfg['apps']['entries'])
        self.assertEqual(reopened.lookup('nhac lam viec.'), Action('Spotify', 'play'))
        for text in ['Đừng nhạc làm việc', 'Tôi đang nghe nhạc làm việc', 'nhạc làm việc rồi xóa file']:
            self.assertIsNone(reopened.lookup(text))

    def test_explicitly_taught_website_is_saved_and_opened(self):
        lesson = parse_lesson('Khi tôi nói trang thư viện thì mở https://library.example.edu.vn/')
        self.assertIsNotNone(lesson)
        target = resolve_target(lesson.target, self.cfg['apps']['entries'])
        self.assertEqual(target, Action('Web', 'open', 'https://library.example.edu.vn/'))
        self.store.put(lesson.phrase, target)
        engine = self.engine()
        with patch('pet.controller.open_web') as launch:
            launch.return_value.message = 'Mình đã gửi địa chỉ library.example.edu.vn tới trình duyệt.'
            launch.return_value.verified = True
            self.answer(engine, 'trang thư viện')
        launch.assert_called_once_with('https://library.example.edu.vn/', 'library.example.edu.vn')
        self.assertIn('library.example.edu.vn', engine.chat.stream.call_args.args[0])

    def test_cannot_replace_existing_command_with_different_action(self):
        with self.assertRaises(ValueError):
            self.store.put('Mở Spotify', Action('Zalo', 'launch'))
        with self.assertRaises(ValueError):
            self.store.put('Dừng lại', Action('Spotify', 'play'))

    def test_rejects_destructive_unknown_and_negated_targets(self):
        for action in [Action('Zalo', 'send', 'xin chào'), Action('PowerShell', 'launch'),
                       Action('Spotify', 'delete', 'file')]:
            with self.assertRaises(ValueError):
                self.store.put('làm việc', action)
        with self.assertRaises(ValueError):
            self.store.put('Đừng mở nhạc', Action('Spotify', 'play'))

    def test_tampered_database_does_not_execute_new_operation(self):
        self.store.put('nhạc riêng', Action('Spotify', 'play'))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE phrases SET action=?', (json.dumps({'app':'Zalo','operation':'send'}),))
        self.assertIsNone(self.store.lookup('nhạc riêng'))

    def test_counts_only_checked_results_and_forgets_exact_phrase(self):
        self.store.put('nhạc riêng', Action('Spotify', 'play'))
        self.store.record_result('nhạc riêng', False); self.store.record_result('nhạc riêng', True)
        row = self.store.rows()[0]
        self.assertEqual((row['successes'], row['failures']), (1, 1))
        self.assertFalse(self.store.forget('nhạc'))
        self.assertTrue(self.store.forget('nhạc riêng'))
        self.assertIsNone(self.store.lookup('nhạc riêng'))

    def test_teaching_does_not_execute_until_phrase_is_used(self):
        engine = self.engine()
        self.answer(engine, 'Khi tôi nói nhạc làm việc thì mở nhạc')
        engine.app_actions.execute.assert_not_called()
        self.assertEqual(self.store.rows()[0]['successes'], 0)
        fresh = self.engine()
        fresh.app_actions.execute.return_value = ActionResult('Đang phát nhạc.', True)
        self.answer(fresh, 'nhạc làm việc')
        self.assertEqual(fresh.app_actions.execute.call_args.args[0], Action('Spotify', 'play'))
        self.assertEqual(self.store.rows()[0]['successes'], 1)
        self.assertIn('nhạc làm việc', fresh.chat.stream.call_args.args[0])

    def test_busy_chat_does_not_write_lesson(self):
        engine = self.engine(); engine.chat.check_ready.side_effect = RuntimeError('busy')
        with self.assertRaisesRegex(RuntimeError, 'busy'):
            self.answer(engine, 'Khi tôi nói nhạc làm việc thì mở nhạc')
        self.assertEqual(self.store.rows(), [])

    def test_explicit_correction_is_learned_only_after_success(self):
        for verified in (False, True):
            engine = self.engine()
            engine.previous_question = 'cho nhạc làm việc'
            engine.previous_question_at = time.monotonic()
            engine.app_actions.execute.return_value = ActionResult('Đã kiểm tra.', verified)
            self.answer(engine, 'Không phải, ý tôi là mở nhạc')
            self.assertEqual(self.store.lookup('cho nhạc làm việc'), Action('Spotify', 'play') if verified else None)

    def test_expired_correction_does_not_teach_stale_phrase(self):
        engine = self.engine(); engine.previous_question = 'cho nhạc làm việc'; engine.previous_question_at = 0
        engine.app_actions.execute.return_value = ActionResult('Đang phát.', True)
        self.answer(engine, 'Ý tôi là mở nhạc')
        self.assertIsNone(self.store.lookup('cho nhạc làm việc'))

    def test_new_teaching_discards_previous_correction_context(self):
        engine = self.engine(); engine.previous_question = 'cho nhạc riêng'
        engine.previous_question_at = time.monotonic()
        self.answer(engine, 'Khi tôi nói nhạc làm việc thì mở nhạc')
        self.assertEqual(engine.previous_question, '')

    def test_disabled_app_actions_stay_disabled_for_learned_phrase(self):
        self.store.put('nhạc làm việc', Action('Spotify', 'play'))
        engine = self.engine(); engine.cfg['actions']['enabled'] = False
        self.answer(engine, 'nhạc làm việc')
        engine.app_actions.execute.assert_not_called()

    def test_generic_workflow_goes_to_bionic_planner_not_fixed_executor(self):
        engine = self.engine()
        with patch('pet.controller.open_registered_app') as launch:
            self.answer(engine, 'Khi tôi nói bảng chi phí thì mở Excel và tạo bảng chi phí')
            launch.assert_not_called(); engine.app_actions.execute.assert_not_called()
        self.assertEqual(self.store.lookup('bảng chi phí'), Action('Desktop', 'task', 'mở Excel và tạo bảng chi phí'))
        self.answer(engine, 'bảng chi phí')
        engine.app_actions.execute.assert_not_called()
        self.assertIn('Plan', engine.chat.stream.call_args.args[0])

    def test_generic_workflow_uses_computer_switch_independently(self):
        self.store.put('bảng chi phí', Action('Desktop', 'task', 'mở Excel và tạo bảng chi phí'))
        engine = self.engine()
        engine.cfg['apps']['enabled'] = False
        engine.cfg['actions']['enabled'] = False
        self.answer(engine, 'bảng chi phí')
        self.assertIn('Plan', engine.chat.stream.call_args.args[0])
        engine.computer_enabled = False
        self.answer(engine, 'bảng chi phí')
        self.assertIn('Thao tác này đang tắt', engine.chat.stream.call_args.args[0])

    def test_contextual_commands_require_context(self):
        for text, operation in [('Dừng lại', 'pause'), ('Mở tiếp', 'play'), ('Bài khác', 'next')]:
            self.assertIsNone(parse_action(text))
            self.assertEqual(parse_action(text, 'Spotify'), Action('Spotify', operation))
        self.assertEqual(parse_action('Vào trong tin nhắn'), Action('Zalo', 'ask_contact'))
        self.assertEqual(parse_action('Mở tin nhắn Zalo'), Action('Zalo', 'ask_contact'))
        self.assertEqual(parse_action('Tìm liên hệ tên Nguyễn An trên Zalo'), Action('Zalo', 'chat', 'Nguyễn An'))

    def test_web_for_explicit_or_project_request(self):
        for text in ['Tìm trên mạng cách dùng Python', 'Tra Google thời tiết hôm nay', 'Đọc https://example.com',
                     'Hãy làm cho tôi một project quản lý kho', 'Tạo dự án quản lý tài liệu',
                     'Bạn hãy xây dựng project học từ vựng']:
            self.assertTrue(web_requested(text), text)
        for text in ['Mở nhạc', 'Đừng tìm trên mạng', 'Giải thích Internet là gì', 'Tôi đang đọc trên web',
                     'Tôi đang làm project quản lý kho', 'Đừng làm project này', 'Cách làm project là gì']:
            self.assertFalse(web_requested(text), text)


if __name__ == '__main__':
    unittest.main()
