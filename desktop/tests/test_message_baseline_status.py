import unittest
from unittest.mock import MagicMock
from pet.message_flow import send_requested_once
from pet.message_intent import SendIntent
from pet.messaging_driver import format_message_result


class MessageBaselineStatusTests(unittest.TestCase):
    def test_unverified_baseline_is_explained_before_draft_or_send(self):
        adapter=MagicMock()
        adapter.find_exact_recipients.return_value=['one']
        adapter.open_and_verify_recipient.return_value=True
        adapter.sent_message_baseline.side_effect=ValueError('no verified baseline')
        intent=SendIntent('Zalo','An','xin chào')
        result=send_requested_once(intent,adapter)
        self.assertEqual(result.status,'verification_unavailable')
        adapter.set_and_verify_draft.assert_not_called()
        adapter.send_once.assert_not_called()
        reply=format_message_result(intent,result)
        self.assertIn('chưa soạn hoặc gửi',reply)
        self.assertNotIn('đăng nhập',reply)
