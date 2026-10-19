import threading
import time
import unittest
from unittest.mock import MagicMock
import numpy as np
from pet.app_actions import Action, ActionResult, parse_action, AppActions, artist_matches
from pet.config import load_config
from pet.controller import Controller
from pet.audio import Utterance


class ActionTests(unittest.TestCase):
    def test_music_commands_and_preserve_names(self):
        cases = {
            'Hãy mở nhạc': Action('Spotify', 'play'),
            'Mở nhạc giúp tôi': Action('Spotify', 'play'),
            'Bật nhạc lên': Action('Spotify', 'play'),
            'Cho tôi nghe nhạc': Action('Spotify', 'play'),
            'Tạm dừng nhạc trên Spotify': Action('Spotify', 'pause'),
            'Chuyển bài tiếp theo': Action('Spotify', 'next'),
            'Quay lại bài trước': Action('Spotify', 'previous'),
            'Phát bài Lạc Trôi của Sơn Tùng M-TP trên Spotify': Action('Spotify', 'song', 'Lạc Trôi', 'Sơn Tùng M-TP'),
            'Hãy mở cho tôi bài Tiểu Thuyết Tình Yêu 2026': Action('Spotify', 'song', 'Tiểu Thuyết Tình Yêu 2026'),
            'Mở bài Thiên Lý ơi trong Spotify cho tôi.': Action('Spotify', 'song', 'Thiên Lý ơi'),
        }
        for question, expected in cases.items():
            with self.subTest(question=question):
                self.assertEqual(parse_action(question), expected)

    def test_contact_names_and_context(self):
        for question in ['Mở tin nhắn với Nguyễn Văn An trên Zalo',
                         'Hãy mở cho tôi cuộc trò chuyện của Nguyễn Văn An',
                         'Tìm và mở Nguyễn Văn An trong Zalo']:
            self.assertEqual(parse_action(question), Action('Zalo', 'chat', 'Nguyễn Văn An'))
        self.assertEqual(parse_action('Tìm My Documents', 'Zalo'), Action('Zalo', 'chat', 'My Documents'))
        self.assertIsNone(parse_action('Hãy mở ad tụi cạch cho tôi', 'Zalo'))
        self.assertIsNone(parse_action('Mở ứng dụng lạ', 'Zalo'))
        self.assertIsNone(parse_action('Tìm My Documents', 'Spotify'))
        self.assertEqual(parse_action('Vào tin nhắn'), Action('Zalo', 'ask_contact'))

    def test_artist_matching_does_not_accept_partial_words(self):
        self.assertTrue(artist_matches('Freaky', 'Freaky, Hành Or, Pinny'))
        self.assertFalse(artist_matches('An', 'Anh Tú'))
        self.assertTrue(artist_matches('Sơn Tùng', 'Sơn Tùng M-TP'))

    def test_no_command_from_negation_explanation_or_compound_request(self):
        for question in ['Đừng mở nhạc', 'Cách phát nhạc', 'Không mở tin nhắn với An',
                         'Mở tin nhắn với An rồi gửi xin chào', 'Mở nhạc rồi xóa file',
                         'Tôi đang nghe nhạc', 'Gửi tin nhắn cho An']:
            self.assertIsNone(parse_action(question), question)

    def test_cancel_does_not_start_worker(self):
        cancelled = threading.Event(); cancelled.set()
        result = AppActions(load_config()).execute(Action('Spotify', 'play'), cancelled)
        self.assertFalse(result.verified)

    def test_voice_action_records_and_speaks_verified_result_once(self):
        cfg = load_config(); engine = Controller(cfg)
        engine.request_plan = MagicMock(return_value=True)
        engine.chat = MagicMock(); engine.speaker = MagicMock(); engine.app_actions = MagicMock()
        result = 'Mình đã mở cuộc trò chuyện với My Documents trên Zalo.'
        engine.app_actions.execute.return_value = ActionResult(result, True, .1)
        def stream(question, cancelled):
            self.assertIn('Mở tin nhắn với My Documents trên Zalo', question)
            self.assertIn(result, question)
            engine.chat.on_submitted()
            yield 'Model paraphrase must not override the checked result.'
        engine.chat.stream.side_effect = stream
        engine._answer('Mở tin nhắn với My Documents trên Zalo', Utterance(np.zeros(480), time.monotonic()), 0)
        engine.app_actions.execute.assert_called_once()
        self.assertEqual(engine.last_app, 'Zalo')
        self.assertEqual(engine.speaker.speak.call_args.args[0], result)
        self.assertEqual(engine.speaker.speak.call_count, 1)

    def test_busy_chat_blocks_action(self):
        engine = Controller(load_config()); engine.chat = MagicMock(); engine.app_actions = MagicMock()
        engine.chat.check_ready.side_effect = RuntimeError('busy')
        with self.assertRaisesRegex(RuntimeError, 'busy'):
            engine._answer('Mở nhạc', Utterance(np.zeros(480), time.monotonic()), 0)
        engine.app_actions.execute.assert_not_called()

    def followup_engine(self, app):
        engine = Controller(load_config())
        engine.request_plan = MagicMock(return_value=True)
        engine.chat = MagicMock(); engine.speaker = MagicMock(); engine.app_actions = MagicMock()
        engine.chat.stream.return_value = iter(())
        engine.app_actions.execute.return_value = ActionResult('Đã kiểm tra.', True)
        engine.last_app, engine.last_app_at = app, time.monotonic()
        return engine

    def test_artist_reply_reuses_requested_song(self):
        engine = self.followup_engine('Spotify')
        engine.pending_song = Action('Spotify', 'song', 'Thiên Lý Ơi')
        engine._answer('Của Jack', Utterance(np.zeros(480), time.monotonic()), 0)
        self.assertEqual(engine.app_actions.execute.call_args.args[0],
                         Action('Spotify', 'song', 'Thiên Lý Ơi', 'Jack'))

    def test_new_command_overrides_pending_artist(self):
        engine = self.followup_engine('Spotify')
        engine.pending_song = Action('Spotify', 'song', 'Thiên Lý Ơi')
        engine._answer('Tạm dừng nhạc', Utterance(np.zeros(480), time.monotonic()), 0)
        self.assertEqual(engine.app_actions.execute.call_args.args[0], Action('Spotify', 'pause'))

    def test_contact_followup_accepts_name_and_expires(self):
        engine = self.followup_engine('Zalo'); engine.awaiting_contact = True
        engine._answer('My Documents', Utterance(np.zeros(480), time.monotonic()), 0)
        self.assertEqual(engine.app_actions.execute.call_args.args[0], Action('Zalo', 'chat', 'My Documents'))
        engine.app_actions.reset_mock(); engine.awaiting_contact = True; engine.last_app_at = 0
        engine._answer('My Documents', Utterance(np.zeros(480), time.monotonic()), 0)
        engine.app_actions.execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
