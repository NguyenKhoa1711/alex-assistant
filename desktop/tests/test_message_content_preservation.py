import unittest
from pet.message_intent import parse_send_intent, extract_partial_message, merge_message_followup


class MessageContentPreservationTests(unittest.TestCase):
    def test_full_requests_keep_punctuation_and_unicode(self):
        for question in (
            'Nhắn tin cho Minh trên Zalo nội dung Xin chào nhé! 😊',
            'Gửi cho Minh qua Messenger tin nhắn là Xin chào nhé! 😊',
            'Nhắn tin cho Minh trên Zalo nội dung Xin chào nhé!',
            'Nhắn tin cho Minh trên Zalo nội dung là Xin chào nhé!',
            'Gửi cho Minh qua Messenger tin nhắn nội dung là Xin chào nhé!',
            'Nhắn tin cho Minh nội dung là Xin chào nhé! qua Messenger',
            'Gửi cho Minh qua Messenger tin nhắn là Xin chào nhé!',
        ):
            with self.subTest(question=question):
                result = parse_send_intent(question)
                self.assertIsNotNone(result)
                self.assertEqual(result.content, 'Xin chào nhé! 😊' if question.endswith('😊') else 'Xin chào nhé!')

    def test_followup_preserves_trailing_punctuation(self):
        result = extract_partial_message('nội dung là Gặp lại sau nhé!')
        self.assertEqual(result.get('content'), 'Gặp lại sau nhé!')
        action, merged = merge_message_followup({'service': 'Zalo', 'recipient': 'Minh'},
                                                'nội dung là Gặp lại sau nhé!')
        self.assertEqual(action, 'execute')
        self.assertEqual(merged['content'], 'Gặp lại sau nhé!')

    def test_quoted_content_and_recipient_are_not_changed(self):
        result = parse_send_intent('Nhắn tin cho Nguyễn Minh trên Messenger là “Cảm ơn mày!”')
        self.assertEqual(result.recipient, 'Nguyễn Minh')
        self.assertEqual(result.content, 'Cảm ơn mày!')
