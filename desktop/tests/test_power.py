from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from pet.audio import Microphone, Utterance
from pet.config import load_config
from pet.controller import Controller
from pet.mobile import MobileJob
from pet.power import _turn_off_display_for_s0, execute_power, parse_power_request


class PowerCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = Controller(load_config())
        self.engine.paused.clear()
        self.engine.chat = self.engine.gemini_chat = MagicMock()
        self.engine.speaker = MagicMock()
        self.utterance = Utterance(np.zeros(100), time.monotonic())

    def say(self, text: str) -> str:
        return self.engine._answer(text, self.utterance, 0.1)

    def test_power_mapping_and_complete_command_only(self) -> None:
        options = self.engine.cfg['power']
        self.assertEqual(parse_power_request('Bạn tắt máy cho tôi', options), 'sleep')
        self.assertEqual(parse_power_request('Hãy tắt nguồn ngay', options), 'shutdown')
        self.assertEqual(parse_power_request('Cho máy ngủ', options), 'sleep')
        for text in ('Cách tắt nguồn', 'Đừng tắt máy', 'Tắt máy rồi mở Chrome',
                     'Tôi nói tắt máy chứ không phải tắt nguồn'):
            with self.subTest(text=text):
                self.assertIsNone(parse_power_request(text, options))

    def test_sleep_runs_on_one_voice_turn_and_releases_microphone(self) -> None:
        self.engine.mic = MagicMock()
        with patch('pet.controller.execute_power') as power:
            answer = self.say('Tắt máy cho tôi')
            self.assertIn('cho máy ngủ', answer)
            power.assert_called_once_with('sleep')
            self.engine.chat.stream.assert_not_called()
        self.assertTrue(self.engine.paused.is_set())
        self.engine.mic.close.assert_called_once_with()

    def test_sleep_is_not_repeated_after_microphone_resumes(self) -> None:
        self.engine.mic = MagicMock()
        with patch('pet.controller.execute_power') as power:
            self.say('Tắt máy')
            self.engine.paused.clear()  # Simulate waking and showing the pet again.
            self.assertEqual(self.say('Tắt máy'), '')
            self.assertEqual(self.say('Tắt máy cho tôi'), '')
            power.assert_called_once_with('sleep')
            self.engine.mic.close.assert_called_once_with()
            self.engine.chat.stream.assert_not_called()

    def test_different_request_rearms_power_action(self) -> None:
        self.engine.mic = MagicMock()
        with patch('pet.controller.execute_power') as power:
            self.say('Tắt máy')
            self.engine.paused.clear()
            self.engine._power_turn('Chào Alex', self.utterance, 0.1, None)
            self.say('Tắt máy')
            self.assertEqual(power.call_count, 2)
            self.assertEqual(self.engine.mic.close.call_count, 2)

    def test_closing_microphone_discards_buffered_audio(self) -> None:
        mic = Microphone(self.engine.cfg['audio'])
        mic.frames.put_nowait((b'old speech', time.monotonic()))
        mic.close()
        self.assertTrue(mic.frames.empty())

    def test_failed_sleep_restores_microphone(self) -> None:
        self.engine.mic = MagicMock()
        with patch('pet.controller.execute_power', side_effect=OSError(50, 'unsupported')):
            self.say('Tắt máy')
        self.assertFalse(self.engine.paused.is_set())
        self.engine.mic.close.assert_called_once_with()
        self.engine.mic.start.assert_called_once_with()
        self.assertFalse(self.engine._power_latched)

    def test_observed_whisper_variants_mean_sleep_only(self) -> None:
        options = self.engine.cfg['power']
        for phrase in ('Tắc mái', 'Tạch mái', 'Tắt mái'):
            with self.subTest(phrase=phrase):
                self.assertEqual(parse_power_request(phrase, options), 'sleep')
                self.assertNotEqual(parse_power_request(phrase, options), 'shutdown')

    def test_shutdown_runs_on_one_voice_turn(self) -> None:
        with patch('pet.controller.execute_power') as power:
            self.say('Tắt nguồn')
            power.assert_called_once_with('shutdown')
        self.engine.chat.stream.assert_not_called()

    def test_remote_wait_locks_once_and_preserves_duplicate_guard(self) -> None:
        self.engine.mic = MagicMock()
        with patch('pet.power.wants_remote_wait', return_value=True), \
             patch('pet.controller.execute_power') as power:
            answer = self.say('Tắt máy')
            self.assertIn('chờ bạn mở khóa từ xa', answer)
            self.assertNotIn('cho máy ngủ', answer)
            self.engine.paused.clear()
            self.assertEqual(self.say('Tắt máy'), '')
            power.assert_called_once_with('remote_wait')
            self.engine.mic.close.assert_called_once()
            self.engine.chat.stream.assert_not_called()

    def test_remote_wait_does_not_change_shutdown_or_wake(self) -> None:
        with patch('pet.power.wants_remote_wait', return_value=True), \
             patch('pet.controller.execute_power') as power:
            self.say('Tắt nguồn')
            power.assert_called_once_with('shutdown')

    def test_remote_wait_verifies_lock_without_sending_monitor_power_or_sleep(self) -> None:
        fake_user = MagicMock()
        fake_user.LockWorkStation.return_value = True
        with patch('pet.power.require_remote_wait') as keep_awake, \
             patch('pet.power.ctypes.WinDLL', return_value=fake_user), \
             patch('pet.power.UnlockGate') as gate, \
             patch('pet.power.begin_display_priority', return_value='ticket') as begin, \
             patch('pet.power.confirm_display_priority') as confirm, \
             patch('pet.power._turn_off_display_for_s0') as blank:
            gate.return_value.status.return_value = {'status': 'locked'}
            execute_power('remote_wait')
        fake_user.LockWorkStation.assert_called_once()
        begin.assert_called_once()
        confirm.assert_called_once_with('ticket')
        fake_user.SetSuspendState.assert_not_called()
        self.assertEqual(keep_awake.call_count, 2)
        blank.assert_not_called()
        fake_user.SendMessageTimeoutW.assert_not_called()

    def test_priority_failure_prevents_lock_and_never_sleeps(self) -> None:
        with patch('pet.power.require_remote_wait'), \
             patch('pet.power.begin_display_priority', side_effect=OSError('task missing')), \
             patch('pet.power.ctypes.WinDLL') as win:
            with self.assertRaises(OSError):
                execute_power('remote_wait')
        win.assert_not_called()

    def test_lock_failure_cancels_temporary_priority(self) -> None:
        fake_user = MagicMock()
        fake_user.LockWorkStation.return_value = False
        with patch('pet.power.require_remote_wait'), \
             patch('pet.power.begin_display_priority', return_value='ticket'), \
             patch('pet.power.cancel_display_priority') as cancel, \
             patch('pet.power.ctypes.WinDLL', return_value=fake_user):
            with self.assertRaises(OSError):
                execute_power('remote_wait')
        cancel.assert_called_once()

    def test_remote_wait_failure_never_falls_back_to_sleep(self) -> None:
        with patch('pet.power.require_remote_wait', side_effect=OSError('on battery')), \
             patch('pet.power.ctypes.WinDLL') as win, \
             patch('pet.power._turn_off_display_for_s0') as blank:
            with self.assertRaises(OSError):
                execute_power('remote_wait')
        win.assert_not_called()
        blank.assert_not_called()

    def test_non_imperatives_never_power_off(self) -> None:
        with patch('pet.controller.execute_power') as power:
            for phrase in ('Cách tắt nguồn', 'Đừng tắt máy', 'Tắt máy rồi mở Chrome'):
                self.say(phrase)
            power.assert_not_called()

    def test_interrupted_announcement_never_executes(self) -> None:
        with patch('pet.controller.execute_power') as power:
            def interrupt(*_args):
                self.engine.cancelled.set()
            self.engine.speaker.speak.side_effect = interrupt
            self.say('Tắt nguồn')
            power.assert_not_called()

    def test_phone_can_issue_power_and_wake_commands_even_when_laptop_mic_paused(self) -> None:
        self.engine.paused.set()
        self.engine.speaker.render_pcm.return_value = (48000, b'\x01\x00')
        with patch('pet.controller.execute_power') as power:
            sleep_job = MobileJob(np.zeros(100, dtype=np.float32))
            sleep_answer = self.engine._answer('Hãy tắt máy cho tôi', self.utterance, 0.1, sleep_job)
            self.assertIn('cho máy ngủ', sleep_answer)
            self.assertTrue(sleep_job.audio)

            wake_job = MobileJob(np.zeros(100, dtype=np.float32))
            wake_answer = self.engine._answer('Bật máy tính lên cho tôi', self.utterance, 0.1, wake_job)
            self.assertIn('bật sáng màn hình', wake_answer)
            self.assertTrue(wake_job.audio)

            shutdown_job = MobileJob(np.zeros(100, dtype=np.float32))
            shutdown_answer = self.engine._answer('Tắt nguồn cho tôi', self.utterance, 0.1, shutdown_job)
            self.assertIn('tắt nguồn', shutdown_answer)
            self.assertTrue(shutdown_job.audio)

        self.assertEqual([c.args[0] for c in power.call_args_list], ['sleep', 'wake', 'shutdown'])
        self.engine.chat.stream.assert_not_called()

    def test_phone_can_show_and_hide_pet_on_pc(self) -> None:
        self.engine.paused.set()
        self.engine.speaker.render_pcm.return_value = (48000, b'\x01\x00')
        events: list[bool] = []
        self.engine.pet_visibility.connect(events.append)
        for phrase in ('mở pet trên máy tính cho tôi.', 'mở Alex trên mê tính cho tôi.'):
            job = MobileJob(np.zeros(100, dtype=np.float32))
            answer = self.engine._answer(phrase, self.utterance, 0.1, job)
            self.assertIn('đã hiện Alex', answer)
            self.assertFalse(self.engine.paused.is_set())
        hide_job = MobileJob(np.zeros(100, dtype=np.float32))
        hide_answer = self.engine._answer('Ẩn pet trên máy tính cho tôi', self.utterance, 0.1, hide_job)
        self.assertIn('đã ẩn Alex', hide_answer)
        self.assertTrue(self.engine.paused.is_set())
        self.assertEqual(events, [True, True, False])

    def test_shutdown_uses_no_force_flag_and_sleep_requests_suspend(self) -> None:
        with patch('pet.power.subprocess.run') as run:
            execute_power('shutdown')
        command = run.call_args.args[0]
        self.assertEqual(command[-3:], ['/s', '/t', '0'])
        self.assertNotIn('/f', command)
        fake_dll = MagicMock()
        fake_dll.SetSuspendState.return_value = 1
        with patch('pet.power._enable_shutdown_privilege'), \
             patch('pet.power.ctypes.WinDLL', return_value=fake_dll):
            execute_power('sleep')
        fake_dll.SetSuspendState.assert_called_once_with(False, False, False)

    def test_s0_sleep_falls_back_to_display_off_only_for_unsupported_api(self) -> None:
        fake_dll = MagicMock()
        fake_dll.SetSuspendState.return_value = 0
        with patch('pet.power._enable_shutdown_privilege'), \
             patch('pet.power.ctypes.WinDLL', return_value=fake_dll), \
             patch('pet.power.ctypes.get_last_error', return_value=50), \
             patch('pet.power._turn_off_display_for_s0') as display_off:
            execute_power('sleep')
        display_off.assert_called_once_with()
        with patch('pet.power._enable_shutdown_privilege'), \
             patch('pet.power.ctypes.WinDLL', return_value=fake_dll), \
             patch('pet.power.ctypes.get_last_error', return_value=5), \
             patch('pet.power._turn_off_display_for_s0') as display_off:
            with self.assertRaises(OSError):
                execute_power('sleep')
        display_off.assert_not_called()

    def test_phone_sleep_completes_http_job_before_suspend_and_blocks_duplicate_retry(self) -> None:
        self.engine.paused.set()
        self.engine.speaker.render_pcm.return_value = (48000, b'\x01\x00')
        done_when_called: list[bool] = []

        def fake_power(action: str) -> None:
            done_when_called.append(first_job.done.is_set())

        first_job = MobileJob(np.zeros(100, dtype=np.float32))
        retry_job = MobileJob(np.zeros(100, dtype=np.float32))
        with patch('pet.controller.execute_power', side_effect=fake_power) as power:
            answer = self.engine._answer('Tắt máy cho tôi', self.utterance, 0.1, first_job)
            self.assertIn('cho máy ngủ', answer)
            self.assertEqual(done_when_called, [True])
            self.assertEqual(first_job.reply, answer)
            # Duplicate retry arriving when laptop wakes up must be ignored.
            retry_answer = self.engine._answer('Tắt máy cho tôi', self.utterance, 0.1, retry_job)
            self.assertEqual(retry_answer, '')
            power.assert_called_once_with('sleep')

    def test_s0_display_off_uses_windows_monitor_power_message(self) -> None:
        fake_dll = MagicMock()
        fake_dll.GetShellWindow.return_value = 0x10010
        fake_dll.SendMessageTimeoutW.return_value = 1
        with patch('pet.power.ctypes.WinDLL', return_value=fake_dll):
            _turn_off_display_for_s0()
        hwnd, message, command, off, flags, timeout, _result = (
            fake_dll.SendMessageTimeoutW.call_args.args)
        self.assertNotEqual(hwnd, 0xFFFF)
        self.assertEqual((hwnd, message, command, off), (0x10010, 0x0112, 0xF170, 2))
        self.assertEqual((flags, timeout), (0x0002, 1000))


if __name__ == '__main__':
    unittest.main()
