import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
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
            'Tìm kiếm nhạc Lạc Trôi': Action('Spotify', 'song', 'Lạc Trôi'),
            'Tìm bài hát Thiên Lý Ơi và phát luôn': Action('Spotify', 'song', 'Thiên Lý Ơi'),
            'Kiếm bài Nơi Này Có Anh rồi phát cho tôi': Action('Spotify', 'song', 'Nơi Này Có Anh'),
            'Tìm nhạc của Sơn Tùng M-TP': Action('Spotify', 'song', 'Sơn Tùng M-TP'),
            'Bật nhạc chill dễ ngủ': Action('Spotify', 'song', 'chill dễ ngủ'),
            'Tìm và phát Lạc Trôi của Sơn Tùng': Action('Spotify', 'song', 'Lạc Trôi', 'Sơn Tùng'),
            'Dừng nhạc đang chạy': Action('Spotify', 'pause'),
            'Dừng nhạc đang phát cho tôi': Action('Spotify', 'pause'),
            'Tắt nhạc đang chạy': Action('Spotify', 'pause'),
            'Tạm dừng bài hát đang chạy': Action('Spotify', 'pause'),
            'Dừng phát nhạc': Action('Spotify', 'pause'),
            'Dừng nhạc vừa kiếm': Action('Spotify', 'pause'),
            'Tìm nhạc Lạc Trôi trên YouTube': Action('YouTube', 'song', 'Lạc Trôi'),
            'Mở nhạc Lạc Trôi trên YouTube': Action('YouTube', 'song', 'Lạc Trôi'),
            'Mở nhạc Nơi Này Có Anh trên YouTube cho tôi': Action('YouTube', 'song', 'Nơi Này Có Anh'),
            'Phát bài Thiên Lý Ơi của Jack trên YouTube': Action('YouTube', 'song', 'Thiên Lý Ơi', 'Jack'),
            'Hãy mở Thiên Lý Ơi trên YouTube cho tôi': Action('YouTube', 'song', 'Thiên Lý Ơi'),
            'Mở YouTube phát bài Nơi Này Có Anh': Action('YouTube', 'song', 'Nơi Này Có Anh'),
            'Mở YouTube phát Nơi Này Có Anh': Action('YouTube', 'song', 'Nơi Này Có Anh'),
            'Mở MV Lạc Trôi của Sơn Tùng': Action('YouTube', 'song', 'Lạc Trôi', 'Sơn Tùng'),
            'Mở video Tiểu Thuyết Tình Yêu': Action('YouTube', 'song', 'Tiểu Thuyết Tình Yêu'),
            'Dừng nhạc đang chạy trên YouTube': Action('YouTube', 'pause'),
            'Tạm dừng YouTube': Action('YouTube', 'pause'),
        }
        for question, expected in cases.items():
            with self.subTest(question=question):
                self.assertEqual(parse_action(question), expected)

    def test_search_music_routes_to_app_actions_instead_of_google_web_search(self):
        engine = self.followup_engine('Spotify')
        engine._answer('Tìm kiếm nhạc Lạc Trôi rồi phát', Utterance(np.zeros(480), time.monotonic()), 0)
        self.assertEqual(engine.app_actions.execute.call_args.args[0], Action('Spotify', 'song', 'Lạc Trôi'))
        engine.app_actions.reset_mock()
        engine._answer('Tìm bài Thiên Lý Ơi trên YouTube', Utterance(np.zeros(480), time.monotonic()), 0)
        self.assertEqual(engine.app_actions.execute.call_args.args[0], Action('YouTube', 'song', 'Thiên Lý Ơi'))
        self.assertEqual(engine.last_app, 'YouTube')

    def test_open_named_music_on_youtube_reaches_action_worker(self):
        engine = self.followup_engine('')
        engine._answer('Mở nhạc Lạc Trôi trên YouTube', Utterance(np.zeros(480), time.monotonic()), 0)
        engine.app_actions.execute.assert_called_once_with(Action('YouTube', 'song', 'Lạc Trôi'), engine.cancelled)

    def test_workers_use_alex_runtime_even_when_external_mcp_is_missing(self):
        for action, worker in [
            (Action('YouTube', 'song', 'Lạc Trôi'), 'app_action_worker.py'),
            (Action('Spotify', 'play'), 'app_action_worker.py'),
            (Action('Zalo', 'chat', 'Test Contact'), 'app_action_worker.py'),
            (Action('Volume', 'up', '10'), 'device_action_worker.py'),
        ]:
            with self.subTest(action=action), \
                 patch('pet.app_actions.ROOT', Path('C:/Alex')), \
                 patch.object(Path, 'is_file', return_value=True), \
                 patch('pet.app_actions.subprocess.Popen') as popen:
                process = popen.return_value
                process.communicate.return_value = ('{"message":"ok","verified":true}', '')
                process.returncode = 0
                process.poll.return_value = 0
                result = AppActions({'computer': {'command': 'C:/missing-mcp/Scripts/windows-mcp.exe'}}).execute(action, threading.Event())
                self.assertEqual(popen.call_args.args[0], [str(Path('C:/Alex/.venv/Scripts/python.exe')), str(Path('C:/Alex') / worker)])
                self.assertTrue(result.verified)

    def test_missing_alex_runtime_does_not_start_external_mcp(self):
        with patch.object(Path, 'is_file', return_value=False), \
             patch('pet.app_actions.subprocess.Popen') as popen:
            with self.assertRaisesRegex(RuntimeError, 'Chưa có bộ điều khiển'):
                AppActions({}).execute(Action('YouTube', 'song', 'Lạc Trôi'), threading.Event())
        popen.assert_not_called()

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
        engine.chat = engine.gemini_chat = MagicMock(); engine.speaker = MagicMock(); engine.app_actions = MagicMock()
        result = 'Mình đã mở cuộc trò chuyện với My Documents trên Zalo.'
        engine.app_actions.execute.return_value = ActionResult(result, True, .1)
        engine._answer('Mở tin nhắn với My Documents trên Zalo', Utterance(np.zeros(480), time.monotonic()), 0)
        engine.app_actions.execute.assert_called_once()
        engine.chat.stream.assert_not_called()
        self.assertEqual(engine.last_app, 'Zalo')
        self.assertEqual(engine.speaker.speak.call_args.args[0], result)
        self.assertEqual(engine.speaker.speak.call_count, 1)

    def test_busy_chat_does_not_block_direct_action(self):
        engine = Controller(load_config()); engine.chat = engine.gemini_chat = MagicMock(); engine.app_actions = MagicMock(); engine.speaker = MagicMock()
        engine.chat.check_ready.side_effect = RuntimeError('busy')
        engine.app_actions.execute.return_value = ActionResult('Đang phát nhạc.', True)
        self.assertEqual(engine._answer('Mở nhạc', Utterance(np.zeros(480), time.monotonic()), 0), 'Đang phát nhạc.')
        engine.app_actions.execute.assert_called_once()
        engine.chat.check_ready.assert_not_called()
        engine.chat.stream.assert_not_called()

    def followup_engine(self, app):
        engine = Controller(load_config())
        engine.request_plan = MagicMock(return_value=True)
        engine.chat = engine.gemini_chat = MagicMock(); engine.speaker = MagicMock(); engine.app_actions = MagicMock()
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

    def test_youtube_context_handles_search_and_bare_open_like_spotify(self):
        from unittest.mock import patch
        from pet.apps import LaunchResult
        engine = self.followup_engine('')
        with patch('pet.controller.open_web', return_value=LaunchResult('YouTube', True, True, .1, 'web')):
            engine._answer('Hãy mở YouTube cho tôi', Utterance(np.zeros(480), time.monotonic()), 0)
        self.assertEqual(engine.last_app, 'YouTube')

        for spoken, expected in [
            ('Tìm kiếm Tiểu Thuyết Tình Yêu cho tôi', Action('YouTube', 'song', 'Tiểu Thuyết Tình Yêu')),
            ('Tìm Thiên Lý Ơi cho tôi', Action('YouTube', 'song', 'Thiên Lý Ơi')),
            ('Mở Thiên Lý Ơi', Action('YouTube', 'song', 'Thiên Lý Ơi')),
            ('Hãy mở Thiết Lý Ơi của Jack cho tôi', Action('YouTube', 'song', 'Thiết Lý Ơi', 'Jack')),
            ('Mở bài Lạc Trôi', Action('YouTube', 'song', 'Lạc Trôi')),
            ('Tạm dừng nhạc', Action('YouTube', 'pause')),
        ]:
            with self.subTest(spoken=spoken):
                engine.app_actions.reset_mock()
                engine._answer(spoken, Utterance(np.zeros(480), time.monotonic()), 0)
                self.assertEqual(engine.app_actions.execute.call_args.args[0], expected)


if __name__ == '__main__':
    unittest.main()
