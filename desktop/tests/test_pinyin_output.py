import unittest
import time
import numpy as np
from unittest.mock import MagicMock, patch
from pet.pinyin_output import filtered_chunks, pinyin_requested
from pet.controller import Controller
from pet.config import load_config
from pet.audio import Utterance
from pet.audio_jobs import AudioJob as MobileJob

class PinyinOutputTests(unittest.TestCase):

    def test_removes_pinyin_across_streamed_character_boundaries(self):
        text = '你好 (Nǐ hǎo)! 你今天怎么样？(Nǐ jīntiān zěnmeyàng?)'
        result = ''.join(filtered_chunks(iter(text), '你好'))
        self.assertEqual(result, '你好 ! 你今天怎么样？')

    def test_removes_leading_pinyin_before_hanzi(self):
        text = '(Nǐ hǎo!)\n\n你好，你好！'
        self.assertEqual(''.join(filtered_chunks(iter(text), '你好')), '你好，你好！')

    def test_keeps_non_pinyin_parentheses_and_technical_acronyms(self):
        text = '人工智能 (AI) 很有用。你好 (hello)! 2 + (3 × 4) = 14.'
        self.assertEqual(''.join(filtered_chunks(iter(text), '你好')), text)

    def test_keeps_pinyin_when_explicitly_requested(self):
        text = '你好 (Nǐ hǎo)!'
        self.assertTrue(pinyin_requested('Cho tôi phiên âm câu đó'))
        self.assertFalse(pinyin_requested('Không cần phiên âm'))
        self.assertEqual(''.join(filtered_chunks(iter(text), 'Cho phiên âm')), text)

    def test_preserves_unclosed_or_unrelated_parentheses(self):
        for text in ('Some text (hi)', 'Test (unfinished', '(nǐ hǎo) friend'):
            with self.subTest(text=text):
                self.assertEqual(''.join(filtered_chunks(iter(text), 'hi')), text)

    def test_controller_and_phone_speech_receive_filtered_reply(self):
        with patch('pet.llm.httpx.Client'):
            engine = Controller(load_config())
        self.addCleanup(engine.local_chat._client.close)
        self.addCleanup(engine.gemini_chat._client.close)
        engine.learning = None
        engine._desktop_speak = False
        engine.speaker = MagicMock()
        engine.speaker.render_pcm.return_value = (48000, b'\x00\x00' * 20)
        engine.gemini_chat.stream = MagicMock(return_value=iter('你好 (Nǐ hǎo)!'))
        job = MobileJob(np.zeros(100))
        utterance = Utterance(np.zeros(100), time.monotonic())
        reply = engine._answer('你好', utterance, 0, job)
        self.assertNotIn('Nǐ', reply)
        self.assertIn('你好', reply)
        self.assertNotIn('Nǐ', str(engine.speaker.render_pcm.call_args_list))
        self.assertEqual(engine.gemini_chat.history[-1], ('你好', reply))
if __name__ == '__main__':
    unittest.main()
