"""Alex adapter for the FatihMakes/MediaPipe portrait from the reference video.

See vendor/fatih_hologram/NOTICE.md. Local rendering only. Mouth motion currently
indicates speaking state; it is not phoneme or measured audio lip sync.
"""
from __future__ import annotations
import math
import time
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QWidget, QSizePolicy
from .vendor.fatih_hologram.avatar import HoloAvatar


def approach(current, target, dt, response):
    return current + (target-current)*(1-math.exp(-max(0., min(dt, .1))/response))


def expression(mode):
    return {'paused': (.16, 0., .62), 'listening': (1., 0., 1.),
            'thinking': (.90, 0., .94), 'speaking': (.94, 1., 1.),
            'error': (.72, 0., .84)}.get(mode, (.84, 0., .88))


class HologramFace(QWidget):
    """Bounded 30 Hz Qt widget; stops animation when not visible."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(220, 270)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setAccessibleName('Khuôn mặt hologram Alex · mẫu FatihMakes')
        self.setWhatsThis('Khuôn mặt: FatihMakes / MediaPipe · CC BY-NC 4.0 / Apache-2.0\n'
                        'https://github.com/FatihMakes/Mark-LVI\n'
                        'Đã điều chỉnh cho Alex. Chuyển động miệng theo trạng thái đang nói.')
        self.mode = 'paused'; self.active = False; self.reduced = False; self.phase = 0.
        self.yaw = self.pitch = self.target_yaw = self.target_pitch = 0.
        self.gaze_x = self.gaze_y = 0.; self.gaze_target = (0., 0.)
        self.eye_level, self.talking, self.light = expression(self.mode)
        self.avatar = HoloAvatar()
        self._base_gaze = [0., 0.]
        self._frame = None; self._frame_key = None; self._revision = 0
        self._last_tick = time.monotonic()
        self.timer = QTimer(self); self.timer.setInterval(33)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._tick)
        self._settle_expression()

    def _invalidate(self):
        self._revision += 1
        self.update()

    def set_active(self, active):
        self.active = bool(active); self._last_tick = time.monotonic()
        if self.active and not self.reduced: self.timer.start()
        else: self.timer.stop()

    def set_reduced_motion(self, reduced):
        self.reduced = bool(reduced)
        if self.reduced: self._settle_expression()
        self.set_active(self.active); self._invalidate()

    def set_mode(self, mode):
        if mode == self.mode: return
        self.mode = mode
        if self.reduced: self._settle_expression()
        self._invalidate()

    def _settle_expression(self):
        self.eye_level, self.talking, self.light = expression(self.mode)
        a = self.avatar
        a._mouth = .40*self.talking; a._wide = 0.; a._blink = 0.
        a._lids = self.eye_level; a._brow = -.28 if self.mode == 'thinking' else -.15 if self.mode == 'error' else 0.
        a._yaw = -.09; a._pitch = .01; a._glow = .16*self.talking
        a._gaze = [.45, .30] if self.mode == 'thinking' else [0., 0.]
        self._base_gaze = a._gaze.copy()
        a._scan = -1.7

    def _advance(self, dt):
        if self.reduced: return
        dt = max(0., min(dt, .1))
        if dt == 0: return
        self.phase += dt
        self.yaw = approach(self.yaw, self.target_yaw, dt, .20)
        self.pitch = approach(self.pitch, self.target_pitch, dt, .23)
        self.gaze_x = approach(self.gaze_x, self.gaze_target[0], dt, .12)
        self.gaze_y = approach(self.gaze_y, self.gaze_target[1], dt, .14)
        eye, talk, light = expression(self.mode)
        self.eye_level = approach(self.eye_level, eye, dt, .21)
        self.talking = approach(self.talking, talk, dt, .16)
        self.light = approach(self.light, light, dt, .30)
        # State-based motion, not a claimed audio measurement. No second mic.
        t = self.phase
        pulse = max(0., math.sin(t*10.8)+.33*math.sin(t*19.1))
        amp = self.talking*(.16+.43*min(1., pulse))
        state = {'paused':'STANDBY', 'thinking':'THINKING', 'listening':'LISTENING'}.get(self.mode, '')
        self.avatar._gaze = self._base_gaze.copy()
        self.avatar.step(dt, amp, speaking=self.mode == 'speaking',
                         muted=self.mode == 'paused', state=state,
                         v_open=.55+.35*math.sin(t*7.3)**2,
                         v_wide=.32*math.sin(t*5.7))
        self.avatar._yaw += self.yaw
        self.avatar._pitch += self.pitch
        self._base_gaze = self.avatar._gaze.copy()
        self.avatar._gaze[0] = max(-1., min(1., self.avatar._gaze[0]+self.gaze_x))
        self.avatar._gaze[1] = max(-1., min(1., self.avatar._gaze[1]+self.gaze_y))
        self.avatar._lids = self.eye_level
        if self.mode == 'error': self.avatar._brow = -.22
        self._invalidate()

    def _tick(self):
        now = time.monotonic(); self._advance(now-self._last_tick); self._last_tick = now

    def mouseMoveEvent(self, event):
        if not self.reduced:
            x = max(-1., min(1., event.position().x()/max(1, self.width())*2-1))
            y = max(-1., min(1., event.position().y()/max(1, self.height())*2-1))
            self.target_yaw = x*.24; self.target_pitch = y*.07
            self.gaze_target = (x*.25, y*.20)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self.target_yaw = self.target_pitch = 0.; self.gaze_target = (0., 0.)
        super().leaveEvent(event)

    def hideEvent(self, event):
        self.set_active(False); super().hideEvent(event)

    def _render_frame(self):
        # One cached image, reused for exposure/repaint of the same pose.
        dpr = self.devicePixelRatioF(); w, h = self.width(), self.height()
        key = (w, h, dpr, self._revision)
        if key == self._frame_key: return self._frame
        frame = QPixmap(math.ceil(w*dpr), math.ceil(h*dpr))
        frame.setDevicePixelRatio(dpr); frame.fill(Qt.GlobalColor.transparent)
        p = QPainter(frame); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = min(w*.45, (h-24)/(self.avatar.SPAN+.20))
        cy = (h-self.avatar.SPAN*r)*.5+r
        blend = max(0., min(1., (self.light-.62)/.38))
        low, high = QColor('#247fa8'), QColor('#00a9ff')
        primary = QColor(*(round(a+(b-a)*blend) for a,b in zip(low.getRgb(),high.getRgb())))
        accent = QColor({'paused':'#8dafc7', 'listening':'#00ff88',
                         'thinking':'#ffdb63', 'speaking':'#ff920f',
                         'error':'#ff604f'}.get(self.mode, '#00d4ff'))
        self.avatar.paint(p, w*.5, cy, r, primary, accent, QColor('#071726'))
        p.end(); self._frame = frame; self._frame_key = key
        return frame

    def paintEvent(self, event):
        p = QPainter(self); p.drawPixmap(0, 0, self._render_frame()); p.end()
