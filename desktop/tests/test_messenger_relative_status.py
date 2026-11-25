import unittest
from pet.messenger_messages import is_user_sender_hint, normalize_delivery_status


class MessengerRelativeStatusTests(unittest.TestCase):
    def test_exact_status_with_relative_time(self):
        for value in ('Đã gửi 3 giờ trước', 'Đã gửi 1 phút trước', 'Sent 2 hours ago'):
            with self.subTest(value=value):
                self.assertEqual(normalize_delivery_status(value), 'sent')

    def test_sender_attachment_and_incomplete_labels_are_not_statuses(self):
        for value in ('Đã gửi 1 ảnh', 'Bạn đã gửi 3 giờ trước', 'Đã gửi 3 giờ',
                      'Sent 2 images ago', 'Đã gửi 3 giờ trước tin nhắn'):
            with self.subTest(value=value):
                self.assertIsNone(normalize_delivery_status(value))

    def test_explicit_vietnamese_uia_sender_clause(self):
        self.assertTrue(is_user_sender_hint('Mẫu, tin nhắn do bạn gửi lúc 08:10'))
        self.assertFalse(is_user_sender_hint('Nhờ bạn gửi lúc 08:10'))
        self.assertFalse(is_user_sender_hint('Tin nhắn do An gửi lúc 08:10'))
