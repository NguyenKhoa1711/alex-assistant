import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import unittest
from unittest.mock import MagicMock
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from pet.app_window import AlexAppWindow
from test_app_window import FakeEngine


class FullscreenMicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.engine = FakeEngine()
        self.engine.mic = MagicMock()
        self.pet = MagicMock()
        self.pet.windowIcon.return_value = QIcon()
        self.pet.isVisible.return_value = False
        self.window = AlexAppWindow(self.engine, self.pet)
        self.window.show()
        self.window._show_page('center')
        self.window._set_center_fullscreen(True)
        self.assertFalse(self.engine.paused.is_set())

    def tearDown(self):
        self.window.hide()
        self.window.avatar.robot.close()
        self.window.deleteLater()
        self.app.processEvents()

    def assert_mic_off(self):
        self.assertTrue(self.engine.paused.is_set())
        self.engine.mic.gate.assert_called_with(False)
        self.assertFalse(self.window._center_fullscreen)

    def test_exit_button_turns_mic_off(self):
        self.window.center_page.fullscreen_requested.emit()
        self.assert_mic_off()

    def test_escape_turns_mic_off_even_when_busy(self):
        self.engine.busy.set()
        self.window._escape()
        self.assert_mic_off()
        self.engine.interrupt.assert_not_called()

    def test_switching_pages_turns_mic_off(self):
        self.window._show_page('chat')
        self.assert_mic_off()

    def test_closing_fullscreen_turns_mic_off(self):
        self.window.close()
        self.assert_mic_off()

    def test_already_muted_never_gets_turned_back_on(self):
        self.engine.paused.set()
        self.window._set_center_fullscreen(False)
        self.assert_mic_off()
        self.window._set_center_fullscreen(False)
        self.assertTrue(self.engine.paused.is_set())
