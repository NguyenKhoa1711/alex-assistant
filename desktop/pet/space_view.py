"""Offline solar-system view, with optional process-isolated hand tracking."""
from __future__ import annotations
import json
import math
import time
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QProcess, QVariantAnimation, QEasingCurve, QEvent
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QCheckBox, QFrame, QSlider, QApplication, QStackedWidget)
from .config import ROOT
from .orbit_math import PLANETS, orbital_point, project, GestureMotion, FullscreenV
from .orbit_scene import OrbitCanvas, PlanetPortrait
from .planet_layers import PlanetLayersCanvas, layers_for


SPACE_STYLE = '''
QWidget#spacePage, QWidget#commandPage { background: #080f1c; color: #dae6f3; }
QWidget#spacePage QLabel, QWidget#commandPage QLabel { color: #d9e7f5; background: transparent; }
QWidget#spacePage QLabel#subtle, QWidget#commandPage QLabel#subtle { color: #8eabc2; font-size: 12px; }
QWidget#spacePage QLabel#spaceTitle, QWidget#commandPage QLabel#spaceTitle { color: #f6f9ff; font-size: 28px; font-weight: 650; }
QWidget#spacePage QPushButton, QWidget#commandPage QPushButton { background: #142438; color: #cce2ef; border: 1px solid #2a4257; padding: 9px 12px; border-radius: 9px; }
QWidget#spacePage QPushButton:hover, QWidget#commandPage QPushButton:hover { background: #213b50; border-color: #56c4b7; }
QWidget#spacePage QPushButton:checked { color: #071b20; background: #79d5c3; }
QWidget#spacePage QComboBox { background: #142438; color: #d7e8f3; border: 1px solid #2a4257; border-radius: 7px; padding: 7px; }
QWidget#spacePage QComboBox QAbstractItemView { background: #142438; color: #d7e8f3; selection-background-color: #285a60; }
QWidget#spacePage QCheckBox { color: #afc9da; }
QWidget#spacePage QFrame#dataCard, QWidget#commandPage QFrame#dataCard { background: #101e30; border: 1px solid #243c50; border-radius: 14px; }
QWidget#spacePage QSlider::groove:horizontal { background: #294153; height: 4px; border-radius: 2px; }
QWidget#spacePage QSlider::handle:horizontal { background: #79d5c3; width: 12px; margin: -4px 0; border-radius: 6px; }
QWidget#spacePage { background: #080f1b; }
QWidget#spacePage QLabel#spaceTitle { font-size: 29px; }
QWidget#spacePage QLabel#overline { color: #8ccfc6; font-size: 10px; font-weight: 600; letter-spacing: 2px; }
QWidget#spacePage QLabel#planetTitle { color: #f4f5ef; font-size: 23px; font-weight: 600; }
QWidget#spacePage QLabel#planetFact { color: #cedce6; font-size: 13px; }
QWidget#spacePage QFrame#planetCard { background: #101d2b; border: 1px solid #283e50; border-radius: 18px; }
QWidget#spacePage QFrame#orbitTools { background: #101c2a; border: 1px solid #22394a; border-radius: 12px; }
QWidget#spacePage QPushButton#tourButton { color: #e7d5a9; border-color: #73634b; background: #262a2c; }
QWidget#spacePage QPushButton#tourButton:checked { color: #071b20; background: #e7cd95; }
QWidget#spacePage QPushButton#viewButton { padding: 6px 9px; font-size: 11px; }
QWidget#spacePage QPushButton#layerButton { color: #bfece0; border-color: #4c9086; background: #163d40; font-weight: 600; }
QWidget#spacePage QPushButton#layerButton:checked { color: #10251f; background: #99e3cd; }
QWidget#spacePage QLabel#zoomValue { color: #c9e2df; font-size: 11px; }
'''


def text(value, name='', wrap=False):
    w = QLabel(value)
    w.setObjectName(name)
    w.setTextFormat(Qt.TextFormat.PlainText)
    w.setWordWrap(wrap)
    return w


def action(title, callback):
    w = QPushButton(title)
    w.setCursor(Qt.CursorShape.PointingHandCursor)
    w.clicked.connect(callback)
    return w


