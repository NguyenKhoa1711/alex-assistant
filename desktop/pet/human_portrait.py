"""A locally rendered portrait for Alex's command center.

The portrait is an illustrated 2-D rig, not a live camera feed or 3-D model.
The mouth follows local output volume approximately, not phonemes.
"""
from __future__ import annotations

import math
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient

from .config import ROOT
from .reference_portrait import HologramFace as ReferenceFace, approach
from . import voice_motion


class HologramFace(ReferenceFace):
    """Use the existing lifecycle and smooth motion with a realistic portrait."""

    def __init__(self, parent=None):
        super().__init__(parent)
        assets = ROOT / 'assets' / 'command-center'
        self.portrait = QPixmap(str(assets / 'alex-human.png'))
        self.blink_frame = QPixmap(str(assets / 'alex-blink.png'))
        self.talk_frame = QPixmap(str(assets / 'alex-speaking.png'))
        self.lip_open = 0.
        self.setAccessibleName('Chân dung Alex')
        self.setWhatsThis('Chân dung minh họa 2D lưu trên laptop; mắt chớp và miệng chuyển động gần theo âm lượng giọng nói, không phải khẩu hình từng âm.')

    def _advance(self, dt):
        super()._advance(dt)
        if not self.reduced:
            target = voice_motion.level() if self.mode == 'speaking' else 0.
            self.lip_open = approach(self.lip_open, target, dt, .055 if target > self.lip_open else .12)

    def _render_frame(self):
        if self.portrait.isNull():
            return super()._render_frame()
        dpr = self.devicePixelRatioF()
        w, h = self.width(), self.height()
        key = (w, h, dpr, self._revision)
        if key == self._frame_key:
            return self._frame
        frame = QPixmap(math.ceil(w*dpr), math.ceil(h*dpr))
        frame.setDevicePixelRatio(dpr)
        frame.fill(Qt.GlobalColor.transparent)
        p = QPainter(frame)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        colors = {'paused': '#72a0a4', 'listening': '#71f2d1',
                  'thinking': '#89bcf5', 'speaking': '#75e9d1', 'error': '#e59c87'}
        tint = QColor(colors.get(self.mode, '#86d9d1'))
        cx, cy = w * .5, h * .48
        radius = min(w * .41, h * .43)
        glow = QRadialGradient(cx, cy, radius * 1.24)
        inner = QColor(tint); inner.setAlpha(28)
        middle = QColor(tint); middle.setAlpha(12)
        outer = QColor(tint); outer.setAlpha(0)
        glow.setColorAt(0, inner); glow.setColorAt(.65, middle); glow.setColorAt(1, outer)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(glow)
        p.drawEllipse(QRectF(cx-radius*1.24, cy-radius*1.24, radius*2.48, radius*2.48))
        p.setBrush(Qt.BrushStyle.NoBrush)
        ring = QColor(tint); ring.setAlpha(62)
        p.setPen(QPen(ring, 1.15))
        p.drawEllipse(QRectF(cx-radius, cy-radius, radius*2, radius*2))
        ring.setAlpha(24); p.setPen(QPen(ring, .8))
        p.drawEllipse(QRectF(cx-radius*1.055, cy-radius*1.055, radius*2.11, radius*2.11))

        # A tiny, bounded sway gives the still portrait presence. It is not a
        # 3-D face or phoneme-level lip sync, and reduced motion freezes it.
        sway = 0.0 if self.reduced else math.sin(self.phase * .85) * .5
        dx = 0.0 if self.reduced else self.yaw * 9.0
        dy = 0.0 if self.reduced else self.pitch * 7.0 + math.sin(self.phase * 1.1) * .65
        scale = min(w * .98 / self.portrait.width(), h * .98 / self.portrait.height())
        pw, ph = self.portrait.width()*scale, self.portrait.height()*scale
        p.save(); p.translate(cx + dx, h*.51 + dy)
        p.rotate(sway + (0 if self.reduced else self.yaw * 3.5))
        target = QRectF(-pw*.5, -ph*.5, pw, ph)
        source = QRectF(0, 0, self.portrait.width(), self.portrait.height())
        p.drawPixmap(target, self.portrait, source)
        blink_time = (self.phase + 1.) % 4.6
        blink = math.sin(math.pi * blink_time / .22) if blink_time < .22 and not self.reduced else 0.
        if blink > .01 and not self.blink_frame.isNull() and self.blink_frame.size() == self.portrait.size():
            clip = QPainterPath(); clip.addRoundedRect(QRectF(-pw*.18,-ph*.19,pw*.36,ph*.13),pw*.025,ph*.025)
            p.save(); p.setClipPath(clip,Qt.ClipOperation.IntersectClip); p.setOpacity(blink)
            p.drawPixmap(target,self.blink_frame,source); p.restore()
        if self.lip_open > .01 and not self.reduced and not self.talk_frame.isNull() and self.talk_frame.size() == self.portrait.size():
            clip = QPainterPath(); clip.addRoundedRect(QRectF(-pw*.13,0.,pw*.26,ph*.12),pw*.025,ph*.025)
            p.save(); p.setClipPath(clip,Qt.ClipOperation.IntersectClip); p.setOpacity(min(1.,self.lip_open))
            p.drawPixmap(target,self.talk_frame,source); p.restore()
        p.restore()
        p.end()
        self._frame, self._frame_key = frame, key
        return frame
