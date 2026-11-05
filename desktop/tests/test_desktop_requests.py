import threading
import time
import unittest
from unittest.mock import MagicMock, patch
from pet.desktop_requests import DesktopRequest, DesktopRequestsMixin


class Engine(DesktopRequestsMixin):
    def __init__(self):
        self._init_desktop_requests()
        self.stopping = threading.Event()
        self.busy = threading.Event()
        self.paused = threading.Event()
        self.cancelled = threading.Event()
        self.desktop_finished = MagicMock()
        self.state = MagicMock()
        self.mic = MagicMock()
        self.chat = MagicMock()
        self.chat.history = [('old question', 'answer')]
        self.opening_contexts = {'desktop': MagicMock(), 'mobile': MagicMock()}
        self.cfg = {'audio': {'echo_cooldown_seconds': 0}}
        self._last_sleep_at = self._woke_at = 0
        self._answer = MagicMock()
        self._idle = MagicMock()
        self._prepare_desktop_target = MagicMock()
        self.desktop_ready.set()

    def isRunning(self):
        return True


class DesktopRequestsTests(unittest.TestCase):
    def setUp(self):
        self.engine = Engine()
        self.unlocked = patch('pet.mobile._pc_unlocked', return_value=True)
        self.unlocked.start()
        self.addCleanup(self.unlocked.stop)

    def test_only_one_pending_request(self):
        self.assertEqual(self.engine.submit_text('Mở KiCad'), '')
        self.assertTrue(self.engine.submit_text('Mở KiCad'))
        self.assertEqual(self.engine.desktop_requests.qsize(), 1)

    def test_rejects_empty_oversize_not_ready_and_busy(self):
        self.assertTrue(self.engine.submit_text('  '))
        self.assertTrue(self.engine.submit_text('a' * 4001))
        self.engine.desktop_ready.clear()
        self.assertTrue(self.engine.submit_text('Xin chào'))
        self.engine.desktop_ready.set()
        self.engine.busy.set()
        self.assertTrue(self.engine.submit_text('Xin chào'))
        self.assertTrue(self.engine.desktop_requests.empty())

    def test_typed_text_runs_router_once_without_stt_and_resets_flags(self):
        self.engine.paused.set()
        def answer(text, audio, seconds):
            self.assertEqual(text, 'Mở KiCad')
            self.assertEqual(seconds, 0)
            self.assertEqual(len(audio.samples), 0)
            self.assertTrue(self.engine.busy.is_set())
            self.assertFalse(self.engine._desktop_speak)
        self.engine._answer.side_effect = answer
        self.engine.submit_text('Mở KiCad')
        self.assertTrue(self.engine._run_desktop_request())
        self.assertFalse(self.engine._run_desktop_request())
        self.engine._answer.assert_called_once()
        self.assertFalse(self.engine.busy.is_set())
        self.assertTrue(self.engine._desktop_speak)
        self.assertTrue(self.engine.paused.is_set())
        self.engine.mic.gate.assert_called_with(False)

    def test_expired_job_never_performs_action(self):
        self.engine.desktop_requests.put(DesktopRequest('Tắt nguồn', created=time.monotonic() - 20))
        self.engine._run_desktop_request()
        self.engine._answer.assert_not_called()

    def test_pre_sleep_job_never_replays_after_wake(self):
        self.engine.submit_text('Tắt máy')
        self.engine._woke_at = time.monotonic() + 1
        self.engine._run_desktop_request()
        self.engine._answer.assert_not_called()

    def test_locked_pc_never_performs_action(self):
        with patch('pet.mobile._pc_unlocked', return_value=False):
            self.engine.submit_text('Mở Notepad')
            self.engine._run_desktop_request()
        self.engine._answer.assert_not_called()

    def test_cancel_pending_request(self):
        self.engine.submit_text('Mở Notepad')
        self.engine._discard_desktop_requests()
        self.assertFalse(self.engine._run_desktop_request())
        self.engine._answer.assert_not_called()

    def test_reset_clears_model_memory_on_worker(self):
        self.engine.submit_text('', reset=True)
        self.engine._run_desktop_request()
        self.assertEqual(self.engine.chat.history, [])
        self.engine._answer.assert_not_called()
        self.engine.opening_contexts['desktop'].clear.assert_called_once()

    def test_failure_restores_gate_and_does_not_echo_private_error(self):
        self.engine._answer.side_effect = RuntimeError('private server response')
        self.engine.submit_text('Xin chào', speak=True)
        self.engine._run_desktop_request()
        self.assertFalse(self.engine.busy.is_set())
        self.engine.mic.gate.assert_called_with(True)
        args = self.engine.desktop_finished.emit.call_args.args
        self.assertFalse(args[0])
        self.assertNotIn('private server response', args[1])

    def test_target_failure_does_not_run_router(self):
        self.engine._prepare_desktop_target.side_effect = ValueError('Cửa sổ đã đổi.')
        self.engine.submit_text('Đóng cửa sổ hiện tại')
        self.engine._run_desktop_request()
        self.engine._answer.assert_not_called()


if __name__ == '__main__':
    unittest.main()