class CameraSession(QObject):
    hands = Signal(list)
    status = Signal(str)
    running = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None
        self.buffer = bytearray()
        self.deadline = QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.timeout.connect(self._timeout)

    def start(self, index=0):
        if self.process is not None:
            return
        if any(p.state() != QProcess.ProcessState.NotRunning for p in self.findChildren(QProcess)):
            self.running.emit(False)
            self.status.emit('Camera đang đóng phiên trước. Bạn bấm lại sau một giây nhé.')
            return
        exe = ROOT / '.venv-gestures/Scripts/python.exe'
        model = ROOT / 'assets/gestures/hand_landmarker.task'
        if not exe.is_file() or not model.is_file():
            self.status.emit('Chưa có bộ cử chỉ tay. Bạn vẫn có thể dùng chuột.')
            self.running.emit(False)
            return
        self.buffer.clear()
        proc = QProcess(self)
        self.process = proc
        proc.setProgram(str(exe))
        proc.setArguments(['-u', str(Path(__file__).with_name('gesture_worker.py')),
                           '--model', str(model), '--camera', str(index)])
        proc.readyReadStandardOutput.connect(self._read)
        # Drain and discard library stderr; never retain frames or session details.
        proc.readyReadStandardError.connect(lambda: proc.readAllStandardError())
        proc.finished.connect(lambda *_: self._finished(proc))
        proc.errorOccurred.connect(lambda *_: self._failed(proc))
        proc.start()
        self.running.emit(True)
        self.status.emit('Đang mở camera trên máy này…')
        self.deadline.start(15000)

    def _failed(self, proc):
        if self.process is proc:
            self.stop()
            self.status.emit('Không mở được camera. Kiểm tra quyền Camera trong Windows hoặc ứng dụng đang dùng camera.')

    def _timeout(self):
        self.stop()
        self.status.emit('Camera không phản hồi. Đã dừng; bạn có thể thử camera khác.')

    def _read(self):
        proc = self.process
        if proc is None:
            return
        self.buffer.extend(bytes(proc.readAllStandardOutput()))
        if len(self.buffer) > 65536:
            self.stop()
            return
        while b'\n' in self.buffer:
            line, _, self.buffer = self.buffer.partition(b'\n')
            try:
                value = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue
            if not isinstance(value, dict):
                continue
            if value.get('error'):
                self._failed(proc)
                return
            if value.get('ready'):
                self.deadline.start(5000)
                self.status.emit('Camera đang bật • hình ảnh chỉ xử lý trên máy')
            hands = value.get('hands')
            if isinstance(hands, list) and len(hands) <= 2:
                valid = all(isinstance(h, list) and len(h) == 21 and all(
                    isinstance(p, list) and len(p) == 2 and all(isinstance(v, (int, float)) and math.isfinite(v) and -1 <= v <= 2 for v in p)
                    for p in h) for h in hands)
                if valid:
                    self.deadline.start(5000)
                    self.hands.emit(hands)

    def stop(self):
        self.deadline.stop()
        proc = self.process
        self.process = None
        self.buffer.clear()
        self.hands.emit([])
        self.running.emit(False)
        if proc is not None:
            proc.write(b'stop\n')
            proc.closeWriteChannel()
            # Release a stuck camera backend too; never block the GUI waiting for it.
            QTimer.singleShot(700, proc, lambda: proc.kill() if proc.state() != QProcess.ProcessState.NotRunning else None)

    def _finished(self, proc):
        if self.process is proc:
            self.process = None
            self.deadline.stop()
            self.hands.emit([])
            self.running.emit(False)
            self.status.emit('Camera đã dừng. Bấm Bật camera để thử lại.')
        proc.deleteLater()

    def shutdown(self):
        # Called at process exit, not while changing pages.
        processes = self.findChildren(QProcess)
        self.stop()
        for proc in processes:
            if proc.state() != QProcess.ProcessState.NotRunning:
                proc.kill()
                proc.waitForFinished(500)


