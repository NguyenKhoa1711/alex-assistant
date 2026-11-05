import subprocess
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from pet import display_priority as priority


class DisplayPriorityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.request = self.root / 'request.txt'
        self.install_patch = patch.object(priority, 'INSTALL', self.root)
        self.request_patch = patch.object(priority, 'REQUEST', self.request)
        self.install_patch.start()
        self.request_patch.start()
        priority._ticket = None

    def tearDown(self):
        priority.cancel_display_priority()
        self.install_patch.stop()
        self.request_patch.stop()
        self.temp.cleanup()

    def test_missing_helper_does_not_start_elevation_or_write_request(self):
        with patch.object(priority.subprocess, 'run') as run:
            with self.assertRaises(OSError):
                priority.begin_display_priority()
        run.assert_not_called()
        self.assertFalse(self.request.exists())

    def test_failed_task_removes_only_owned_request(self):
        (self.root / 'AlexDisplayPriority.exe').touch()
        with patch.object(priority.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'task')):
            with self.assertRaises(OSError):
                priority.begin_display_priority()
        self.assertFalse(self.request.exists())
        self.assertIsNone(priority._ticket)

    def test_stale_status_cannot_authorize_current_request(self):
        (self.root / 'status.txt').write_text('old|active|date', encoding='utf-8')
        self.assertEqual(priority._status('new'), '')
        self.assertEqual(priority._status('old'), 'active')

    def test_request_creation_failure_clears_pending_ticket(self):
        (self.root / 'AlexDisplayPriority.exe').touch()
        with patch.object(Path, 'mkdir', side_effect=PermissionError('test')):
            with self.assertRaises(OSError):
                priority.begin_display_priority()
        self.assertIsNone(priority._ticket)

    def test_cancel_preserves_another_process_request(self):
        priority._ticket = 'old'
        self.request.write_text('new|123|456', encoding='ascii')
        priority.cancel_display_priority()
        self.assertEqual(self.request.read_text(), 'new|123|456')

    def test_task_error_fails_immediately(self):
        with patch.object(priority, '_status', return_value='error_InvalidOperationException'):
            with self.assertRaises(OSError):
                priority.confirm_display_priority('ticket')


if __name__ == '__main__':
    unittest.main()
