import unittest
from pet.apps import incomplete_open_kind, launch_name, requested_app, suggest_installed_app


class OpenPronounTests(unittest.TestCase):
    def test_polite_tao_tui_prefixes_and_suffixes(self):
        for phrase in ('Mở KiCad cho tao', 'Mày mở KiCad cho tao đi',
                       'Mở cho tao KiCad', 'Mày mở phần mềm KiCad giúp tao nhé',
                       'Mở Zalo cho tui', 'Tao muốn mày mở KiCad'):
            with self.subTest(phrase=phrase):
                expected = 'zalo' if 'Zalo' in phrase else 'kicad'
                self.assertEqual(launch_name(phrase), expected)

    def test_transcribed_app_name_matches_existing_phonetic_catalog(self):
        for phrase in ('Mở Keycard cho tao', 'Mày mở KitKat cho tao đi'):
            with self.subTest(phrase=phrase):
                result = suggest_installed_app(phrase,[{'name':'KiCad'},{'name':'Zalo'}],
                                               apps=[],shortcuts=(),app_paths=[])
                self.assertIsNotNone(result)
                self.assertEqual(result.entry['name'],'KiCad')
                self.assertTrue(result.automatic)

    def test_exact_alias_and_ambiguous_or_compound_stay_safe(self):
        entries = [{'name':'KiCad','aliases':['Keycard']},{'name':'Zalo'}]
        self.assertEqual(requested_app('Mày mở Keycard cho tao',entries)['name'],'KiCad')
        for text in ('Đừng mở KiCad cho tao', 'Mở KiCad rồi xóa tệp cho tao',
                     'Mày có biết KiCad không?', 'Mở KiCad và đóng Zalo cho tao'):
            with self.subTest(text=text):
                self.assertIsNone(launch_name(text))
        both = suggest_installed_app('Mở Keycard cho tao',
                    [{'name':'KiCad'},{'name':'Keycard'}],apps=[],shortcuts=(),app_paths=[])
        self.assertIsNone(both)

    def test_missing_target_is_clarified_not_guessed(self):
        for phrase in ('Mày mở ứng dụng cho tao', 'Mở cho tao phần mềm',
                       'Mở app giúp tui nhé'):
            with self.subTest(phrase=phrase):
                self.assertEqual(incomplete_open_kind(phrase),'app')
        self.assertEqual(incomplete_open_kind('Mày mở thư mục cho tao'),'folder')


if __name__ == '__main__':
    unittest.main()
