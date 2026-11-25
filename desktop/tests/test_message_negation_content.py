import unittest
from pet.message_flow import MessageResult
from pet.message_intent import SendIntent, classify_message_request, merge_message_followup
from pet.messaging_driver import format_message_result


class MessageNegationContentTests(unittest.TestCase):
    def test_negative_words_in_message_are_not_a_cancel(self):
        cases = (
            ('Gửi tin nhắn đừng gửi ảnh cho Lan trên Zalo',
             SendIntent('Zalo', 'Lan', 'đừng gửi ảnh')),
            ('Nhắn tin cho Lan trên Messenger nội dung là đừng gửi tin nhắn đó nhé',
             SendIntent('Messenger', 'Lan', 'đừng gửi tin nhắn đó nhé')),
            ('Nhắn tin cho Lan trên Zalo nội dung là không gửi ảnh nhé.',
             SendIntent('Zalo', 'Lan', 'không gửi ảnh nhé.')),
        )
        for question, intent in cases:
            with self.subTest(question=question):
                result = classify_message_request(question)
                self.assertTrue(result.recognized)
                self.assertEqual(result.intent, intent)

    def test_cancel_before_command_is_not_a_send(self):
        for question in ('Đừng gửi tin nhắn cho Lan trên Zalo',
                         'Alex ơi, không gửi tin nhắn cho Lan trên Messenger',
                         'Tôi chưa nói xong, đừng gửi tin nhắn cho Lan trên Zalo'):
            with self.subTest(question=question):
                result = classify_message_request(question)
                self.assertIsNone(result.intent)
                self.assertFalse(result.recognized)

    def test_incomplete_command_with_negative_content_stays_in_messaging(self):
        result = classify_message_request('Gửi tin nhắn đừng gửi ảnh cho Lan')
        self.assertTrue(result.recognized)
        self.assertIsNone(result.intent)

    def test_unverified_draft_status_warns_a_draft_may_remain(self):
        result = format_message_result(SendIntent('Zalo', 'Lan', 'chào'), MessageResult('draft_unverified'))
        self.assertIn('chưa gửi', result)
        self.assertIn('còn chữ nháp', result)

    def test_labeled_followup_content_preserves_negation(self):
        pending = {'service': 'Zalo', 'recipient': 'Lan'}
        outcome, value = merge_message_followup(pending, 'Nội dung là đừng gửi ảnh nhé.')
        self.assertEqual(outcome, 'execute')
        self.assertEqual(value['content'], 'đừng gửi ảnh nhé.')

    def test_explicit_cancel_still_cancels_pending_send(self):
        pending = {'service': 'Zalo', 'recipient': 'Lan'}
        outcome, value = merge_message_followup(pending, 'Đừng gửi')
        self.assertEqual((outcome, value), ('cancel', {}))
