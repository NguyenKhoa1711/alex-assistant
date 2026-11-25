import unittest
from unittest.mock import MagicMock

from pet.message_flow import send_requested_once
from pet.message_intent import SendIntent


class MessagePrivacyTests(unittest.TestCase):
    def test_exceptions_do_not_log_message_text(self):
        adapter = MagicMock()
        adapter.find_exact_recipients.side_effect = RuntimeError('PRIVATE_CONTACT PRIVATE_DRAFT')
        with self.assertLogs(level='WARNING') as logs:
            result = send_requested_once(SendIntent('Zalo', 'PRIVATE_CONTACT', 'PRIVATE_DRAFT'), adapter)
        self.assertEqual(result.status, 'not_sent')
        self.assertIn('RuntimeError', logs.output[0])
        self.assertNotIn('PRIVATE_CONTACT', logs.output[0])
        self.assertNotIn('PRIVATE_DRAFT', logs.output[0])
        adapter.send_once.assert_not_called()

    def test_uncertain_submit_does_not_retry_or_log_exception_content(self):
        adapter = MagicMock()
        adapter.find_exact_recipients.return_value = ['id']
        adapter.open_and_verify_recipient.return_value = True
        adapter.sent_message_baseline.return_value = frozenset()
        adapter.set_and_verify_draft.return_value = True
        adapter.still_matches.return_value = True
        adapter.send_once.side_effect = RuntimeError('PRIVATE_DRAFT')
        with self.assertLogs(level='WARNING') as logs:
            result = send_requested_once(SendIntent('Zalo', 'An', 'PRIVATE_DRAFT'), adapter)
        self.assertEqual(result.status, 'send_unverified')
        adapter.send_once.assert_called_once()
        self.assertNotIn('PRIVATE_DRAFT', logs.output[0])
