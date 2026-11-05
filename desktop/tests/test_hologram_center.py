import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from test_app_window import FakeEngine, MagicMock, QIcon
from pet.app_window import AlexAppWindow
from pet.hologram_face import HologramFace, approach


class MotionTests(unittest.TestCase):
    def test_easing_is_independent_of_render_rate(self):
        def integrate(fps):
            value=-.2
            for _ in range(fps): value=approach(value,.25,1/fps,.16)
            return value
        self.assertAlmostEqual(integrate(20),integrate(30),places=10)
        self.assertAlmostEqual(integrate(30),integrate(60),places=10)

    def test_easing_never_overshoots_and_large_wake_gap_is_bounded(self):
        self.assertEqual(approach(.1,.3,-1,.16),.1)
        self.assertAlmostEqual(approach(.1,.3,100,.16),approach(.1,.3,.1,.16))
        value=-.2
        for _ in range(60):
            next_value=approach(value,.25,1/30,.16)
            self.assertGreaterEqual(next_value,value); self.assertLessEqual(next_value,.25)
            value=next_value


class HologramCenterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.engine=FakeEngine(); self.pet=MagicMock(); self.pet.windowIcon.return_value=QIcon()
        self.window=AlexAppWindow(self.engine,self.pet)
        self.window.resize(1120,780); self.window.show(); self.window._show_page('center')
        self.app.processEvents(); self.page=self.window.center_page

    def tearDown(self):
        self.window.hide(); self.window.avatar.robot.close()
        self.window.deleteLater(); self.app.processEvents()

    def test_navigation_and_reduced_motion_never_enable_mic(self):
        self.assertTrue(self.engine.paused.is_set())
        self.assertTrue(self.page.reactor.timer.isActive())
        self.page.motion.click(); self.assertFalse(self.page.reactor.timer.isActive())
        self.window._show_page('chat'); self.window._show_page('center'); self.app.processEvents()
        self.assertFalse(self.page.reactor.timer.isActive())
        self.assertTrue(self.engine.paused.is_set()); self.engine.submit_text.assert_not_called()
        self.page.motion.click(); self.assertTrue(self.page.reactor.timer.isActive())

    def test_hidden_and_minimized_stop_both_timers(self):
        self.window.showMinimized(); self.app.processEvents()
        self.assertFalse(self.page.timer.isActive()); self.assertFalse(self.page.reactor.timer.isActive())
        self.window.showNormal(); self.app.processEvents()
        self.assertTrue(self.page.reactor.timer.isActive())
        self.window._show_page('chat'); self.app.processEvents()
        self.assertFalse(self.page.timer.isActive()); self.assertFalse(self.page.reactor.timer.isActive())

    def test_real_worker_state_controls_distinct_face_and_stop_button(self):
        face=self.page.reactor; face.timer.stop(); face.phase=.4
        paused=face.grab().toImage()
        self.engine.paused.clear(); self.engine.state.emit('listening','')
        for _ in range(30): face._advance(1/30)
        self.assertEqual(face.mode,'listening'); self.assertNotEqual(paused,face.grab().toImage())
        self.assertFalse(self.page.stop.isEnabled())
        self.engine.busy.set(); self.engine.state.emit('speaking','')
        self.assertEqual(face.mode,'speaking'); self.assertTrue(self.page.stop.isEnabled())
        first=face.grab().toImage()
        for _ in range(12): face._advance(1/30)
        self.assertNotEqual(first,face.grab().toImage())
        self.page.stop.click(); self.engine.interrupt.assert_called_once()

    def test_narrow_window_keeps_controls_inside_page_and_restores_telemetry(self):
        self.window.resize(800,650); self.app.processEvents()
        self.assertTrue(self.page.compact)
        self.assertLessEqual(self.window.width(),800)
        for child in (self.page.face_panel,self.page.controls):
            self.assertTrue(self.page.rect().contains(child.geometry()))
        self.assertFalse(self.page.face_panel.geometry().intersects(self.page.controls.geometry()))
        self.window.resize(1280,860); self.app.processEvents()
        self.assertFalse(self.page.compact); self.assertTrue(self.page.telemetry.isVisible())

    def test_metrics_are_real_samples_and_history_is_bounded(self):
        for trace in self.page.traces.values(): trace.samples.clear()
        with patch.object(self.page.metrics,'sample',return_value=('25%','8.0 / 16.0 GB')):
            self.page._sample()
        self.assertEqual(self.page.traces['cpu'].samples[-1],25)
        self.assertEqual(self.page.traces['ram'].samples[-1],50)
        with patch.object(self.page.metrics,'sample',side_effect=OSError('unavailable')):
            for _ in range(35): self.page._sample()
        self.assertEqual(len(self.page.traces['cpu'].samples),30)
        self.assertIsNone(self.page.traces['cpu'].samples[-1])
        self.assertEqual(self.page.values['cpu'].text(),'—')

    def test_expression_transitions_smoothly_and_no_catch_up_after_hiding(self):
        face=self.page.reactor; face.timer.stop()
        initial=face.eye_level; face.set_mode('speaking')
        self.assertEqual(face.eye_level,initial)
        face._advance(1/30)
        self.assertGreater(face.eye_level,initial); self.assertLess(face.eye_level,.94)
        self.assertGreater(face.talking,0); self.assertLess(face.talking,1)
        before=face.phase; face._advance(500)
        self.assertAlmostEqual(face.phase-before,.1)
        face.set_reduced_motion(True)
        face.set_mode('paused'); self.assertEqual(face.talking,0)
        self.assertFalse(face.timer.isActive())

    def test_repaint_reuses_frame_but_cursor_motion_changes_geometry(self):
        face=self.page.reactor; face.timer.stop()
        face.grab(); key=face._frame.cacheKey()
        for _ in range(5): face.grab()
        self.assertEqual(face._frame.cacheKey(),key)
        before=face.grab().toImage()
        face.target_yaw=.2; face._advance(1/30); face.grab()
        self.assertNotEqual(face._frame.cacheKey(),key)
        self.assertNotEqual(face.grab().toImage(),before)

    def test_every_state_remains_distinct_with_reduced_motion(self):
        face=self.page.reactor; face.set_reduced_motion(True)
        images=[]
        for mode in ('paused','listening','thinking','speaking','error'):
            face.set_mode(mode); current=face.grab().toImage()
            for other in images: self.assertNotEqual(current,other)
            images.append(current)
            face.phase+=2.7
            self.assertEqual(current,face.grab().toImage())
            self.assertFalse(face.timer.isActive())

    def test_size_change_refreshes_portrait_at_new_resolution(self):
        face=HologramFace(); face.resize(260,300); face.grab()
        first=face._frame.cacheKey(); old_width=face._frame.width()
        face.resize(520,600); face.grab()
        self.assertNotEqual(face._frame.cacheKey(),first)
        self.assertGreater(face._frame.width(),old_width)
        face.deleteLater()

    def test_real_anatomy_has_landmarks_and_paused_lids(self):
        face=self.page.reactor; face.set_reduced_motion(True)
        self.assertGreaterEqual(len(face.avatar._v0),468)
        self.assertEqual(set(face.avatar._lm), {'eye_l','eye_r','brow_l','brow_r','lips_in','lips_out'})
        face.set_mode('paused'); self.assertLess(face.avatar._lids,.2)
        face.set_mode('listening'); self.assertEqual(face.avatar._lids,1.)


if __name__=='__main__': unittest.main()
