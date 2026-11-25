import contextlib, threading, time, unittest
from unittest.mock import MagicMock,patch
import numpy as np
from pet.audio import Utterance
from pet.config import load_config
from pet.controller import Controller
from pet.gemma import GemmaChat, _compact_chat_payload
from pet.session_memory import contextual_followup, context_history

class MemoryTests(unittest.TestCase):
    def test_relevant_older_turn_and_recent_are_available(self):
        history=[('Mèo của mình tên Mướp','Mướp là một chú mèo dễ thương.')]
        history += [(f'Chủ đề khác số {i}',f'Trả lời {i}') for i in range(12)]
        selected=context_history(history,'Mèo của mình tên gì?')
        self.assertEqual(selected[0],history[0])
        self.assertEqual(selected[-4:],history[-4:])
        self.assertLessEqual(sum(len(a)+len(b) for a,b in selected),3200)
    def test_long_recent_turn_does_not_erase_memory(self):
        history=[('Mèo tên Mướp','Mình nhớ Mướp.'),('X'*4000,'Y'*4000)]
        messages=[{'role':'system','content':'x'}]
        for user,answer in context_history(history,'Mèo tên gì?'):
            messages += [{'role':'user','content':user},{'role':'assistant','content':answer}]
        messages.append({'role':'user','content':'Mèo tên gì?'})
        payload={'messages':messages};_compact_chat_payload(payload,'Alex')
        self.assertIn('Mướp',str(payload['messages']))
        self.assertLessEqual(len(str(payload['messages'])),4500)
    def test_old_relevant_turn_survives_four_long_recent_turns(self):
        history=[('Mèo Mướp '+ 'x'*4000,'Mướp '+ 'y'*4000)]
        history += [(f'Khác {i} '+ 'x'*4000,'y'*4000) for i in range(7)]
        selected=context_history(history,'Mèo Mướp tên gì?')
        self.assertEqual(len(selected),5)
        self.assertIn('Mướp',selected[0][0])
        messages=[{'role':'system','content':'x'}]
        for user,answer in selected:
            messages += [{'role':'user','content':user},{'role':'assistant','content':answer}]
        messages.append({'role':'user','content':'Mèo Mướp tên gì?'})
        payload={'messages':messages};_compact_chat_payload(payload,'Alex')
        self.assertIn('Mướp',str(payload['messages']))
    def test_no_web_research_for_pronoun_followup_with_existing_context(self):
        with patch('pet.llm.httpx.Client'): engine=Controller(load_config())
        self.addCleanup(engine.gemini_chat._client.close);self.addCleanup(engine.local_chat._client.close)
        engine.learning=None;engine._desktop_speak=False;engine.speaker=MagicMock()
        engine.gemini_chat.history[:]=[('Giới thiệu Mặt Trăng','Mặt Trăng là vệ tinh của Trái Đất.')]
        engine.gemini_chat.stream=MagicMock(return_value=iter(['Mặt Trăng có một vệ tinh?']))
        with patch('pet.controller.search_web',side_effect=AssertionError('Network should not get unresolved follow-up')):
            engine._answer('Nó cách Trái Đất bao nhiêu?',Utterance(np.zeros(10),time.monotonic()),0)
        self.assertEqual(engine.gemini_chat.history[-1][0],'Nó cách Trái Đất bao nhiêu?')
        self.assertTrue(contextual_followup('Nó có bao nhiêu?'))
        self.assertFalse(contextual_followup('Vậy thời tiết Hà Nội hôm nay thế nào?'))
    def test_quick_local_action_is_saved_and_cancelled_is_not(self):
        with patch('pet.llm.httpx.Client'): engine=Controller(load_config())
        self.addCleanup(engine.gemini_chat._client.close);self.addCleanup(engine.local_chat._client.close)
        engine.gemini_chat.history=[]
        with patch.object(engine,'_answer_impl',return_value='Đã mở Zalo.'):
            engine._answer('Mở Zalo',Utterance(np.zeros(10),time.monotonic()),0)
        self.assertEqual(engine.gemini_chat.history,[('Mở Zalo','Đã mở Zalo.')])
        engine.cancelled.set()
        with patch.object(engine,'_answer_impl',return_value='Không nên lưu'):
            engine._answer('Dừng',Utterance(np.zeros(10),time.monotonic()),0)
        self.assertEqual(len(engine.gemini_chat.history),1)
    def test_model_turn_is_saved_once_as_user_exchange(self):
        with patch('pet.llm.httpx.Client'): engine=Controller(load_config())
        self.addCleanup(engine.gemini_chat._client.close);self.addCleanup(engine.local_chat._client.close)
        engine.gemini_chat.history=[('Trước','Đáp')]
        def inner(*a,**kw):
            engine.gemini_chat.history.append(('Internal prompt with screen data','answer'))
            return 'Trả lời thực tế'
        with patch.object(engine,'_answer_impl',side_effect=inner):
            engine._answer('Câu hỏi thật',Utterance(np.zeros(10),time.monotonic()),0)
        self.assertEqual(engine.gemini_chat.history,[('Trước','Đáp'),('Câu hỏi thật','Trả lời thực tế')])
    def test_gemma_keeps_more_than_old_six_turn_limit(self):
        from pet.gemini import GeminiChat
        chat=object.__new__(GemmaChat); chat.name='Alex';chat.cfg={'history_turns':6,'model':'x'}
        chat.history=[];chat.session_memory=True;chat.computer=None;chat.computer_enabled=False
        chat.computer_for_turn=False;chat.on_submitted=None;chat._client=object();chat.trend_updates_enabled=False
        chat.check_ready=MagicMock();chat.response=None
        response=MagicMock();response.status_code=200
        response.iter_lines.return_value=iter(['data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}','data: [DONE]'])
        @contextlib.contextmanager
        def request(*a,**k):
            response.iter_lines.return_value=iter(['data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}','data: [DONE]'])
            yield response
        with patch.object(GeminiChat,'_retry_stream',side_effect=request):
            for i in range(9):
                self.assertEqual(''.join(chat.stream(f'Câu {i}',threading.Event())),'ok')
        self.assertEqual(len(chat.history),9)
        self.assertEqual(chat.history[0][0],'Câu 0')

if __name__ == '__main__':unittest.main()
