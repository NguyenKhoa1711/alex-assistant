import unittest
from unittest.mock import patch
from pet.messaging_driver import _find_zalo_hwnd


class ZaloWindowBindingTests(unittest.TestCase):
    @patch('pet.messaging_driver.app_windows')
    @patch('pet.messaging_driver.requested_app')
    @patch('pet.messaging_driver.load_config')
    def test_unique_configured_zalo_window(self, config, requested, windows):
        config.return_value = {'apps': {'entries': [{'name': 'Zalo'}]}}
        requested.return_value = {'name': 'Zalo'}
        windows.return_value = [42]
        self.assertEqual(_find_zalo_hwnd(), 42)
        requested.assert_called_once_with('Mở Zalo', [{'name': 'Zalo'}])

    @patch('pet.messaging_driver.app_windows')
    @patch('pet.messaging_driver.requested_app')
    @patch('pet.messaging_driver.load_config')
    def test_multiple_or_missing_windows_are_not_guessed(self, config, requested, windows):
        config.return_value = {'apps': {'entries': []}}
        requested.return_value = {'name': 'Zalo'}
        windows.return_value = [42, 43]
        self.assertIsNone(_find_zalo_hwnd())
        windows.return_value = []
        self.assertIsNone(_find_zalo_hwnd())
        requested.return_value = None
        self.assertIsNone(_find_zalo_hwnd())

    @patch('pet.messaging_driver.app_windows', side_effect=OSError('unavailable'))
    @patch('pet.messaging_driver.requested_app', return_value={'name': 'Zalo'})
    @patch('pet.messaging_driver.load_config', return_value={'apps': {'entries': []}})
    def test_unavailable_process_does_not_guess(self, *_):
        self.assertIsNone(_find_zalo_hwnd())
