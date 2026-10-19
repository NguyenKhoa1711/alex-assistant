import tempfile
from pathlib import Path
import unittest
from unittest.mock import MagicMock
from pet.desktop_guard import DesktopGuard, Window, app_matches


class DesktopGuardTests(unittest.TestCase):
    def setUp(self):
        self.window = Window(12, 34, r'C:\Windows\notepad.exe', 'Untitled - Notepad')
        self.foreground = MagicMock(side_effect=lambda: self.window)
        self.permission_calls = []
        self.active = True; self.allow_plan = True; self.allow_action = True
        def approve(operation, grant='', description=''):
            self.permission_calls.append((operation, description))
            if operation == 'approve_plan':
                return {'allowed': self.allow_plan, 'grant': 'test-grant' if self.allow_plan else ''}
            if operation == 'approve_action':
                return {'allowed': self.active and self.allow_action}
            return {'allowed': self.active}
        self.guard = DesktopGuard(approve, self.foreground, MagicMock(return_value=True))

    def plan(self, paths=None):
        return self.guard.plan('Tạo ghi chú thử', ['Mở Notepad', 'Nhập ghi chú', 'Kiểm tra'], ['Notepad'], paths or [])

    def snapshot(self, text='├── (100,100) edit "Text Editor"  [action: fill]\n└── (200,200) button "Send"  [action: click]'):
        self.guard.after('Snapshot', {}, self.window, text, False)

    def test_no_mutation_before_approved_plan(self):
        with self.assertRaisesRegex(ValueError, 'kế hoạch'):
            self.guard.before('App', {'mode': 'launch', 'name': 'Notepad'})

    def test_denied_plan_does_not_grant_access(self):
        self.allow_plan = False
        self.assertFalse(self.plan()['approved'])
        with self.assertRaises(ValueError):self.guard.before('Type', {'text': 'hello', 'loc': [100,100]})

    def test_plan_covers_routine_steps_but_send_requires_separate_approval(self):
        self.plan(); self.snapshot()
        self.guard.before('Type', {'text': 'hello', 'loc': [100,100]})
        self.assertEqual(sum(op == 'approve_action' for op, _ in self.permission_calls), 0)
        self.guard.before('Click', {'loc': [200,200]})
        self.assertEqual(sum(op == 'approve_action' for op, _ in self.permission_calls), 1)

    def test_deny_sensitive_action_revokes_plan(self):
        self.plan(); self.snapshot(); self.allow_action = False
        with self.assertRaisesRegex(ValueError, 'hủy'):self.guard.before('Click', {'loc': [200,200]})
        with self.assertRaises(ValueError):self.guard.before('Type', {'text': 'hello', 'loc': [100,100]})

    def test_stop_revokes_next_action(self):
        self.plan(); self.snapshot(); self.active = False
        with self.assertRaisesRegex(ValueError, 'thu hồi'):self.guard.before('Type', {'text': 'hello', 'loc': [100,100]})

    def test_changed_foreground_and_old_labels_block_input(self):
        self.plan(); self.snapshot()
        with self.assertRaisesRegex(ValueError, 'nhãn'):self.guard.before('Click', {'label': 999})
        self.window = Window(13, 35, r'C:\mail.exe', 'Inbox')
        with self.assertRaisesRegex(ValueError, 'không thuộc'):self.guard.before('Type', {'text': 'hello', 'loc': [100,100]})

    def test_each_mutation_requires_new_snapshot(self):
        self.plan(); self.snapshot()
        self.guard.after('Click', {}, self.window, 'Clicked', False)
        with self.assertRaisesRegex(ValueError, 'Ảnh giao diện'):self.guard.before('Type', {'text': 'hello', 'loc': [100,100]})

    def test_new_file_in_scope_allowed_overwrite_or_delete_asks(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'note.txt'; self.plan([str(path)])
            self.guard.before('FileSystem', {'mode': 'write', 'path': str(path), 'content': 'hello'})
            self.assertFalse(any(op == 'approve_action' for op, _ in self.permission_calls))
            path.write_text('old')
            self.guard.before('FileSystem', {'mode': 'write', 'path': str(path), 'content': 'new'})
            self.assertTrue(any(op == 'approve_action' for op, _ in self.permission_calls))
            with self.assertRaisesRegex(ValueError, 'ngoài kế hoạch'):
                self.guard.before('FileSystem', {'mode': 'read', 'path': str(Path(temp) / 'other.txt')})

    def test_shell_and_multiline_input_always_ask(self):
        self.plan(); self.snapshot()
        self.guard.before('PowerShell', {'command': 'Write-Output hello'})
        self.guard.before('Type', {'text': 'hello\n', 'loc': [100,100]})
        self.assertEqual(sum(op == 'approve_action' for op, _ in self.permission_calls), 2)

    def test_cannot_claim_finished_without_readback(self):
        self.plan(); self.snapshot()
        self.guard.after('Type', {}, self.window, 'Typed hello', False)
        with self.assertRaises(ValueError):self.guard.verified_finish('hello')
        self.snapshot('└── (100,100) edit "hello"  [action: fill]')
        self.assertTrue(self.guard.verified_finish('hello')['finished'])
        self.assertEqual(self.guard.grant, '')

    def test_layout_change_blocks_a_click_even_with_same_window(self):
        self.plan(); self.snapshot()
        with self.assertRaisesRegex(ValueError, 'giao diện đã thay đổi'):
            self.guard.validate_live_target('Click', {'loc': [200,200]},
                '└── (200,200) button "Delete"  [action: click]', self.window)

    def test_confirm_location_that_has_no_named_control(self):
        self.plan(); self.snapshot()
        self.guard.before('Click', {'loc': [400,400]})
        self.assertEqual(sum(op == 'approve_action' for op, _ in self.permission_calls), 1)

    def test_any_named_app_not_only_original_allowlist(self):
        self.guard.plan('Dùng ứng dụng đồ họa', ['Mở ứng dụng'], ['Krita'], [])
        self.window = Window(20, 40, r'D:\Krita\bin\krita.exe', 'Untitled')
        self.snapshot();self.guard.before('Click', {'loc': [100,100]})
        self.assertTrue(app_matches('Krita', self.window))
        with self.assertRaises(ValueError):self.guard.before('App', {'name': 'Mail'})

    def test_exact_executable_must_match_planned_app_and_get_separate_approval(self):
        self.plan()
        with self.assertRaisesRegex(ValueError, 'chưa thuộc'):
            self.guard.before('App', {'mode': 'launch_executable', 'executable': r'C:\Temp\other.exe'})
        self.guard.before('App', {'mode': 'launch_executable', 'executable': r'C:\Windows\notepad.exe'})
        self.assertEqual(sum(op == 'approve_action' for op, _ in self.permission_calls), 1)

    def test_successful_launch_binds_branded_window_with_different_executable(self):
        self.guard.plan('Dùng ứng dụng đồ họa', ['Mở và kiểm tra'], ['Krita'], [])
        old = self.window
        self.window = Window(20, 40, r'D:\Vendor\designer.exe', 'Untitled - Krita')
        self.guard.after('App', {'mode': 'launch', 'name': 'Krita'}, old, 'Krita launched.', False)
        self.snapshot()
        self.guard.before('Click', {'loc': [100, 100]})
        self.assertTrue(app_matches('Paint', Window(2, 3, r'C:\Windows\mspaint.exe', 'Untitled - Paint')))


if __name__ == '__main__':unittest.main()
