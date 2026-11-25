import unittest
from pet.message_intent import classify_message_request, extract_partial_message, merge_message_followup


class MessageRecipientNamesTests(unittest.TestCase):
    def test_accented_names_are_preserved(self):
        for name in ('Nguyễn Mây', 'Nguyễn Thị Nở', 'Mây', 'Nở', 'Nguyễn Minh', 'Minh'):
            with self.subTest(name=name):
                partial = extract_partial_message(f'gửi tin nhắn cho {name} trên Zalo')
                self.assertEqual(partial.get('recipient'), name)
                parsed = classify_message_request(f'nhắn tin cho {name} trên Zalo nội dung xin chào')
                self.assertEqual(parsed.intent.recipient, name)

    def test_pronouns_and_misheard_followups_do_not_become_recipient(self):
        for name in ('nó', 'mày', 'tao', 'mình', 'ta', 'nó máy gọi truyền may mình'):
            with self.subTest(name=name):
                partial = extract_partial_message(f'gửi tin nhắn cho {name} trên Zalo')
                self.assertNotIn('recipient', partial)
                parsed = classify_message_request(f'nhắn tin cho {name} trên Zalo nội dung xin chào')
                self.assertTrue(parsed.recognized)
                self.assertIsNone(parsed.intent)
                status, pending = merge_message_followup({'service': 'Zalo', 'content': 'xin chào'}, name)
                self.assertEqual(status, 'ask')
                self.assertNotIn('recipient', pending)


if __name__ == '__main__':
    unittest.main()
