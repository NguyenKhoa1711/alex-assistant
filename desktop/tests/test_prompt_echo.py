import importlib.util
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

if os.environ.get('ALEX_STT_FIX'):
    spec = importlib.util.spec_from_file_location('pet.stt_echo_test', os.environ['ALEX_STT_FIX'])
    stt_module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = stt_module
    spec.loader.exec_module(stt_module)
else:
    from pet import stt as stt_module


class PromptEchoTests(unittest.TestCase):
    def recognizer(self, result):
        model = MagicMock()
        model.transcribe.return_value = (iter([
            MagicMock(text=result, no_speech_prob=0.01, avg_logprob=-0.2)]), None)
        config = {'device': 'cpu', 'compute_type': 'int8', 'beam_size': 3,
                  'initial_prompt': 'Tiếng Việt. Phóng to, thu nhỏ, khôi phục cửa sổ.'}
        with patch.object(stt_module.SpeechToText, '_load', return_value=model):
            recognizer = stt_module.SpeechToText(config, lambda _: None)
        return recognizer, model

    def test_repeated_prompt_echo_is_not_answered(self):
        recognizer, _ = self.recognizer('Điều khiển cửa sổ. Điều khiển cửa sổ.')
        text, _ = recognizer.transcribe(np.full(32000, .03, dtype=np.float32))
        self.assertEqual(text, '')
        self.assertEqual(recognizer.last_diagnostic.reason, 'repeated_prompt_echo')

    def test_one_phrase_and_real_commands_are_preserved(self):
        for phrase in ('Điều khiển cửa sổ', 'Phóng to cửa sổ hiện tại',
                       'Thu nhỏ cửa sổ cho tôi', 'Mở KiCad cho tôi',
                       'Điều khiển cửa sổ điều khiển cửa sổ giúp tôi'):
            with self.subTest(phrase=phrase):
                recognizer, _ = self.recognizer(phrase)
                self.assertEqual(recognizer.transcribe(np.full(32000, .03, dtype=np.float32))[0], phrase)

    def test_quiet_audio_does_not_reach_model(self):
        recognizer, model = self.recognizer('Điều khiển cửa sổ. Điều khiển cửa sổ.')
        self.assertEqual(recognizer.transcribe(np.zeros(32000, dtype=np.float32))[0], '')
        model.transcribe.assert_not_called()

    def test_hint_keeps_window_terms_without_ghost_heading(self):
        config = stt_module.recognition_config({'stt': {'initial_prompt': 'Tiếng Việt.'}})
        self.assertNotIn('Điều khiển cửa sổ', config['initial_prompt'])
        self.assertIn('phóng to, thu nhỏ', config['initial_prompt'])
        self.assertEqual(stt_module.recognition_config({'stt': config})['initial_prompt'], config['initial_prompt'])


if __name__ == '__main__':
    unittest.main()
