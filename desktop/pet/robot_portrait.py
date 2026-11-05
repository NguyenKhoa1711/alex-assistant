"""Local robot portrait. Cached vector shell; live eyes, expression and pose.

Mouth movement represents speaking state, not audio amplitude or phonemes.
No microphone, camera, network, model, or external assets are used here.
"""
from __future__ import annotations
import math
import time
from PySide6.QtCore import Qt, QTimer, QPointF, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QRadialGradient, QPixmap, QPainterPath, QLinearGradient
from PySide6.QtWidgets import QWidget, QSizePolicy


def approach(current, target, dt, response):
    """Frame-rate independent easing, with no catch-up after sleep."""
    return current + (target-current)*(1-math.exp(-max(0., min(dt, .1))/response))


def expression(mode):
    # Eye openness, speaking blend, illumination.
    return {'paused': (0., 0., .72), 'listening': (1., 0., 1.),
            'thinking': (.76, 0., .90), 'speaking': (.94, 1., 1.),
            'error': (.78, 0., .88)}.get(mode, (.84, 0., .88))


def blend_color(a, b, amount):
    amount = max(0., min(1., amount)); a, b = QColor(a), QColor(b)
    return QColor(*(round(x+(y-x)*amount) for x, y in zip(a.getRgb(), b.getRgb())))


def rounded_pen(color, width):
    return QPen(QColor(color), width, Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)


def glass_path():
    path = QPainterPath(); path.addRoundedRect(QRectF(-143, -109, 286, 218), 83, 83)
    return path


def shell_path():
    path = QPainterPath(QPointF(0, -141))
    path.cubicTo(-114, -141, -170, -103, -170, -13)
    path.cubicTo(-170, 84, -117, 137, 0, 137)
    path.cubicTo(117, 137, 170, 84, 170, -13)
    path.cubicTo(170, -103, 114, -141, 0, -141)
    path.closeSubpath(); return path


