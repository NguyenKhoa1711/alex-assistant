import importlib.util
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

if os.getenv('ALEX_STT_FIX'):
    spec = importlib.util.spec_from_file_location('pet.stt_onset_test', os.environ['ALEX_STT_FIX'])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
else:
    from pet import stt as mod


class SpeechOnsetTests(unittest.TestCase):
    def test_soft_beginning_is_preserved_for_recognizer(self):
        samples = np.zeros(48000, dtype=np.float32)
        samples[4000:8000] = .001  # below silence_floor, before louder speech
        samples[16000:24000] = .03
        model = MagicMock()
        model.transcribe.return_value = (iter([
            MagicMock(text='Mở YouTube cho tôi.', no_speech_prob=.01, avg_logprob=-.2)]), None)
        cfg = {'device': 'cpu', 'compute_type': 'int8', 'beam_size': 3, 'silence_floor': .0015}
        with patch.object(mod.SpeechToText, '_load', return_value=model):
            recognizer = mod.SpeechToText(cfg, lambda _: None)
        self.assertEqual(recognizer.transcribe(samples)[0], 'Mở YouTube cho tôi.')
        captured = model.transcribe.call_args.args[0]
        np.testing.assert_array_equal(captured[:24000], samples[:24000])

    def test_boi_vi_is_not_rewritten_as_an_open_command(self):
        for text in ('Bởi vì YouTube bị lỗi, giúp tôi nhé.',
                     'Hãy bởi vì chuyện đó, cho tôi thêm thời gian.'):
            with self.subTest(text=text):
                self.assertEqual(mod.correct_command_prefix(text), text)
        self.assertEqual(mod.correct_command_prefix('Bởi YouTube cho tôi.'), 'Mở YouTube cho tôi.')


if __name__ == '__main__':
    unittest.main()
