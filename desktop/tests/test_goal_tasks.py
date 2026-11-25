import json
from pathlib import Path
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import patch

from pet.task_intent import is_goal_task
from pet.task_tools import compact_task_tools, task_arguments, task_snapshot, GoalUIReferences, required_search_query, search_completed
from pet.controller import Controller
from pet.gemma import GemmaChat
from pet.agent_dispatch import should_require_empty, is_eligible


class IntentTests(unittest.TestCase):
    def test_full_goals(self):
        for text in (
            'Mở Notepad rồi nhập chữ xin chào',
            'Mở Notepad rồi nhập chữ xin chào. Không gửi hay lưu tệp.',
            'Mày mở Chrome, sau đó tìm lịch học cho tao',
            'Mở thư mục HỌC TẬP rồi liệt kê các file PDF',
            'Tìm file kế hoạch rồi sao chép sang thư mục Bản sao',
            'Tạo file ghi-chu.txt trong thư mục đã chọn',
            'Đọc tài liệu kế hoạch cho tao',
            'Sao chép file báo cáo sang thư mục Sao lưu',
        ):
            with self.subTest(text=text): self.assertTrue(is_goal_task(text))

    def test_single_commands_and_data_stay_on_existing_router(self):
        for text in (
            'Mở KiCad cho tao', 'Mở Zalo', 'Mở thư mục HỌC TẬP',
            'Mở TikTok trên web', 'Mở nhạc Lạc Trôi trên YouTube',
            'Tìm "mở Notepad rồi nhập chữ" trên Google',
            'Mở bài “Và rồi tạo file” trên YouTube',
            'Làm sao tạo file trong Notepad?', 'Tao đang học lập trình',
            'Đừng mở Chrome rồi nhập chữ', 'Tắt máy',
            'Khi tao nói học thì mở Notepad rồi nhập chữ',
            'Mở ứng dụng dụng.', 'Bấm nút tìm kiếm trên màn hình',
        ):
            with self.subTest(text=text): self.assertFalse(is_goal_task(text))


class RouterHarness:
    _answer_impl = Controller._answer_impl
    computer_enabled = True
    def __init__(self):
        self.opening_contexts = {'desktop': SimpleNamespace(resolve=lambda q:(q,False), clear=lambda:None)}
        self.web_scroller = SimpleNamespace(is_active=lambda:False)
        self.transcript = SimpleNamespace(emit=lambda q:None)
        self.state = SimpleNamespace(emit=lambda *args:None)
        self.received = []
    def _compound_turn(self, *args): return None
    def _trace(self, *args, **kwargs): pass
    def _model_turn(self, question, spoken_question, *args, **kwargs):
        self.received.append((question, spoken_question, kwargs))
        return 'actual model route'


class RouterTests(unittest.TestCase):
    def test_entire_goal_reaches_model_before_site_app_file_parsers(self):
        for text in ('Mở Notepad rồi nhập chữ xin chào',
                     'Mở YouTube rồi chọn ô tìm kiếm',
                     'Mở thư mục HỌC TẬP rồi đọc file kế hoạch'):
            h = RouterHarness()
            with patch('pet.controller.requested_app', side_effect=AssertionError('must not eat first clause')), \
                 patch('pet.controller.requested_web', side_effect=AssertionError('must not eat first clause')), \
                 patch('pet.controller.requested_file', side_effect=AssertionError('must not eat first clause')):
                self.assertEqual(h._answer_impl(text, None, 0), 'actual model route')
            self.assertEqual(h.received, [(text, text, {'force_task':True})])

    def test_disabled_tools_report_truth_without_model(self):
        h = RouterHarness(); h.computer_enabled = False
        h._speak_action_result = lambda *args: None
        self.assertIn('chưa thực hiện', h._answer_impl('Mở Notepad rồi nhập chữ xin chào', None, 0))
        self.assertFalse(h.received)


