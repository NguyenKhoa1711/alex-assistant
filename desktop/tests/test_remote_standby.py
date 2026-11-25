import ctypes
import unittest
from unittest.mock import MagicMock, patch

from pet import remote_standby as rs


class RemoteStandbyTests(unittest.TestCase):
    def setUp(self):
        self.backend = MagicMock()
        self.backend.on_ac.return_value = True
        self.backend.acquire.return_value = 123
        self.guard = rs.RemoteStandby(True, self.backend)

    def tearDown(self):
        self.guard.close()

    def test_ac_reuses_one_request_battery_releases_and_replug_reacquires(self):
        for _ in range(10):
            self.assertTrue(self.guard.update())
        self.backend.acquire.assert_called_once()
        self.backend.on_ac.return_value = False
        self.assertFalse(self.guard.update())
        self.assertFalse(self.guard.update())
        self.backend.release.assert_called_once_with(123)
        self.backend.on_ac.return_value = True
        self.assertTrue(self.guard.update())
        self.assertEqual(self.backend.acquire.call_count, 2)

    def test_disabled_never_acquires(self):
        self.guard.enabled = False
        self.assertFalse(self.guard.update())
        self.backend.acquire.assert_not_called()

    def test_power_query_failure_releases_existing_request(self):
        self.guard.update()
        self.backend.on_ac.side_effect = OSError('query failed')
        with self.assertRaises(OSError):
            self.guard.update()
        self.backend.release.assert_called_once_with(123)

    def test_exit_releases_once_and_cannot_reacquire(self):
        self.guard.update()
        self.guard.close()
        self.guard.close()
        self.assertFalse(self.guard.update())
        self.backend.release.assert_called_once_with(123)
        self.backend.acquire.assert_called_once()

    def test_ac_removed_between_router_and_action_fails_without_sleep(self):
        self.assertTrue(self.guard.wants_remote_wait())
        self.backend.on_ac.return_value = False
        with self.assertRaises(OSError):
            self.guard.require_active()
        self.backend.acquire.assert_not_called()

    def test_failed_acquisition_can_retry(self):
        self.backend.acquire.side_effect = [OSError('unavailable'), 123]
        with self.assertRaises(OSError):
            self.guard.update()
        self.assertTrue(self.guard.update())

    def test_resume_replaces_cancelled_lease_only_if_still_on_ac(self):
        self.guard.update()
        self.guard.notify_resume()
        self.assertTrue(self.guard.update())
        self.backend.release.assert_called_once_with(123)
        self.assertEqual(self.backend.acquire.call_count, 2)
        self.backend.on_ac.return_value = False
        self.guard.notify_resume()
        self.assertFalse(self.guard.update())
        self.assertEqual(self.backend.acquire.call_count, 2)

    def test_native_request_never_keeps_display_on(self):
        api = MagicMock()
        api.PowerCreateRequest.return_value = 123
        api.PowerSetRequest.return_value = True
        with patch.object(rs.ctypes, 'WinDLL', return_value=api):
            backend = rs.WindowsPowerRequest()
            handle = backend.acquire()
            backend.release(handle)
        self.assertEqual([call.args[1] for call in api.PowerSetRequest.call_args_list], [1, 3])
        self.assertEqual([call.args[1] for call in api.PowerClearRequest.call_args_list], [3, 1])
        api.CloseHandle.assert_called_once_with(123)

    def test_second_native_request_failure_rolls_back_first_and_closes(self):
        api = MagicMock()
        api.PowerCreateRequest.return_value = 123
        api.PowerSetRequest.side_effect = [True, False]
        with patch.object(rs.ctypes, 'WinDLL', return_value=api), \
             patch.object(rs.ctypes, 'get_last_error', return_value=5):
            backend = rs.WindowsPowerRequest()
            with self.assertRaises(OSError):
                backend.acquire()
        api.PowerClearRequest.assert_called_once_with(123, 1)
        api.CloseHandle.assert_called_once_with(123)

    def test_unknown_ac_status_does_not_hold_battery_awake(self):
        api = MagicMock()
        def fill_status(pointer):
            ctypes.cast(pointer, ctypes.POINTER(rs._SystemPowerStatus)).contents.ACLineStatus = 255
            return True
        api.GetSystemPowerStatus.side_effect = fill_status
        with patch.object(rs.ctypes, 'WinDLL', return_value=api):
            self.assertFalse(rs.WindowsPowerRequest().on_ac())


class DisplayAwakeTests(unittest.TestCase):
    def setUp(self):
        self.backend = MagicMock()
        self.backend.on_ac.return_value = True
        self.backend.session_unlocked.return_value = True
        self.backend.acquire.return_value = 123
        self.backend.acquire_display.return_value = 456
        self.guard = rs.RemoteStandby(True, self.backend, display_enabled=True)

    def tearDown(self):
        self.guard.close()

    def test_display_only_while_plugged_in_and_unlocked(self):
        self.guard.update()
        self.guard.update()
        self.backend.acquire_display.assert_called_once()
        self.backend.session_unlocked.return_value = False
        self.guard.update()
        self.backend.release_display.assert_called_once_with(456)
        self.backend.release.assert_not_called()  # remote waiting remains active
        self.backend.session_unlocked.return_value = True
        self.guard.update()
        self.assertEqual(self.backend.acquire_display.call_count, 2)
        self.backend.on_ac.return_value = False
        self.guard.update()
        self.assertEqual(self.backend.release_display.call_count, 2)
        self.backend.release.assert_called_once_with(123)

    def test_screen_hold_works_without_phone_bridge(self):
        self.guard.enabled = False
        self.assertFalse(self.guard.update())
        self.backend.acquire.assert_not_called()
        self.backend.acquire_display.assert_called_once()

    def test_prepare_lock_never_reacquires_before_lock_then_unlock(self):
        self.guard.update()
        self.guard.prepare_lock()
        self.backend.release_display.assert_called_once_with(456)
        self.guard.update()  # still unlocked while Windows is preparing to lock
        self.assertEqual(self.backend.acquire_display.call_count, 1)
        self.guard.confirm_locked()
        self.backend.session_unlocked.return_value = False
        self.guard.update()
        self.assertEqual(self.backend.acquire_display.call_count, 1)
        self.backend.session_unlocked.return_value = True
        self.guard.update()
        self.assertEqual(self.backend.acquire_display.call_count, 2)

    def test_unreadable_session_does_not_keep_screen_on_or_fake_lock(self):
        self.guard.update()
        self.guard.prepare_lock()
        self.backend.session_unlocked.side_effect = [OSError('unknown'), True, True]
        self.guard.update()
        self.guard.update()
        self.assertEqual(self.backend.acquire_display.call_count, 1)
        self.guard.cancel_lock()
        self.assertEqual(self.backend.acquire_display.call_count, 2)

    def test_close_releases_both_requests(self):
        self.guard.update()
        self.guard.close()
        self.backend.release.assert_called_once_with(123)
        self.backend.release_display.assert_called_once_with(456)

    def test_native_display_request_is_separate_and_released(self):
        api = MagicMock()
        api.PowerCreateRequest.return_value = 123
        api.PowerSetRequest.return_value = True
        with patch.object(rs.ctypes, 'WinDLL', return_value=api):
            backend = rs.WindowsPowerRequest()
            handle = backend.acquire_display()
            backend.release_display(handle)
        api.PowerSetRequest.assert_called_once_with(123, 0)
        api.PowerClearRequest.assert_called_once_with(123, 0)
        api.CloseHandle.assert_called_once_with(123)


if __name__ == '__main__':
    unittest.main()