class SpacePage(QWidget):
    fullscreen_requested = Signal()
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName('spacePage'); self.setStyleSheet(SPACE_STYLE)
        self.active = False
        self._tight = False
        self._immersive = False
        layout = QVBoxLayout(self); layout.setContentsMargins(24,22,24,18); layout.setSpacing(12)
        self.page_layout=layout
        self.page_overline=text('ĐÀI QUAN SÁT  /  ALEX', 'overline');layout.addWidget(self.page_overline)
        self.page_title=text('Vũ trụ Alex','spaceTitle')
        title = QHBoxLayout(); title.addWidget(self.page_title,1)
        self.tour = action('Tham quan tự động', self._tour_changed)
        self.tour.setObjectName('tourButton'); self.tour.setCheckable(True)
        title.addWidget(self.tour)
        self.pause = action('Tạm dừng', self._pause)
        title.addWidget(self.pause)
        self.fullscreen_button=action('Toàn màn hình',self.fullscreen_requested.emit)
        self.fullscreen_button.setAccessibleName('Vũ trụ toàn màn hình')
        self.fullscreen_button.setToolTip('Giơ ngón trỏ và giữa hình chữ V khoảng một giây để đổi toàn màn hình; Esc để thoát.')
        title.addWidget(self.fullscreen_button)
        layout.addLayout(title)
        self.intro = text('Một góc nhỏ của vũ trụ. Chọn một hành tinh để bắt đầu khám phá.', 'subtle', True)
        layout.addWidget(self.intro)
        self.canvas = OrbitCanvas()
        self.layer_canvas = PlanetLayersCanvas(self.canvas.art)
        self._gesture_closed_latched = False
        self.view_stack = QStackedWidget()
        self.view_stack.addWidget(self.canvas); self.view_stack.addWidget(self.layer_canvas)
        body_layout = QHBoxLayout(); body_layout.setSpacing(12);self.body_layout=body_layout
        body_layout.addWidget(self.view_stack,1)
        self.detail = QFrame(); self.detail.setObjectName('planetCard'); self.detail.setFixedWidth(224)
        detail = QVBoxLayout(self.detail); detail.setContentsMargins(17,18,17,16); detail.setSpacing(9)
        self.destination_label=text('ĐIỂM ĐẾN CỦA BẠN','overline'); detail.addWidget(self.destination_label)
        self.planet_name = text('','planetTitle'); detail.addWidget(self.planet_name)
        self.portrait = PlanetPortrait(self.canvas.art); detail.addWidget(self.portrait,1)
        self.canvas.advanced.connect(self.portrait.set_time)
        self.planet_facts = text('','planetFact',True); detail.addWidget(self.planet_facts)
        self.planet_note = text('','subtle',True); detail.addWidget(self.planet_note)
        self.layer_button=action('Bóc tách hành tinh', self._toggle_layers)
        self.layer_button.setObjectName('layerButton'); self.layer_button.setCheckable(True)
        self.layer_button.setToolTip('Xem các lớp bên trong hành tinh đang chọn (hình minh họa).')
        detail.addWidget(self.layer_button)
        zoom_row=QHBoxLayout(); zoom_row.setSpacing(6)
        self.zoom_out=action('−',lambda:self._zoom(1/1.3)); self.zoom_out.setAccessibleName('Thu nhỏ')
        self.zoom_in=action('+',lambda:self._zoom(1.3)); self.zoom_in.setAccessibleName('Phóng to')
        self.zoom_value=text('100%', 'zoomValue'); self.zoom_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zoom_out.setObjectName('viewButton'); self.zoom_in.setObjectName('viewButton')
        for zoom_button in (self.zoom_out,self.zoom_in):
            zoom_button.setFixedSize(38,30)
            zoom_button.setStyleSheet('font-size: 16px; font-weight: 700; padding: 2px; color: #d7f5ee;')
        self.zoom_out.setToolTip('Thu nhỏ'); self.zoom_in.setToolTip('Phóng to')
        zoom_row.addWidget(self.zoom_out); zoom_row.addWidget(self.zoom_value,1); zoom_row.addWidget(self.zoom_in)
        detail.addLayout(zoom_row)
        self.canvas.zoomChanged.connect(self._show_zoom); self.layer_canvas.changed.connect(self._show_zoom)
        detail.addSpacing(6)
        self.pick = QComboBox(); self.pick.setAccessibleName('Chọn hành tinh')
        self.pick.addItems([v.name for v in PLANETS]); self.pick.setCurrentIndex(2)
        self.pick.currentIndexChanged.connect(self._planet); self.canvas.selected.connect(self.pick.setCurrentIndex)
        detail.addWidget(self.pick)
        nav=QHBoxLayout(); nav.setSpacing(8)
        self.previous=action('← Trước', lambda:self._step(-1)); self.previous.setAccessibleName('Hành tinh trước')
        self.following=action('Tiếp →', lambda:self._step(1)); self.following.setAccessibleName('Hành tinh tiếp theo')
        nav.addWidget(self.previous); nav.addWidget(self.following); detail.addLayout(nav)
        body_layout.addWidget(self.detail); layout.addLayout(body_layout,1)

        toolbar=QFrame(); self.toolbar=toolbar;toolbar.setObjectName('orbitTools'); tools=QHBoxLayout(toolbar)
        tools.setContentsMargins(12,8,12,8); tools.setSpacing(12)
        self.overview=action('Góc nghiêng',self._reset); self.overview.setObjectName('viewButton')
        self.overhead=action('Nhìn từ trên',self.canvas.view_from_above); self.overhead.setObjectName('viewButton')
        tools.addWidget(self.overview); tools.addWidget(self.overhead)
        self.orbits = QCheckBox('Quỹ đạo'); self.orbits.setChecked(True); self.orbits.toggled.connect(self._orbits)
        self.labels = QCheckBox('Tên'); self.labels.setChecked(True); self.labels.toggled.connect(self._labels)
        self.trails = QCheckBox('Vệt sáng'); self.trails.setChecked(True); self.trails.toggled.connect(self._trails)
        tools.addWidget(self.orbits); tools.addWidget(self.labels); tools.addWidget(self.trails); tools.addStretch()
        self.effects = QCheckBox('Hiệu ứng'); self.effects.setChecked(True)
        self.effects.setToolTip('Tự xoay hành tinh cận cảnh, ánh sáng và sao nhấp nháy nhẹ. Tắt để giảm tải.')
        self.effects.toggled.connect(self._effects); tools.addWidget(self.effects)
        layout.addWidget(toolbar)
        speed_row=QHBoxLayout(); speed_row.setSpacing(12)
        self.scale_note=text('Minh họa · kích thước và khoảng cách đã thu gọn','subtle',True)
        speed_row.addWidget(self.scale_note,1)
        self.speed_text = text('35 ngày / giây','subtle')
        self.speed = QSlider(Qt.Orientation.Horizontal); self.speed.setRange(1,100); self.speed.setValue(35)
        self.speed.setAccessibleName('Tốc độ mô phỏng'); self.speed.setFixedWidth(100)
        self.speed.valueChanged.connect(self._speed)
        self.layer_text=text('Mức tách 0%', 'subtle'); self.layer_text.hide()
        self.layer_amount=QSlider(Qt.Orientation.Horizontal); self.layer_amount.setRange(0,100)
        self.layer_amount.setFixedWidth(100); self.layer_amount.setAccessibleName('Mức bóc tách hành tinh')
        self.layer_amount.valueChanged.connect(self._layer_slider); self.layer_amount.hide()
        self.glass_effect=QCheckBox('Hiệu ứng vỡ'); self.glass_effect.setChecked(True); self.glass_effect.hide()
        self.glass_effect.setToolTip('Các lớp ngoài tách dần, lõi trong cùng nguyên vẹn. Bỏ chọn để xem hình cắt lớp.')
        self.glass_effect.toggled.connect(self.layer_canvas.set_glass_effect)
        speed_row.addWidget(self.speed_text); speed_row.addWidget(self.speed)
        speed_row.addWidget(self.layer_text); speed_row.addWidget(self.layer_amount)
        speed_row.addWidget(self.glass_effect); layout.addLayout(speed_row)
        camera_row = QHBoxLayout()
        self.camera_button = action('Bật camera cử chỉ', self._toggle_camera)
        self.camera_button.setCheckable(True)
        camera_row.addWidget(self.camera_button)
        self.camera_pick=QComboBox(); self.camera_pick.addItems(['Camera 1','Camera 2','Camera 3'])
        self.camera_pick.setAccessibleName('Chọn camera'); camera_row.addWidget(self.camera_pick)
        self.camera_status = text('Camera tắt • chỉ bật khi bạn chọn', 'subtle', True)
        camera_row.addWidget(self.camera_status,1); layout.addLayout(camera_row)
        self.gesture_help=text('Chụm 1 tay xoay · Mở 2 tay zoom · Chụm 2 tay tách / ghép · Giữ chữ V: toàn màn hình.','subtle',True)
        layout.addWidget(self.gesture_help)
        # Floating controls sit over the actual scene, not in its layout.
        self.immersive_bar=QFrame(self.view_stack);self.immersive_bar.setObjectName('immersiveBar')
        self.immersive_bar.setStyleSheet('QFrame#immersiveBar { background: rgba(8, 20, 34, 220); border: 1px solid #335260; border-radius: 10px; }')
        bar=QHBoxLayout(self.immersive_bar);bar.setContentsMargins(5,5,5,5);bar.setSpacing(5)
        self.immersive_hint=text('','subtle');self.immersive_hint.hide();bar.addWidget(self.immersive_hint)
        self.immersive_camera=action('Bật camera',lambda:self.camera_button.click())
        self.immersive_layer=action('Bóc tách',lambda:self.layer_button.click())
        self.immersive_exit=action('Thoát toàn màn hình',self.fullscreen_requested.emit)
        self.immersive_exit.setAccessibleName('Thoát toàn màn hình Vũ trụ')
        for item in (self.immersive_camera,self.immersive_layer,self.immersive_exit):bar.addWidget(item)
        self.immersive_bar.hide();self.view_stack.installEventFilter(self)
        self.view_stack.currentChanged.connect(lambda _index:self._place_immersive_bar())
        self.camera_button.toggled.connect(lambda _checked:self._sync_immersive_controls())
        self.camera = CameraSession(self)
        self.camera.status.connect(self.camera_status.setText)
        self.camera.running.connect(self._camera_state)
        self.camera.hands.connect(self._hands)
        self.tour_timer=QTimer(self); self.tour_timer.setInterval(9000)
        self.tour_timer.timeout.connect(lambda:self.pick.setCurrentIndex((self.pick.currentIndex()+1)%len(PLANETS)))
        self.layer_animation=QVariantAnimation(self); self.layer_animation.setDuration(700)
        self.layer_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.layer_animation.valueChanged.connect(self._layer_progress)
        self.layer_animation.finished.connect(self._layer_finished)
        self.gesture_animation=QVariantAnimation(self); self.gesture_animation.setDuration(180)
        self.gesture_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.gesture_animation.valueChanged.connect(self._layer_progress)
        self._gesture_target=None
        self._fullscreen_v=FullscreenV()
        self._pending_motion=[0.,0.,0.]
        self._motion_view=None
        self._motion_timer=QTimer(self);self._motion_timer.setInterval(16)
        self._motion_timer.timeout.connect(self._motion_step)
        self._planet(2)
        QApplication.instance().aboutToQuit.connect(self.camera.shutdown)

    def _sync_immersive_controls(self):
        self.immersive_camera.setText('Tắt camera' if self.camera_button.isChecked() else 'Bật camera')
        self.immersive_layer.setText('Ghép hành tinh' if self.layer_button.isChecked() else 'Bóc tách')
        if self._immersive:self._place_immersive_bar()

    def _place_immersive_bar(self):
        if not self._immersive:return
        self.immersive_bar.adjustSize()
        self.immersive_bar.move(max(8,self.view_stack.width()-self.immersive_bar.width()-14),12)
        self.immersive_bar.raise_()

    def eventFilter(self,watched,event):
        if watched is self.view_stack and event.type()==QEvent.Type.Resize:
            self._place_immersive_bar()
        return super().eventFilter(watched,event)

    def set_immersive(self,enabled):
        enabled=bool(enabled)
        if enabled==self._immersive:return
        self._immersive=enabled
        for widget in (self.page_overline,self.page_title,self.tour,self.pause,self.fullscreen_button,
                       self.detail,self.toolbar,self.scale_note,self.camera_button,self.camera_pick,self.camera_status):
            widget.setVisible(not enabled)
        layers=self.layer_button.isChecked()
        for widget in (self.speed_text,self.speed):widget.setVisible(not enabled and not layers)
        for widget in (self.layer_text,self.layer_amount,self.glass_effect):widget.setVisible(not enabled and layers)
        compact=self.width()<760 or self.height()<690
        self.intro.setVisible(not enabled and not compact)
        self.gesture_help.setVisible(not enabled and not compact)
        self.page_layout.setContentsMargins(*(0,0,0,0) if enabled else (24,22,24,18))
        self.page_layout.setSpacing(0 if enabled else 12)
        self.body_layout.setSpacing(0 if enabled else 12)
        self.immersive_bar.setVisible(enabled)
        if enabled:self._sync_immersive_controls()

    def _planet(self,index):
        self.gesture_animation.stop(); self._gesture_target=None
        self.canvas.selection=index; self.canvas.update()
        body=PLANETS[index]; self.planet_name.setText(body.name)
        period = f'{body.days:g} ngày' if body.days < 1000 else f'{body.days/365.2:.1f} năm'
        period=period.replace('.',','); distance=f'{body.distance:g}'.replace('.',',')
        # Keep both facts visible beside the controls even on laptop screens.
        self.planet_facts.setText(f'{period} / vòng\n≈ {distance} triệu km từ Mặt Trời')
        self.planet_note.setText(body.note)
        self.portrait.index=index; self.portrait.update()
        self.layer_canvas.set_planet(index)
        self._update_layer_stage()

    def _step(self,delta):
        self.pick.setCurrentIndex((self.pick.currentIndex()+delta)%len(PLANETS))

    def _tour_changed(self):
        self._sync_tour()

    def _sync_tour(self):
        running=self.active and self.canvas.playing and self.tour.isChecked() and self.view_stack.currentWidget() is self.canvas
        self.tour_timer.start() if running else self.tour_timer.stop()
        self.tour.setText('Dừng tham quan' if self.tour.isChecked() else 'Tham quan tự động')

    def _pause(self):
        self.canvas.set_playing(not self.canvas.playing)
        self.pause.setText('Tạm dừng' if self.canvas.playing else 'Tiếp tục')
        self._sync_layer_animation()
        self._sync_tour()

    def _current_view(self):
        return self.layer_canvas if self.view_stack.currentWidget() is self.layer_canvas else self.canvas

    def _show_zoom(self,*_):
        self.zoom_value.setText(f'{round(self._current_view().zoom*100)}%')

    def _zoom(self,factor):
        self._current_view().zoom_at(factor)
        self._show_zoom()

    def _reset(self):
        self._current_view().reset_view()
        self._show_zoom()

    def _toggle_layers(self):
        self._clear_motion()
        enabled=self.layer_button.isChecked()
        self.layer_animation.stop()
        self.gesture_animation.stop(); self._gesture_target=None
        if enabled:
            self.view_stack.setCurrentWidget(self.layer_canvas)
            self.canvas.set_active(False)
            self.layer_button.setText('Ghép lại hành tinh')
        else:
            self.layer_button.setText('Bóc tách hành tinh')
        self.speed_text.setVisible(not enabled and not self._immersive); self.speed.setVisible(not enabled and not self._immersive)
        self.layer_text.setVisible(enabled and not self._immersive); self.layer_amount.setVisible(enabled and not self._immersive)
        self.glass_effect.setVisible(enabled and not self._immersive)
        self._sync_immersive_controls()
        self.intro.setText('Bấm tên lớp để xem · Kéo để dịch · Cuộn để thu phóng.' if enabled else
                           'Một góc nhỏ của vũ trụ. Chọn một hành tinh để bắt đầu khám phá.')
        self.scale_note.setText('Minh họa · cấu trúc và tỉ lệ đã đơn giản hóa' if enabled else
                                'Minh họa · kích thước và khoảng cách đã thu gọn')
        self.overview.setText('Đặt lại góc nhìn' if enabled else 'Góc nghiêng')
        self.overhead.setEnabled(not enabled)
        self.tour.setEnabled(not enabled)
        self._sync_layer_animation()
        self._sync_tour(); self._show_zoom()
        self.layer_animation.setStartValue(self.layer_canvas.amount)
        self.layer_animation.setEndValue(1. if enabled else 0.)
        if self.active:
            self.layer_animation.start()
        else:
            self._layer_progress(1. if enabled else 0.); self._layer_finished()

    def _layer_progress(self,value):
        self.layer_canvas.set_amount(value)
        self.layer_amount.blockSignals(True); self.layer_amount.setValue(round(value*100)); self.layer_amount.blockSignals(False)
        self._update_layer_stage()

    def _update_layer_stage(self):
        count=len(layers_for(self.layer_canvas.index))
        stage,_=self.layer_canvas.stage_for(self.layer_canvas.amount,count)
        self.layer_text.setText(f'Điểm {stage+1}/{count} · {round(self.layer_canvas.amount*100)}%')

    def _layer_slider(self,value):
        self.layer_animation.stop(); self.gesture_animation.stop(); self._gesture_target=None
        self.layer_canvas.set_amount(value/100.)
        self._update_layer_stage()

    def _layer_finished(self):
        if not self.layer_button.isChecked():
            self.view_stack.setCurrentWidget(self.canvas)
            self.canvas.set_active(self.active); self._sync_tour()
        self._sync_layer_animation()
        self._show_zoom()
    def _orbits(self,value): self.canvas.orbits=value; self.canvas.update()
    def _labels(self,value): self.canvas.labels=value; self.canvas.update()
    def _trails(self,value): self.canvas.trails=value; self.canvas.update()
    def _effects(self,value):
        self.canvas.effects=value; self.canvas.update(); self._sync_layer_animation()
    def _speed(self,value):
        self.canvas.rate=float(value); self.speed_text.setText(f'{value} ngày / giây')

    def _toggle_camera(self):
        if self.camera_button.isChecked() and self.active:
            self.canvas.motion.reset(); self.camera.start(self.camera_pick.currentIndex())
        else:
            self.camera.stop(); self.camera_status.setText('Camera tắt • chỉ bật khi bạn chọn')

    def _camera_state(self, running):
        self.camera_button.setChecked(running)
        self.camera_button.setText('Tắt camera' if running else 'Bật camera cử chỉ')
        self.camera_pick.setEnabled(not running)
        if not running:
            self._clear_motion()
            self._fullscreen_v.reset()
            self.immersive_hint.clear();self.immersive_hint.hide()
            if self._immersive:self._place_immersive_bar()
            self._gesture_closed_latched=False
            self.gesture_animation.stop(); self._gesture_target=None
            self.canvas.hands=[]; self.canvas.motion.reset(); self.canvas.update()

    def _hands(self,hands):
        if not self.active:
            return
        self.canvas.hands=hands
        now=time.monotonic()
        toggle_fullscreen=self._fullscreen_v.update(hands,now)
        old_mode=self.canvas.motion.mode
        dx,dy,zoom,tip=self.canvas.motion.update(hands,now)
        if old_mode!=self.canvas.motion.mode:
            self._clear_motion()
            if old_mode=='separate':self.gesture_animation.stop()
        if self.canvas.motion.mode != 'separate':
            self._gesture_closed_latched=False
            self._gesture_target=None
        separation=self.canvas.motion.separation_delta
        if separation and not self._gesture_closed_latched:
            if not self.layer_button.isChecked() and separation > 0:
                self.layer_button.click()
                self.layer_animation.stop()
                self._layer_progress(0.)
            if self.layer_button.isChecked():
                # Accumulate without rounding; a gentler gain avoids skipping
                # several stages from one fast camera sample.
                if self._gesture_target is None:self._gesture_target=self.layer_canvas.amount
                gain=2.6 if separation < 0 else 1.8
                amount=max(0.,min(1.,self._gesture_target+separation*gain))
                self._gesture_target=amount
                if separation < 0 and amount <= .05:
                    # Finish the closing animation and return to the orbit. Keep
                    # this pinch latched until released to avoid reopening on jitter.
                    self._gesture_closed_latched=True
                    self.layer_button.click()
                else:
                    # The camera reports discrete samples; interpolate visual
                    # progress while preserving the raw target for the next one.
                    self.layer_animation.stop(); self.gesture_animation.stop()
                    self.gesture_animation.setStartValue(self.layer_canvas.amount)
                    self.gesture_animation.setEndValue(amount)
                    self.gesture_animation.start()
        if self._fullscreen_v.holding:
            self._clear_motion()
            self.canvas.motion.reset()
        if toggle_fullscreen:
            self.fullscreen_requested.emit()
            tip='Đã đổi chế độ toàn màn hình'
        elif not self._fullscreen_v.holding:self._queue_motion(dx,dy,zoom)
        feedback=self._fullscreen_v.feedback
        if self.immersive_hint.text()!=feedback:
            self.immersive_hint.setText(feedback)
            self.immersive_hint.setVisible(bool(feedback))
            if self._immersive:self._place_immersive_bar()
        if self.camera_button.isChecked():self.camera_status.setText('Camera bật • '+(feedback or tip))

    def _clear_motion(self):
        self._motion_timer.stop()
        self._pending_motion=[0.,0.,0.]
        self._motion_view=None

    def _queue_motion(self,dx,dy,zoom):
        if not (dx or dy or abs(zoom-1.)>1e-8):return
        view=self._current_view()
        if self._motion_view is not None and self._motion_view is not view:self._clear_motion()
        self._motion_view=view
        self._pending_motion[0]+=dx;self._pending_motion[1]+=dy
        self._pending_motion[2]+=math.log(zoom)
        # Start immediately, then interpolate the remainder between camera frames.
        self._motion_step()
        if self._motion_view is not None:self._motion_timer.start()

    def _motion_step(self):
        if not self.active or self._motion_view is not self._current_view():
            self._clear_motion();return
        dx,dy,dz=self._pending_motion
        if max(abs(dx),abs(dy),abs(dz))<.00015:
            self._clear_motion();return
        part=.34
        self._motion_view.rotate_zoom(dx*part,dy*part,math.exp(dz*part))
        self._pending_motion=[dx*(1-part),dy*(1-part),dz*(1-part)]

    def _sync_layer_animation(self):
        self.layer_canvas.set_active(bool(self.active and self.layer_button.isChecked()
                                          and self.canvas.playing and self.canvas.effects))

    def set_active(self,active):
        self.active=active; self.canvas.set_active(active and self.view_stack.currentWidget() is self.canvas)
        self._sync_layer_animation()
        self._sync_tour()
        if not active:
            self._clear_motion()
            self._fullscreen_v.reset()
            self.gesture_animation.stop(); self._gesture_target=None
            if self.layer_animation.state()==QVariantAnimation.State.Running:
                self.layer_animation.stop()
                self._layer_progress(1. if self.layer_button.isChecked() else 0.)
                self._layer_finished()
            self.camera.stop(); self.camera_status.setText('Camera tắt • chỉ bật khi bạn chọn')

    def resizeEvent(self,event):
        super().resizeEvent(event)
        compact=self.width()<760 or self.height()<690
        self._tight=self.height()<630
        self.detail.setFixedWidth(190 if compact else 224)
        # The extra layer and zoom controls need room; allowing the portrait
        # to shrink prevents Qt overlapping it with the facts at laptop sizes.
        self.portrait.setMinimumHeight(40 if self._tight else 70 if compact else 85)
        self.portrait.setMaximumHeight(120 if self._tight else 150 if compact else 190)
        self.destination_label.setVisible(not self._tight)
        self.previous.setVisible(not self._tight); self.following.setVisible(not self._tight)
        self.planet_note.setVisible(not compact)
        self.intro.setVisible(not compact and not self._immersive)
        self.gesture_help.setVisible(not compact and not self._immersive)
        self.trails.setVisible(self.width()>=650)
        self.effects.setVisible(self.width()>=760)

    def showEvent(self,event):
        super().showEvent(event); self.set_active(not self.window().isMinimized())

    def hideEvent(self,event):
        self.set_active(False); super().hideEvent(event)
