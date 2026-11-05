import unittest
from pet.audio import FRAME_MS, Segmenter


class SpeechPauseTests(unittest.TestCase):
    def test_short_pause_does_not_split_a_sentence(self):
        config = {'sample_rate': 16000, 'vad_aggressiveness': 2, 'min_rms': .0025,
                  'silence_ms': 1500, 'min_speech_ms': 240, 'max_utterance_seconds': 20}
        segmenter = Segmenter(config)
        frame = bytes(16000 * FRAME_MS // 1000 * 2)
        turns = []
        for index, voiced in enumerate([True] * 12 + [False] * 38 + [True] * 12 + [False] * 52):
            result = segmenter.feed(frame, index * FRAME_MS / 1000, voiced=voiced)
            if result is not None:
                turns.append(result)
        self.assertEqual(len(turns), 1)
        self.assertGreater(len(turns[0].samples) / 16000, 3.0)


if __name__ == '__main__':
    unittest.main()
