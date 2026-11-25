"""Regression tests: labels alone cannot prove a message was sent."""
import threading
import unittest
from unittest.mock import MagicMock
from pet.messaging_driver import ZaloUiDriver, MessengerUiDriver
from pet.message_flow import send_requested_once
from pet.message_intent import SendIntent


class MessagingEvidenceGuardTests(unittest.TestCase):
    def test_scoped_label_without_verified_author_is_not_a_sent_message(self):
        for driver_type, root in (
            (ZaloUiDriver, {'role': 'group', 'native_id': {'value': 'messageViewContainer'}}),
            (MessengerUiDriver, {'role': 'main'}),
        ):
            with self.subTest(driver=driver_type.__name__):
                driver = driver_type()
                bridge = MagicMock()
                bridge.snapshot.return_value = {'complete': True, 'tree': {
                    **root, 'children': [{'role': 'text', 'name': 'synthetic test message'}]}}
                driver._ensure_bridge = lambda: bridge
                self.assertIsNone(driver.outgoing_messages())

    def test_missing_baseline_stops_before_draft_and_submit(self):
        adapter = MagicMock()
        adapter.find_exact_recipients.return_value = ['recipient']
        adapter.open_and_verify_recipient.return_value = True
        adapter.sent_message_baseline.side_effect = ValueError('no verified baseline')
        result = send_requested_once(SendIntent('Zalo', 'An', 'synthetic test message'),
                                     adapter, threading.Event().is_set)
        self.assertFalse(result.sent)
        adapter.set_and_verify_draft.assert_not_called()
        adapter.send_once.assert_not_called()


if __name__ == '__main__':
    unittest.main()
