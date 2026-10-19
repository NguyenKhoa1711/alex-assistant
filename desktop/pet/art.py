"""Vector fallback for the desktop pet when no sprite PNG is installed."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF, QRadialGradient,
)


ACCENTS = {
    'idle': '#80e1e5',
    'listening': '#7fe5b0',
    'thinking': '#c2a9ff',
    'speaking': '#ffc77e',
    'paused': '#aebbc9',
    'error': '#ffa5a5',
}

BODY = {
    'idle': ('#d9fcff', '#85dce9', '#65c5dc'),
    'listening': ('#e4fff0', '#89e7bd', '#58c69b'),
    'thinking': ('#f2eaff', '#ccb9ff', '#a893e3'),
    'speaking': ('#fff0d8', '#ffce91', '#eea869'),
    'paused': ('#e5edf2', '#aabcca', '#839caf'),
    'error': ('#ffe8e9', '#f4a9b0', '#d88496'),
}

INK = QColor('#244358')


def _fill(colors: tuple[str, str, str]) -> QLinearGradient:
    gradient = QLinearGradient(32, 37, 132, 148)
    gradient.setColorAt(0, QColor(colors[0]))
    gradient.setColorAt(.54, QColor(colors[1]))
    gradient.setColorAt(1, QColor(colors[2]))
    return gradient


def _ellipse(p: QPainter, x: float, y: float, w: float, h: float, color: str) -> None:
    p.setBrush(QColor(color))
    p.drawEllipse(QRectF(x, y, w, h))


def draw_pet(p: QPainter, shape: str, mode: str, phase: int) -> None:
    """Draw a 170 × 170 character; callers can scale it to any pet size."""
    mode = mode if mode in BODY else 'idle'
    accent = QColor(ACCENTS[mode])
    t = phase / 8
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)

    shadow = QRadialGradient(QPointF(85, 152), 58)
    shadow.setColorAt(0, QColor(14, 41, 60, 63))
    shadow.setColorAt(1, QColor(14, 41, 60, 0))
    p.setBrush(shadow)
    p.drawEllipse(QRectF(26, 141, 118, 23))

    if mode in ('listening', 'speaking', 'thinking'):
        radius = 72 + 2.2 * math.sin(t)
        ring = QColor(accent)
        ring.setAlpha(95)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(ring, 2.3))
        p.drawEllipse(QPointF(85, 87), radius, radius)
        p.setPen(Qt.PenStyle.NoPen)

    # Float the character while the shadow stays on the desktop.
    p.translate(0, 2.3 * math.sin(phase / 13))
    colors = BODY[mode]
    rim = QColor(colors[2]).darker(115)

    if shape == 'cat':
        p.setBrush(_fill(colors))
        p.setPen(QPen(rim, 2.4))
        p.drawPolygon(QPolygonF([
            QPointF(27, 74), QPointF(32, 18), QPointF(67, 48), QPointF(85, 43),
            QPointF(103, 48), QPointF(138, 18), QPointF(143, 74),
        ]))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor('#f9b6c8'))
        p.drawPolygon(QPolygonF([QPointF(38, 55), QPointF(39, 33), QPointF(59, 52)]))
        p.drawPolygon(QPolygonF([QPointF(111, 52), QPointF(131, 33), QPointF(132, 55)]))
        p.setBrush(_fill(colors))
        p.setPen(QPen(rim, 2.4))
        p.drawEllipse(QRectF(22, 42, 126, 106))
    elif shape == 'blob':
        body = QPainterPath()
        body.moveTo(83, 26)
        body.cubicTo(131, 20, 153, 60, 145, 101)
        body.cubicTo(144, 134, 120, 150, 84, 147)
        body.cubicTo(50, 151, 23, 135, 23, 100)
        body.cubicTo(18, 59, 42, 31, 83, 26)
        p.setBrush(_fill(colors))
        p.setPen(QPen(rim, 2.4))
        p.drawPath(body)
    else:
        # Robot: small side pods and an antenna stay behind the face.
        p.setPen(QPen(rim, 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(85, 30), QPointF(85, 18))
        p.setPen(Qt.PenStyle.NoPen)
        _ellipse(p, 78, 8, 14, 14, ACCENTS[mode])
        p.setBrush(QColor(colors[2]))
        p.drawRoundedRect(QRectF(9, 76, 18, 33), 9, 9)
        p.drawRoundedRect(QRectF(143, 76, 18, 33), 9, 9)
        p.setBrush(_fill(colors))
        p.setPen(QPen(rim, 2.4))
        p.drawRoundedRect(QRectF(21, 35, 128, 110), 39, 39)

    # A translucent forehead sheen gives all three silhouettes depth.
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255, 67))
    p.drawEllipse(QRectF(36, 42, 95, 54))
    p.setBrush(QColor(255, 255, 255, 112))
    p.drawEllipse(QRectF(40, 47, 29, 10))
    if shape == 'robot':
        p.setBrush(QColor(255, 255, 255, 39))
        p.drawRoundedRect(QRectF(31, 43, 108, 85), 28, 28)

    blink = mode == 'paused' or phase % 137 in (0, 1, 2, 3)
    for x in (53, 104):
        if blink:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(INK, 3.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(QRectF(x-1, 75, 16, 12), 195 * 16, 150 * 16)
            p.setPen(Qt.PenStyle.NoPen)
        else:
            p.setBrush(INK)
            p.drawRoundedRect(QRectF(x, 72, 14, 20), 7, 7)
            _ellipse(p, x+3, 75, 4, 5, '#ffffff')

    if mode != 'paused':
        _ellipse(p, 37, 101, 17, 8, '#eaa3ac')
        _ellipse(p, 116, 101, 17, 8, '#eaa3ac')

    if shape == 'cat':
        p.setBrush(QColor('#bb6c85'))
        p.drawPolygon(QPolygonF([QPointF(80, 101), QPointF(90, 101), QPointF(85, 107)]))
        p.setPen(QPen(INK, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for y in (106, 114):
            p.drawLine(QPointF(28, y), QPointF(48, y+2))
            p.drawLine(QPointF(122, y+2), QPointF(142, y))
        p.setPen(Qt.PenStyle.NoPen)

    p.setPen(QPen(INK, 3.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.BrushStyle.NoBrush)
    if mode == 'speaking':
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(INK)
        p.drawEllipse(QRectF(77, 106, 16, 11 + 8 * abs(math.sin(phase / 3))))
        p.setBrush(QColor('#f49aa5'))
        p.drawEllipse(QRectF(81, 117, 8, 4))
    elif mode == 'thinking':
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(INK)
        p.drawRoundedRect(QRectF(80, 111, 10, 5), 2.5, 2.5)
    elif mode == 'paused':
        p.drawLine(QPointF(77, 115), QPointF(93, 115))
    else:
        p.drawArc(QRectF(70, 100, 30, 25), 205 * 16, 130 * 16)
    p.setPen(Qt.PenStyle.NoPen)

    if mode == 'listening':
        p.setBrush(Qt.BrushStyle.NoBrush)
        wave = QColor(ACCENTS[mode])
        for side in (-1, 1):
            p.setPen(QPen(wave, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            x = 8 if side < 0 else 143
            p.drawArc(QRectF(x, 67, 19, 39), (290 if side < 0 else 70) * 16, 140 * 16)
    elif mode == 'speaking':
        p.setPen(QPen(accent, 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for side in (-1, 1):
            x = 7 if side < 0 else 160
            for index, height in enumerate((9, 20, 12)):
                dx = index * (6 if side < 0 else -6)
                p.drawLine(QPointF(x+dx, 87-height/2), QPointF(x+dx, 87+height/2))
    elif mode == 'thinking':
        p.setPen(Qt.PenStyle.NoPen)
        for index in range(3):
            alpha = 100 + 50 * (1 + math.sin(t + index))
            dot = QColor(ACCENTS[mode])
            dot.setAlpha(int(alpha))
            p.setBrush(dot)
            p.drawEllipse(QRectF(119 + index * 11, 13 + index * 8, 7-index, 7-index))
    p.restore()
