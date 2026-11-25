import json
import threading
import unittest
from contextlib import nullcontext
from pet.gemini import GeminiChat


class Response:
    status_code=200
    def __init__(self,delta): self.delta=delta
    def __enter__(self): return self
    def __exit__(self,*a): return False
    def iter_lines(self):
        yield 'data: '+json.dumps({'choices':[{'delta':self.delta,'finish_reason':'stop'}]})


def call(name, args=None):
    return {'index':0,'id':name,'function':{'name':name,'arguments':json.dumps(args or {})}}


class Backend:
    cfg={'max_steps':8}
    def __init__(self): self.calls=[]
    def tools(self,event):
        return [{'type':'function','function':{'name':n}} for n in ('Plan','Type','OpenLocal','Cancel','Finish')]
    def call(self,name,args,event):
        self.calls.append(name)
        return json.dumps({'is_error':name=='Type','result':{'approved':True} if name=='Plan' else 'blocked fixture'})


class Chat:
    _computer_stream=GeminiChat._computer_stream
    goal_task_for_turn=True
    name='Alex'
    cfg={'model':'fixture'}
    def __init__(self,responses): self.responses=responses; self.computer=Backend(); self.history=[]; self.payloads=[]
    def _history_for(self,q): return []
    def _make_http_client(self,**kw): return nullcontext()
    def _retry_stream(self,client,payload,event,**kw):
        self.payloads.append(payload.copy())
        return self.responses.pop(0)


class ProtocolTests(unittest.TestCase):
    def test_failure_stops_before_sibling_action_and_no_generation_retry(self):
        a=call('Type'); b={**call('OpenLocal'),'index':1}
        chat=Chat([Response({'tool_calls':[call('Plan')]}),Response({'tool_calls':[a,b]})])
        answer=''.join(chat._computer_stream('fixture',threading.Event()))
        self.assertEqual(chat.computer.calls,['Plan','Type'])
        self.assertEqual(len(chat.payloads),2)
        self.assertIn('đã dừng',answer)

    def test_mutation_not_exposed_or_executed_before_plan(self):
        chat=Chat([Response({'tool_calls':[call('Type')]}),Response({'content':'Chưa thực hiện.'})])
        list(chat._computer_stream('fixture',threading.Event()))
        self.assertEqual(chat.computer.calls,[])
        exposed={t['function']['name'] for t in chat.payloads[0]['tools']}
        self.assertNotIn('Type',exposed)
        self.assertIn('Plan',exposed)
        self.assertEqual(chat.payloads[0]['tool_choice'],'required')
        self.assertEqual(chat.payloads[0]['temperature'],.1)


if __name__=='__main__': unittest.main()
