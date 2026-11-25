import threading
import unittest
from unittest.mock import patch

from pet.gemma import GemmaChat, _deduplicate_continuation
from pet.gemini import GeminiChat


def chat_stub():
    chat = object.__new__(GemmaChat)
    chat.computer = None
    chat.computer_for_turn = False
    chat.computer_enabled = True
    chat.history = [('trước đó', 'đã nhớ')]
    chat.first_token_seconds = 0.1
    chat.response_seconds = 1.0
    return chat


def parent_stream(reasons, outputs, calls):
    def fake(self, question, cancelled):
        i = len(calls)
        calls.append(question)
        self.last_finish_reason = reasons[i]
        self.first_token_seconds = 0.1 + i
        self.response_seconds = 1.0 + i
        yield outputs[i]
        if not cancelled.is_set():
            self.history.append((question, outputs[i]))
    return fake


class GemmaContinuationTests(unittest.TestCase):
    def test_overlap_is_removed_without_changing_distinct_content(self):
        self.assertEqual(_deduplicate_continuation('Một chú mèo tên là Miu', 'Miu đi học.'), ' đi học.')
        self.assertEqual(_deduplicate_continuation('Mèo đi học. ', 'Hôm sau...'), 'Hôm sau...')
        self.assertEqual(_deduplicate_continuation('Đây là đoạn đầu của câu chuyện.', 'Đây là đoạn đầu'), '')

    def test_stream_removes_overlap_before_emitting_and_storing(self):
        chat, calls = chat_stub(), []
        with patch.object(GeminiChat, 'stream', parent_stream(['length', 'stop'], ['Tên là Miu', 'Miu đi học.'], calls)):
            answer = ''.join(chat.stream('Kể chuyện', threading.Event()))
        self.assertEqual(answer, 'Tên là Miu đi học.')
        self.assertEqual(chat.history[-1], ('Kể chuyện', answer))

    def test_whole_repeated_continuation_is_not_replayed(self):
        chat, calls = chat_stub(), []
        initial = 'Đây là đoạn đầu của câu chuyện.'
        with patch.object(GeminiChat, 'stream', parent_stream(['length', 'stop'], [initial, initial], calls)):
            answer = ''.join(chat.stream('Kể chuyện', threading.Event()))
        self.assertEqual(answer.count(initial), 1)
        self.assertIn('còn phần chưa nói hết', answer)

    def test_length_continues_once_and_keeps_one_session_turn(self):
        chat, calls = chat_stub(), []
        with patch.object(GeminiChat, 'stream', parent_stream(['length', 'stop'], ['Một phần ', 'và kết thúc.'], calls)):
            answer = ''.join(chat.stream('Giải thích giúp tao', threading.Event()))
        self.assertEqual(answer, 'Một phần và kết thúc.')
        self.assertEqual(len(calls), 2)
        self.assertIn('Một phần', calls[1])
        self.assertEqual(chat.history, [('trước đó', 'đã nhớ'), ('Giải thích giúp tao', answer)])
        self.assertEqual(chat.first_token_seconds, 0.1)

    def test_finished_answer_does_not_continue(self):
        chat, calls = chat_stub(), []
        with patch.object(GeminiChat, 'stream', parent_stream(['stop'], ['Xong.'], calls)):
            self.assertEqual(''.join(chat.stream('Chào', threading.Event())), 'Xong.')
        self.assertEqual(len(calls), 1)

    def test_second_length_stops_and_reports_limit(self):
        chat, calls = chat_stub(), []
        with patch.object(GeminiChat, 'stream', parent_stream(['length', 'length'], ['Đầu ', 'thêm'], calls)):
            answer = ''.join(chat.stream('Dài', threading.Event()))
        self.assertEqual(len(calls), 2)
        self.assertIn('còn phần chưa nói hết', answer)

    def test_cancelled_turn_never_continues(self):
        chat, calls, cancelled = chat_stub(), [], threading.Event()
        def fake(self, question, event):
            calls.append(question)
            self.last_finish_reason = 'length'
            event.set()
            yield 'Đã dừng'
        with patch.object(GeminiChat, 'stream', fake):
            self.assertEqual(''.join(chat.stream('Dài', cancelled)), 'Đã dừng')
        self.assertEqual(len(calls), 1)

    def test_computer_turn_never_replays(self):
        chat, calls = chat_stub(), []
        chat.computer = type('Computer', (), {'cfg': {}})()
        chat.computer_for_turn = True
        with patch.object(GeminiChat, 'stream', parent_stream(['length'], ['Đã thử.'], calls)):
            self.assertEqual(''.join(chat.stream('Mở app', threading.Event())), 'Đã thử.')
        self.assertEqual(len(calls), 1)
