from __future__ import annotations
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import numpy as np
from pet.stt import SpeechToText, recognition_config, DEFAULT_PROMPT, excessive_repetition
from pet.bionic import active_session
from pet.config import load_config
from pet.controller import Controller
from pet.apps import requested_app, launch_name, suggest_installed_app
from pet.diagnostics import trace


class VoiceDiagnosticsTests(unittest.TestCase):
    def recognizer(self, text: str, **extra):
        model = MagicMock()
        model.transcribe.return_value = (iter([MagicMock(text=text, no_speech_prob=.01, avg_logprob=-.2)]), None)
        config = dict(load_config()['stt'], **extra)
        with patch.object(SpeechToText, '_load', return_value=model):
            stt = SpeechToText(config, lambda _: None)
        return stt, model

    def test_temporary_and_saved_tabs_resolve_same_uuid_without_writing(self):
        project = 'd49037d8-47f4-5808-9028-c707de117f8f'
        session = '61fc81cf-49eb-46af-80aa-3836a237c6dc'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'window-1.json'
            for prefix in ('bionicSession', 'bionicTemporarySession'):
                path.write_text(json.dumps({'tabLayouts': {'bionic.sessions': {
                    'type': 'pane', 'active': 0,
                    'tabs': [f'{prefix}:v2:{project}:module:{session}']}}}))
                before = path.read_bytes()
                self.assertEqual(active_session(Path(tmp)), (project, session))
                self.assertEqual(path.read_bytes(), before)
            path.write_text(path.read_text().replace('bionicTemporarySession', 'unknownTab'))
            with self.assertRaises(RuntimeError):
                active_session(Path(tmp))

    def test_raw_text_precedes_prefix_repair_and_empty_prompt_uses_default(self):
        stt, model = self.recognizer('Bởi YouTube cho tôi.', initial_prompt='')
        text, _ = stt.transcribe(np.full(32000, .03, dtype=np.float32))
        self.assertEqual(text, 'Mở YouTube cho tôi.')
        self.assertEqual(stt.last_diagnostic.raw_text, 'Bởi YouTube cho tôi.')
        self.assertEqual(model.transcribe.call_args.kwargs['initial_prompt'], DEFAULT_PROMPT)

    def test_dynamic_hotwords_are_bounded_and_never_teach_wrong_aliases(self):
        config = {'stt': {'hotwords': 'Alex, KiCad'}, 'apps': {'entries': [
            {'name': 'KiCad', 'aliases': ['ghi card']}, {'name': 'FreeCAD'}]}}
        result = recognition_config(config)
        self.assertEqual(result['hotwords'], 'Alex, KiCad, FreeCAD')
        self.assertNotIn('FreeCAD', config['stt']['hotwords'])
        config['apps']['entries'] += [{'name': 'Software ' + str(i)} for i in range(100)]
        self.assertLessEqual(len(recognition_config(config)['hotwords']), 500)

    def test_fast_valid_speech_not_silently_dropped(self):
        raw = 'Mở thư mục học tập rồi cho tôi biết hôm nay chúng ta cần làm những gì.'
        stt, _ = self.recognizer(raw, max_chars_per_second=45)
        text, _ = stt.transcribe(np.full(25600, .03, dtype=np.float32))
        self.assertEqual(text, raw)

    def test_long_repetition_rejected_but_normal_emphasis_kept(self):
        self.assertFalse(excessive_repetition('Không không, tôi muốn mở ứng dụng khác.'))
        stt, _ = self.recognizer('xin chào bạn ' * 6)
        text, _ = stt.transcribe(np.full(160000, .03, dtype=np.float32))
        self.assertEqual(text, '')
        self.assertEqual(stt.last_diagnostic.reason, 'repetition')

    def test_rejection_caption_and_no_private_text_when_logging_disabled(self):
        engine = Controller(load_config())
        engine.cfg['privacy']['save_transcripts'] = False
        captions = []
        engine.state.connect(lambda mode, caption: captions.append(caption))
        stt, _ = self.recognizer('abc ' * 80, max_chars_per_second=45)
        with self.assertLogs(level='INFO') as logs:
            text, _ = engine._recognize(stt, np.full(32000, .03, dtype=np.float32))
        self.assertFalse(text)
        self.assertIn('Chưa nghe rõ, bạn nói lại nhé', captions)
        self.assertNotIn('abc abc', ' '.join(logs.output))

    def test_trace_escapes_newlines_and_includes_raw_only_if_enabled(self):
        with self.assertLogs(level='INFO') as logs:
            trace('raw_stt', 'test', True, 'một\nhai')
        data = json.loads(logs.output[0].split('VOICE_TRACE ', 1)[1])
        self.assertEqual(data['text'], 'một\nhai')

    def test_open_variants_require_explicit_command_and_known_target(self):
        apps = [{'name': 'KiCad'}]
        for value in ['Mơ KiCad', 'Mỡ KiCad', 'Vô KiCad', 'Bơ KiCad cho tôi']:
            self.assertEqual(requested_app(value, apps), apps[0])
        for value in ['Bơ đậu phộng cho tôi', 'Bơ KiCad rồi xóa file cho tôi',
                      'Không vô KiCad', 'Đừng mở KiCad', 'Bơ KiCad']:
            self.assertIsNone(requested_app(value, apps))
        self.assertIsNone(launch_name('Bơ KiCad cho tôi'))

    def test_fuzzy_match_reports_score_without_lowering_safety_threshold(self):
        metrics = {}
        result = suggest_installed_app('Mở Keycard cho tôi', [{'name': 'KiCad'}], [], (), [], metrics)
        self.assertIsNotNone(result)
        self.assertEqual(metrics['score'], 1.0)
        self.assertTrue(result.automatic)


if __name__ == '__main__':
    unittest.main()
