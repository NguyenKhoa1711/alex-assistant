from __future__ import annotations
from contextlib import ExitStack
import time
import unicodedata
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse
import numpy as np
from pet.apps import LaunchResult, open_web, requested_web
from pet.app_actions import parse_action
from pet.audio import Utterance
from pet.config import load_config
from pet.controller import Controller
from pet.audio_jobs import AudioJob as MobileJob
from pet.web_search import parse_web_search

class GoogleSearchTests(unittest.TestCase):

    def assert_query(self, phrase, expected, last_app=''):
        target = requested_web(phrase, last_app=last_app)
        self.assertIsNotNone(target, phrase)
        parsed = urlparse(target[0])
        self.assertEqual((parsed.scheme, parsed.netloc, parsed.path), ('https', 'www.google.com', '/search'))
        self.assertEqual(parse_qs(parsed.query), {'q': [expected]})

    def test_natural_searches_preserve_accents_and_remove_polite_words(self):
        for phrase, query in [('Mở cách học tiếng Anh trên Google cho tôi', 'cách học tiếng Anh'), ('Bạn mở Đại học Giao thông vận tải cho tôi trên Google nhé', 'Đại học Giao thông vận tải'), ('Alex ơi, bạn tìm trên Google công thức bánh flan giúp mình nhé', 'công thức bánh flan'), ('Mở Google tìm học bổng Việt Nam cho tôi', 'học bổng Việt Nam'), ('Tìm kiếm học bổng Việt Nam trên mạng', 'học bổng Việt Nam'), ('Tìm công thức nấu ăn cho tôi', 'công thức nấu ăn'), ('Tra cứu quỹ đạo hệ Mặt Trời qua Google', 'quỹ đạo hệ Mặt Trời'), ('Google giúp tôi lịch thi tiếng Anh', 'lịch thi tiếng Anh'), ('Mở vật lý và hóa học trên Google', 'vật lý và hóa học'), ('Mở cửa hàng An & Bình trên Google', 'cửa hàng An & Bình'), ('Mở C++ UTF-8 trên Google', 'C++ UTF-8'), ('Tìm YouTube trên Google', 'YouTube'), ('Mở YouTube cách nấu ăn trên Google', 'YouTube cách nấu ăn')]:
            with self.subTest(phrase=phrase):
                self.assert_query(phrase, query)
        self.assert_query(unicodedata.normalize('NFD', 'Mở điện tử trên Google'), 'điện tử')

    def test_explicit_google_overrides_music_and_contact_context(self):
        for last_app in ('Spotify', 'YouTube', 'Zalo'):
            with self.subTest(last_app=last_app):
                self.assert_query('Tìm Sơn Tùng trên Google', 'Sơn Tùng', last_app)
                self.assert_query('Mở nhạc Trịnh trên Google', 'nhạc Trịnh', last_app)
                self.assert_query('Tìm tài liệu KiCad trên Google', 'tài liệu KiCad', last_app)
        self.assertIsNone(requested_web('Tìm Đại ca', last_app='Zalo'))
        self.assertIsNotNone(parse_action('Tìm Đại ca', 'Zalo'))
        self.assertIsNone(requested_web('Mở nhạc Nàng thơ trên YouTube'))
        self.assertEqual(parse_action('Mở nhạc Nàng thơ trên YouTube').app, 'YouTube')

    def test_known_sites_and_full_links_remain_direct(self):
        sites = [{'name': 'Portal UT', 'aliases': ['trang học tập'], 'url': 'https://portal.ut.edu.vn/'}]
        for phrase, expected in [('Mở YouTube ở trong Google cho tôi', 'https://www.youtube.com'), ('Mở trang học tập trên Google', 'https://portal.ut.edu.vn/'), ('Mở https://example.org/hoc-tap?q=1&x=2 trên Google', 'https://example.org/hoc-tap?q=1&x=2'), ('Mở example.org trên Chrome', 'https://example.org')]:
            with self.subTest(phrase=phrase):
                self.assertEqual(requested_web(phrase, sites)[0], expected)

    def test_no_search_without_request_or_for_unqualified_unknown_app(self):
        for phrase in ('Đừng mở học bổng trên Google', 'Không tìm KiCad trên Google', 'Khoan mở nhà sách trên Google', 'Cách mở YouTube trên Google là gì?', 'Tôi đã tìm học bổng trên Google', 'Mở phần mềm lạ', 'Mở trang học bạ mới', 'Trả lời câu hỏi cho tôi', 'Kiểm tra laptop', 'Tôi không muốn tìm trên Google', 'Mở nhà sách trên Google rồi gửi tin nhắn', 'Tìm học bổng rồi xóa file'):
            with self.subTest(phrase=phrase):
                self.assertIsNone(requested_web(phrase))

    def make_engine(self):
        with patch('pet.llm.httpx.Client'):
            engine = Controller(load_config())
        engine.learning = None
        engine.speaker = MagicMock()
        engine._speak_action_result = MagicMock(return_value=True)
        engine.gemini_chat.stream = MagicMock(side_effect=AssertionError('Unexpected LLM turn'))
        engine.app_actions.execute = MagicMock(side_effect=AssertionError('Unexpected app action'))
        self.addCleanup(engine.gemini_chat._client.close)
        self.addCleanup(engine.local_chat._client.close)
        return engine

    def test_router_does_not_scan_disk_launch_apps_split_queries_or_call_model(self):
        for phrase in ('Mở vật lý và hóa học trên Google', 'Tìm tài liệu KiCad trên Google', 'Mở nhạc Trịnh trên Google', 'Tìm Sơn Tùng trên Google'):
            for phone in (False, True):
                with self.subTest(phrase=phrase, phone=phone), ExitStack() as stack:
                    engine = self.make_engine()
                    engine.last_app, engine.last_app_at = ('Zalo', time.monotonic())
                    engine.awaiting_contact = True
                    for name in ('find_paths', 'requested_system_app', 'requested_shortcut', 'requested_app_path', 'suggest_installed_app', 'open_registered_app'):
                        stack.enter_context(patch('pet.controller.' + name, side_effect=AssertionError('Unexpected lookup: ' + name)))
                    browser = stack.enter_context(patch('pet.controller.open_web', return_value=LaunchResult('Tìm kiếm web', True, True, 0.01, 'web')))
                    job = MobileJob(np.zeros(10, dtype=np.float32)) if phone else None
                    answer = engine._answer(phrase, Utterance(np.zeros(10), time.monotonic()), 0, job)
                    browser.assert_called_once()
                    self.assertEqual(browser.call_args.args, requested_web(phrase))
                    self.assertIn('Google', answer)
                    engine.gemini_chat.stream.assert_not_called()
                    engine._speak_action_result.assert_called_once()
                    self.assertFalse(engine.awaiting_contact)
                    self.assertEqual(engine.last_app, 'Trình duyệt')

    def test_missing_target_disabled_opening_and_cancel_do_not_launch(self):
        for phrase in ('Tìm kiếm trên Google', 'Mở Google tìm kiếm'):
            with self.subTest(phrase=phrase):
                engine = self.make_engine()
                with patch('pet.controller.open_web') as browser:
                    answer = engine._answer(phrase, Utterance(np.zeros(10), time.monotonic()), 0)
                self.assertIn('nội dung gì', answer)
                browser.assert_not_called()
        engine = self.make_engine()
        engine.cfg['apps']['enabled'] = False
        with patch('pet.controller.open_web') as browser:
            answer = engine._answer('Mở KiCad trên Google', Utterance(np.zeros(10), time.monotonic()), 0)
            browser.assert_not_called()
        self.assertIn('đang tắt', answer)
        engine.cfg['apps']['enabled'] = True
        engine.cancelled.set()
        with patch('pet.controller.open_web') as browser:
            engine._answer('Mở KiCad trên Google', Utterance(np.zeros(10), time.monotonic()), 0)
            browser.assert_not_called()

    def test_browser_dispatch_result_is_honest(self):
        target = requested_web('Mở học bổng trên Google')
        with patch('pet.apps.webbrowser.open', return_value=False) as browser:
            result = open_web(*target)
        self.assertFalse(result.verified)
        self.assertIn('chưa mở được', result.message)
        browser.assert_called_once_with(target[0])
if __name__ == '__main__':
    unittest.main()
