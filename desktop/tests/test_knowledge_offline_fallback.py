import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
from pet.audio import Utterance
from pet.config import load_config
from pet.controller import Controller
from pet.web_research import requires_fresh_results


class OfflineKnowledgeTests(unittest.TestCase):
    def make_engine(self):
        with patch('pet.llm.httpx.Client'):
            engine = Controller(load_config())
        engine.learning = None
        engine._desktop_speak = False
        engine.speaker = MagicMock()
        engine.app_actions.execute = MagicMock(side_effect=AssertionError('action'))
        self.addCleanup(engine.gemini_chat._client.close)
        self.addCleanup(engine.local_chat._client.close)
        return engine

    def test_offline_general_question_uses_model_not_fake_web_results(self):
        engine = self.make_engine()
        engine.gemini_chat.stream = MagicMock(return_value=iter(['Hà Nội.']))
        with patch('pet.controller.search_web', return_value=[]):
            result = engine._answer('Thủ đô Việt Nam là gì?', Utterance(np.zeros(10), time.monotonic()), 0)
        self.assertEqual(result, 'Hà Nội.')
        prompt = engine.gemini_chat.stream.call_args.args[0]
        self.assertIn('Không lấy được kết quả tra cứu mạng', prompt)
        self.assertIn('không nói hoặc ngụ ý đã tra cứu', prompt)
        engine.app_actions.execute.assert_not_called()

    def test_current_data_is_not_guessed_offline(self):
        engine = self.make_engine()
        engine.gemini_chat.stream = MagicMock()
        engine._speak_action_result = MagicMock()
        with patch('pet.controller.search_web', return_value=[]):
            result = engine._answer('Giá vàng hôm nay bao nhiêu?', Utterance(np.zeros(10), time.monotonic()), 0)
        self.assertIn('chưa lấy được kết quả', result)
        engine.gemini_chat.stream.assert_not_called()
        self.assertTrue(requires_fresh_results('Thời tiết hiện tại thế nào?'))
        self.assertFalse(requires_fresh_results('Thủ đô Việt Nam là gì?'))

    def test_cancelled_search_does_not_answer(self):
        engine = self.make_engine()
        engine.gemini_chat.stream = MagicMock()
        engine.cancelled.set()
        with patch('pet.controller.search_web', return_value=[]):
            result = engine._research_turn('Thủ đô Việt Nam là gì?', Utterance(np.zeros(10), time.monotonic()), 0, None)
        self.assertEqual(result, '')
        engine.gemini_chat.stream.assert_not_called()