class CompactToolsTests(unittest.TestCase):
    def test_web_service_plan_adds_only_registered_browser(self):
        import desktop_mcp
        with patch.object(desktop_mcp,'resolve_web',side_effect=lambda n,c: ('https://example.com','Demo') if n=='Demo' else None), \
             patch.object(desktop_mcp,'resolve_app',return_value=None), \
             patch.object(desktop_mcp,'default_browser_app',return_value='Chrome'):
            self.assertEqual(desktop_mcp.expand_web_plan_apps(['Demo'],{}),['Demo','Chrome'])
            self.assertEqual(desktop_mcp.expand_web_plan_apps(['Notepad'],{}),['Notepad'])
            self.assertEqual(desktop_mcp.expand_web_plan_apps(['Demo','Chrome'],{}),['Demo','Chrome'])
            with patch.object(desktop_mcp,'resolve_app',return_value={'name':'Demo'}):
                self.assertEqual(desktop_mcp.expand_web_plan_apps(['Demo'],{}),['Demo'])

    def test_search_clause_requires_correct_search_readback(self):
        query=required_search_query('Mày hãy mở Messenger cho tao và tìm kiếm An Mẫu.')
        self.assertEqual(query,'An Mẫu')
        self.assertEqual(required_search_query('Mở YouTube rồi chọn ô tìm kiếm'), '')
        self.assertFalse(search_completed(query,'','Tìm kiếm','Messenger'))
        self.assertFalse(search_completed(query,'An Mẫu','Nhập tin nhắn','An Mẫu'))
        self.assertFalse(search_completed(query,'Sai tên','Tìm kiếm','Sai tên'))
        self.assertFalse(search_completed(query,'An Mẫu','Tìm kiếm','Messenger'))
        self.assertTrue(search_completed(query,'An Mẫu','Tìm kiếm trên Messenger','Value="An Mẫu"'))

    def test_premature_finish_does_not_reach_backend_or_replay_open(self):
        from pet import gemini
        calls=[]; text=''
        def backend(name,args,event):
            nonlocal text
            calls.append(name)
            if name=='Type': text=args['text']
            result=('UI Tree:\nwindow "Messenger - Chrome"\n└── (10,20) edit "Tìm kiếm trên Messenger" [action: fill] [value:"'+text+'"]'
                    if name=='Snapshot' else {'finished':True} if name=='Finish' else 'opened')
            return json.dumps({'is_error':False,'result':result},ensure_ascii=False)
        instance=object.__new__(GemmaChat)
        instance.__dict__.update(computer=SimpleNamespace(cfg={},tools=lambda _:[],call=backend),
            computer_for_turn=True,computer_enabled=True,goal_task_for_turn=True,history=[],
            computer_original_request='Mở Messenger và tìm kiếm An Mẫu')
        def stream(self,q,event):
            self.computer.call('OpenLocal',{'name':'Messenger','kind':'app'},event)
            result=json.loads(self.computer.call('Finish',{'evidence':'Messenger'},event))
            self.assertion_result=result
            self.computer.call('TypeUI',{'target':'ui1_0','text':'An Mẫu'},event)
            self.computer.call('Finish',{'evidence':'An Mẫu'},event)
            yield 'Đã tìm kiếm.'
        with patch.object(gemini.GeminiChat,'stream',stream):
            self.assertEqual(''.join(instance.stream('fixture',threading.Event())),'Đã tìm kiếm.')
        self.assertFalse(instance.assertion_result['is_error'])
        self.assertEqual(instance.assertion_result['result']['pending'],'search_not_verified')
        self.assertEqual(calls,['OpenLocal','Snapshot','Type','Snapshot','Finish'])

    def test_target_ids_resolve_observed_coordinates_and_expire(self):
        refs=GoalUIReferences()
        projected=refs.project('UI Tree:\nwindow "Demo"\n└── (57,63) edit "Search" [action: fill]')
        self.assertIn('ui1_0',projected)
        self.assertNotIn('(57,63)',projected)
        self.assertEqual(refs.resolve('TypeUI',{'target':'ui1_0','text':'hello','loc':[1,2]}),
            ('Type',{'loc':[57,63],'text':'hello'}))
        refs.invalidate()
        with self.assertRaises(ValueError): refs.resolve('ClickUI',{'target':'ui1_0'})
    def test_document_input_chooses_native_backend_before_any_attempt(self):
        self.assertFalse(is_eligible('Type',{'clear':False,'press_enter':False},True,
            '└── (50,60) document "Text editor" [action: scroll]'))
        self.assertTrue(is_eligible('Type',{'clear':False,'press_enter':False},True,
            '└── (50,60) edit "Search" [action: fill]'))
    def test_snapshot_preserves_actual_editor_after_long_window_header(self):
        line='└── (500,300) edit "Text editor"  [action: fill] [focused]'
        raw='Focused Window:\nUntitled - Notepad  0 Normal\nOpened Windows:\n'+('other-window '*400)+'\nUI Tree:\nwindow "Untitled - Notepad"\n'+line
        compact=task_snapshot(json.dumps([raw]))
        self.assertIn(line,compact)
        self.assertNotIn('other-window',compact)
        self.assertLess(len(compact),1601)
    def test_snapshot_does_not_include_other_window_controls(self):
        raw='Focused Window:\nUntitled - Notepad 0 Normal\nOpened Windows:\nUI Tree:\nwindow "Untitled - Notepad"\n└── (1,2) edit "Text editor" [action: fill]\nwindow "Private chat"\n└── (9,9) button "Send" [action: click]'
        compact=task_snapshot(raw)
        self.assertIn('(1,2)',compact)
        self.assertNotIn('Private chat',compact)
        self.assertNotIn('(9,9)',compact)
    def test_open_then_type_keeps_empty_field_guard(self):
        args={'clear':True,'press_enter':False,'text':'xin chào'}
        self.assertTrue(should_require_empty('Type',args,True,'Mở Notepad rồi nhập chữ xin chào vào ô văn bản'))
        self.assertTrue(should_require_empty('Type',args,True,'Nhập chữ xin chào vào ô văn bản'))
        self.assertFalse(should_require_empty('Type',args,True,'Mở Notepad rồi xóa văn bản cũ và nhập chữ mới'))
        self.assertFalse(should_require_empty('Type',{**args,'press_enter':True},True,'Mở Notepad rồi nhập chữ xin chào vào ô văn bản'))
    def test_coordinate_encoding_never_bypasses_target_checks(self):
        self.assertEqual(task_arguments('Type',{'loc':'[12,34]','text':'hello'})['loc'],[12,34])
        for point in ('[true,2]','[1,2,3]','bad','[1.5,2]'):
            self.assertEqual(task_arguments('Click',{'loc':point})['loc'],point)
        self.assertEqual(task_arguments('Snapshot',{'use_vision':True}),
            {'use_vision':False,'use_annotation':False,'use_ui_tree':True})
    def test_compatible_schemas_smaller_and_original_unchanged(self):
        schemas = json.loads((Path(__file__).parent / 'fixtures/desktop_tool_schemas.json').read_text(encoding='utf-8'))
        original = json.dumps(schemas, ensure_ascii=False)
        compact = compact_task_tools(schemas)
        by_name = {s['function']['name']:s['function']['parameters'] for s in schemas}
        for s in compact:
            fn=s['function']; name={'InspectUI':'Snapshot','ClickUI':'Click','TypeUI':'Type','ScrollUI':'Scroll'}.get(fn['name'],fn['name']); prior=by_name[name]
            expected=set(prior.get('required',[]))-({'loc'} if name in ('Click','Type','Scroll') else set())
            self.assertGreaterEqual(set(fn['parameters'].get('required', [])),expected)
            self.assertLessEqual(set(fn['parameters']['properties'])-{'target'},set(prior['properties']))
        self.assertEqual(json.dumps(schemas, ensure_ascii=False), original)
        self.assertLess(len(json.dumps(compact, ensure_ascii=False)), len(original)*.65)
        self.assertNotIn('PowerShell', {s['function']['name'] for s in compact})

    def test_claim_is_blocked_without_verified_finish(self):
        from pet import gemini
        backend = SimpleNamespace(cfg={}, tools=lambda _:[], call=lambda *a:json.dumps({'result':'opened'}))
        chat = SimpleNamespace(computer=backend, computer_for_turn=True, computer_enabled=True,
            goal_task_for_turn=True, history=[], cancelled=threading.Event())
        def stream(self, question, cancelled):
            self.computer.call('OpenLocal', {'name':'Notepad','kind':'app'}, cancelled)
            yield 'Đã hoàn thành toàn bộ.'
        with patch.object(gemini.GeminiChat, 'stream', stream):
            # This wrapper uses super(), so construct a real subclass instance
            # without starting its runtime/server.
            instance = object.__new__(GemmaChat)
            instance.__dict__.update(chat.__dict__)
            answer = ''.join(instance.stream('test', threading.Event()))
        self.assertIn('chưa xác nhận', answer)
        self.assertNotIn('Đã hoàn thành', answer)

    def test_plan_only_and_no_tools_cannot_claim_completion(self):
        from pet import gemini
        for plan_only in (False,True):
            backend=SimpleNamespace(cfg={},tools=lambda _:[],call=lambda *a:json.dumps({'result':{'approved':True}}))
            instance=object.__new__(GemmaChat)
            instance.__dict__.update(computer=backend, computer_for_turn=True,computer_enabled=True,
                                     goal_task_for_turn=True, history=[])
            def stream(self,q,event):
                if plan_only: self.computer.call('Plan',{},event)
                yield 'Đã hoàn thành toàn bộ.'
            with patch.object(gemini.GeminiChat,'stream',stream):
                answer=''.join(instance.stream('test',threading.Event()))
            self.assertIn('chưa xác nhận',answer)
            self.assertNotIn('Đã hoàn thành',answer)

    def test_escaped_finish_evidence_is_only_unescaped_if_observed(self):
        from pet import gemini
        calls=[]
        def call(name,args,event):
            calls.append((name,args))
            if name=='Snapshot': result='TextBox "Văn bản" Value="xin chào"'
            elif name=='Finish': result={'finished':args['evidence']=='Value="xin chào"'}
            else: result='typed'
            return json.dumps({'is_error':False,'result':result},ensure_ascii=False)
        backend=SimpleNamespace(cfg={},tools=lambda _:[],call=call)
        instance=object.__new__(GemmaChat)
        instance.__dict__.update(computer=backend,computer_for_turn=True,computer_enabled=True,
                                 goal_task_for_turn=True,history=[])
        def stream(self,q,event):
            self.computer.call('Type',{'text':'xin chào'},event)
            self.computer.call('Snapshot',{},event)
            self.computer.call('Finish',{'evidence':'Value=\\"xin chào\\"'},event)
            yield 'Đã kiểm tra đúng chữ.'
        with patch.object(gemini.GeminiChat,'stream',stream):
            answer=''.join(instance.stream('test',threading.Event()))
        self.assertEqual(calls[-1][1]['evidence'],'Value="xin chào"')
        self.assertEqual(answer,'Đã kiểm tra đúng chữ.')

    def test_finish_reads_ui_after_mutation_even_if_model_skips_snapshot(self):
        from pet import gemini
        calls=[]
        def call(name,args,event):
            calls.append(name)
            result='└── (1,2) text "Đã tìm kiếm" [action: click]' if name=='Snapshot' else {'finished':True} if name=='Finish' else 'clicked'
            return json.dumps({'is_error':False,'result':result},ensure_ascii=False)
        instance=object.__new__(GemmaChat)
        instance.__dict__.update(computer=SimpleNamespace(cfg={},tools=lambda _:[],call=call),
            computer_for_turn=True,computer_enabled=True,goal_task_for_turn=True,history=[])
        def stream(self,q,event):
            self.computer.call('Click',{'loc':[1,2]},event)
            self.computer.call('Finish',{'evidence':'Đã tìm kiếm'},event)
            yield 'Đã kiểm tra.'
        with patch.object(gemini.GeminiChat,'stream',stream):
            self.assertEqual(''.join(instance.stream('test',threading.Event())),'Đã kiểm tra.')
        self.assertEqual(calls,['Click','Snapshot','Finish'])

    def test_messenger_search_box_survives_verbose_chrome_snapshot(self):
        from pet.task_tools import task_snapshot, GoalUIReferences, search_completed
        filler='\n'.join(f'├── ({100+i},60) button "Conversation Item {i} with long title" [action: click]' for i in range(30))
        raw=(
            'Focused Window: Messenger - Google Chrome\n'
            'UI Tree:\n'
            'window "Messenger - Google Chrome"\n'
            '├── (300,50) edit "Thanh địa chỉ và tìm kiếm" [focused] [action: fill]\n'
            '├── (300,90) edit "Tìm trên Google hoặc nhập URL" [action: fill]\n'
            f'{filler}\n'
            '├── (215,142) combobox "Tìm kiếm trên Messenger" [action: click]\n'
        )
        compact=task_snapshot(raw)
        self.assertIn('Tìm kiếm trên Messenger',compact)
        refs=GoalUIReferences()
        projected=refs.project(raw)
        self.assertIn('Tìm kiếm trên Messenger',projected)
        self.assertTrue(search_completed('alex-kiem-tra','alex-kiem-tra','Tìm kiếm trên Messenger','... alex-kiem-tra ...'))

    def test_search_task_constrains_type_clear_and_enter_to_false(self):
        from pet import gemini
        type_schema={'type':'function','function':{'name':'Type','description':'Type loc=[x,y] from fresh Snapshot','parameters':{'type':'object','properties':{'loc':{'type':'array'},'text':{'type':'string'}},'required':['loc','text']}}}
        seen=[]
        backend=SimpleNamespace(cfg={},tools=lambda _:[type_schema],call=lambda *a:json.dumps({'is_error':False,'result':'ok'}))
        instance=object.__new__(GemmaChat)
        instance.__dict__.update(computer=backend,computer_for_turn=True,computer_enabled=True,goal_task_for_turn=True,computer_original_request='Mày hãy mở Messenger cho tao và tìm kiếm alex-kiem-tra.',history=[])
        def stream(self,q,event):
            seen.extend(self.computer.tools(event))
            yield 'Dừng test.'
        with patch.object(gemini.GeminiChat,'stream',stream):
            list(instance.stream('Mày hãy mở Messenger cho tao và tìm kiếm alex-kiem-tra.',threading.Event()))
        props=next(s['function']['parameters']['properties'] for s in seen if s['function']['name']=='TypeUI')
        self.assertEqual(props['clear']['enum'],[False])
        self.assertEqual(props['press_enter']['enum'],[False])

    def test_search_task_preflight_clamps_clear_and_enter_before_backend(self):
        from pet import gemini
        from pet.task_tools import GoalUIReferences
        snapshot_tree=(
            'Focused Window: Messenger - Google Chrome\n'
            'UI Tree:\n'
            'window "Messenger - Google Chrome"\n'
            '├── (300,50) edit "Thanh địa chỉ và tìm kiếm" [action: fill]\n'
            '├── (215,142) edit "Tìm kiếm trên Messenger" [focused] [action: fill]\n'
            '├── (500,900) edit "Aa" [action: fill]\n'
        )
        for use_pending in (False, True):
            sent=[]
            def call(name,args,event):
                sent.append((name,dict(args)))
                if name=='Plan': return json.dumps({'is_error':False,'result':{'approved':True}})
                if name=='OpenLocal': return json.dumps({'is_error':False,'result':'opened'})
                if name=='Snapshot':
                    res=snapshot_tree + ('\n├── (215,200) text "alex-kiem-tra" [action: click]' if any(n=='Type' for n,_ in sent) else '')
                    return json.dumps({'is_error':False,'result':res},ensure_ascii=False)
                if name=='Type': return json.dumps({'is_error':False,'result':'typed'})
                if name=='Finish': return json.dumps({'is_error':False,'result':{'finished':True}})
                return json.dumps({'is_error':False,'result':'ok'})
            backend=SimpleNamespace(cfg={},tools=lambda _:[],call=call)
            instance=object.__new__(GemmaChat)
            instance.__dict__.update(computer=backend,computer_for_turn=True,computer_enabled=True,goal_task_for_turn=True,computer_original_request='Mày hãy mở Messenger cho tao và tìm kiếm alex-kiem-tra.',history=[])
            def stream(self,q,event):
                self.computer.call('Plan',{'goal':q,'apps':['Messenger','Chrome']},event)
                self.computer.call('OpenLocal',{'name':'Messenger'},event)
                snap=json.loads(self.computer.call('InspectUI',{},event))['result']
                search_ref=next(line.split()[0] for line in snap.splitlines() if 'Tìm kiếm trên Messenger' in line)
                if use_pending:
                    self.computer.call('Finish',{'evidence':'Messenger'},event)
                self.computer.call('TypeUI',{'target':search_ref,'text':'alex-kiem-tra','clear':True,'press_enter':True},event)
                self.computer.call('InspectUI',{},event)
                self.computer.call('Finish',{'evidence':'alex-kiem-tra'},event)
                yield 'Đã tìm thấy alex-kiem-tra.'
            with patch.object(gemini.GeminiChat,'stream',stream):
                ans=''.join(instance.stream('Mày hãy mở Messenger cho tao và tìm kiếm alex-kiem-tra.',threading.Event()))
            type_calls=[args for name,args in sent if name=='Type']
            self.assertEqual(len(type_calls),1)
            self.assertIs(type_calls[0]['clear'],False)
            self.assertIs(type_calls[0]['press_enter'],False)
            self.assertEqual(type_calls[0]['loc'],[215,142])
            self.assertIn('alex-kiem-tra',ans)

    def test_search_input_refs_excludes_buttons_history_omnibox_and_composer(self):
        from pet import gemini
        from pet.task_tools import GoalUIReferences
        raw=(
            'Focused Window: Messenger - Google Chrome\n'
            'UI Tree:\n'
            'window "Messenger - Google Chrome"\n'
            '├── (300,50) edit "Thanh địa chỉ và tìm kiếm" [action: fill]\n'
            '├── (300,90) edit "Tìm trên Google hoặc nhập URL" [action: fill]\n'
            '├── (215,142) edit "Tìm kiếm trên Messenger" [focused] [action: fill]\n'
            '├── (250,142) button "Tìm kiếm" [action: click]\n'
            '├── (215,210) listitem "Tìm kiếm gần đây" [action: click]\n'
            '├── (500,900) edit "Aa" [action: fill]\n'
        )
        refs=GoalUIReferences()
        refs.project(raw)
        selected=refs.search_input_refs()
        self.assertEqual([refs.labels[r] for r in selected],['Tìm kiếm trên Messenger'])
        sent=[]
        backend=SimpleNamespace(cfg={},tools=lambda _:[],call=lambda n,a,e:(sent.append(n),json.dumps({'is_error':False,'result':raw if n=='Snapshot' else 'ok'}))[1])
        instance=object.__new__(GemmaChat)
        instance.__dict__.update(computer=backend,computer_for_turn=True,computer_enabled=True,goal_task_for_turn=True,computer_original_request='Mày hãy mở Messenger cho tao và tìm kiếm alex-kiem-tra.',history=[])
        captured={}
        def stream(self,q,event):
            snap=json.loads(self.computer.call('InspectUI',{},event))['result']
            composer_ref=next(line.split()[0] for line in snap.splitlines() if '"Aa"' in line)
            captured['res']=json.loads(self.computer.call('TypeUI',{'target':composer_ref,'text':'alex-kiem-tra','clear':True,'press_enter':True},event))
            yield captured['res']['result']
        with patch.object(gemini.GeminiChat,'stream',stream):
            list(instance.stream('Mày hãy mở Messenger cho tao và tìm kiếm alex-kiem-tra.',threading.Event()))
        self.assertNotIn('Type',sent)
        self.assertTrue(captured['res']['is_error'])
        self.assertIn('ô tìm kiếm',captured['res']['result'])

    def test_agent_dispatch_verifies_focus_via_is_focused_without_fallback(self):
        from pet import agent_dispatch
        from pet.agent_bridge import AgentBridgeError
        from pet.desktop_guard import Window
        win=Window(1,100,'chrome.exe','Messenger - Google Chrome')
        guard=SimpleNamespace(_target_line=lambda _:'├── (215,142) edit "Tìm kiếm trên Messenger" [action: fill]')
        snap={'tree':{'ref_id':'@s1:e1','role':'edit','name':'Tìm kiếm trên Messenger','bounds':{'x':200,'y':130,'width':40,'height':24},'available_actions':['SetFocus','SetValue']}}
        class Bridge:
            def __init__(self,binary,wid,win_ok,auth_ok,priv): pass
            def __enter__(self): return self
            def __exit__(self,*a): pass
            def snapshot(self,max_depth=10): return snap
            def is_focused(self,ref): return self._focused
            def focus_for_type(self,ref,text):
                self._focused=self._focus_succeeds
                return {'ok':True,'data':{'disposition':{'delivery':'delivered_unverified'}}}
            def act(self,op,ref,text=''): return {'ok':True,'data':{'disposition':{'delivery':'delivered_verified'},'details':{'verification_scope':'element_value'}}}
        Bridge._focused=False
        Bridge._focus_succeeds=True
        with patch.object(agent_dispatch,'_binary',return_value='agent-desktop.exe'), patch.object(agent_dispatch,'current_window',return_value=win):
            res=agent_dispatch.run_agent_step(guard,win,'Type',{'loc':[215,142],'text':'alex-kiem-tra','clear':False,'press_enter':False},bridge_type=Bridge)
            self.assertEqual(res['delivery'],'delivered_verified')
            Bridge._focused=False
            Bridge._focus_succeeds=False
            with self.assertRaises(AgentBridgeError):
                agent_dispatch.run_agent_step(guard,win,'Type',{'loc':[215,142],'text':'alex-kiem-tra','clear':False,'press_enter':False},bridge_type=Bridge)

    def test_pending_completion_withholds_cancel_while_page_loading(self):
        from pet import gemini
        empty_snap='Focused Window: Messenger - Google Chrome\nUI Tree:\nwindow "Messenger - Google Chrome"\n'
        ready_snap=empty_snap+'├── (215,142) edit "Tìm kiếm trên Messenger" [action: fill]\n'
        observed_tools=[]
        calls=0
        def call(name,args,event):
            nonlocal calls
            if name=='Plan': return json.dumps({'is_error':False,'result':{'approved':True}})
            if name=='Snapshot':
                calls+=1
                return json.dumps({'is_error':False,'result':ready_snap if calls>=3 else empty_snap},ensure_ascii=False)
            return json.dumps({'is_error':False,'result':'ok'})
        backend=SimpleNamespace(cfg={},tools=lambda _:[
            {'type':'function','function':{'name':'Snapshot','description':'snap','parameters':{'type':'object','properties':{}}}},
            {'type':'function','function':{'name':'Type','description':'loc=[x,y] from fresh Snapshot','parameters':{'type':'object','properties':{'loc':{'type':'array'},'text':{'type':'string'}},'required':['loc','text']}}},
            {'type':'function','function':{'name':'Cancel','description':'cancel','parameters':{'type':'object','properties':{}}}},
            {'type':'function','function':{'name':'Finish','description':'finish','parameters':{'type':'object','properties':{'evidence':{'type':'string'}}}}},
        ],call=call)
        instance=object.__new__(GemmaChat)
        instance.__dict__.update(computer=backend,computer_for_turn=True,computer_enabled=True,goal_task_for_turn=True,computer_original_request='Mày hãy mở Messenger cho tao và tìm kiếm alex-kiem-tra.',history=[])
        def stream(self,q,event):
            self.computer.call('Plan',{'goal':q,'apps':['Messenger','Chrome']},event)
            self.computer.call('InspectUI',{},event)
            self.computer.call('Finish',{'evidence':'Messenger'},event)
            observed_tools.append([t['function']['name'] for t in self.computer.tools(event)])
            self.computer.call('InspectUI',{},event)
            observed_tools.append([t['function']['name'] for t in self.computer.tools(event)])
            self.computer.call('InspectUI',{},event)
            observed_tools.append([t['function']['name'] for t in self.computer.tools(event)])
            yield 'ok'
        with patch.object(gemini.GeminiChat,'stream',stream):
            list(instance.stream('Mày hãy mở Messenger cho tao và tìm kiếm alex-kiem-tra.',threading.Event()))
        self.assertEqual(observed_tools[0],['InspectUI'])
        self.assertEqual(observed_tools[1],['InspectUI'])
        self.assertIn('TypeUI',observed_tools[2])

    def test_chromium_web_input_chooses_native_backend_before_any_attempt(self):
        self.assertFalse(is_eligible('Type',{'clear':False,'press_enter':False},True,
            '└── (215,142) edit "Tìm kiếm trên Messenger" [action: fill]',executable='chrome'))
        self.assertFalse(is_eligible('Type',{'clear':False,'press_enter':False},True,
            '└── (215,142) combobox "Tìm kiếm trên Messenger" [action: click]',executable='msedge'))
        self.assertTrue(is_eligible('Click',{'button':'left','clicks':1},True,
            '└── (250,142) button "Tìm kiếm" [action: click]',executable='chrome'))


if __name__ == '__main__': unittest.main()
