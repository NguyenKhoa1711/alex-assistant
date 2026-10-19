"""UI smoke tests with a dummy engine: never record, speak, or open an app."""
from __future__ import annotations
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import types
import unittest

from PySide6.QtCore import QObject, Signal, QPoint, Qt
from PySide6.QtGui import QFontDatabase, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
import yaml

ROOT = Path(__file__).resolve().parent.parent
LIVE = Path(sys.argv.pop(1))
package = types.ModuleType('pet')
package.__path__ = [str(ROOT / 'pet'), str(LIVE / 'pet')]
sys.modules['pet'] = package
for name, value in [('controller', 'Controller'), ('mobile', 'MobileBridge')]:
    module = types.ModuleType('pet.' + name)
    setattr(module, value, object)
    sys.modules[module.__name__] = module
from pet import window as module
from pet.robot_head import RobotHeadAnimation


class Engine(QObject):
    state = Signal(str, str)
    transcript = Signal(str)
    reply = Signal(str)
    timing = Signal(str)
    confirmation = Signal(str, object)
    finished = Signal()

    def __init__(self):
        super().__init__()
        self.paused = threading.Event()
        self.mic = None
        self.learning = None
        self.toggles = 0
    def toggle(self): self.toggles += 1
    def interrupt(self): pass
    def stop(self): pass
    def isRunning(self): return False


class DummyHotkey:
    def __init__(self, callback): self.registered = True
    def close(self): pass


class DummyTray(QObject):
    activated = Signal(object)
    ActivationReason = QSystemTrayIcon.ActivationReason
    MessageIcon = QSystemTrayIcon.MessageIcon
    def __init__(self, *args): super().__init__()
    def setToolTip(self, *args): pass
    def setContextMenu(self, *args): pass
    def show(self): pass
    def showMessage(self, *args): pass
    def hide(self): pass


class RobotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/segoeui.ttf')
        module.GlobalHotkey = DummyHotkey
        module.QSystemTrayIcon = DummyTray
        module.ROOT = ROOT

    def make_window(self):
        cfg = {'name':'Alex', 'pet':{'shape':'robot-heads','size':110,'x':40,'y':40,
                                   'fps':30,'start_hidden':True}}
        win = module.PetWindow(cfg, Engine())
        self.addCleanup(win.robot_head.close)
        self.addCleanup(win.hide)
        return win

    def test_frames_cache_and_all_states(self):
        robot = RobotHeadAnimation(ROOT / 'assets/robot-heads')
        self.addCleanup(robot.close)
        self.assertTrue(robot.available)
        signatures = set()
        for state in robot.STATES:
            robot.set_state(state)
            for index in range(robot.count):
                frame = robot.frame(state, index)
                self.assertFalse(frame.isNull())
                self.assertTrue(frame.hasAlphaChannel())
            signatures.add(robot.frame(state, 30).cacheKey())
            self.assertLessEqual(len(robot.cache), robot.CACHE_LIMIT)
        self.assertEqual(len(signatures), 9)
        robot.set_state('paused')
        self.assertEqual(robot.state, 'sleeping')
        robot.set_state('unknown')
        self.assertEqual(robot.state, 'idle')

    def test_state_signals_click_drag_and_hidden_timer(self):
        win = self.make_window()
        win.save_position = lambda: None
        self.assertFalse(win.timer.isActive())
        win.show()
        QTest.qWait(80)
        self.assertTrue(win.timer.isActive())
        for mode in ['idle','listening','thinking','speaking','error','paused']:
            win.engine.state.emit(mode, mode)
            self.assertEqual(win.robot_head.state, 'sleeping' if mode == 'paused' else mode)
            self.assertEqual(win.caption, mode)
        QTest.mouseClick(win, Qt.MouseButton.LeftButton, pos=QPoint(110,170))
        self.assertEqual(win.engine.toggles, 1)
        old_pos = win.pos()
        QTest.mousePress(win, Qt.MouseButton.LeftButton, pos=QPoint(110,170))
        QTest.mouseMove(win, QPoint(155,185), 40)
        QTest.mouseRelease(win, Qt.MouseButton.LeftButton, pos=QPoint(155,185))
        self.assertNotEqual(win.pos(), old_pos)
        self.assertEqual(win.engine.toggles, 1)
        win.hide()
        self.assertFalse(win.timer.isActive())
        frozen = win.robot_head.index()
        QTest.qWait(120)
        self.assertEqual(win.robot_head.index(), frozen)
        win.show()
        self.assertTrue(win.timer.isActive())

    def test_old_shape_and_config_merge(self):
        win = self.make_window()
        with tempfile.TemporaryDirectory() as temp:
            cfg_path = Path(temp) / 'config.yaml'
            cfg_path.write_text(yaml.safe_dump({'pet':{'size':110},'stt':{'model':'unchanged'}}))
            old_root = module.ROOT
            try:
                module.ROOT = Path(temp)
                win.change_shape('mascot')
                saved = yaml.safe_load(cfg_path.read_text())
                self.assertEqual(saved['stt']['model'], 'unchanged')
                self.assertEqual(saved['pet']['shape'], 'mascot')
                self.assertEqual(win.height(), 222)
                win.change_shape('robot-heads')
                self.assertEqual(win.height(), 261)
            finally:
                module.ROOT = old_root

    def test_missing_asset_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            robot = RobotHeadAnimation(Path(temp))
            self.assertFalse(robot.available)
            robot.set_state('speaking')
            robot.close()
        win = self.make_window()
        win.robot_head.close()
        self.assertFalse(win.grab().isNull())

    def test_preview_and_decode_cost(self):
        win = self.make_window()
        states = [('idle','Sẵn sàng'),('listening','Mình đang nghe…'),
                  ('thinking','Đang nghĩ…'),('speaking','Đang nói · bấm pet để ngắt'),
                  ('paused','Mic tắt · bấm pet để bật'),('error','Có lỗi · xem nhật ký')]
        board = QImage(win.width()*3, win.height()*2, QImage.Format.Format_ARGB32)
        board.fill(Qt.GlobalColor.transparent)
        painter = QPainter(board)
        for i, (mode, caption) in enumerate(states):
            win.set_state(mode, caption)
            win.robot_head.started = win.robot_head._now() - 1.5
            win.robot_head.previous = None
            painter.drawPixmap((i%3)*win.width(), (i//3)*win.height(), win.grab())
        painter.end()
        board.save(str(ROOT / 'robot-preview.png'))
        started = time.perf_counter()
        for i in range(160): win.robot_head.frame('idle', i)
        ms = (time.perf_counter() - started)*1000/160
        print(json.dumps({'decode_ms_per_frame':round(ms,3),
              'cache_upper_mib':round(20*195*276*4/1024**2,2)}))
        self.assertLess(ms, 50, 'Frame decode exceeds a full 20 fps frame budget')


if __name__ == '__main__': unittest.main()
