import unittest
from pet.app_actions import Action, parse_action


class ZaloCommandTests(unittest.TestCase):
    def test_contact_names_are_preserved_without_instruction_words(self):
        commands = [
            'Mở Đại ca trong Zalo cho tôi',
            'Tìm tên Đại ca trên Zalo',
            'Tìm kiếm Đại ca trong Zalo',
            'Tìm kiếm liên hệ tên Đại ca trên ứng dụng Zalo',
            'Tìm người tên Đại ca trong Zalo',
            'Mở cuộc trò chuyện với Đại ca',
            'Hãy tìm giúp tôi Đại ca trong Zalo',
            'Tìm Đại ca giúp tôi trên Zalo',
            'Mở Zalo rồi tìm Đại ca cho tôi',
            'Vào Zalo tìm tên Đại ca',
            'Vào ứng dụng Zalo và tìm kiếm Đại ca',
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(parse_action(command), Action('Zalo', 'chat', 'Đại ca'))

    def test_contextual_search(self):
        for command in ('Tìm My Documents', 'Tìm kiếm My Documents', 'Tìm tên My Documents'):
            with self.subTest(command=command):
                self.assertEqual(parse_action(command, 'Zalo'), Action('Zalo', 'chat', 'My Documents'))

    def test_missing_name_asks_locally(self):
        for command in ('Tìm liên hệ trong Zalo', 'Mở tin nhắn Zalo', 'Tìm tên trên Zalo', 'Tìm tên'):
            with self.subTest(command=command):
                self.assertEqual(parse_action(command, 'Zalo'), Action('Zalo', 'ask_contact'))

    def test_unrelated_and_compound_actions_not_treated_as_contact(self):
        for command in ('Tìm KiCad', 'Tìm thời tiết trên Google', 'Mở Notion',
                        'Đừng tìm Đại ca trên Zalo', 'Mở Zalo rồi tìm Đại ca rồi gọi',
                        'Tìm Đại ca trên Zalo và gửi tin', 'Tìm Đại ca trên Zalo và xóa tin'):
            with self.subTest(command=command):
                self.assertNotEqual(getattr(parse_action(command), 'app', None), 'Zalo')
        for command in ('Tìm ứng dụng KiCad', 'Tìm thư mục HỌC TẬP', 'Tìm thời tiết trên Google'):
            with self.subTest(command=command):
                self.assertNotEqual(getattr(parse_action(command, 'Zalo'), 'app', None), 'Zalo')


if __name__ == '__main__':
    unittest.main()
