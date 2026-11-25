import unittest
from unittest.mock import MagicMock, patch
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from pet.app_window import AlexAppWindow
from pet.orbit_math import PlanetSwipe
from test_app_window import FakeEngine
from test_space_view import hand, open_hand, v_hand


def palm(x=.4, y=.5):
    p = [[x,y] for _ in range(21)]
    p[0] = [x,y+.22]; p[9] = [x,y]
    p[4] = [x-.16,y-.05]
    for tip,pip,dx in ((8,6,-.09),(12,10,-.03),(16,14,.04),(20,18,.10)):
        p[pip] = [x+dx,y-.04]; p[tip] = [x+dx,y-.20]
    return p


class PlanetSwipeTests(unittest.TestCase):
    def test_swipe_once_then_release_before_next(self):
        gesture = PlanetSwipe()
        self.assertEqual(gesture.update([palm(.25)], 1.), 0)
        self.assertEqual(gesture.update([palm(.33)], 1.1), 0)
        self.assertEqual(gesture.update([palm(.42)], 1.2), 1)
        for t,x in ((1.3,.50),(1.4,.35),(1.5,.25),(2.3,.45)):
            self.assertEqual(gesture.update([palm(x)],t),0)
        gesture.update([],2.4); gesture.update([],2.7)
        self.assertEqual(gesture.update([palm(.65)],2.8),0)
        self.assertEqual(gesture.update([palm(.56)],2.9),0)
        self.assertEqual(gesture.update([palm(.47)],3.),-1)

    def test_other_gestures_and_jumps_do_not_swipe(self):
        g=PlanetSwipe()
        for i in range(6):
            self.assertEqual(g.update([hand(.2+i*.04)],1+i*.1),0)
            self.assertEqual(g.update([v_hand(.2+i*.04)],2+i*.1),0)
            self.assertEqual(g.update([palm(.2+i*.04),open_hand(.8)],3+i*.1),0)
        g.reset()
        for t,x in ((5.,.2),(5.1,.21),(5.2,.7),(5.3,.71)):
            self.assertEqual(g.update([palm(x)],t),0)

    def test_real_page_changes_planet_without_camera_and_two_hands_do_not(self):
        app=QApplication.instance() or QApplication([])
        engine=FakeEngine(); pet=MagicMock(); pet.windowIcon.return_value=QIcon()
        pet.isVisible.return_value=False
        window=AlexAppWindow(engine,pet); window.resize(1000,750)
        window.show(); window._show_page('space'); app.processEvents()
        page=window.space_page; original=page.pick.currentIndex()
        try:
            with patch('pet.space_view.time.monotonic',side_effect=(1.,1.1,1.2,1.3,1.4)):
                page._hands([palm(.25)]); page._hands([palm(.33)]); page._hands([palm(.42)])
                self.assertEqual(page.pick.currentIndex(),(original+1)%page.pick.count())
                page._hands([palm(.33)]); page._hands([palm(.25)])
                self.assertEqual(page.pick.currentIndex(),(original+1)%page.pick.count())
            self.assertFalse(page.camera_button.isChecked())
        finally:
            window.hide(); page.camera.shutdown(); window.avatar.robot.close(); window.deleteLater()
            app.processEvents()
