import unittest
from unittest.mock import MagicMock, patch
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from pet.app_window import AlexAppWindow
from pet.orbit_math import GestureMotion
from test_space_view import hand, open_hand, FakeEngine


class GestureContinuityTests(unittest.TestCase):
    def test_slow_drag_accumulates_in_both_directions(self):
        motion = GestureMotion()
        motion.update([hand(.30), hand(.70)], 1.)
        outward = 0.
        for i in range(1, 31):
            motion.update([hand(.30-i*.0004), hand(.70+i*.0004)], 1+i/15)
            outward += motion.separation_delta
        self.assertGreater(outward, .020)
        inward = 0.
        for i in range(1, 31):
            motion.update([hand(.288+i*.0004), hand(.712-i*.0004)], 3+i/15)
            inward += motion.separation_delta
        self.assertLess(inward, -.020)

    def test_jitter_and_reacquisition_do_not_jump(self):
        motion = GestureMotion()
        motion.update([hand(.30), hand(.70)], 1.)
        for i in range(1, 15):
            offset = .0004 if i % 2 else -.0004
            motion.update([hand(.30-offset), hand(.70+offset)], 1+i/15)
            self.assertEqual(motion.separation_delta, 0.)
        motion.update([], 2.)
        motion.update([hand(.15), hand(.85)], 2.1)
        self.assertEqual(motion.separation_delta, 0.)
        motion.update([hand(.30), open_hand(.70)], 2.2)
        self.assertEqual(motion.separation_delta, 0.)

    def test_slow_drag_reaches_layer_canvas_and_reverses(self):
        app = QApplication.instance() or QApplication([])
        engine, pet = FakeEngine(), MagicMock()
        pet.windowIcon.return_value = QIcon()
        pet.isVisible.return_value = False
        window = AlexAppWindow(engine, pet)
        window.resize(1000, 750); window.show(); window._show_page('space'); app.processEvents()
        page = window.space_page
        clock = iter(1.0 + i/15 for i in range(100))
        try:
            with patch('pet.space_view.time.monotonic', side_effect=lambda: next(clock)):
                page._hands([hand(.30), hand(.70)])
                for i in range(1, 31):
                    page._hands([hand(.30-i*.0004), hand(.70+i*.0004)])
                    page.gesture_animation.setCurrentTime(page.gesture_animation.duration())
                self.assertTrue(page.layer_button.isChecked())
                opened = page.layer_canvas.amount
                self.assertGreater(opened, .02)
                for i in range(1, 16):
                    page._hands([hand(.288+i*.0004), hand(.712-i*.0004)])
                    page.gesture_animation.setCurrentTime(page.gesture_animation.duration())
                if not page.layer_button.isChecked():
                    page.layer_animation.setCurrentTime(page.layer_animation.duration())
                self.assertLess(page.layer_canvas.amount, opened)
        finally:
            window.hide(); page.camera.shutdown(); window.avatar.robot.close(); window.deleteLater()
            app.processEvents()