class HologramFace(QWidget):
    """Keep the command-center API; draw an expressive robot, entirely offline."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(220, 270)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setAccessibleName('Khuôn mặt robot Alex · biểu cảm theo trạng thái')
        self.mode = 'paused'; self.active = False; self.phase = 0.
        self.yaw = 0.; self.pitch = 0.; self.target_yaw = 0.; self.target_pitch = 0.
        self.reduced = False; self._last_tick = time.monotonic()
        self._shell_cache = None; self._shell_key = None
        self.eye_level, self.talking, self.light = expression(self.mode)
        self.gaze_x = 0.; self.gaze_y = 0.; self.gaze_target = (0., 0.)
        self.thought = 0.; self.concern = 0.
        self.timer = QTimer(self); self.timer.setInterval(33)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._tick)

    def set_active(self, active):
        self.active = bool(active); self._last_tick = time.monotonic()
        if self.active and not self.reduced: self.timer.start()
        else: self.timer.stop()

    def set_reduced_motion(self, reduced):
        self.reduced = bool(reduced); self.set_active(self.active)
        if self.reduced: self._settle_expression()
        self.update()

    def _settle_expression(self):
        self.eye_level, self.talking, self.light = expression(self.mode)
        self.thought = float(self.mode == 'thinking'); self.concern = float(self.mode == 'error')

    def set_mode(self, mode):
        if mode != self.mode:
            self.mode = mode
            if self.reduced: self._settle_expression()
            self.update()

    def _advance(self, dt):
        dt = max(0., min(dt, .1)); self.phase += dt
        self.yaw = approach(self.yaw, self.target_yaw, dt, .20)
        self.pitch = approach(self.pitch, self.target_pitch, dt, .23)
        self.gaze_x = approach(self.gaze_x, self.gaze_target[0], dt, .12)
        self.gaze_y = approach(self.gaze_y, self.gaze_target[1], dt, .14)
        eye, talk, light = expression(self.mode)
        self.eye_level = approach(self.eye_level, eye, dt, .21)
        self.talking = approach(self.talking, talk, dt, .16)
        self.light = approach(self.light, light, dt, .30)
        self.thought = approach(self.thought, float(self.mode == 'thinking'), dt, .26)
        self.concern = approach(self.concern, float(self.mode == 'error'), dt, .26)

    def _tick(self):
        now = time.monotonic(); self._advance(now-self._last_tick); self._last_tick = now; self.update()

    def mouseMoveEvent(self, event):
        if not self.reduced:
            x = max(-1., min(1., event.position().x()/max(1, self.width())*2-1))
            y = max(-1., min(1., event.position().y()/max(1, self.height())*2-1))
            self.target_yaw = x*.23; self.target_pitch = y*.08; self.gaze_target = (x*7., y*4.)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self.target_yaw = 0.; self.target_pitch = 0.; self.gaze_target = (0., 0.)
        super().leaveEvent(event)

    def hideEvent(self, event):
        self.set_active(False); super().hideEvent(event)

    def _cached_shell(self, scale):
        # One bounded pixmap. Cursor motion transforms it without re-rasterizing.
        density = max(.5, max(1.5, self.devicePixelRatioF())*scale); key = round(density, 3)
        if self._shell_cache is not None and self._shell_key == key: return self._shell_cache
        image = QPixmap(math.ceil(440*density), math.ceil(450*density))
        image.setDevicePixelRatio(density); image.fill(Qt.GlobalColor.transparent)
        p = QPainter(image); p.setRenderHint(QPainter.RenderHint.Antialiasing); p.translate(220, 218)
        # Antenna and ear housings sit behind the continuous shell silhouette.
        p.setPen(rounded_pen('#255e64', 9)); p.drawLine(QPointF(0, -128), QPointF(0, -172))
        p.setPen(rounded_pen('#a1e5da', 3)); p.drawLine(QPointF(-2, -143), QPointF(-2, -172))
        p.setPen(rounded_pen('#285d66', 2)); p.setBrush(QColor('#82cfc7')); p.drawEllipse(QPointF(0, -181), 12, 12)
        for side in (-1, 1):
            x = side*166; ear = QLinearGradient(x-22, -35, x+22, 24)
            ear.setColorAt(0, QColor('#b4e9db')); ear.setColorAt(.42, QColor('#5baaa9')); ear.setColorAt(1, QColor('#275767'))
            p.setPen(rounded_pen('#183f4b', 2)); p.setBrush(ear); p.drawRoundedRect(QRectF(x-22, -36, 44, 72), 20, 20)
            p.setPen(rounded_pen('#b0eee1', 2)); p.setBrush(QColor('#123a48')); p.drawRoundedRect(QRectF(x-10, -22, 20, 43), 10, 10)
        outer = shell_path(); body = QLinearGradient(-125, -144, 122, 145)
        for at, color in ((0, '#ddfff0'), (.23, '#87ded0'), (.55, '#3baaa5'), (.82, '#247b85'), (1, '#174956')):
            body.setColorAt(at, QColor(color))
        p.setPen(rounded_pen('#286873', 2)); p.setBrush(body); p.drawPath(outer)
        sheen = QRadialGradient(QPointF(-91, -121), 241)
        sheen.setColorAt(0, QColor(233, 255, 246, 95)); sheen.setColorAt(1, QColor(182, 255, 228, 0)); p.fillPath(outer, sheen)
        # Crisp inner bezel and deep glass give the eyes a stable background.
        p.setPen(rounded_pen('#b7f7df', 1.6)); p.setBrush(QColor('#1c5963')); p.drawRoundedRect(QRectF(-150, -116, 300, 232), 90, 90)
        p.setPen(rounded_pen('#0e3542', 4)); screen = QLinearGradient(-90, -109, 70, 109)
        screen.setColorAt(0, QColor('#173941')); screen.setColorAt(.45, QColor('#0a202a')); screen.setColorAt(1, QColor('#06151f'))
        p.setBrush(screen); p.drawPath(glass_path())
        p.save(); p.setClipPath(glass_path()); p.setPen(Qt.PenStyle.NoPen)
        reflection = QPainterPath(QPointF(-150, -110)); reflection.lineTo(70, -110)
        reflection.cubicTo(-5, -80, -67, -48, -149, -42); reflection.closeSubpath()
        highlight = QLinearGradient(0, -112, 0, -35)
        highlight.setColorAt(0, QColor(199, 255, 244, 22)); highlight.setColorAt(1, QColor(199, 255, 244, 0))
        p.fillPath(reflection, highlight); p.restore()
        p.setPen(rounded_pen('#d4fff0', 2)); p.setBrush(Qt.BrushStyle.NoBrush)
        arc = QPainterPath(QPointF(-121, -99)); arc.cubicTo(-88, -129, -43, -132, 16, -130); p.drawPath(arc)
        p.setPen(rounded_pen('#20666d', 2))
        for x in (-8, 0, 8): p.drawPoint(QPointF(x, 125))
        p.end(); self._shell_key = key; self._shell_cache = image; return image

    def _draw_eyes(self, p, t, accent):
        blink_phase = t % 5.8
        blink = (math.sin(math.pi*(blink_phase-5.28)/.36)**2 if 5.28 < blink_phase < 5.64 and not self.reduced else 0.)
        opening = self.eye_level*(1-blink)
        for side in (-1, 1):
            ex = side*56+self.gaze_x; ey = -22+self.gaze_y-self.thought*3
            openness = opening*(1-.24*self.thought if side == 1 else 1); height = 61*openness
            # Crossfade sleeping eyelids into rounded luminous eyes.
            p.save(); p.setOpacity(max(0., 1-openness*4))
            lid = QPainterPath(QPointF(ex-23, ey+2)); lid.cubicTo(ex-12, ey+14, ex+12, ey+14, ex+23, ey+2)
            p.setPen(rounded_pen(accent, 4)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawPath(lid); p.restore()
            if height < .1: continue
            p.save(); p.setOpacity(min(1., openness*4))
            eye = QPainterPath(); eye.addRoundedRect(QRectF(ex-23, ey-height/2, 46, height), 22, min(22, height/2))
            aura = QRadialGradient(QPointF(ex, ey), 48)
            aura.setColorAt(0, QColor(accent.red(), accent.green(), accent.blue(), 45)); aura.setColorAt(1, QColor(accent.red(), accent.green(), accent.blue(), 0))
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(aura); p.drawEllipse(QPointF(ex, ey), 48, 48)
            iris = QLinearGradient(ex, ey-height/2, ex+10, ey+height/2)
            iris.setColorAt(0, blend_color(accent, '#f0fff8', .7)); iris.setColorAt(.6, accent); iris.setColorAt(1, blend_color(accent, '#1b838d', .55))
            p.fillPath(eye, iris); p.setClipPath(eye)
            px = ex+self.gaze_x*.38; py = ey+self.gaze_y*.3
            p.setBrush(QColor('#0a3946')); p.drawEllipse(QPointF(px, py+1), 10, 16)
            p.setBrush(QColor(242, 255, 247, 235)); p.drawEllipse(QPointF(px-7, py-13), 5.5, 7)
            p.setBrush(QColor(224, 255, 242, 155)); p.drawEllipse(QPointF(px+7, py+12), 2.2, 2.2); p.restore()
        for side in (-1, 1):
            strength = max(self.thought, self.concern)
            if strength < .01: continue
            ex = side*56; p.save(); p.setOpacity(strength*.7); p.setPen(rounded_pen(accent, 3))
            brow = QPainterPath(QPointF(ex-19, -67+side*self.concern*5))
            brow.quadTo(QPointF(ex, -72-self.thought*4), QPointF(ex+19, -67-side*self.concern*5))
            p.setBrush(Qt.BrushStyle.NoBrush); p.drawPath(brow); p.restore()

    def _draw_mouth(self, p, t, accent):
        wave = .5+.5*math.sin(t*9.2)
        opening = self.talking*(9 if self.reduced else 5+17*wave*(.72+.28*math.sin(t*3.7)**2))
        smile = 16-21*self.concern-7*self.thought
        path = QPainterPath(QPointF(-25, 43)); path.cubicTo(-17, 43+smile, 17, 43+smile, 25, 43)
        p.setBrush(Qt.BrushStyle.NoBrush); p.setPen(rounded_pen(accent, 4)); p.drawPath(path)
        if opening > .15:
            mouth = QPainterPath(QPointF(-24, 44)); mouth.cubicTo(-12, 49, 12, 49, 24, 44)
            mouth.cubicTo(19, 52+opening, -19, 52+opening, -24, 44)
            p.setPen(rounded_pen(accent, 2.5)); p.setBrush(QColor('#061a25')); p.drawPath(mouth)
            p.save(); p.setClipPath(mouth); p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(blend_color(accent, '#328f9b', .55)); p.drawEllipse(QPointF(0, 59+opening), 15, 8); p.restore()

    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing); p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w, h = self.width(), self.height(); scale = min(w/448, h/458); cx, cy = w*.5, h*.49
        t = 0. if self.reduced else self.phase; bob = 0. if self.reduced else math.sin(t*1.35)*2.8
        accent = blend_color('#81aeb5', '#9df5de', (self.light-.72)/.28); accent = blend_color(accent, '#ffd29b', self.concern)
        halo = QRadialGradient(QPointF(cx, cy), 218*scale)
        halo.setColorAt(0, QColor(53, 180, 175, 33)); halo.setColorAt(1, QColor(25, 137, 158, 0))
        p.setBrush(halo); p.setPen(Qt.PenStyle.NoPen); p.drawEllipse(QPointF(cx, cy), 218*scale, 216*scale)
        p.setBrush(Qt.BrushStyle.NoBrush); p.setPen(rounded_pen(QColor(110, 221, 209, 22), 1))
        p.drawEllipse(QPointF(cx, cy-7*scale), 201*scale, 201*scale)
        p.save(); p.translate(cx, cy); p.scale(scale, scale)
        shadow = QRadialGradient(QPointF(0, 185), 100)
        shadow.setColorAt(0, QColor(2, 10, 20, 115)); shadow.setColorAt(1, QColor(2, 10, 20, 0))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(shadow); p.drawEllipse(QRectF(-111, 173, 222, 25))
        p.setPen(rounded_pen(QColor(109, 218, 205, 55), 1)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(-65, 182, 130, 8)); p.restore()
        p.save(); p.translate(cx+self.yaw*24*scale, cy+bob*scale+self.pitch*20*scale)
        p.rotate(self.yaw*9); p.scale(scale*(1-abs(self.yaw)*.12), scale)
        p.setOpacity(.84+.16*self.light); p.drawPixmap(QPointF(-220, -218), self._cached_shell(scale)); p.setOpacity(1.)
        p.save(); p.setClipPath(glass_path()); p.translate(self.yaw*13, self.pitch*17)
        self._draw_eyes(p, t, accent); self._draw_mouth(p, t, accent); p.restore()
        p.setPen(Qt.PenStyle.NoPen); light = QRadialGradient(QPointF(0, -181), 18)
        light.setColorAt(0, QColor(accent.red(), accent.green(), accent.blue(), 135)); light.setColorAt(1, QColor(accent.red(), accent.green(), accent.blue(), 0))
        p.setBrush(light); p.drawEllipse(QPointF(0, -181), 18, 18); p.setBrush(accent); p.drawEllipse(QPointF(0, -181), 6, 6)
        # State dots are not a pretend microphone meter.
        for i in range(3):
            pulse = .35+.65*(.5+.5*math.sin(t*3-i*.85)) if self.mode == 'thinking' and not self.reduced else .55
            p.setOpacity(pulse if self.mode == 'thinking' else .28+.42*self.eye_level)
            p.setBrush(accent); p.drawEllipse(QPointF((i-1)*13, 86), 2.2, 2.2)
        p.restore(); p.end()
