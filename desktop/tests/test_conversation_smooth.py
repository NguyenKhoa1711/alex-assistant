import copy
import json
import threading
import time
import unittest
from unittest.mock import MagicMock, patch
import numpy as np

from pet.audio import Utterance
from pet.config import load_config
from pet.controller import Controller, _computer_request
from pet.wake import SentenceBuffer
from pet.web_research import SearchResult


class ConversationRoutingTests(unittest.TestCase):
    def test_pronouns_are_not_accent_folded_to_computer_commands(self):
        for question in ('Tao có một con mèo tên là Bắp.', 'Tao đang vui.', 'Đúng rồi.',
                         'Tao thích ăn cá.'):
            with self.subTest(question=question):
                self.assertFalse(_computer_request(question))
        for question in ('Tạo bảng giúp tao', 'Dừng việc đang làm', 'Mở Zalo',
                         'Tạo chương trình tính toán'):
            with self.subTest(question=question):
                self.assertTrue(_computer_request(question))

    def test_real_chat_payload_keeps_previous_turns_without_tool_instructions(self):
        with patch('pet.llm.httpx.Client'):
            engine = Controller(load_config())
        engine.learning = None
        engine._desktop_speak = False
        engine.computer_enabled = True
        engine.gemini_chat.check_ready = MagicMock()
        payloads = []
        responses = iter(('Tao nhớ rồi, mèo tên Bắp.', 'Tên nó là Bắp.', 'Nó thích ăn cá.'))

        class Response:
            status_code = 200
            def __init__(self, text): self.text = text
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def iter_lines(self):
                yield 'data: ' + json.dumps({'choices': [{'delta': {'content': self.text}}]}, ensure_ascii=False)
                yield 'data: ' + json.dumps({'choices': [{'delta': {}, 'finish_reason': 'stop'}]})
                yield 'data: [DONE]'

        def fake_stream(_self, client, payload, cancelled, **kwargs):
            payloads.append(copy.deepcopy(payload))
            return Response(next(responses))

        try:
            with patch('pet.gemini.GeminiChat._retry_stream', autospec=True, side_effect=fake_stream), \
                    patch('pet.controller.search_web', side_effect=AssertionError('unexpected network')):
                for question in ('Trong chuyện này, con mèo của tao tên là Bắp và thích ăn cá.',
                                 'Con mèo đó tên gì?', 'Thế nó thích ăn gì?'):
                    engine._answer(question, Utterance(np.zeros(10), time.monotonic()), 0)
            self.assertEqual(len(engine.gemini_chat.history), 3)
            for payload in payloads:
                self.assertNotIn('tools', payload)
                self.assertNotIn('Dùng công cụ Alex được cấp', payload['messages'][-1]['content'])
            self.assertTrue(any('mèo của tao tên là Bắp' in m.get('content', '')
                                for m in payloads[1]['messages']))
            self.assertTrue(any('Con mèo đó tên gì?' in m.get('content', '')
                                for m in payloads[2]['messages']))
        finally:
            engine.gemini_chat._client.close()
            engine.local_chat._client.close()


class SpeechChunkTests(unittest.TestCase):
    def test_first_clause_can_be_ready_before_eighty_characters(self):
        buffer = SentenceBuffer()
        text = 'Tao sẽ giải thích điều này cho mày, rồi lấy một ví dụ thật dễ hiểu nhé'
        self.assertLess(len(text), 80)
        first = buffer.add(text)
        self.assertEqual(first, ['Tao sẽ giải thích điều này cho mày,'])
        self.assertTrue(buffer.pending.strip())

    def test_long_unpunctuated_text_is_cut_at_word_boundary_without_loss(self):
        buffer = SentenceBuffer()
        text = ' '.join(['hành tinh'] * 30)
        chunks = buffer.add(text) + buffer.add('', final=True)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertEqual(' '.join(chunks), text)
        self.assertTrue(all(not x.endswith('hành') for x in chunks))

    def test_long_single_stream_chunk_does_not_wait_for_a_distant_full_stop(self):
        buffer = SentenceBuffer()
        text = ' '.join(['hành tinh'] * 30) + '.'
        chunks = buffer.add(text) + buffer.add('', final=True)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertLessEqual(len(chunks[0]), 180)
        self.assertEqual(' '.join(chunks), text)

    def test_research_uses_continuous_playback_without_losing_sentences(self):
        with patch('pet.llm.httpx.Client'):
            engine = Controller(load_config())
        engine.learning = None
        engine._desktop_speak = True
        engine.gemini_chat.stream = MagicMock(return_value=iter([
            'Câu trả lời đầu tiên đã đủ dài. ',
            'Đây là câu thứ hai để kiểm tra cách phát liên tục cho bạn.']))
        speaker = MagicMock()
        spoken = []
        def sequence(texts, cancelled, on_play):
            for text in texts:
                spoken.append(text)
            on_play(0)
        speaker.speak_sequence.side_effect = sequence
        engine.speaker = speaker
        found = [SearchResult('Tiêu đề', 'Một nội dung.', 'https://example.org/')]
        try:
            with patch('pet.controller.search_web', return_value=found):
                answer = engine._research_turn('Thủ đô Việt Nam là gì?',
                                                Utterance(np.zeros(10), time.monotonic()), 0, None)
            self.assertIn('Câu trả lời đầu tiên', answer)
            self.assertGreaterEqual(len(spoken), 2)
            speaker.speak_sequence.assert_called_once()
            speaker.speak.assert_not_called()
        finally:
            engine.gemini_chat._client.close()
            engine.local_chat._client.close()
