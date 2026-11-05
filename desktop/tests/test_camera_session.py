"""Exercise the actual Qt process lifecycle with a fake landmark source, no camera."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch
from PySide6.QtCore import QProcess
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pet.space_view import CameraSession


class StubProcess(QProcess):
    def setProgram(self, program): super().setProgram(sys.executable)
    def setArguments(self, args):
        super().setArguments(['-u','-c',
            "import sys,time; print('[1]',flush=True); print('{\"ready\":true}',flush=True); print('{\"hands\":[]}',flush=True); sys.stdin.readline()"])


def until(predicate):
    end=time.monotonic()+4
    while not predicate() and time.monotonic()<end: QTest.qWait(20)
    return predicate()


class CameraLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.session=CameraSession(); self.states=[]; self.status=[]; self.frames=[]
        self.session.running.connect(self.states.append); self.session.status.connect(self.status.append)
        self.session.hands.connect(self.frames.append)

    def tearDown(self): self.session.shutdown(); self.session.deleteLater(); self.app.processEvents()

    def test_missing_dependencies_do_not_start_camera(self):
        with patch.object(Path,'is_file',return_value=False): self.session.start()
        self.assertIsNone(self.session.process); self.assertEqual(self.states, [False])

    def test_real_child_stops_and_protocol_ignores_non_object_json(self):
        with patch('pet.space_view.QProcess',StubProcess),patch.object(Path,'is_file',return_value=True):
            self.session.start()
        proc=self.session.process
        self.assertTrue(until(lambda: bool(self.frames)))
        self.session.stop()
        self.assertTrue(until(lambda: not self.session.findChildren(QProcess)))
        self.assertFalse(self.session.deadline.isActive())
        self.assertIsNone(self.session.process)
        self.assertEqual(self.states,[True,False])

    def test_failure_message_survives_stop_signal(self):
        with patch('pet.space_view.QProcess',StubProcess),patch.object(Path,'is_file',return_value=True):
            self.session.start()
        self.session._failed(self.session.process)
        self.assertIn('Không mở được camera',self.status[-1])
        self.assertIsNone(self.session.process)


if __name__=='__main__': unittest.main()
