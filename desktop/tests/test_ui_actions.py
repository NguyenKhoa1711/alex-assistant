"""Decision tests for contact matching; UIA calls are exercised separately on Windows."""
import importlib
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from pet.app_actions import Action

with patch.dict(sys.modules, {'windows_mcp': SimpleNamespace(uia=MagicMock())}):
    worker = importlib.import_module('app_action_worker')


class ContactSelectionTests(unittest.TestCase):
    def run_search(self, names, query='Nguyễn An', header='Nguyễn An'):
        ui = MagicMock()
        ui.root.EditControl.return_value.Exists.return_value = True
        ui.root.GroupControl.return_value.Exists.return_value = True
        rows = [SimpleNamespace(AutomationId=f'friend-item-{i}', IsOffscreen=False) for i in range(len(names))]
        def text_parts(control, depth):
            for i, row in enumerate(rows):
                if control is row:
                    return names[i]
            return [header]
        with patch.object(worker, 'Ui', return_value=ui), patch.object(worker, 'nodes', return_value=rows), \
             patch.object(worker, 'texts', side_effect=text_parts), patch.object(worker.time, 'sleep'):
            result = worker.zalo(Action('Zalo', 'chat', query))
        return result, ui

    def test_name_split_into_highlighted_parts(self):
        result, ui = self.run_search([['Nguyễn', '\u00a0', 'An']])
        self.assertTrue(result['verified'])
        ui.invoke.assert_called_once()

    def test_duplicate_exact_names_are_not_opened(self):
        result, ui = self.run_search([['Nguyễn An'], ['Nguyễn An']])
        self.assertFalse(result['verified'])
        self.assertIn('trùng tên', result['message'])
        ui.invoke.assert_not_called()

    def test_partial_name_does_not_open_wrong_person(self):
        result, ui = self.run_search([['Nguyễn Anh'], ['Nguyễn An Bình']])
        self.assertFalse(result['verified'])
        ui.invoke.assert_not_called()

    def test_changed_chat_header_does_not_claim_success(self):
        result, ui = self.run_search([['Nguyễn An']], header='Người khác')
        self.assertFalse(result['verified'])
        ui.invoke.assert_called_once()


class PlaybackVerificationTests(unittest.TestCase):
    def test_old_track_with_same_title_but_other_artist_is_not_success(self):
        self.assertFalse(worker.song_is_playing('Thiên Lý Ơi của Người khác', 'Thiên Lý Ơi', 'Jack - J97', 'playing'))
        self.assertFalse(worker.song_is_playing('Thiên Lý Ơi', 'Thiên Lý Ơi', 'Jack - J97', 'playing'))
        self.assertTrue(worker.song_is_playing('Thiên Lý Ơi của Jack - J97', 'Thiên Lý Ơi', 'Jack - J97', 'playing'))

    def test_event_error_after_invoke_checks_state_without_second_click(self):
        ui = MagicMock()
        ui.invoke.side_effect = worker.COMError(-2147467259, 'stale event', None)
        verify = MagicMock(side_effect=[worker.COMError(-2147467259, 'stale read', None),
                                       {'verified': True, 'message': 'paused'}])
        with patch.object(worker.time, 'sleep'):
            result = worker.invoke_and_verify(ui, object(), verify)
        self.assertTrue(result['verified'])
        ui.invoke.assert_called_once()

    def test_no_success_without_confirmed_state(self):
        ui = MagicMock()
        with patch.object(worker.time, 'sleep'):
            result = worker.invoke_and_verify(ui, object(), lambda: None, attempts=3)
        self.assertIsNone(result)
        ui.invoke.assert_called_once()

    def test_read_retries_stale_element(self):
        read = MagicMock(side_effect=[worker.COMError(-2147467259, 'stale', None), 'playing'])
        with patch.object(worker.time, 'sleep'):
            self.assertEqual(worker.retry_uia_read(read)(), 'playing')


if __name__ == '__main__':
    unittest.main()
