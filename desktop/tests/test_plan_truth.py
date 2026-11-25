import json
import threading
import unittest
from unittest.mock import patch

from pet.gemma import GemmaChat


class FakeComputer:
    cfg = {}
    def tools(self, _): return []
    def call(self, name, arguments, event):
        return json.dumps({'is_error': False, 'result': 'ok'})


class PlanTruthTests(unittest.TestCase):
    def setUp(self):
        self.chat = GemmaChat.__new__(GemmaChat)
        self.chat.computer = FakeComputer()
        self.chat.computer_for_turn = True
        self.chat.computer_enabled = True
        self.chat.history = []
        self.cancelled = threading.Event()

    def reply(self, response, names=()):
        def parent(chat, question, cancelled):
            for name in names:
                chat.computer.call(name, {}, cancelled)
            yield response
        with patch('pet.gemini.GeminiChat.stream', parent):
            return ''.join(self.chat.stream('Gửi tin nhắn', self.cancelled))

    def test_textual_plan_without_tool_actions_is_not_reported_as_execution(self):
        response = 'Plan:\nGoal: Gửi tin\nSteps:\n1. Mở Messenger\nTao sẽ thực hiện nhé.'
        self.assertIn('chưa thực hiện', self.reply(response))
        self.assertIn('chưa thực hiện', self.reply(response, ('Plan', 'Snapshot')))

    def test_real_action_or_clarifying_question_are_not_discarded(self):
        self.assertEqual('Tao đã nhập.', self.reply('Tao đã nhập.', ('Type',)))
        prompt = 'Mày muốn gửi nội dung gì và cho ai?'
        self.assertEqual(prompt, self.reply(prompt))

    def test_non_computer_chat_is_unchanged(self):
        self.chat.computer_for_turn = False
        self.assertEqual('Plan: một khái niệm trong tiếng Anh.', self.reply('Plan: một khái niệm trong tiếng Anh.'))

if __name__ == '__main__': unittest.main()
