import unittest
from pet.message_intent import merge_message_followup


class FollowupDiacriticsTests(unittest.TestCase):
    def test_dung_confirmation_is_not_confused_with_stop(self):
        pending={'service':'Zalo','recipient':'An','content':'Chào bạn'}
        self.assertEqual(merge_message_followup(pending,'đúng')[0], 'execute')
        self.assertEqual(merge_message_followup(pending,'ĐÚNG!')[0], 'execute')
        self.assertEqual(merge_message_followup(pending,'đúng rồi')[0], 'execute')
        self.assertEqual(merge_message_followup(pending,'dừng')[0], 'cancel')
        self.assertEqual(merge_message_followup(pending,'dừng rồi')[0], 'cancel')
        self.assertEqual(merge_message_followup(pending,'đừng')[0], 'cancel')
        self.assertEqual(merge_message_followup(pending,'dung')[0], 'ask')
        self.assertEqual(merge_message_followup(pending,'dung roi')[0], 'ask')

    def test_confirmation_does_not_fill_missing_fields(self):
        pending={'service':'Zalo'}
        status, merged=merge_message_followup(pending,'đúng')
        self.assertEqual(status,'ask')
        self.assertEqual(merged,pending)
