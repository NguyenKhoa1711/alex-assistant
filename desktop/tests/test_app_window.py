import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import threading
import unittest
from unittest.mock import MagicMock
from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from pet.app_window import AlexAppWindow, Message


class FakeEngine(QObject):
    state = Signal(str, str)
    transcript = Signal(str)
    reply = Signal(str)
    desktop_finished = Signal(bool, str)
    finished = Signal()

    def __init__(self):
        super().__init__()
        self.desktop_ready = threading.Event()
        self.desktop_ready.set()
        self.busy = threading.Event()
        self.paused = threading.Event()
        self.paused.set()
        self.submit_text = MagicMock(return_value='')
        self.interrupt = MagicMock()

    def isRunning(self):
        return True

    def toggle(self):
        self.paused.clear() if self.paused.is_set() else self.paused.set()


class AppWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.engine = FakeEngine()
        self.pet = MagicMock()
        self.pet.windowIcon.return_value = QIcon()
        self.pet.isVisible.return_value = False
        self.window = AlexAppWindow(self.engine, self.pet)

    def tearDown(self):
        self.window.hide()
        self.window.avatar.robot.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_enter_sends_once_and_shift_enter_adds_newline(self):
        self.window.editor.setPlainText('Xin chào')
        QTest.keyClick(self.window.editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
        self.engine.submit_text.assert_not_called()
        self.window.editor.setPlainText('Xin chào')
        QTest.keyClick(self.window.editor, Qt.Key.Key_Return)
        QTest.keyClick(self.window.editor, Qt.Key.Key_Return)
        self.engine.submit_text.assert_called_once()

    def test_raw_html_is_plain_text(self):
        message = Message('Alex', '<img src="https://example.org/tracker">')
        self.assertEqual(message.content.textFormat(), Qt.TextFormat.PlainText)
        message.deleteLater()

    def test_reply_stream_updates_one_bubble(self):
        self.window.editor.setPlainText('Xin chào')
        self.window._send()
        self.engine.transcript.emit('Xin chào')
        self.engine.reply.emit('Chào')
        self.engine.reply.emit('Chào bạn.')
        self.assertEqual(len(self.window.message_rows), 2)
        self.assertEqual(self.window.current_answer.content.text(), 'Chào bạn.')

    def test_close_preserves_pet_and_worker(self):
        self.window.show()
        self.window.close()
        self.assertFalse(self.window.isVisible())
        self.engine.interrupt.assert_not_called()
        self.pet.quit_pet.assert_not_called()

    def test_pet_visibility_does_not_turn_on_mic(self):
        self.window._toggle_pet()
        self.assertTrue(self.engine.paused.is_set())
        self.pet.setVisible.assert_called_once_with(True)

    def test_stop_button_stops_background_scroll_after_reply_finished(self):
        self.engine.web_scroller = MagicMock()
        self.engine.web_scroller.is_active.return_value = True
        def stop_scroll():
            self.engine.web_scroller.is_active.return_value = False
        self.engine.interrupt.side_effect = stop_scroll
        self.engine.desktop_finished.emit(True, 'Đã bật chế độ tự động.')
        self.assertFalse(self.engine.busy.is_set())
        self.assertTrue(self.window.stop_button.isEnabled())
        QTest.mouseClick(self.window.stop_button, Qt.MouseButton.LeftButton)
        self.engine.interrupt.assert_called_once_with()
        self.assertFalse(self.window.stop_button.isEnabled())
        self.assertEqual(self.window.notice.text(), 'Đã dừng lướt web.')

    def test_new_conversation_clears_only_after_worker_accepts_reset(self):
        self.window._question('Xin chào')
        self.window._reply('Chào bạn.')
        self.window._new_chat()
        self.assertEqual(len(self.window.message_rows), 2)
        self.engine.desktop_finished.emit(True, 'Đã bắt đầu lại.')
        self.assertEqual(len(self.window.message_rows), 0)


if __name__ == '__main__':
    unittest.main()
