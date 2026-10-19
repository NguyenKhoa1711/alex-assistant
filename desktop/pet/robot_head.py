"""Offline robot-heads playback; small bounded frame cache, no browser runtime."""
from __future__ import annotations

from collections import OrderedDict
import json
import logging
from pathlib import Path
import time
from zipfile import BadZipFile, ZipFile

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter, QPixmap


class RobotHeadAnimation:
    CACHE_LIMIT = 20
    STATES = {'idle', 'listening', 'thinking', 'speaking', 'sleeping',
              'error', 'happy', 'working', 'searching'}

    def __init__(self, assets: Path) -> None:
        self.available = False
        self.archive: ZipFile | None = None
        self.cache: OrderedDict[tuple[str, int], QPixmap] = OrderedDict()
        self.state = 'idle'
        self.started = time.monotonic()
        self.previous: QPixmap | None = None
        self.transition = self.started
        self.frozen: float | None = None
        try:
            self.info = json.loads((assets / 'manifest.json').read_text(encoding='utf-8'))
            self.fps = int(self.info['fps'])
            self.count = int(self.info['count'])
            if not 1 <= self.fps <= 60 or not 10 <= self.count <= 1000:
                raise ValueError('Invalid animation frame rate/count')
            self.archive = ZipFile(assets / 'circle-teal.zip')
            names = set(self.archive.namelist())
            if any(f'{state}/{i:03}.png' not in names
                   for state in self.STATES for i in range(self.count)):
                raise ValueError('Incomplete robot-heads frames')
            self.available = not self.frame('idle', 0).isNull()
            logging.info('Robot-heads circle loaded; offline animation at %s fps', self.fps)
        except (OSError, ValueError, KeyError, BadZipFile) as exc:
            logging.warning('Robot-heads unavailable, using original drawing: %s', exc)
            self.close()

    def frame(self, state: str, index: int) -> QPixmap:
        key = (state, index % self.count)
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        pixmap = QPixmap()
        if self.archive is None:
            return pixmap
        try:
            if not pixmap.loadFromData(self.archive.read(f'{state}/{key[1]:03}.png'), 'PNG'):
                raise ValueError('Invalid PNG frame')
        except (OSError, KeyError, ValueError, BadZipFile) as exc:
            self.available = False
            logging.warning('Robot animation frame failed: %s', exc)
            return pixmap
        self.cache[key] = pixmap
        while len(self.cache) > self.CACHE_LIMIT:
            self.cache.popitem(last=False)
        return pixmap

    def _now(self) -> float:
        return self.frozen if self.frozen is not None else time.monotonic()

    def index(self, now: float | None = None) -> int:
        return int(max(0, (self._now() if now is None else now) - self.started) * self.fps) % self.count

    def set_state(self, mode: str) -> None:
        state = 'sleeping' if mode == 'paused' else mode
        if state not in self.STATES:
            state = 'idle'
        if state == self.state or not self.available:
            return
        now = self._now()
        self.previous = self.frame(self.state, self.index(now))
        self.state, self.started, self.transition = state, now, now

    def suspend(self, suspended: bool) -> None:
        now = time.monotonic()
        if suspended and self.frozen is None:
            self.frozen = now
        elif not suspended and self.frozen is not None:
            elapsed = now - self.frozen
            self.started += elapsed
            self.transition += elapsed
            self.frozen = None

    def paint(self, painter: QPainter, box: QRectF) -> bool:
        if not self.available:
            return False
        now = self._now()
        index = self.index(now)
        current = self.frame(self.state, index)
        if current.isNull():
            return False
        frame = self.info['frame']
        scale = box.width() / self.info['size']
        target = QRectF(box.x() - frame['padSide'] * scale,
                        box.y() - frame['padTop'] * scale,
                        self.info['width'] / self.info['dpr'] * scale,
                        self.info['height'] / self.info['dpr'] * scale)
        transition = min(1.0, max(0.0, (now - self.transition) / .18))
        painter.save()
        if self.previous is not None and transition < 1:
            painter.setOpacity(1 - transition)
            painter.drawPixmap(target, self.previous, QRectF(self.previous.rect()))
            painter.setOpacity(transition)
        else:
            self.previous = None
        painter.drawPixmap(target, current, QRectF(current.rect()))
        # Blend the end of a baked loop into its first pose to avoid a hard cut.
        loop_mix = max(0.0, (index - (self.count - 5)) / 4)
        if loop_mix:
            first = self.frame(self.state, 0)
            painter.setOpacity(loop_mix * transition)
            painter.drawPixmap(target, first, QRectF(first.rect()))
        painter.restore()
        return True

    def close(self) -> None:
        if self.archive is not None:
            self.archive.close()
        self.archive = None
        self.cache.clear()
        self.available = False
