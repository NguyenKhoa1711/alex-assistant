from __future__ import annotations
import threading
import unittest
from unittest.mock import patch, MagicMock
import numpy as np
from pet.audio import Segmenter, Microphone
from pet.config import load_config
from pet.wake import extract_wake, speech_text, SentenceBuffer
from pet.stt import SpeechToText, correct_command_prefix


class CoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = load_config()

    def test_wake_and_question(self) -> None:
        aliases = self.cfg['wake']['aliases']
        for text in ['A lếch, hai cộng ba bằng mấy?', 'Alex ơi, hai cộng ba bằng mấy?',
                     'Này A lệch, hai cộng ba bằng mấy?']:
            self.assertEqual(extract_wake(text, aliases), (True, 'hai cộng ba bằng mấy?'))
        for text in ['Hai cộng ba bằng mấy?', 'Alexa hãy nói', 'Tôi đang xem phim về Alex']:
            self.assertFalse(extract_wake(text, aliases)[0])
        self.assertEqual(extract_wake('A lếch ơi!', aliases), (True, ''))

    def test_spoken_name(self) -> None:
        self.assertEqual(speech_text('Mình là **Alex**!', 'Alex', 'A lếch'), 'Mình là A lếch!')

    def test_stream_buffer(self) -> None:
        buf = SentenceBuffer()
        self.assertEqual(buf.add('Mình là '), [])
        self.assertEqual(buf.add('Alex. Chào'), ['Mình là Alex.'])
        self.assertEqual(buf.add(' bạn', final=True), ['Chào bạn'])

    def test_vad_silence_and_end(self) -> None:
        seg = Segmenter(self.cfg['audio'])
        frame = np.zeros(480, np.int16).tobytes()
        for i in range(100):
            self.assertIsNone(seg.feed(frame, i * .03, voiced=False))
        for i in range(12):
            self.assertIsNone(seg.feed(frame, 3 + i * .03, voiced=True))
        result = None
        for i in range(self.cfg['audio']['silence_ms'] // 30 + 2):
            result = seg.feed(frame, 4 + i * .03, voiced=False) or result
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result.ended_at, 3.33)
        self.assertFalse(seg.frames)

    def test_microphone_gate_flushes_echo(self) -> None:
        mic = Microphone(self.cfg['audio'])
        mic.gate(True)
        mic._callback(b'abc', 1, None, None)
        self.assertFalse(mic.frames.empty())
        mic.gate(False)
        mic._callback(b'echo', 1, None, None)
        self.assertTrue(mic.frames.empty())
        mic.gate(True)
        self.assertTrue(mic.frames.empty())

    def test_cuda_fallback_on_load(self) -> None:
        cfg = dict(self.cfg['stt'], device='cuda', compute_type='float16')
        notices = []
        with patch.object(SpeechToText, '_load', side_effect=[RuntimeError('CUDA unavailable'), MagicMock()]) as loader:
            stt = SpeechToText(cfg, notices.append)
        self.assertEqual(stt.device, 'cpu')
        self.assertEqual(loader.call_args.args, ('cpu', 'int8'))
        self.assertIn('CPU int8', notices[0])

    def test_cuda_decode_failure_retries_on_cpu(self) -> None:
        cfg = dict(self.cfg['stt'], device='cuda')
        cuda = MagicMock()
        def fail_during_iteration():
            raise RuntimeError('CUDA library error')
            yield
        cuda.transcribe.return_value = (fail_during_iteration(), None)
        cpu = MagicMock()
        segment = MagicMock(text='Xin chào', no_speech_prob=.01, avg_logprob=-.2)
        cpu.transcribe.return_value = (iter([segment]), None)
        notices = []
        with patch.object(SpeechToText, '_load', side_effect=[cuda, cpu]):
            recognizer = SpeechToText(cfg, notices.append)
            text, _ = recognizer.transcribe(np.full(16000, .02, dtype=np.float32))
        self.assertEqual(text, 'Xin chào')
        self.assertEqual(recognizer.device, 'cpu')
        self.assertIn('CPU int8', notices[0])
        cuda.model.unload_model.assert_called_once()
        self.assertEqual(cpu.transcribe.call_args.kwargs['temperature'], 0.0)
        self.assertEqual(cpu.transcribe.call_args.kwargs['language'], 'vi')

    def test_silent_audio_is_not_sent_to_whisper(self) -> None:
        model = MagicMock()
        with patch.object(SpeechToText, '_load', return_value=model):
            recognizer = SpeechToText(self.cfg['stt'], lambda _: None)
        text, _ = recognizer.transcribe(np.zeros(16000, dtype=np.float32))
        self.assertEqual(text, '')
        model.transcribe.assert_not_called()

    def test_punctuation_only_transcript_is_ignored(self) -> None:
        model = MagicMock()
        model.transcribe.return_value = (iter([
            MagicMock(text='.', no_speech_prob=.01, avg_logprob=-.2)]), None)
        with patch.object(SpeechToText, '_load', return_value=model):
            recognizer = SpeechToText(self.cfg['stt'], lambda _: None)
        text, _ = recognizer.transcribe(np.full(16000, .02, dtype=np.float32))
        self.assertEqual(text, '')

    def test_configured_density_guard_rejects_excess_text(self) -> None:
        model = MagicMock()
        segment = MagicMock(text='Hãy subscribe cho kênh Ghiền Mì Gõ Để không bỏ lỡ những video hấp dẫn.',
                            no_speech_prob=.01, avg_logprob=-.2)
        model.transcribe.return_value = (iter([segment]), None)
        with patch.object(SpeechToText, '_load', return_value=model):
            recognizer = SpeechToText(dict(self.cfg['stt'], max_chars_per_second=30), lambda _: None)
        text, _ = recognizer.transcribe(np.full(24000, .02, dtype=np.float32))
        self.assertEqual(text, '')

    def test_misheard_open_command_is_repaired_only_in_command_context(self) -> None:
        self.assertEqual(correct_command_prefix('Bởi YouTube ở trong Google cho tôi.'),
                         'Mở YouTube ở trong Google cho tôi.')
        self.assertEqual(correct_command_prefix('Bởi vì YouTube có video hay.'),
                         'Bởi vì YouTube có video hay.')

    def test_short_pause_keeps_one_utterance(self) -> None:
        seg = Segmenter(self.cfg['audio'])
        frame = np.zeros(480, np.int16).tobytes()
        flags = [True] * 15 + [False] * 20 + [True] * 15
        for index, voiced in enumerate(flags):
            self.assertIsNone(seg.feed(frame, index * .03, voiced=voiced))
        result = None
        for index in range(self.cfg['audio']['silence_ms'] // 30 + 2):
            result = seg.feed(frame, (len(flags) + index) * .03, voiced=False) or result
        self.assertIsNotNone(result)
        self.assertGreater(len(result.samples), 480 * len(flags))


if __name__ == '__main__':
    unittest.main()
