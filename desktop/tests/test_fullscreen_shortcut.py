import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from unittest.mock import MagicMock
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pet.app_window import AlexAppWindow
from test_app_window import FakeEngine


class FullscreenShortcutTests(unittest.TestCase):
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
        QApplication.setActiveWindow(self.window)
        self.app.processEvents()

    def tearDown(self):
        self.window.hide()
        self.window.avatar.robot.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_key_toggles_center_fullscreen_and_mic(self):
        self.window._show_page('center')
        QApplication.setActiveWindow(self.window)
        self.window.center_page.mic.setFocus()
        self.app.processEvents()
        self.assertEqual(self.window.center_fullscreen_key.key().toString(), '`')
        # The offscreen platform has no active native window; real key delivery
        # is exercised separately against QWebEngine on Windows.
        self.window.center_fullscreen_key.activated.emit()
        self.app.processEvents()
        self.assertTrue(self.window._center_fullscreen)
        self.assertFalse(self.engine.paused.is_set())
        self.window.center_fullscreen_key.activated.emit()
        self.app.processEvents()
        self.assertFalse(self.window._center_fullscreen)
        self.assertTrue(self.engine.paused.is_set())
        self.assertFalse(self.window.center_fullscreen_key.autoRepeat())

    def test_key_remains_normal_text_in_chat(self):
        self.assertFalse(self.window.center_fullscreen_key.isEnabled())
        self.window.editor.setFocus()
        QTest.keyClicks(self.window.editor, '`')
        self.assertEqual(self.window.editor.toPlainText(), '`')
        self.assertFalse(self.window._center_fullscreen)

    def test_key_is_disabled_after_switching_away(self):
        self.window._show_page('center')
        self.assertTrue(self.window.center_fullscreen_key.isEnabled())
        self.window._show_page('chat')
        self.assertFalse(self.window.center_fullscreen_key.isEnabled())
