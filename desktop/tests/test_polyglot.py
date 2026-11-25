import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pet.polyglot_tts import HybridSpeaker, _model_dir, prepare_text, split_text


class PolyglotTests(unittest.TestCase):
    def setUp(self):
        self.stop=threading.Event()
        self.vi=MagicMock()
        self.vi.engine_label='Thái Sơn'
        self.vi.render_pcm.return_value=(48000,bytes(9600))
        local_models=Path(__file__).resolve().parent
        if not (local_models/'en_US-joe-medium.onnx').is_file():
            local_models=_model_dir()
        self.speaker=HybridSpeaker(self.vi,None,local_models)

    def parts(self, text):
        return split_text(prepare_text(text,'Alex','A lếch'))

    def test_vietnamese_does_not_switch_voices(self):
        self.assertEqual(self.parts('Chào bạn, mình là Alex.'),[('vi','Chào bạn, mình là A lếch.')])
        self.assertEqual(self.parts('Mình đã mở ứng dụng Spotify rồi nhé.'),
                         [('vi','Mình đã mở ứng dụng Spotify rồi nhé.')])

    def test_chinese_hanzi_preferred_and_pinyin_not_repeated(self):
        parts=self.parts('Xin chào là 你好 (Nǐ hǎo), cảm ơn là 谢谢 (Xièxie).')
        self.assertEqual([text for lang,text in parts if lang=='zh'],['你好','谢谢.'])
        self.assertNotIn('hảo',str(parts))

    def test_english_in_vietnamese_and_single_word(self):
        parts=self.parts('Từ "go" nghĩa là đi, hello bạn nhé.')
        self.assertEqual([text for lang,text in parts if lang=='en'],['go','hello'])
        self.assertEqual(self.parts('Hello!'),[('en','Hello!')])

    def test_english_turn_uses_one_voice_for_whole_english_sentence(self):
        text='I like music because it makes me happy.'
        prepared=prepare_text(text,'Alex','A lếch',preferred_language='en')
        self.assertEqual(split_text(prepared),[('en',text)])
        mixed=prepare_text('Mở Spotify cho tôi.','Alex','A lếch',preferred_language='en')
        self.assertEqual(split_text(mixed),[('vi','Mở Spotify cho tôi.')])

    def test_playback_calls_are_serialized_and_cancel_while_waiting(self):
        started=threading.Event();release=threading.Event();second_started=threading.Event()
        first_cancel=threading.Event();second_cancel=threading.Event()
        def play(text,cancelled,on_play):
            if text=='first':
                started.set();release.wait(3)
            else:
                second_started.set()
        with patch.object(self.speaker,'_speak_unlocked',side_effect=play):
            first=threading.Thread(target=self.speaker.speak,args=('first',first_cancel,lambda _:None))
            second=threading.Thread(target=self.speaker.speak,args=('second',second_cancel,lambda _:None))
            first.start();self.assertTrue(started.wait(2));second.start()
            self.assertFalse(second_started.wait(.15))
            second_cancel.set();second.join(2)
            self.assertFalse(second.is_alive())
            self.assertFalse(second_started.is_set())
            release.set();first.join(2);self.assertFalse(first.is_alive())

    def test_sequence_and_single_playback_share_same_slot(self):
        started=threading.Event();release=threading.Event();single_started=threading.Event()
        def sequence(*_):started.set();release.wait(3)
        def single(*_):single_started.set()
        with patch.object(self.speaker,'_speak_sequence_unlocked',side_effect=sequence), \
             patch.object(self.speaker,'_speak_unlocked',side_effect=single):
            first=threading.Thread(target=self.speaker.speak_sequence,args=([],self.stop,lambda _:None))
            second=threading.Thread(target=self.speaker.speak,args=('hello',self.stop,lambda _:None))
            first.start();self.assertTrue(started.wait(2));second.start()
            self.assertFalse(single_started.wait(.15))
            release.set();first.join(2);second.join(2)
            self.assertFalse(first.is_alive());self.assertFalse(second.is_alive())
            self.assertTrue(single_started.is_set())

    def test_pinyin_before_hanzi_is_not_repeated(self):
        parts=self.parts('Tiếng Trung là Nǐ hǎo (你好).')
        self.assertEqual(parts,[('vi','Tiếng Trung là'),('zh','你好.')])

    def test_pinyin_on_its_own_is_spoken_by_mandarin_voice(self):
        self.assertEqual(self.parts('Tiếng Trung: Nǐ hǎo!'),
                         [('vi','Tiếng Trung:'),('zh','ni3 hao3!')])

    def test_no_punctuation_only_voice_segments(self):
        parts=self.parts('Tiếng Anh là Hello, how are you?')
        self.assertEqual([text for lang,text in parts if lang=='en'],['Hello, how are you?'])
        self.assertFalse(any(not any(c.isalnum() for c in t) for _,t in parts))

    def test_actual_english_and_mandarin_synthesis_at_phone_rate(self):
        for text in ('Hello, how are you?', '你好，我很高兴。'):
            with self.subTest(text=text):
                output=self.speaker.render_pcm(prepare_text(text,'Alex','A lếch'),self.stop)
                self.assertIsNotNone(output)
                self.assertEqual(output[0],48000)
                self.assertGreater(len(output[1]),24000)
                self.assertTrue(any(output[1]))

    def test_mixed_audio_and_cancellation(self):
        output=self.speaker.render_pcm(prepare_text('Xin chào, 你好 (Nǐ hǎo).','Alex','A lếch'),self.stop)
        self.assertEqual(output[0],48000)
        self.assertGreater(len(output[1]),9600)
        self.stop.set()
        self.assertIsNone(self.speaker.render_pcm(prepare_text('你好','Alex','A lếch'),self.stop))

    def test_model_failure_falls_back_to_existing_voice(self):
        self.speaker.model_dir=Path('does-not-exist')
        output=self.speaker.render_pcm(prepare_text('你好','Alex','A lếch'),self.stop)
        self.assertEqual(output,(48000,bytes(9600)))
        self.vi.render_pcm.assert_called_once()

    def test_controller_uses_native_preprocessing(self):
        from pet.config import load_config
        from pet.controller import Controller
        from unittest.mock import patch
        with patch('pet.llm.httpx.Client'):
            engine = Controller(load_config())
        self.addCleanup(engine.gemini_chat._client.close)
        self.addCleanup(engine.local_chat._client.close)
        engine.speaker = self.speaker
        self.assertEqual(split_text(engine._speech_for_audio('你好 (Nǐ hǎo)')),[('zh','你好')])

    def test_sequence_keeps_existing_fast_vietnamese_stream_and_order(self):
        played=[]
        def vietnamese_group(texts, cancelled, callback):
            for text in texts:
                played.append(('vi',text))
            callback(0.1)
        self.vi.speak_sequence.side_effect=vietnamese_group
        def foreign(text, cancelled, callback):
            played.append(('foreign',text))
            callback(0.1)
        self.speaker.speak=foreign
        tagged=prepare_text('你好','Alex','A lếch')
        callbacks=[]
        self.speaker.speak_sequence(iter(['một',tagged,'hai']),self.stop,callbacks.append)
        self.assertEqual(played,[('vi','một'),('foreign',tagged),('vi','hai')])
        self.assertEqual(len(callbacks),1)


if __name__=='__main__':unittest.main()
