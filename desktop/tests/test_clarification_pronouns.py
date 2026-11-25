import unittest
from pet.action_reply import style_action_result


class ClarificationPronounsTests(unittest.TestCase):
    def test_missing_target_uses_requested_pronouns(self):
        for noun in ('ứng dụng', 'thư mục'):
            with self.subTest(noun=noun):
                self.assertEqual(
                    style_action_result(f'Bạn muốn mở {noun} nào, nói lại giúp mình nhé.'),
                    f'Mày muốn mở {noun} nào, nói lại giúp tao nhé.')

    def test_target_names_are_not_rewritten(self):
        text = 'Đã mở thư mục D:\\Bạn và mình.'
        self.assertEqual(style_action_result(text), text)


if __name__ == '__main__':
    unittest.main()
