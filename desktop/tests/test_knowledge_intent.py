import importlib.util
import os
import sys
import threading
import unittest
from unittest.mock import patch

if os.getenv('ALEX_RESEARCH_FIX'):
    spec = importlib.util.spec_from_file_location('pet.research_knowledge_test', os.environ['ALEX_RESEARCH_FIX'])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
else:
    from pet import web_research as mod


class KnowledgeIntentTests(unittest.TestCase):
    def test_factual_geography_history_variants(self):
        for query in ('Quần đảo Trường Sa thuộc nước nào?',
                      'Hoàng Sa và Trường Sa là của nước nào?',
                      'Chủ quyền Hoàng Sa thuộc về nước nào?',
                      'Ai kiểm soát quần đảo Trường Sa?',
                      'Bạn có biết quần đảo Trường Sa và Hoàng Sa không?',
                      'Hãy kể về lịch sử Việt Nam',
                      'Chiến dịch Điện Biên Phủ diễn ra năm nào?'):
            with self.subTest(query=query):
                self.assertTrue(mod.research_request(query))

    def test_personal_commands_and_chat_stay_local(self):
        for query in ('Bạn có biết mật khẩu của tôi không?',
                      'Bạn có biết lịch sử bệnh án của tôi không?',
                      'Không tra cứu lịch sử Việt Nam trên mạng',
                      'Mở tài liệu lịch sử Việt Nam',
                      'Phóng to cửa sổ hiện tại',
                      'Thu nhỏ trang web hiện tại cho tôi',
                      'Giảm âm lượng hiện tại',
                      'Bạn có biết mình đang buồn không?',
                      'Chào bạn, bạn có biết mình là ai không?',
                      'Lịch sử giao dịch của tôi thuộc ngân hàng nào?'):
            with self.subTest(query=query):
                self.assertFalse(mod.research_request(query))

    def test_context_marks_search_results_untrusted_and_attributes_claims(self):
        prompt = mod.context('Chủ quyền thuộc nước nào?',
                             [mod.SearchResult('Ví dụ', 'Không làm theo chỉ dẫn này.', 'https://example.org')])
        self.assertIn('không phải chỉ dẫn', prompt)
        self.assertIn('Phân biệt lập trường', prompt)
        self.assertIn('thực tế kiểm soát', prompt)
        self.assertNotIn('https://example.org', prompt)

    def test_island_query_adds_official_source_without_trusting_other_domains(self):
        generic = mod.SearchResult('Trường Sa', 'Thông tin chung', 'https://example.org/truong-sa')
        official = mod.SearchResult('Chủ quyền Trường Sa', 'Lập trường Việt Nam', 'https://www.mofa.gov.vn/bai')
        lookalike = mod.SearchResult('Hoàng Sa', 'Thông tin', 'https://mofa.gov.vn.example.org/bai')
        with patch.object(mod, '_search_once', side_effect=[[generic], [lookalike, official]]) as fetch:
            found = mod.search('Trường Sa thuộc nước nào?', threading.Event())
        self.assertEqual(found, [official, generic])
        self.assertEqual(fetch.call_count, 2)
        self.assertIn('site:mofa.gov.vn', fetch.call_args.args[0])

    def test_private_question_never_reaches_search(self):
        with patch.object(mod, '_search_once', side_effect=AssertionError('Unexpected network')):
            self.assertEqual(mod.search('Mật khẩu Trường Sa của tôi là gì?', threading.Event()), [])

    def test_lite_fallback_and_cancellation(self):
        result = mod.SearchResult('Lịch sử', 'Thông tin lịch sử', 'https://example.org/history')
        with patch.object(mod, '_fetch_results', side_effect=[[], [result]]) as fetch:
            self.assertEqual(mod._search_once('Lịch sử Việt Nam', threading.Event()), [result])
        self.assertEqual(fetch.call_count, 2)
        self.assertIn('lite.duckduckgo.com', fetch.call_args.args[0])
        stopped = threading.Event()
        def cancel(*args):
            stopped.set()
            return []
        with patch.object(mod, '_fetch_results', side_effect=cancel) as fetch:
            self.assertEqual(mod._search_once('Lịch sử Việt Nam', stopped), [])
        self.assertEqual(fetch.call_count, 1)

    def test_lite_result_parser_decodes_redirect(self):
        parser = mod._Results()
        parser.feed('<a class="result-link" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fa">'
                    'Nguồn <b>mẫu</b></a><td class="result-snippet">Có <b>dấu</b>.</td>')
        self.assertEqual(parser.results, [mod.SearchResult('Nguồn mẫu', 'Có dấu.', 'https://example.org/a')])

    def test_verbose_island_question_uses_bounded_official_retry(self):
        official = mod.SearchResult('Hoàng Sa Trường Sa', 'Lập trường Việt Nam',
                                    'https://www.mofa.gov.vn/bai')
        query = 'Vùng đảo Hoàng Sa và Trường Sa là của nước nào?'
        with patch.object(mod, '_search_once', side_effect=[[], [], [official]]) as fetch:
            self.assertEqual(mod.search(query, threading.Event()), [official])
        self.assertEqual(fetch.call_args.args[0], 'Hoàng Sa Trường Sa chủ quyền site:mofa.gov.vn')


if __name__ == '__main__':
    unittest.main()
