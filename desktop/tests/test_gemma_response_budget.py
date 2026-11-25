import unittest
from pet.gemma import _adjust_chat_response_budget


class GemmaResponseBudgetTests(unittest.TestCase):
    def test_explanation_and_example_have_room(self):
        for question in ('Giải thích vì sao cần chia hàm.', 'Cho tao một ví dụ.',
                         'Phân tích hai lựa chọn này.', 'Hướng dẫn tao làm bài tập.'):
            with self.subTest(question=question):
                payload = {'max_tokens': 256}
                _adjust_chat_response_budget(payload, question)
                self.assertEqual(payload['max_tokens'], 512)

    def test_short_chat_or_explicit_short_request_stays_fast(self):
        for question in ('Chào Alex!', 'Giải thích ngắn gọn cho tao nhé.',
                         'Trả lời ngắn và cho tao ví dụ.'):
            with self.subTest(question=question):
                payload = {'max_tokens': 256}
                _adjust_chat_response_budget(payload, question)
                self.assertEqual(payload['max_tokens'], 256)

    def test_tool_turn_and_larger_config_are_not_changed(self):
        payload = {'max_tokens': 256, 'tools': []}
        _adjust_chat_response_budget(payload, 'Giải thích và mở Notepad')
        self.assertEqual(payload['max_tokens'], 256)
        payload = {'max_tokens': 768}
        _adjust_chat_response_budget(payload, 'Giải thích')
        self.assertEqual(payload['max_tokens'], 768)

    def test_reminder_is_single_and_does_not_discard_question(self):
        payload = {'max_tokens': 256, 'messages': [{'role': 'user', 'content': 'Giải thích giúp tao'}]}
        _adjust_chat_response_budget(payload, 'Giải thích giúp tao')
        _adjust_chat_response_budget(payload, 'Giải thích giúp tao')
        self.assertTrue(payload['messages'][0]['content'].startswith('Giải thích giúp tao'))
        self.assertEqual(payload['messages'][0]['content'].count('kết thúc trọn câu'), 1)

    def test_invalid_input_is_left_alone(self):
        for tokens in (None, True, 0, '256'):
            payload = {'max_tokens': tokens}
            _adjust_chat_response_budget(payload, 'Giải thích')
            self.assertEqual(payload['max_tokens'], tokens)
