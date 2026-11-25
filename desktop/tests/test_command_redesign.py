import unittest
from unittest.mock import MagicMock
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QPushButton
from pet.app_window import AlexAppWindow
from test_app_window import FakeEngine


class CommandRedesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.engine = FakeEngine()
        self.pet = MagicMock()
        self.pet.windowIcon.return_value = QIcon()
        self.window = AlexAppWindow(self.engine, self.pet)
        self.window.resize(1280, 860)
        self.window.show()
        self.window._show_page('center')
        self.window._page_transition.stop()
        self.window._page_overlay.hide()
        self.app.processEvents()
        self.page = self.window.center_page

    def tearDown(self):
        self.window.hide()
        self.window.avatar.robot.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_wide_and_compact_labels_and_controls_fit(self):
        self.assertEqual(self.page.face_brand.text(), 'ALEX  /  TRỢ LÝ CỦA BẠN')
        for size in ((800, 650), (800, 580)):
            with self.subTest(size=size):
                self.window.resize(*size)
                self.app.processEvents()
                self.assertLessEqual(self.window.height(), size[1])
                self.assertTrue(self.page.compact)
                self.assertEqual(self.page.face_brand.text(), 'ALEX')
                for widget in (self.page.face_panel, self.page.controls, self.page.latest_panel):
                    self.assertTrue(self.page.rect().contains(widget.geometry()))
                self.assertFalse(self.page.face_panel.geometry().intersects(self.page.controls.geometry()))

    def test_requested_shortcuts_removed_and_mic_still_works(self):
        switches = []
        self.page.mic_requested.connect(lambda: switches.append(True))
        buttons = {button.text(): button for button in self.page.findChildren(QPushButton)}
        self.assertNotIn('Thư mục học tập    ↗', buttons)
        self.assertNotIn('Mở YouTube    ↗', buttons)
        self.assertNotIn('Khám phá vũ trụ    ↗', buttons)
        self.page.mic.click()
        self.assertEqual(switches, [True])
        self.assertTrue(self.page.latest_panel.isVisible())
