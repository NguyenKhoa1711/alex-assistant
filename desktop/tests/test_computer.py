import tempfile
from pathlib import Path
import threading
import unittest
from unittest.mock import patch, MagicMock
from pet.computer import confirmation_reason, Computer


class ComputerTests(unittest.TestCase):
    def test_new_file_allowed_but_overwrite_delete_require_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'note.txt'
            self.assertIsNone(confirmation_reason('FileSystem', {'mode': 'write', 'path': str(path), 'content': 'hi'}))
            path.write_text('original')
            self.assertIsNotNone(confirmation_reason('FileSystem', {'mode': 'write', 'path': str(path)}))
            self.assertIsNotNone(confirmation_reason('FileSystem', {'mode': 'delete', 'path': str(path)}))

    def test_relative_and_network_paths_rejected(self):
        for path in ['notes.txt', r'\\server\shared\notes.txt']:
            with self.assertRaises(ValueError):
                confirmation_reason('FileSystem', {'mode': 'write', 'path': path})

    def test_submission_and_shell_need_review(self):
        self.assertIsNotNone(confirmation_reason('Type', {'text': 'hi', 'press_enter': True}))
        self.assertIsNotNone(confirmation_reason('Shortcut', {'shortcut': 'win+r'}))
        self.assertIsNotNone(confirmation_reason('Type', {'text': 'command'}, window='Windows PowerShell'))
        self.assertIsNotNone(confirmation_reason('Click', {'label': 7}, snapshot='7 | Button | Send'))
        self.assertIsNone(confirmation_reason('Click', {'label': 3}, snapshot='3 | Button | Open'))

    def test_stale_focus_prevents_input(self):
        computer = Computer.__new__(Computer)
        computer.snapshot_window = (123, 'Notepad')
        with patch('pet.computer.foreground', return_value=(456, 'Mail')):
            result = computer.call('Type', {'text': 'hello', 'label': 1}, threading.Event())
        self.assertIn('Cửa sổ đã thay đổi', result)

    def test_cancel_and_denial_never_execute_tool(self):
        computer = Computer.__new__(Computer)
        computer.snapshot_window = None
        computer.snapshot_text = ''
        def deny(reason, decision):
            decision.done.set()
        computer.confirm = deny
        with patch('pet.computer.foreground', return_value=(123, 'Notepad')):
            result = computer.call('FileSystem', {'mode': 'delete', 'path': str(Path.cwd() / 'test.txt')}, threading.Event())
        self.assertIn('hủy thao tác', result)
        cancel = threading.Event()
        cancel.set()
        self.assertIn('dừng', computer.call('App', {}, cancel))


if __name__ == '__main__':
    unittest.main()
