import threading
import unittest
from unittest.mock import MagicMock, patch

from pet.desktop_requests import DesktopRequestsMixin


class FakeEngine(DesktopRequestsMixin):
    def __init__(self, answer):
        self._init_desktop_requests()
        self.stopping = threading.Event()
        self.busy = threading.Event()
        self.paused = threading.Event()
        self.cancelled = threading.Event()
        self.desktop_finished = MagicMock()
        self.state = MagicMock()
        self.mic = MagicMock()
        self.cfg = {'audio': {'echo_cooldown_seconds': 0}}
        self._last_sleep_at = self._woke_at = 0
        self._answer = MagicMock(return_value=answer)
        self._idle = MagicMock()
        self._prepare_desktop_target = MagicMock()
        self.desktop_ready.set()

    def isRunning(self): return True


class DesktopEmptyResponseTests(unittest.TestCase):
    def run_request(self, engine):
        with patch('pet.session_state._pc_unlocked', return_value=True):
            self.assertEqual(engine.submit_text('Câu thử'), '')
            self.assertTrue(engine._run_desktop_request())

    def test_empty_answer_is_not_silently_marked_complete_or_retried(self):
        for answer in ('', '  ', None):
            with self.subTest(answer=answer):
                engine = FakeEngine(answer)
                self.run_request(engine)
                engine._answer.assert_called_once()
                ok, message = engine.desktop_finished.emit.call_args.args
                self.assertFalse(ok)
                self.assertIn('chưa tạo được câu trả lời', message)
                self.assertIn('kiểm tra kết quả', message)
                self.assertFalse(engine.busy.is_set())
                engine.mic.gate.assert_called_with(True)

    def test_valid_answer_finishes_normally(self):
        engine = FakeEngine('Tao đây!')
        self.run_request(engine)
        ok, _ = engine.desktop_finished.emit.call_args.args
        self.assertTrue(ok)

    def test_cancelled_turn_reports_stop_instead_of_no_answer(self):
        engine = FakeEngine('')
        def cancel(*args):
            engine.cancelled.set()
            return ''
        engine._answer.side_effect = cancel
        self.run_request(engine)
        self.assertEqual(engine.desktop_finished.emit.call_args.args, (False, 'Đã dừng.'))
