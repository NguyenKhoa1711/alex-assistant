import threading
import time
import unittest
from unittest.mock import MagicMock, patch
import numpy as np
from pet.stt import SpeechToText, response_language_for_text
from pet.gemma import GemmaChat, _compact_chat_payload
from pet.gemini import GeminiChat
from pet.audio import Utterance
from pet.config import load_config
from pet.controller import Controller

class MultilingualSttTests(unittest.TestCase):
    def recognize(self, detected, probability, transcript):
        cfg={'device':'cpu','compute_type':'int8','beam_size':3,'language_mode':'auto',
             'initial_prompt':'Tiếng Việt. Mở ứng dụng.', 'hotwords':'Zalo, YouTube'}
        model=MagicMock()
        model.detect_language.return_value=(detected,probability,[])
        model.transcribe.return_value=(iter([MagicMock(text=transcript,no_speech_prob=.01,avg_logprob=-.2)]),None)
        with patch.object(SpeechToText,'_load',return_value=model):
            stt=SpeechToText(cfg,lambda _:None)
        text,_=stt.transcribe(np.full(24000,.02,dtype=np.float32))
        return text,stt.last_diagnostic,model.transcribe.call_args.kwargs

    def test_language_selection_preserves_original_language_and_vietnamese_hints(self):
        for lang, phrase in [('en','Hello, how are you?'),('zh','你好，你怎么样？'),
                             ('vi','Mở YouTube cho tôi.')]:
            with self.subTest(lang=lang):
                text,diag,params=self.recognize(lang,.95,phrase)
                self.assertEqual(text,phrase)
                self.assertEqual(diag.language,lang)
                self.assertEqual(params['language'],lang)
                self.assertEqual(params['task'],'transcribe')
                self.assertEqual(bool(params['initial_prompt']),lang=='vi')
                self.assertEqual(bool(params['hotwords']),lang=='vi')

    def test_low_confidence_and_unsupported_language_fall_back_to_vietnamese(self):
        for lang,prob in [('en',.15),('fr',.99)]:
            _,diag,params=self.recognize(lang,prob,'Mở YouTube cho tôi.')
            self.assertEqual(diag.language,'vi')
            self.assertEqual(params['language'],'vi')

    def test_english_best_with_moderate_confidence_is_not_forced_to_vietnamese(self):
        text,diag,params=self.recognize('en',.38,'It is a beautiful day.')
        self.assertEqual(params['language'],'en')
        self.assertEqual(diag.response_language,'en')
        self.assertEqual(text,'It is a beautiful day.')

    def test_low_confidence_decoder_fallback_does_not_force_vietnamese_reply(self):
        text,diag,params=self.recognize('nn',.35,'Hello Alex, how are you today?')
        self.assertEqual(params['language'],'vi')
        self.assertEqual(diag.detected_language,'nn')
        self.assertEqual(diag.response_language,'en')
        self.assertEqual(text,'Hello Alex, how are you today?')

    def test_english_text_overrides_a_wrong_vietnamese_language_detection(self):
        _,diag,_=self.recognize('vi',.88,'Hello Alex, how are you today?')
        self.assertEqual(diag.response_language,'en')

    def test_text_language_checks_do_not_rewrite_content(self):
        for text,language in [('Hello Alex, how are you today?','en'),
                              ('你好，你今天怎么样？','zh'),
                              ('Mở YouTube cho tôi.','vi'),
                              ('hello','en'),('Spotify','')]:
            with self.subTest(text=text):self.assertEqual(response_language_for_text(text),language)

    def test_unknown_language_with_ambiguous_text_does_not_force_vietnamese(self):
        _,diag,_=self.recognize('nn',.35,'Alex Spotify')
        self.assertEqual(diag.language,'vi')
        self.assertEqual(diag.response_language,'')

    def test_foreign_text_is_not_changed_by_vietnamese_command_correction(self):
        text,_,_=self.recognize('en',.9,'Look web.')
        self.assertEqual(text,'Look web.')

    def test_gemma_instructed_to_respond_in_language_of_latest_turn(self):
        payload={'messages':[{'role':'system','content':'x'},
                             {'role':'user','content':'Hello, how are you?'}]}
        _compact_chat_payload(payload,'Alex')
        system=payload['messages'][0]['content']
        self.assertIn('ngôn ngữ người dùng vừa nói',system)
        self.assertIn('chỉ dịch hoặc đổi ngôn ngữ khi người dùng yêu cầu',system)
        self.assertIn('xưng tao, gọi mày',system)

    def test_detected_language_is_scoped_to_the_audio_turn(self):
        with patch('pet.llm.httpx.Client'):engine=Controller(load_config())
        self.addCleanup(engine.local_chat._client.close);self.addCleanup(engine.gemini_chat._client.close)
        engine.gemini_chat.response_language='vi'
        utterance=Utterance(np.zeros(10),time.monotonic());utterance.language='en'
        with patch.object(engine,'_answer_impl',side_effect=lambda *a,**kw:engine.gemini_chat.response_language):
            self.assertEqual(engine._answer('Hello',utterance,0),'en')
        self.assertEqual(engine.gemini_chat.response_language,'vi')
        self.assertEqual(engine.gemini_chat.history[-1][0],'Hello')

    def test_detected_language_instruction_preserves_user_request(self):
        chat=object.__new__(GemmaChat);chat.name='Alex';chat.response_language='zh'
        payload={'messages':[{'role':'system','content':'original'},
                             {'role':'user','content':'你好'}]}
        with patch.object(GeminiChat,'_retry_stream',return_value='ok') as send:
            chat._retry_stream(None,payload,threading.Event())
        messages=send.call_args.args[1]['messages']
        self.assertIn('本次请使用中文回答',messages[0]['content'])
        self.assertTrue(messages[-1]['content'].startswith('你好'))
        self.assertIn('请用中文回答',messages[-1]['content'])

if __name__=='__main__': unittest.main()
