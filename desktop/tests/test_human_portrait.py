import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from pet.hologram_face import HologramFace


class HumanPortraitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.face = HologramFace()
        self.face.resize(520, 440)
        self.face.show()
        self.app.processEvents()
        self.face.timer.stop()

    def tearDown(self):
        self.face.hide()
        self.face.deleteLater()
        self.app.processEvents()

    def test_local_asset_loads_and_frame_cache_updates_on_motion(self):
        self.assertFalse(self.face.portrait.isNull())
        self.face.grab(); key = self.face._frame.cacheKey()
        self.face.grab(); self.assertEqual(self.face._frame.cacheKey(), key)
        before = self.face.grab().toImage()
        self.face.target_yaw = .2
        self.face._advance(1/30)
        self.assertNotEqual(before, self.face.grab().toImage())

    def test_states_have_visual_cues_and_reduced_motion_stays_still(self):
        self.face.set_reduced_motion(True)
        frames = []
        for mode in ('paused', 'listening', 'thinking', 'speaking', 'error'):
            self.face.set_mode(mode)
            image = self.face.grab().toImage()
            self.assertTrue(all(image != prior for prior in frames))
            frames.append(image)
            self.face._advance(1)
            self.assertEqual(image, self.face.grab().toImage())
            self.assertFalse(self.face.timer.isActive())

    def test_hidden_stops_animation_and_missing_image_has_fallback(self):
        self.face.set_active(True)
        self.assertTrue(self.face.timer.isActive())
        self.face.hide()
        self.app.processEvents()
        self.assertFalse(self.face.timer.isActive())
        self.face.portrait = self.face.portrait.__class__()
        self.face._invalidate()
        self.assertFalse(self.face.grab().isNull())
