import math
import itertools
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QAbstractAnimation, QPoint, QPointF, Qt
from PySide6.QtGui import QIcon
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pet.app_window import AlexAppWindow
from pet.orbit_math import PLANETS
from pet.planet_layers import EARTH, layers_for
from test_app_window import FakeEngine
from test_space_view import hand, open_hand


class PlanetLayerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.engine=FakeEngine(); self.pet=MagicMock(); self.pet.windowIcon.return_value=QIcon()
        self.pet.isVisible.return_value=False
        self.window=AlexAppWindow(self.engine,self.pet)
        self.window.resize(1280,860); self.window.show(); self.window._show_page('space')
        self.app.processEvents(); self.page=self.window.space_page

    def tearDown(self):
        self.window.hide(); self.page.camera.shutdown()
        self.window.avatar.robot.close(); self.window.deleteLater(); self.app.processEvents()

    def finish_animation(self):
        self.page.layer_animation.setCurrentTime(self.page.layer_animation.duration())
        self.app.processEvents()

    def test_every_planet_has_named_interior_and_earth_has_four_layers(self):
        self.assertEqual(len(PLANETS),8)
        self.assertEqual([x.name for x in layers_for(2)],
                         ['Vỏ Trái Đất','Lớp phủ','Lõi ngoài','Lõi trong'])
        self.assertIs(layers_for(2),EARTH)
        for index in range(8):
            self.assertGreaterEqual(len(layers_for(index)),3)
            self.page.pick.setCurrentIndex(index)
            self.assertEqual(self.page.layer_canvas.index,index)
        self.assertIn('Hydro',layers_for(4)[1].name)
        self.assertIn('Chất lưu',layers_for(7)[1].name)

    def test_stage_description_follows_split_and_selection_can_be_inspected(self):
        view=self.page.layer_canvas
        for index in range(8):
            view.set_planet(index)
            count=len(layers_for(index))
            for stage in range(count):
                view.set_amount((stage+.2)/count)
                self.assertEqual(view.selected_layer,stage)
            view.selected_layer=0
            view.set_amount((count-.1)/count)
            self.assertEqual(view.selected_layer,0)  # Manual selection persists within a stage.
            view.set_amount(0.)
            self.assertEqual(view.selected_layer,0)
        view.set_amount(.7)
        view.set_planet(6)
        self.assertEqual(view.selected_layer,2)

    def test_venus_clouds_and_giant_interiors_are_planet_specific(self):
        self.assertIn('khí quyển',layers_for(1)[0].name)
        self.assertIn('lỏng',layers_for(3)[2].description)
        self.assertIn('Sao Mộc',layers_for(4)[0].description)
        self.assertIn('Sao Thổ',layers_for(5)[0].description)
        self.assertIn('Sao Thiên Vương',layers_for(6)[0].description)
        self.assertIn('Sao Hải Vương',layers_for(7)[0].description)

    def test_toggle_animates_slider_and_restores_orbit(self):
        page=self.page
        with patch.object(page.camera,'start') as start:
            page.layer_button.click()
            self.assertIs(page.view_stack.currentWidget(),page.layer_canvas)
            self.assertFalse(page.canvas.timer.isActive())
            self.assertTrue(page.layer_canvas.timer.isActive())
            self.assertEqual(page.layer_animation.state(),QAbstractAnimation.State.Running)
            self.finish_animation()
            self.assertAlmostEqual(page.layer_canvas.amount,1.)
            self.assertEqual(page.layer_amount.value(),100)
            page.layer_amount.setValue(45)
            self.assertAlmostEqual(page.layer_canvas.amount,.45)
            page.layer_button.click(); self.finish_animation()
            self.assertIs(page.view_stack.currentWidget(),page.canvas)
            self.assertTrue(page.canvas.timer.isActive())
            self.assertFalse(page.layer_canvas.timer.isActive())
            self.assertEqual(page.layer_canvas.amount,0.)
            start.assert_not_called()

    def test_zoom_keeps_point_under_pointer_and_reaches_six_times(self):
        canvas=self.page.canvas; canvas.resize(650,400)
        point=(2.5,.4,0.)
        anchor,_=canvas._screen(point)
        canvas.zoom_at(2.,anchor)
        new,_=canvas._screen(point)
        self.assertLess(math.hypot(anchor.x()-new.x(),anchor.y()-new.y()),.001)
        canvas.rotate_zoom(0,0,100)
        self.assertEqual(canvas.zoom,6.)
        canvas.reset_view(); self.assertEqual(canvas.zoom,1.)
        self.assertEqual(canvas.pan,QPointF())

    def test_layer_zoom_pan_click_and_reset(self):
        page=self.page; page.layer_button.click(); self.finish_animation()
        self.assertGreaterEqual(page.zoom_out.width(),38)
        self.assertGreaterEqual(page.zoom_in.width(),38)
        view=page.layer_canvas; view.grab()
        self.assertEqual(len(view.hit_boxes),len(layers_for(view.index)))
        box=next(box for index,box in view.hit_boxes if index==2)
        QTest.mouseClick(view,Qt.MouseButton.LeftButton,pos=box.center().toPoint())
        self.assertEqual(view.selected_layer,2)
        page.zoom_in.click(); self.assertGreater(view.zoom,1.)
        self.assertEqual(page.zoom_value.text(),f'{round(view.zoom*100)}%')
        view.pan=QPointF(25,12); page.overview.click()
        self.assertEqual(view.zoom,1.); self.assertEqual(view.pan,QPointF())

    def test_spherical_layers_change_with_split_and_keep_labels_clickable(self):
        page=self.page; page.layer_button.click(); self.finish_animation()
        view=page.layer_canvas
        view.set_amount(0.)
        intact=view.grab().toImage()
        self.assertEqual(view.hit_boxes,[])
        view.set_amount(.5)
        halfway=view.grab().toImage()
        self.assertNotEqual(intact,halfway)
        view.set_amount(1.)
        expanded=view.grab().toImage()
        self.assertNotEqual(halfway,expanded)
        self.assertEqual(len(view.hit_boxes),len(layers_for(view.index)))
        for i,box in view.hit_boxes:
            QTest.mouseClick(view,Qt.MouseButton.LeftButton,pos=box.center().toPoint())
            self.assertEqual(view.selected_layer,i)
        for index in range(8):
            page.pick.setCurrentIndex(index)
            self.assertFalse(view.grab().isNull())
            self.assertEqual(len(view.hit_boxes),len(layers_for(index)))

    def test_four_ordered_breaking_stages_and_reversal(self):
        view=self.page.layer_canvas
        self.page.layer_button.click(); self.finish_animation()
        images=[]
        for value in (12,37,62,87):
            self.page.layer_amount.setValue(value)
            stage,progress=view.stage_for(view.amount,4)
            self.assertEqual(stage,len(images)); self.assertAlmostEqual(progress,.48,places=2)
            self.assertIn(f'Điểm {stage+1}/4',self.page.layer_text.text())
            images.append(view.grab().toImage())
        for first,second in zip(images,images[1:]):self.assertNotEqual(first,second)
        self.page.layer_amount.setValue(24)
        self.assertEqual(view.stage_for(view.amount,4)[0],0)
        self.assertEqual(view.stage_for(1.,4),(3,1.))
        self.assertEqual(view.stage_for(1.,3),(2,1.))

    def test_shards_cover_the_intact_disc_without_overlap(self):
        view=self.page.layer_canvas
        for radius in (.12,.35,.63,.85):
            for i in range(40):
                angle=math.tau*(i+.173)/40
                point=QPointF(radius*math.cos(angle),radius*math.sin(angle))
                self.assertEqual(sum(path.contains(point) for path,_ in view._shards),1)

    def test_completed_shard_cache_is_bounded_and_cleared(self):
        page=self.page; page.layer_button.click(); self.finish_animation()
        view=page.layer_canvas; page.glass_effect.setChecked(True); view.set_amount(.87); view.grab()
        self.assertEqual(len(view._completed_cache),3)
        cached=list(view._completed_cache.values())
        view.grab()
        self.assertEqual([p.cacheKey() for p in cached],
                         [p.cacheKey() for p in view._completed_cache.values()])
        page.pick.setCurrentIndex(3)
        self.assertEqual(len(view._completed_cache),0)

    def test_cutaway_and_optional_glass_for_every_planet(self):
        from pet.planet_layers import LAYER_RADII
        page=self.page; page.layer_button.click(); self.finish_animation()
        view=page.layer_canvas
        self.assertTrue(page.glass_effect.isChecked())
        page.glass_effect.setChecked(False)
        for index in range(8):
            page.pick.setCurrentIndex(index)
            self.assertEqual(len(LAYER_RADII[index]),len(layers_for(index)))
            self.assertEqual(LAYER_RADII[index][0],1.)
            self.assertTrue(all(a>b>0 for a,b in zip(LAYER_RADII[index],LAYER_RADII[index][1:])))
            view.set_amount(0.); intact=view.grab().toImage()
            view.set_amount(.5); half=view.grab().toImage()
            view.set_amount(1.); cut=view.grab().toImage()
            self.assertNotEqual(intact,half); self.assertNotEqual(half,cut)
        page.glass_effect.setChecked(True)
        self.assertTrue(view.glass_effect)
        glass=view.grab().toImage()
        page.glass_effect.setChecked(False)
        self.assertFalse(view.glass_effect)
        self.assertNotEqual(glass,view.grab().toImage())

    def test_only_innermost_region_stays_intact_for_every_planet(self):
        page=self.page; page.layer_button.click(); self.finish_animation()
        view=page.layer_canvas;page.glass_effect.setChecked(True)
        for index in range(8):
            page.pick.setCurrentIndex(index);view._completed_cache.clear()
            final=len(layers_for(index))-1
            with patch.object(view,'_draw_shards',wraps=view._draw_shards) as shattered:
                for amount in (0.,.15,.3,.49,.51,.74,.76,.99,1.):
                    view.set_amount(amount);view.grab()
                indices={call.args[3] for call in shattered.call_args_list}
                self.assertNotIn(final,indices)
                self.assertEqual(indices,set(range(final)))
                if index==2:self.assertIn(2,indices)  # Outer core can break; inner cannot.

    def test_displayed_shards_follow_planet_radii(self):
        from pet.planet_layers import LAYER_RADII
        page=self.page;page.layer_button.click();self.finish_animation()
        view=page.layer_canvas;view.set_amount(1.)
        for index in (0,2,3,4,7):
            page.pick.setCurrentIndex(index);view._completed_cache.clear()
            _,radius=view._scene_layout(float(view.width()),float(view.height()))
            with patch.object(view,'_draw_completed',wraps=view._draw_completed) as completed:
                view.grab()
                for call in completed.call_args_list:
                    layer=call.args[3]
                    self.assertAlmostEqual(call.args[2],radius*LAYER_RADII[index][layer])

    def test_material_cache_is_bounded_and_cleared_on_planet_change(self):
        page=self.page;page.layer_button.click();self.finish_animation()
        view=page.layer_canvas
        for index in range(8):
            page.pick.setCurrentIndex(index);view.grab()
            self.assertLessEqual(len(view._material_cache),8)
        self.assertGreater(len(view._material_cache),0)
        view.set_active(False)
        self.assertEqual(len(view._material_cache),0)

    def test_completed_shards_cache_adapts_to_zoom(self):
        page=self.page; page.layer_button.click(); self.finish_animation()
        view=page.layer_canvas; page.glass_effect.setChecked(True); view.set_amount(.87); view.grab()
        previous=list(view._completed_cache.values())[-1].width()
        view.zoom=2.2; view.grab()
        self.assertEqual(len(view._completed_cache),3)
        current=list(view._completed_cache.values())[-1].width()
        self.assertGreater(current,previous)
        self.assertLessEqual(current,1536)

    def test_layer_labels_remain_clickable_when_zoomed_and_panned(self):
        page=self.page; page.layer_button.click(); self.finish_animation()
        view=page.layer_canvas; view.zoom=2.; view.pan=QPointF(75,-30); view.grab()
        box=next(box for index,box in view.hit_boxes if index==2)
        QTest.mouseClick(view,Qt.MouseButton.LeftButton,pos=box.center().toPoint())
        self.assertEqual(view.selected_layer,2)

    def test_hand_separation_reaches_all_four_stages(self):
        page=self.page; seen=set(); clock=itertools.count(10)
        with patch('pet.space_view.time.monotonic',side_effect=lambda: next(clock)/10):
            page._hands([hand(.42),hand(.58)])
            for step in range(1,31):
                page._hands([hand(.42-.01*step),hand(.58+.01*step)])
                page.gesture_animation.setCurrentTime(page.gesture_animation.duration())
                seen.add(page.layer_canvas.stage_for(page.layer_canvas.amount,4)[0])
        self.assertEqual(seen,{0,1,2,3})

    def test_hide_stops_all_animations_and_camera_never_starts(self):
        page=self.page
        with patch.object(page.camera,'start') as start, patch.object(page.camera,'stop') as stop:
            page.layer_button.click()
            self.window._show_page('chat'); self.app.processEvents()
            self.assertFalse(page.canvas.timer.isActive())
            self.assertFalse(page.layer_canvas.timer.isActive())
            self.assertEqual(page.layer_animation.state(),QAbstractAnimation.State.Stopped)
            stop.assert_called(); start.assert_not_called()

    def test_compact_layout_reaches_controls(self):
        self.window.resize(800,580); self.app.processEvents()
        page=self.page; page.layer_button.click(); self.finish_animation()
        for widget in (page.layer_canvas,page.pick,page.layer_button,page.zoom_out,
                       page.zoom_in,page.camera_button,page.layer_amount):
            pos=widget.mapTo(page,QPoint(0,0))
            self.assertGreaterEqual(pos.x(),0,widget.objectName())
            self.assertGreaterEqual(pos.y(),0,widget.objectName())
            self.assertLessEqual(pos.x()+widget.width(),page.width(),widget.objectName())
            self.assertLessEqual(pos.y()+widget.height(),page.height(),widget.objectName())

    def test_planet_portrait_does_not_overlap_facts_on_laptop_sizes(self):
        for width,height in ((1122,810),(1280,860),(800,580)):
            with self.subTest(size=(width,height)):
                self.window.resize(width,height); self.app.processEvents()
                portrait=self.page.portrait.geometry()
                facts=self.page.planet_facts.geometry()
                self.assertLess(portrait.bottom(),facts.top(),
                                f'portrait {portrait}, facts {facts}')

    def test_gestures_open_and_close_layers_without_zoom(self):
        page=self.page
        clock=itertools.count(10)
        with patch('pet.space_view.time.monotonic',side_effect=lambda: next(clock)/10):
            page._hands([hand(.3),hand(.7)])
            self.assertFalse(page.layer_button.isChecked())
            page._hands([hand(.25),hand(.75)])
            self.assertTrue(page.layer_button.isChecked())
            page.gesture_animation.setCurrentTime(page.gesture_animation.duration())
            self.assertGreater(page.layer_canvas.amount,0.)
            before=page.layer_canvas.amount
            self.assertEqual(page.layer_canvas.zoom,1.)
            page._hands([hand(.27),hand(.73)])
            page.gesture_animation.setCurrentTime(page.gesture_animation.duration())
            self.assertLess(page.layer_canvas.amount,before)
            page._hands([])
            page._hands([open_hand(.3),open_hand(.7)])
            page._hands([open_hand(.25),open_hand(.75)])
            self.assertGreater(page.layer_canvas.zoom,1.)

    def test_gesture_closes_layers_returns_to_orbit_and_does_not_reopen_on_jitter(self):
        page=self.page
        clock=itertools.count(10)
        with patch('pet.space_view.time.monotonic',side_effect=lambda: next(clock)/10):
            page._hands([hand(.30),hand(.70)])
            page._hands([hand(.25),hand(.75)])
            self.assertTrue(page.layer_button.isChecked())
            page._hands([hand(.30),hand(.70)])
            self.assertFalse(page.layer_button.isChecked())
            self.finish_animation()
            self.assertIs(page.view_stack.currentWidget(),page.canvas)
            page._hands([hand(.29),hand(.71)])
            self.assertFalse(page.layer_button.isChecked())
            page._hands([])
            page._hands([hand(.30),hand(.70)])
            page._hands([hand(.26),hand(.74)])
            self.assertTrue(page.layer_button.isChecked())

    def test_gesture_interpolates_and_accumulates_without_jumping(self):
        page=self.page; clock=itertools.count(10)
        with patch('pet.space_view.time.monotonic',side_effect=lambda: next(clock)/10):
            page._hands([hand(.30),hand(.70)])
            page._hands([hand(.25),hand(.75)])
            first_target=page._gesture_target
            self.assertGreater(first_target,0.)
            self.assertAlmostEqual(page.layer_canvas.amount,0.)
            page.gesture_animation.setCurrentTime(50)
            self.assertGreater(page.layer_canvas.amount,0.)
            self.assertLess(page.layer_canvas.amount,first_target)
            page._hands([hand(.24),hand(.76)])
            self.assertGreater(page._gesture_target,first_target)
            target=page._gesture_target
            page.gesture_animation.setCurrentTime(page.gesture_animation.duration())
            self.assertAlmostEqual(page.layer_canvas.amount,target,places=5)
            page._hands([])
            page._hands([hand(.30),hand(.70)])
            self.assertAlmostEqual(page.layer_canvas.amount,target,places=5)

    def test_slider_and_hide_cancel_pending_gesture_animation(self):
        page=self.page; clock=itertools.count(10)
        with patch('pet.space_view.time.monotonic',side_effect=lambda: next(clock)/10):
            page._hands([hand(.30),hand(.70)])
            page._hands([hand(.25),hand(.75)])
            self.assertEqual(page.gesture_animation.state(),QAbstractAnimation.State.Running)
            page.layer_amount.setValue(40)
            self.assertEqual(page.gesture_animation.state(),QAbstractAnimation.State.Stopped)
            self.assertIsNone(page._gesture_target)
            self.assertAlmostEqual(page.layer_canvas.amount,.4)
            page._hands([])
            page._hands([hand(.30),hand(.70)])
            page._hands([hand(.29),hand(.71)])
            self.assertEqual(page.gesture_animation.state(),QAbstractAnimation.State.Running)
            self.window._show_page('chat')
            self.assertEqual(page.gesture_animation.state(),QAbstractAnimation.State.Stopped)

    def test_orbit_rotates_full_turn_and_layers_rotate_surface(self):
        orbit=self.page.canvas
        before=orbit.tilt
        orbit.rotate_zoom(0,math.pi,1.)
        self.assertAlmostEqual(abs((orbit.tilt-before+math.pi) % math.tau-math.pi),math.pi)
        orbit.rotate_zoom(0,math.pi,1.)
        self.assertAlmostEqual(orbit.tilt,before)
        view=self.page.layer_canvas
        view.rotate_zoom(math.pi,0,1.)
        self.assertAlmostEqual(view.angle,math.pi)
        view.rotate_zoom(math.pi,0,1.)
        self.assertAlmostEqual(view.angle,0.)


if __name__=='__main__': unittest.main()
