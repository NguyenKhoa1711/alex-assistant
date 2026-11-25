import unittest
from pet.message_intent import classify_message_request


class IncompleteMessageTests(unittest.TestCase):
    def test_direct_message_without_service_is_incomplete(self):
        for request in ('Gửi tin nhắn cho An', 'Mày gửi tin nhắn cho tao đi',
                        'Alex ơi, nhắn tin cho An', 'Nhắn cho An'):
            with self.subTest(request=request):
                value = classify_message_request(request)
                self.assertTrue(value.recognized)
                self.assertIsNone(value.intent)

    def test_conversation_questions_and_negations_are_not_send_commands(self):
        for request in ('Tại sao tôi không gửi tin nhắn được?',
                        'Đừng gửi tin nhắn cho An', 'Tao không muốn nhắn tin'):
            with self.subTest(request=request):
                self.assertFalse(classify_message_request(request).recognized)
