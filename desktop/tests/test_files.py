from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from pet.files import find_paths, open_path, requested_file


class FileNavigationTests(unittest.TestCase):
    def test_explicit_folder_and_file_requests_only(self) -> None:
        self.assertEqual(requested_file('Mở thư mục HỌC TẬP cho tôi'), ('folder', 'hoc tap'))
        self.assertEqual(requested_file('Mở file README.md trong Explorer'), ('file', 'readme.md'))
        self.assertIsNone(requested_file('Mở Minecraft'))
        self.assertIsNone(requested_file('Mở file README rồi xóa'))

    def test_exact_name_and_ambiguity(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'one').mkdir(); (root / 'two').mkdir()
            (root / 'one' / 'notes.txt').write_text('1')
            (root / 'two' / 'notes.txt').write_text('2')
            found = find_paths('notes.txt', 'file', [root])
            self.assertEqual(len(found), 2)
            self.assertEqual(find_paths('notes.txt trong thư mục one', 'file', [root]),
                             [root / 'one' / 'notes.txt'])
            self.assertEqual(find_paths('missing', 'file', [root]), [])

    def test_file_is_revealed_not_executed(self) -> None:
        with TemporaryDirectory() as temp:
            file = Path(temp) / 'setup.exe'
            file.write_bytes(b'test')
            with patch('pet.files.subprocess.Popen') as launch:
                self.assertTrue(open_path(file))
            args = launch.call_args.args[0]
            self.assertEqual(args[0:2], ['explorer.exe', '/select,'])
            self.assertEqual(args[2], str(file))

    def test_folder_uses_windows_shell(self) -> None:
        with TemporaryDirectory() as temp:
            with patch('pet.files.os.startfile') as launch, \
                 patch('pet.files._explorer_window_for', return_value=123), \
                 patch('pet.files.focus_window') as focus:
                self.assertTrue(open_path(Path(temp)))
            launch.assert_called_once_with(temp)
            focus.assert_called_once_with(123)


if __name__ == '__main__':
    unittest.main()
