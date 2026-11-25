import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pet.agent_bridge import unique_ref_for_point, AgentBridgeError
from pet.desktop_guard import DesktopGuard, Window
from pet.gemma import GemmaChat
from pet.gemini import GeminiChat
from pet.task_tools import GoalUIReferences

FOCUSED='├── (215,142) edit "Tìm kiếm trên Messenger" [focused] [action: fill]'
QUERY='alex-kiem-tra'
GOAL='Mở Messenger và tìm kiếm '+QUERY


class FocusedTargetTests(unittest.TestCase):
    def test_decorative_text_does_not_hide_field_and_two_fields_remain_ambiguous(self):
        g=DesktopGuard()
        g.snapshot=FOCUSED+'\n└── (215,142) text "sample" [action: click]'
        self.assertEqual(g._target_line([215,142]),FOCUSED)
        g.snapshot+='\n└── (215,142) edit "Other field" [action: fill]'
        self.assertEqual(g._target_line([215,142]),'')

    def guard(self):
        win=Window(1,123,'chrome.exe','Messenger - Google Chrome')
        approvals=[]
        def approve(op,grant='',description=''):
            approvals.append(op)
            return {'allowed':op!='approve_action','grant':'fixture'}
        g=DesktopGuard(approve,lambda:win,lambda _:True)
        g.plan(GOAL,['Mở Messenger','Tìm kiếm'],['Chrome'],[])
        g.after('Snapshot',{},win,FOCUSED,False)
        return g,win,approvals

    def test_focused_field_remains_exactly_guarded_and_matches_agent_ref(self):
        g,win,approvals=self.guard()
        args,_=g.before('Type',{'loc':[215,142],'text':QUERY,'clear':False,'press_enter':False})
        g.validate_live_target('Type',args,FOCUSED,win)
        self.assertNotIn('approve_action',approvals)
        snap={'tree':{'ref_id':'@s1:e1','role':'edit','name':'Tìm kiếm trên Messenger',
                      'bounds':{'x':200,'y':130,'width':100,'height':30},'available_actions':['SetFocus','SetValue']}}
        self.assertEqual(unique_ref_for_point(snap,[215,142],g._target_line([215,142]),'type'),'@s1:e1')
        with self.assertRaises(AgentBridgeError):
            unique_ref_for_point(snap,[216,142],FOCUSED,'type')

    def test_changed_label_still_blocks_focused_target(self):
        g,win,_=self.guard()
        with self.assertRaises(ValueError):
            g.validate_live_target('Type',{'loc':[215,142]},FOCUSED.replace('Tìm kiếm trên Messenger','Nhập tin nhắn'),win)

    def test_duplicate_point_and_point_in_label_do_not_establish_target(self):
        g,_,_=self.guard()
        forged='└── (900,900) edit "Search (215,142)" [focused] [action: fill]'
        self.assertEqual(g._target_line([215,142],forged),'')
        self.assertEqual(g._target_line([215,142],FOCUSED+'\n'+FOCUSED.replace('Tìm kiếm trên Messenger','Khác')),'')
        self.assertEqual(g._target_line([True,142]),'')


class SearchExecutionTests(unittest.TestCase):
    def run_input(self,tree,text=QUERY):
        calls=[]; result={}
        def backend(n,a,e):
            calls.append((n,a.copy()))
            return json.dumps({'is_error':False,'result':tree if n=='Snapshot' else 'typed'})
        chat=object.__new__(GemmaChat)
        chat.__dict__.update(computer=SimpleNamespace(cfg={},tools=lambda _:[],call=backend),
            computer_for_turn=True,computer_enabled=True,goal_task_for_turn=True,history=[],computer_original_request=GOAL)
        def stream(self,q,event):
            raw=json.loads(self.computer.call('InspectUI',{},event))['result']
            ref=next(line.split()[0] for line in raw.splitlines() if line.startswith('ui'))
            result.update(json.loads(self.computer.call('TypeUI',{'target':ref,'text':text,'clear':True,'press_enter':True},event)))
            yield 'fixture'
        with patch.object(GeminiChat,'stream',stream):
            list(chat.stream(GOAL,threading.Event()))
        return calls,result

    def test_only_search_button_does_not_enable_type(self):
        refs=GoalUIReferences()
        refs.project('UI Tree:\nwindow "Demo"\n└── (1,2) button "Search" [action: click]')
        self.assertEqual(refs.search_input_refs(),[])

    def test_no_search_field_cannot_fall_through_into_composer(self):
        calls,result=self.run_input('UI Tree:\nwindow "Messenger"\n└── (1,2) edit "Aa" [action: fill]')
        self.assertTrue(result['is_error'])
        self.assertNotIn('Type',[n for n,_ in calls])

    def test_wrong_query_cannot_be_typed_even_into_correct_search_field(self):
        calls,result=self.run_input('UI Tree:\nwindow "Messenger"\n'+FOCUSED,text='wrong query')
        self.assertTrue(result['is_error'])
        self.assertNotIn('Type',[n for n,_ in calls])

    def test_model_flags_cannot_reach_backend_for_verified_search_field(self):
        calls,result=self.run_input('UI Tree:\nwindow "Messenger"\n'+FOCUSED)
        self.assertFalse(result['is_error'])
        typed=[a for n,a in calls if n=='Type']
        self.assertEqual(len(typed),1)
        self.assertIs(typed[0]['clear'],False)
        self.assertIs(typed[0]['press_enter'],False)
        self.assertEqual(typed[0]['text'],QUERY)

if __name__=='__main__': unittest.main()
