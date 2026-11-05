import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import math
import itertools
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QPushButton
from PySide6.QtCore import QAbstractAnimation, Qt, QPoint
from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest
from pet.orbit_math import PLANETS, orbital_point, GestureMotion, DoublePinch, FullscreenV
from pet.space_view import SpacePage
from test_app_window import FakeEngine, MagicMock, QIcon
from pet.app_window import AlexAppWindow


def hand(x=.4,y=.5):
    points=[[x,y] for _ in range(21)]
    points[0]=[x,y+.2]; points[9]=[x,y]
    points[4]=[x-.01,y-.1]; points[8]=[x+.01,y-.1]
    return points


def open_hand(x=.4,y=.5):
    points=hand(x,y)
    points[4]=[x-.14,y-.10]
    return points


def v_hand(x=.4,y=.5):
    points=hand(x,y)
    points[4]=[x-.10,y+.08]
    points[6]=[x-.04,y-.06];points[8]=[x-.08,y-.22]
    points[10]=[x+.02,y-.06];points[12]=[x+.07,y-.22]
    points[14]=[x+.05,y-.03];points[16]=[x+.05,y+.08]
    points[18]=[x+.08,y-.01];points[20]=[x+.08,y+.10]
    return points


class OrbitMathTests(unittest.TestCase):
    def test_v_hold_requires_time_releases_and_does_not_repeat(self):
        gesture=FullscreenV()
        for t in (1.,1.25,1.5,1.75):self.assertFalse(gesture.update([v_hand()],t))
        self.assertTrue(gesture.update([v_hand()],2.15))
        for t in (2.3,2.7,3.5):self.assertFalse(gesture.update([v_hand()],t))
        gesture.update([open_hand()],3.6);gesture.update([open_hand()],3.9)
        for t in (4.,4.3,4.6,4.9):self.assertFalse(gesture.update([v_hand()],t))
        self.assertTrue(gesture.update([v_hand()],5.2))

    def test_v_hold_does_not_conflict_with_pinch_zoom_or_two_hands(self):
        gesture=FullscreenV()
        for t in (1.,1.3,1.6,1.9,2.2):
            self.assertFalse(gesture.update([hand()],t))
            self.assertFalse(gesture.update([open_hand(.3),open_hand(.7)],t+.01))
            self.assertFalse(gesture.update([v_hand(.3),hand(.7)],t+.02))
        self.assertFalse(FullscreenV.is_v(hand()))
        self.assertFalse(FullscreenV.is_v(open_hand()))
        self.assertTrue(FullscreenV.is_v(v_hand()))

    def test_v_hold_tolerates_short_dropout_and_relaxed_second_hand(self):
        gesture=FullscreenV()
        for t in (1.,1.25,1.5):self.assertFalse(gesture.update([v_hand(.3),open_hand(.7)],t))
        self.assertFalse(gesture.update([],1.6))
        self.assertFalse(gesture.update([open_hand(.7),v_hand(.3)],1.7))
        self.assertTrue(gesture.update([v_hand(.3),open_hand(.7)],2.15))

    def test_v_detection_is_independent_of_screen_rotation_and_hand_scale(self):
        source=v_hand()
        for scale in (.55,1.,1.5):
            for angle in (0.,math.pi/2,math.pi):
                c,s=math.cos(angle),math.sin(angle)
                transformed=[[.5+scale*(x*c-y*s),.5+scale*(x*s+y*c)] for x,y in source]
                self.assertTrue(FullscreenV.is_v(transformed))

    def test_v_hold_brief_tracking_loss_does_not_rearm_while_still_held(self):
        gesture=FullscreenV()
        for t in (1.,1.25,1.5,1.75):gesture.update([v_hand()],t)
        self.assertTrue(gesture.update([v_hand()],2.15))
        gesture.update([],2.4)
        for t in (2.5,2.8,3.2,3.6,4.):
            self.assertFalse(gesture.update([v_hand()],t))
    def test_double_pinch_recognizes_once_with_release_and_cooldown(self):
        gesture=DoublePinch()
        for h,t in ((hand(),1.),(open_hand(),1.12)):
            self.assertFalse(gesture.update([h],t))
        self.assertTrue(gesture.update([hand()],1.25))
        for h,t in ((hand(),1.35),(open_hand(),1.48),(hand(),1.6)):
            self.assertFalse(gesture.update([h],t))
        gesture.update([open_hand()],2.5)
        gesture.update([hand()],2.7);gesture.update([open_hand()],2.85)
        self.assertTrue(gesture.update([hand()],3.0))

    def test_double_pinch_ignores_holds_rotation_and_two_hands(self):
        gesture=DoublePinch()
        gesture.update([hand()],1.);gesture.update([hand()],1.9)
        gesture.update([open_hand()],2.)
        self.assertFalse(gesture.update([hand()],2.1))
        gesture.reset();gesture.update([hand(.3)],3.)
        gesture.update([hand(.45)],3.1);gesture.update([open_hand(.45)],3.2)
        self.assertFalse(gesture.update([hand(.45)],3.3))
        gesture.reset();gesture.update([hand(.3)],4.);gesture.update([open_hand(.3)],4.1)
        self.assertFalse(gesture.update([hand(.3),hand(.7)],4.2))
        self.assertFalse(gesture.update([hand(.3)],4.3))

    def test_double_pinch_tolerates_slow_taps_short_dropout_and_other_open_hand(self):
        gesture=DoublePinch()
        self.assertFalse(gesture.update([hand(.3),open_hand(.7)],1.))
        self.assertIn('1',gesture.feedback)
        self.assertFalse(gesture.update([],1.10))
        self.assertFalse(gesture.update([open_hand(.7),open_hand(.3)],1.40))
        self.assertIn('2',gesture.feedback)
        self.assertTrue(gesture.update([open_hand(.7),hand(.3)],2.30))

    def test_double_pinch_does_not_mix_hands_or_turn_two_hand_pinch_into_toggle(self):
        gesture=DoublePinch()
        gesture.update([hand(.3),open_hand(.7)],1.)
        gesture.update([open_hand(.3),open_hand(.7)],1.1)
        self.assertFalse(gesture.update([open_hand(.3),hand(.7)],1.25))
        gesture.reset();gesture.update([hand(.3),open_hand(.7)],3.)
        self.assertFalse(gesture.update([hand(.3),hand(.7)],3.1))
        self.assertFalse(gesture.update([open_hand(.3),hand(.7)],3.2))

    def test_kepler_period_returns_to_start(self):
        for p in PLANETS:
            self.assertLess(math.dist(orbital_point(p,0),orbital_point(p,p.days)),1e-10)

    def test_eight_planets_in_order_with_increasing_periods(self):
        self.assertEqual(len(PLANETS),8)
        self.assertEqual([p.days for p in PLANETS],sorted(p.days for p in PLANETS))
        self.assertEqual(PLANETS[2].name,'Trái Đất')

    def test_no_jump_on_acquiring_or_reacquiring_hand(self):
        motion=GestureMotion()
        self.assertEqual(motion.update([hand()],1)[:3],(0.,0.,1.))
        self.assertGreater(motion.update([hand(.45)],1.1)[0],0)
        motion.update([],1.2)
        self.assertEqual(motion.update([hand(.8)],1.3)[:3],(0.,0.,1.))
        self.assertEqual(motion.update([hand(.2)],3)[:3],(0.,0.,1.))

    def test_two_hands_zoom_and_switching_modes_does_not_jump(self):
        motion=GestureMotion()
        motion.update([open_hand(.3),open_hand(.7)],1)
        self.assertGreater(motion.update([open_hand(.28),open_hand(.72)],1.1)[2],1)
        self.assertEqual(motion.update([hand(.2)],1.2)[:3],(0.,0.,1.))

    def test_pinched_hand_takes_over_rotation_before_other_hand_leaves(self):
        motion=GestureMotion()
        motion.update([open_hand(.3),open_hand(.7)],1)
        self.assertGreater(motion.update([open_hand(.28),open_hand(.72)],1.1)[2],1)
        self.assertEqual(motion.update([hand(.28),open_hand(.72)],1.2)[:3],(0.,0.,1.))
        dx,dy,zoom,_=motion.update([hand(.31),open_hand(.82)],1.3)
        self.assertGreater(dx,0);self.assertEqual(zoom,1.)
        dx,dy,zoom,_=motion.update([hand(.33)],1.4)
        self.assertGreater(dx,0);self.assertEqual(zoom,1.)

    def test_zoom_freezes_at_camera_edge_and_after_reacquisition(self):
        motion=GestureMotion()
        motion.update([open_hand(.3),open_hand(.7)],1)
        self.assertGreater(motion.update([open_hand(.28),open_hand(.72)],1.1)[2],1.)
        self.assertEqual(motion.update([open_hand(.28),open_hand(.96)],1.2)[2],1.)
        self.assertEqual(motion.update([open_hand(.28),open_hand(.72)],1.3)[2],1.)
        self.assertEqual(motion.update([open_hand(.28),open_hand(.721)],1.4)[2],1.)

    def test_open_hand_does_not_move_orbit(self):
        motion=GestureMotion(); h=hand(); h[4]=[.1,.1]
        self.assertEqual(motion.update([h],1)[:3],(0.,0.,1.))

    def test_two_pinches_separate_without_zoom_and_reacquire_safely(self):
        motion=GestureMotion()
        motion.update([hand(.3),hand(.7)],1)
        dx,dy,zoom,_=motion.update([hand(.28),hand(.72)],1.1)
        self.assertEqual((dx,dy,zoom),(0.,0.,1.))
        self.assertGreater(motion.separation_delta,0.)
        motion.update([hand(.3),hand(.7)],1.2)
        self.assertLess(motion.separation_delta,0.)
        motion.update([],1.3)
        motion.update([hand(.2),hand(.8)],1.4)
        self.assertEqual(motion.separation_delta,0.)


class SpaceUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.engine=FakeEngine(); self.pet=MagicMock(); self.pet.windowIcon.return_value=QIcon()
        self.pet.isVisible.return_value=False
        self.window=AlexAppWindow(self.engine,self.pet)

    def tearDown(self):
        self.window.hide()
        if self.window.space_page: self.window.space_page.camera.shutdown()
        if self.window.center_page: self.window.center_page.set_active(False)
        self.window.avatar.robot.close(); self.window.deleteLater(); self.app.processEvents()

    def test_lazy_pages_and_old_menu_replaced(self):
        self.assertIsNone(self.window.space_page)
        self.assertNotIn('Các cách nói đã học',[w.text() for w in self.window.findChildren(QPushButton)])
        self.window._show_page('center')
        self.assertIsNotNone(self.window.center_page)
        self.assertIsNone(self.window.space_page)
        self.engine.submit_text.assert_not_called()

    def test_camera_is_never_started_by_navigation(self):
        with patch('pet.space_view.CameraSession.start') as start:
            self.window.show(); self.window._show_page('space'); self.app.processEvents()
            page=self.window.space_page
            start.assert_not_called(); self.assertFalse(page.camera_button.isChecked())
            page.camera_button.click(); start.assert_called_once_with(0)

    def test_fullscreen_restores_sidebar_window_state_and_camera_choice(self):
        self.window.show();self.window._show_page('space');self.app.processEvents()
        page=self.window.space_page
        with patch.object(page.camera,'start') as start,patch.object(page.camera,'stop') as stop:
            page.fullscreen_button.click();self.app.processEvents()
            self.assertTrue(self.window.isFullScreen());self.assertTrue(self.window.sidebar.isHidden())
            self.assertIn('Thoát',page.fullscreen_button.text())
            QTest.keyClick(self.window,Qt.Key.Key_Escape);self.app.processEvents()
            self.assertFalse(self.window.isFullScreen());self.assertFalse(self.window.sidebar.isHidden())
            self.assertEqual(page.fullscreen_button.text(),'Toàn màn hình')
            start.assert_not_called();stop.assert_not_called()
            self.engine.interrupt.assert_not_called()
            page.fullscreen_button.click();self.app.processEvents()
            self.window._show_page('chat');self.app.processEvents()
            self.assertFalse(self.window.isFullScreen());self.assertFalse(self.window.sidebar.isHidden())

    def test_v_hold_toggles_immersive_fullscreen_without_changing_zoom_or_camera(self):
        self.window.show();self.window._show_page('space');self.app.processEvents()
        page=self.window.space_page;page.canvas.zoom=1.6
        current=[1.]
        with patch('pet.space_view.time.monotonic',side_effect=lambda:current[0]), \
             patch.object(page.camera,'start') as start, patch.object(page.camera,'stop') as stop:
            for t in (1.,1.25,1.5,1.75,2.15):
                h=v_hand()
                current[0]=t;page._hands([h]);self.app.processEvents()
                if t==1.:self.assertIn('V',page.immersive_hint.text())
            self.assertTrue(self.window.isFullScreen());self.assertTrue(page._immersive)
            self.assertEqual(page.canvas.zoom,1.6)
            for t in (2.4,2.7):current[0]=t;page._hands([open_hand()])
            for t in (3.4,3.7,4.,4.3,4.6):
                h=v_hand()
                current[0]=t;page._hands([h]);self.app.processEvents()
            self.assertFalse(self.window.isFullScreen());self.assertFalse(page._immersive)
            self.assertEqual(page.canvas.zoom,1.6)
            start.assert_not_called();stop.assert_not_called()

    def test_old_double_pinch_does_not_toggle_fullscreen(self):
        self.window.show();self.window._show_page('space');self.app.processEvents()
        page=self.window.space_page;current=[1.]
        with patch('pet.space_view.time.monotonic',side_effect=lambda:current[0]):
            for h,t in ((hand(),1.),(open_hand(),1.12),(hand(),1.25)):
                current[0]=t;page._hands([h]);self.app.processEvents()
        self.assertFalse(self.window.isFullScreen())

    def test_maximized_state_is_restored_after_fullscreen(self):
        self.window.showMaximized();self.window._show_page('space');self.app.processEvents()
        self.window.space_page.fullscreen_button.click();self.app.processEvents()
        self.window.space_page.fullscreen_button.click();self.app.processEvents()
        self.assertTrue(self.window.isMaximized())

    def test_fullscreen_uses_entire_scene_and_restores_controls(self):
        self.window.resize(1100,780);self.window.show();self.window._show_page('space')
        for _ in range(3):self.app.processEvents()
        page=self.window.space_page;page.canvas.zoom=2.;page.canvas.yaw=.6
        previous=page.canvas.size()
        page.fullscreen_button.click()
        for _ in range(3):self.app.processEvents()
        self.assertTrue(page._immersive);self.assertTrue(page.detail.isHidden())
        self.assertTrue(page.toolbar.isHidden());self.assertTrue(page.fullscreen_button.isHidden())
        self.assertTrue(page.immersive_exit.isVisible());self.assertTrue(page.immersive_camera.isVisible())
        self.assertGreaterEqual(page.view_stack.width(),self.window.width()-2)
        self.assertGreaterEqual(page.view_stack.height(),self.window.height()-2)
        self.assertGreater(page.canvas.width(),previous.width())
        self.assertGreater(page.canvas.height(),previous.height())
        self.assertEqual(page.canvas.zoom,2.);self.assertEqual(page.canvas.yaw,.6)
        page.immersive_exit.click()
        for _ in range(3):self.app.processEvents()
        self.assertFalse(page._immersive);self.assertFalse(page.detail.isHidden())
        self.assertFalse(page.toolbar.isHidden());self.assertFalse(page.fullscreen_button.isHidden())
        self.assertEqual(page.canvas.zoom,2.)

    def test_immersive_overlay_controls_camera_and_layer_without_auto_start(self):
        self.window.show();self.window._show_page('space');self.app.processEvents()
        page=self.window.space_page
        with patch.object(page.camera,'start') as start,patch.object(page.camera,'stop') as stop:
            page.fullscreen_button.click();self.app.processEvents()
            start.assert_not_called();stop.assert_not_called()
            page.immersive_camera.click();start.assert_called_once_with(0)
            page._camera_state(True)
            self.assertEqual(page.immersive_camera.text(),'Tắt camera')
            page.immersive_layer.click();self.app.processEvents()
            self.assertTrue(page.layer_button.isChecked());self.assertTrue(page.layer_text.isHidden())
            self.assertTrue(page.immersive_exit.isVisible())
            page.immersive_exit.click();self.app.processEvents()
            self.assertFalse(page.layer_text.isHidden());self.assertFalse(page.glass_effect.isHidden())
            self.assertTrue(page.camera_button.isChecked())

    def test_immersive_temporarily_hides_pet_without_changing_mic(self):
        self.window.show();self.window._show_page('space');self.app.processEvents()
        self.pet.isVisible.side_effect=(True,False)
        with patch.object(self.engine,'interrupt') as interrupt:
            self.window.space_page.fullscreen_button.click()
            self.pet.setVisible.assert_called_with(False)
            self.window.space_page.immersive_exit.click()
            self.pet.setVisible.assert_called_with(True)
            interrupt.assert_not_called()
        self.pet.isVisible.side_effect=None

    def test_motion_transition_cancels_pending_zoom(self):
        self.window.show();self.window._show_page('space');self.app.processEvents()
        page=self.window.space_page
        with patch('pet.space_view.time.monotonic',side_effect=(1.,1.1,1.2,1.3,1.4)):
            page._hands([open_hand(.3),open_hand(.7)])
            page._hands([open_hand(.28),open_hand(.72)])
            self.assertGreater(page.canvas.zoom,1.)
            page._hands([hand(.28),open_hand(.72)])
            locked=page.canvas.zoom
            for _ in range(5):page._motion_step()
            self.assertEqual(page.canvas.zoom,locked)
            page._hands([hand(.31),open_hand(.9)])
            page._hands([hand(.32)])
            self.assertEqual(page.canvas.zoom,locked)

    def test_changing_from_layer_separation_freezes_pending_animation(self):
        self.window.show();self.window._show_page('space');self.app.processEvents()
        page=self.window.space_page;released=open_hand(.75);released[4][0]-=.08
        clock=itertools.count(10)
        with patch('pet.space_view.time.monotonic',side_effect=lambda:next(clock)/10):
            page._hands([hand(.30),hand(.70)])
            page._hands([hand(.25),hand(.75)])
            self.assertTrue(page.layer_button.isChecked())
            page._hands([hand(.25),released])
            self.assertEqual(page.canvas.motion.mode,'rotate')
            self.assertEqual(page.gesture_animation.state(),QAbstractAnimation.State.Stopped)

    def test_leave_page_stops_camera_and_animation_without_touching_mic(self):
        self.window.show(); self.window._show_page('space'); self.app.processEvents()
        page=self.window.space_page
        self.assertTrue(page.canvas.timer.isActive())
        with patch.object(page.camera,'stop') as stop:
            self.window._show_page('chat'); self.app.processEvents()
            self.assertFalse(page.canvas.timer.isActive()); stop.assert_called()
        self.assertTrue(self.engine.paused.is_set())

    def test_minimize_closes_camera_and_restoring_never_reopens_it(self):
        self.window.show(); self.window._show_page('space'); self.app.processEvents()
        page=self.window.space_page
        with patch.object(page.camera,'stop') as stop,patch.object(page.camera,'start') as start:
            self.window.showMinimized(); self.app.processEvents()
            stop.assert_called(); self.assertFalse(page.canvas.timer.isActive())
            self.window.showNormal(); self.app.processEvents(); start.assert_not_called()

    def test_pause_selection_speed_and_reset(self):
        self.window.show(); self.window._show_page('space'); self.app.processEvents()
        page=self.window.space_page
        page.pause.click(); self.assertFalse(page.canvas.timer.isActive())
        page.pick.setCurrentIndex(5); self.assertEqual(page.planet_name.text(),'Sao Thổ')
        page.speed.setValue(62); self.assertEqual(page.canvas.rate,62)
        page.canvas.rotate_zoom(2,100,100); self.assertEqual(page.canvas.zoom,6.0)
        page.canvas.reset_view(); self.assertEqual(page.canvas.zoom,1)

    def test_robot_controls_use_same_engine_once(self):
        self.window._show_page('center'); center=self.window.center_page
        center.mic.click(); self.assertFalse(self.engine.paused.is_set())
        center.command_requested.emit('Mở YouTube cho tôi')
        self.engine.submit_text.assert_called_once()
        self.assertIs(self.window.pages.currentWidget(),self.window.chat_page)

    def test_stream_updates_center_without_changing_active_page(self):
        self.window._show_page('center')
        self.engine.reply.emit('Chào bạn.'); self.engine.reply.emit('Chào bạn. Mình đây.')
        self.assertEqual(self.window.center_page.latest.text(),'Chào bạn. Mình đây.')
        self.assertIs(self.window.pages.currentWidget(),self.window.center_page)

    def test_center_reflects_live_mic_if_opened_after_listening_began(self):
        self.engine.paused.clear()
        self.window._show_page('center')
        self.assertEqual(self.window.center_page.mode.text(),'Đang nghe')
        self.engine.paused.set(); self.window._sync()
        self.assertEqual(self.window.center_page.mode.text(),'Mic đang tắt')

    def test_close_stops_visuals_and_camera_but_keeps_pet(self):
        self.window.show(); self.window._show_page('space'); self.app.processEvents()
        self.window.close(); self.app.processEvents()
        self.assertFalse(self.window.space_page.canvas.timer.isActive())
        self.assertFalse(self.window.space_page.active)
        self.engine.interrupt.assert_not_called(); self.pet.quit_pet.assert_not_called()

    def test_tour_changes_selection_but_stops_on_pause_and_hide(self):
        self.window.show(); self.window._show_page('space'); self.app.processEvents()
        page=self.window.space_page
        with patch.object(page.camera,'start') as start:
            page.tour.click(); self.assertTrue(page.tour_timer.isActive())
            page.tour_timer.timeout.emit()
            self.assertEqual(page.pick.currentIndex(),3)
            self.assertEqual(page.portrait.index,3)
            page.pause.click(); self.assertFalse(page.tour_timer.isActive())
            page.pause.click(); self.assertTrue(page.tour_timer.isActive())
            self.window._show_page('chat'); self.app.processEvents()
            self.assertFalse(page.tour_timer.isActive()); start.assert_not_called()
            self.engine.submit_text.assert_not_called()

    def test_orbit_geometry_and_art_are_reused_when_time_changes(self):
        self.window._show_page('space'); canvas=self.window.space_page.canvas
        canvas.resize(650,400); canvas.grab()
        old_paths=canvas._paths; old_background=canvas.stars.cacheKey()
        sprites={i:p.cacheKey() for i,p in canvas.art.cache.items()}
        self.assertEqual(len(sprites),9)
        canvas.days+=50; canvas.grab()
        self.assertIs(canvas._paths,old_paths)
        self.assertEqual(canvas.stars.cacheKey(),old_background)
        self.assertEqual({i:p.cacheKey() for i,p in canvas.art.cache.items()},sprites)
        canvas.rotate_zoom(.2,0,1); canvas.grab()
        self.assertIsNot(canvas._paths,old_paths)
        self.assertEqual(canvas.stars.cacheKey(),old_background)

    def test_compact_layout_keeps_controls_within_window(self):
        self.window.resize(800,580); self.window.show(); self.window._show_page('space')
        for _ in range(3): self.app.processEvents()
        page=self.window.space_page
        self.assertLessEqual(self.window.width(),800)
        self.assertLessEqual(self.window.height(),580)
        for widget in (page.canvas,page.pick,page.pause,page.tour,page.camera_button,page.speed):
            pos=widget.mapTo(page,QPoint(0,0))
            self.assertGreaterEqual(pos.x(),0); self.assertGreaterEqual(pos.y(),0)
            self.assertLessEqual(pos.x()+widget.width(),page.width())
            self.assertLessEqual(pos.y()+widget.height(),page.height())
        self.assertFalse(page.camera_button.isChecked())

    def test_clicking_visible_planet_selects_its_detail(self):
        self.window.resize(1280,860); self.window.show(); self.window._show_page('space')
        self.app.processEvents(); page=self.window.space_page
        page.canvas.set_playing(False); page.canvas.grab()
        point=next(point for i,point,_ in page.canvas.hit_points if i==5)
        QTest.mouseClick(page.canvas,Qt.MouseButton.LeftButton,pos=point.toPoint())
        self.assertEqual(page.pick.currentIndex(),5)
        self.assertEqual(page.planet_name.text(),'Sao Thổ')
        self.assertEqual(page.portrait.index,5)

    def test_rotation_freezes_on_pause_hide_and_effects_off(self):
        self.window.show(); self.window._show_page('space'); self.app.processEvents()
        page=self.window.space_page; canvas=page.canvas
        canvas.last_tick-=.08; canvas._tick()
        moving=page.portrait.seconds; self.assertGreater(moving,0)
        page.pause.click(); canvas.last_tick-=1; canvas._tick()
        self.assertEqual(page.portrait.seconds,moving)
        page.pause.click(); page.effects.setChecked(False)
        days=canvas.days; canvas.last_tick-=.08; canvas._tick()
        self.assertEqual(page.portrait.seconds,moving)
        self.assertGreater(canvas.days,days)
        self.window._show_page('chat'); canvas.last_tick-=1; canvas._tick()
        self.assertEqual(page.portrait.seconds,moving)
        self.assertFalse(canvas.timer.isActive())

    def test_portrait_changes_surface_without_growing_scene_cache(self):
        self.window._show_page('space'); page=self.window.space_page
        first=page.portrait.grab().toImage()
        sprites={i:p.cacheKey() for i,p in page.canvas.art.cache.items()}
        page.portrait.set_time(9)
        second=page.portrait.grab().toImage()
        self.assertNotEqual(first,second)
        cached=page.canvas.art._portrait.cacheKey()
        page.portrait.grab()
        self.assertEqual(cached,page.canvas.art._portrait.cacheKey())
        for i in range(8):
            page.pick.setCurrentIndex(i); page.portrait.grab()
        self.assertEqual({i:p.cacheKey() for i,p in page.canvas.art.cache.items()},sprites)

    def test_portrait_renders_at_device_resolution(self):
        self.window._show_page('space'); page=self.window.space_page
        art=page.canvas.art
        from PySide6.QtCore import QPointF
        sides=[]
        for dpr in (1.,2.):
            image=QImage(int(300*dpr),int(300*dpr),QImage.Format.Format_ARGB32)
            image.setDevicePixelRatio(dpr); image.fill(Qt.GlobalColor.transparent)
            p=QPainter(image); art.draw(p,2,QPointF(150,150),70,seconds=1); p.end()
            sides.append(art._portrait.width())
        self.assertGreaterEqual(sides[1],sides[0]*1.8)
        self.assertLessEqual(sides[1],1024)

    def test_detail_resolution_follows_transform_and_stays_bounded(self):
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QPixmap
        art=self.window.space_page.canvas.art if self.window.space_page else None
        if art is None:
            self.window._show_page('space'); art=self.window.space_page.canvas.art
        image=QImage(1200,1200,QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        with patch.object(art,'_render',return_value=QPixmap(4,4)):
            p=QPainter(image)
            art.draw_detail(p,2,QPointF(50,50),50); initial=art._detail_key[1]
            p.scale(3,3)
            art.draw_detail(p,2,QPointF(50,50),50); zoomed=art._detail_key[1]
            p.scale(100,100)
            art.draw_detail(p,2,QPointF(0,0),50); maximum=art._detail_key[1]
            p.end()
        self.assertGreater(zoomed,initial)
        self.assertEqual(maximum,1536)

    def test_nasa_earth_asset_is_local_and_has_fallback(self):
        from pet.planet_surface import _blue_marble
        earth=_blue_marble()
        self.assertIsNotNone(earth)
        self.assertEqual(earth.shape,(1024,2048,3))
        self.assertEqual(str(earth.dtype),'uint8')
        with patch('pet.planet_surface.QImage') as image:
            image.return_value.isNull.return_value=True
            self.assertIsNone(_blue_marble())

    def test_all_planets_have_local_maps_with_bounded_resolution_and_fallback(self):
        from pet.planet_surface import _mapped_planet, _texture, sphere
        for index in range(8):
            with self.subTest(index=index):
                self.assertEqual(_mapped_planet(index).shape,(512,1024,3))
                self.assertEqual(_mapped_planet(index,True).shape,(1024,2048,3))
                self.assertFalse(sphere(index,128).isNull())
        self.assertEqual(_texture.cache_info().maxsize,10)
        with patch('pet.planet_surface.QImage') as image:
            image.return_value.isNull.return_value=True
            self.assertIsNone(_mapped_planet(0))

    def test_above_view_eases_and_manual_drag_takes_over(self):
        self.window.show(); self.window._show_page('space'); self.app.processEvents()
        canvas=self.window.space_page.canvas
        old=canvas.tilt; canvas.view_from_above()
        self.assertEqual(canvas.tilt,old)
        canvas.last_tick-=.05; canvas._tick()
        self.assertGreater(canvas.tilt,old); self.assertLess(canvas.tilt,1.5)
        canvas.rotate_zoom(.1,-.1,1)
        self.assertIsNone(canvas._view_target)

    def test_sphere_has_owned_alpha_pixels_and_wraps_rotation(self):
        from pet.planet_surface import sphere
        a=sphere(2,160,0); b=sphere(2,160,math.tau)
        self.assertEqual(a,b)
        self.assertEqual(a.pixelColor(0,0).alpha(),0)
        self.assertEqual(a.pixelColor(80,80).alpha(),255)
        self.assertNotEqual(a,sphere(2,160,1))
        # A subsequent render must not invalidate the previous image's memory.
        self.assertEqual(a,b)


if __name__=='__main__': unittest.main()
