import threading,time,unittest
import json
from unittest.mock import Mock,patch
import numpy as np
from pet.audio import Utterance
from pet.config import load_config
from pet.controller import Controller
from pet.screen_context import (ScreenObservation, _compact, is_screen_action, is_screen_element_action,
                                is_screen_question, screen_prompt, prepare_screen_action, youtube_named_target, named_screen_target, youtube_premium_request)
from pet.screen_tools import screen_tools, snapshot_excerpt, validate_screen_tool, search_focus_hint, search_focus_target, focused_search_is_verified, is_search_focus_request, target_is_in_excerpt, excerpt_matches_window, named_click_locations, prioritize_named_excerpt

class ScreenContextTests(unittest.TestCase):
    @staticmethod
    def snapshot_result():
        return json.dumps({'is_error':False,'result':'UI Tree:\ndesktop\n├── window "Ví dụ"\n│   └── (100,120) button "Cài đặt" [action: click]'})
    @staticmethod
    def fixture_windows():
        api=Mock();api.foreground.return_value=123;api.identity.return_value=(123,99,'fixture.exe','Class')
        return api
    def test_named_youtube_request_and_negation(self):
        text='Mày nhấn vào Greenium trên YouTube cho tao.'
        self.assertEqual(youtube_named_target(text),'greenium')
        self.assertTrue(youtube_premium_request(text))
        self.assertTrue(is_screen_action('Nhấn vào mục Chia sẻ trên YouTube'))
        self.assertTrue(is_screen_element_action('Nhấn vào mục Chia sẻ trên YouTube'))
        self.assertEqual(named_screen_target('Nhấn vào Cài đặt cho tao'), 'cai dat')
        self.assertTrue(is_screen_action('Nhấn vào Ví dụ cho tôi'))
        self.assertEqual(named_screen_target('Bấm vào nút Chia sẻ trên màn hình'), 'chia se')
        self.assertIsNone(named_screen_target('Đừng nhấn vào Cài đặt'))
        self.assertIsNone(named_screen_target('Mở ứng dụng Cài đặt'))
        self.assertIsNone(named_screen_target('Bấm vào ô nhập tìm kiếm cho tôi'))
        self.assertFalse(youtube_premium_request('Đừng nhấn vào Greenium trên YouTube'))
        self.assertFalse(youtube_premium_request('YouTube Premium có giá bao nhiêu?'))
        self.assertFalse(youtube_premium_request('Nhấn vào YouTube Music trên YouTube'))

    def test_named_target_beyond_short_excerpt_is_prioritized(self):
        compact='UI Tree:\n├── window "YouTube"\n│   └── (1,2) button "A" [action: click]'
        extended=compact+'\n│   └── (30,40) link "YouTube Premium" [action: click]'
        prioritized=prioritize_named_excerpt('premium',compact,extended)
        self.assertEqual(named_click_locations('premium',prioritized), [[30,40]])
        dup=extended+'\n│   └── (50,60) link "YouTube Premium" [action: click]'
        self.assertEqual(prioritize_named_excerpt('premium',compact,dup),compact)

    def test_named_youtube_click_requires_unique_correct_target(self):
        tree=('UI Tree:\n├── window "YouTube"\n│   ├── (100,200) button "Chia sẻ" [action: click]\n'
              '│   └── (300,400) button "Đăng ký" [action: click]')
        self.assertEqual(named_click_locations('chia se',tree),[[100,200]])
        self.assertEqual(named_click_locations('premium',tree),[])
        self.assertEqual(len(named_click_locations('chia se',tree+'\n│   └── (10,20) link "Chia sẻ" [action: click]')),2)

    def test_named_youtube_click_wont_forward_wrong_control(self):
        with patch('pet.llm.httpx.Client'): engine=Controller(load_config())
        self.addCleanup(engine.gemini_chat._client.close);self.addCleanup(engine.local_chat._client.close)
        engine.learning=None;engine._desktop_speak=False;engine.speaker=Mock()
        tree='UI Tree:\ndesktop\n├── window "YouTube"\n│   ├── (100,120) button "Chia sẻ" [action: click]\n│   └── (200,120) button "Đăng ký" [action: click]'
        def call(name,args,cancelled):
            result=tree if name=='Snapshot' else json.dumps({'finished':True}) if name=='Finish' else 'clicked'
            return json.dumps({'is_error':False,'result':result},ensure_ascii=False)
        backend=Mock(cfg={});backend.call.side_effect=call;engine.gemini_chat.computer=backend
        def stream(question,cancelled):
            engine.gemini_chat.computer.call('Click',{'loc':[200,120]},cancelled)
            engine.gemini_chat.computer.call('Click',{'loc':[100,120]},cancelled)
            engine.gemini_chat.computer.call('Finish',{'evidence':'invalid escaped label'},cancelled)
            yield 'Đã nhấn Chia sẻ.'
        engine.gemini_chat.stream=stream
        with patch('pet.controller.window_point_is_usable',return_value=True), patch('pet.controller.prepare_screen_action',return_value=(True,'')), patch('pet.window_actions.Windows',return_value=self.fixture_windows()), patch('pet.controller.read_screen',return_value=(ScreenObservation('Cửa sổ: YouTube\nbutton: Chia sẻ',123,99,'fixture.exe'),None)):
            answer=engine._answer('Nhấn vào Chia sẻ trên YouTube cho tôi',Utterance(np.zeros(10),time.monotonic()),0)
        clicks=[call.args[1] for call in backend.call.call_args_list if call.args[0]=='Click']
        self.assertEqual(clicks,[{'loc':[100,120]}])
        self.assertEqual(answer,'Đã nhấn Chia sẻ.')
        finish=[call.args[1] for call in backend.call.call_args_list if call.args[0]=='Finish']
        self.assertEqual(finish,[{'evidence':'Chia sẻ'}])

    def test_named_click_allows_navigation_in_same_window(self):
        with patch('pet.llm.httpx.Client'): engine=Controller(load_config())
        self.addCleanup(engine.gemini_chat._client.close);self.addCleanup(engine.local_chat._client.close)
        engine.learning=None;engine._desktop_speak=False;engine.speaker=Mock()
        old='UI Tree:\ndesktop\n├── window "Trang cũ"\n│   └── (100,120) button "Ví dụ" [action: click]'
        new='UI Tree:\ndesktop\n├── window "Trang mới"\n│   └── (200,120) button "Tiếp tục" [action: click]'
        state={'snapshots':0}
        def call(name,args,cancelled):
            if name=='Snapshot':
                state['snapshots']+=1; result=old if state['snapshots']==1 else new
            else:result=json.dumps({'finished':True}) if name=='Finish' else 'clicked'
            return json.dumps({'is_error':False,'result':result},ensure_ascii=False)
        backend=Mock(cfg={});backend.call.side_effect=call;engine.gemini_chat.computer=backend
        def stream(question,cancelled):
            engine.gemini_chat.computer.call('Click',{'loc':[100,120]},cancelled)
            snapshot=json.loads(engine.gemini_chat.computer.call('Snapshot',{},cancelled))
            self.assertFalse(snapshot['is_error'])
            engine.gemini_chat.computer.call('Finish',{'evidence':'Tiếp tục'},cancelled)
            yield 'Đã nhấn Ví dụ.'
        engine.gemini_chat.stream=stream
        with patch('pet.controller.window_caption',return_value='Trang mới'), patch('pet.controller.window_point_is_usable',return_value=True), patch('pet.controller.prepare_screen_action',return_value=(True,'')), patch('pet.window_actions.Windows',return_value=self.fixture_windows()), patch('pet.controller.read_screen',return_value=(ScreenObservation('Cửa sổ: Trang cũ\nbutton: Ví dụ',123,99,'fixture.exe'),None)):
            answer=engine._answer('Nhấn vào Ví dụ cho tôi',Utterance(np.zeros(10),time.monotonic()),0)
        self.assertEqual(answer,'Đã nhấn Ví dụ.')

    def test_premium_uses_agent_first_when_target_visible(self):
        with patch('pet.llm.httpx.Client'): engine=Controller(load_config())
        self.addCleanup(engine.gemini_chat._client.close);self.addCleanup(engine.local_chat._client.close)
        engine.learning=None;engine._desktop_speak=False;engine.speaker=Mock()
        tree='UI Tree:\ndesktop\n├── window "YouTube"\n│   └── (100,120) link "YouTube Premium" [action: click]'
        def call(name,args,cancelled):
            result=tree if name=='Snapshot' else json.dumps({'finished':True}) if name=='Finish' else 'clicked'
            return json.dumps({'is_error':False,'result':result},ensure_ascii=False)
        backend=Mock(cfg={});backend.call.side_effect=call;engine.gemini_chat.computer=backend
        def stream(question,cancelled):
            engine.gemini_chat.computer.call('Click',{'loc':[100,120]},cancelled)
            engine.gemini_chat.computer.call('Snapshot',{},cancelled)
            engine.gemini_chat.computer.call('Finish',{'evidence':'YouTube Premium'},cancelled)
            yield 'Đã nhấn YouTube Premium.'
        engine.gemini_chat.stream=stream
        with patch('pet.controller.open_web') as open_site, patch('pet.controller.window_point_is_usable',return_value=True), patch('pet.controller.prepare_screen_action',return_value=(True,'')), patch('pet.window_actions.Windows',return_value=self.fixture_windows()), patch('pet.controller.read_screen',return_value=(ScreenObservation('Cửa sổ: YouTube\nlink: YouTube Premium',123,99,'fixture.exe'),None)):
            answer=engine._answer('Mày nhấn vào Greenium trên YouTube cho tao.',Utterance(np.zeros(10),time.monotonic()),0)
        self.assertEqual(answer,'Đã nhấn YouTube Premium.')
        open_site.assert_not_called()
        self.assertEqual([call.args[1] for call in backend.call.call_args_list if call.args[0]=='Click'],[{'loc':[100,120]}])

    def test_premium_falls_back_to_known_page_if_not_visible(self):
        with patch('pet.llm.httpx.Client'): engine=Controller(load_config())
        self.addCleanup(engine.gemini_chat._client.close);self.addCleanup(engine.local_chat._client.close)
        engine.learning=None;engine._desktop_speak=False;engine.speaker=Mock()
        tree='UI Tree:\ndesktop\n├── window "YouTube"\n│   └── (100,120) button "Khác" [action: click]'
        backend=Mock(cfg={});backend.call.return_value=json.dumps({'is_error':False,'result':tree},ensure_ascii=False);engine.gemini_chat.computer=backend
        result=Mock(message='Đã gửi YouTube Premium đến trình duyệt.',verified=True)
        with patch('pet.controller.open_web',return_value=result) as open_site, patch('pet.controller.prepare_screen_action',return_value=(True,'')), patch('pet.window_actions.Windows',return_value=self.fixture_windows()), patch('pet.controller.read_screen',return_value=(ScreenObservation('Cửa sổ: YouTube\nbutton: Khác',123,99,'fixture.exe'),None)), patch('pet.controller.phrase_action_result',side_effect=lambda cfg,q,msg,c:msg):
            answer=engine._answer('Mày nhấn vào Greenium trên YouTube cho tao.',Utterance(np.zeros(10),time.monotonic()),0)
        open_site.assert_called_once_with('https://www.youtube.com/premium','YouTube Premium')
        self.assertIn('YouTube Premium',answer)
        self.assertFalse(any(call.args[0]=='Click' for call in backend.call.call_args_list))

    def test_questions_only_no_action(self):
        for value in ('Màn hình đang hiển thị gì?', 'Đọc giúp thông báo này', 'Cửa sổ đang báo lỗi gì?'):
            self.assertTrue(is_screen_question(value),value)
        for value in ('Bấm nút trên màn hình', 'Mở ứng dụng này', 'Thời tiết hôm nay thế nào?'):
            self.assertFalse(is_screen_question(value),value)
    def test_action_intent_is_distinct(self):
        self.assertTrue(is_screen_action('Bấm nút tìm kiếm trên màn hình'))
        self.assertTrue(is_screen_action('Bấm vào ô nhập tìm kiếm cho tôi'))
        self.assertTrue(is_screen_element_action('Bấm vào ô nhập tìm kiếm cho tôi'))
        self.assertTrue(is_screen_action('Chọn video thứ hai'))
        self.assertFalse(is_screen_action('Màn hình đang hiển thị gì?'))

    def test_type_into_named_text_field_without_screen_suffix(self):
        for text in ('Nhập chữ xin chào vào ô văn bản cho tao',
                     'Gõ chữ xin chào vào khung soạn thảo',
                     'Điền chữ ví dụ vào ô nhập liệu'):
            with self.subTest(text=text):
                self.assertTrue(is_screen_action(text))
                self.assertTrue(is_screen_element_action(text))
                tools = screen_tools([{'function': {'name': name}} for name in
                                      ('Snapshot', 'Click', 'Type', 'Finish', 'Cancel')], text)
                self.assertIn('Type', {item['function']['name'] for item in tools})
        for text in ('Mở file văn bản', 'Mở thư mục văn bản',
                     'Đừng nhập chữ xin chào vào ô văn bản'):
            with self.subTest(text=text):
                self.assertFalse(is_screen_action(text))
                self.assertFalse(is_screen_element_action(text))

    def test_type_text_field_routes_to_screen_agent(self):
        question = 'Nhập chữ xin chào vào ô văn bản cho tao'
        observation = ScreenObservation('Cửa sổ: Ví dụ\nedit: Văn bản',123,99,'fixture.exe')
        with patch('pet.llm.httpx.Client'):
            engine=Controller(load_config())
            engine.learning=None;engine._desktop_speak=False;engine.speaker=Mock()
            engine.gemini_chat.computer=Mock(cfg={})
            engine.gemini_chat.computer.call.return_value=self.snapshot_result()
            engine.gemini_chat.stream=Mock(return_value=iter(['Đã làm xong.']))
            with patch('pet.controller.read_screen',return_value=(observation,None)) as observe, \
                 patch('pet.controller.prepare_screen_action',return_value=(True,'')) as plan, \
                 patch('pet.window_actions.Windows',return_value=self.fixture_windows()), \
                 patch('pet.controller.open_registered_app',side_effect=AssertionError('Unexpected app')), \
                 patch('pet.controller.open_web',side_effect=AssertionError('Unexpected web')):
                answer=engine._answer(question,Utterance(np.zeros(10),time.monotonic()),0)
            observe.assert_called_once();plan.assert_called_once()
            self.assertIn('chưa xác nhận',answer)
            engine.gemini_chat._client.close();engine.local_chat._client.close()

    def test_agent_verified_simple_type_finishes_with_fresh_snapshot(self):
        question='Nhập chữ xin chào vào ô văn bản cho tao'
        observation=ScreenObservation('Cửa sổ: Ví dụ\nedit: Ô nhập',123,99,'fixture.exe')
        tree='UI Tree:\ndesktop\n├── window "Ví dụ"\n│   └── (100,120) edit "Ô nhập" [action: fill]'
        backend=Mock(cfg={})
        def call(name,args,cancelled):
            value = (tree if name=='Snapshot' else
                     json.dumps({'finished':True}) if name=='Finish' else
                     json.dumps({'delivery':'delivered_verified','element_value_verified':True}))
            return json.dumps({'is_error':False,'result':value},ensure_ascii=False)
        backend.call.side_effect=call
        with patch('pet.llm.httpx.Client'):
            engine=Controller(load_config());engine.learning=None;engine._desktop_speak=False;engine.speaker=Mock()
            engine.gemini_chat.computer=backend
            def stream(*_args,**_kwargs):
                engine.gemini_chat.computer.call('Type',{'loc':[100,120],'text':'xin chào'},engine.cancelled)
                yield 'Đã nhập rồi.'
            engine.gemini_chat.stream=stream
            with patch('pet.controller.window_point_is_usable',return_value=True), \
                 patch('pet.controller.prepare_screen_action',return_value=(True,'')), \
                 patch('pet.window_actions.Windows',return_value=self.fixture_windows()), \
                 patch('pet.controller.read_screen',return_value=(observation,None)):
                answer=engine._answer(question,Utterance(np.zeros(10),time.monotonic()),0)
            self.assertNotIn('chưa xác nhận',answer)
            self.assertEqual(sum(c.args[0]=='Type' for c in backend.call.call_args_list),1)
            self.assertEqual(sum(c.args[0]=='Finish' for c in backend.call.call_args_list),1)
            engine.gemini_chat._client.close();engine.local_chat._client.close()

    def test_explicit_screen_elements_are_not_file_or_app_names(self):
        for text in ('Mở nút cài đặt trên màn hình', 'Mở video thứ hai trên màn hình',
                     'Mở cái này', 'Bấm mục cài đặt', 'Nhấn nút này'):
            with self.subTest(text=text):self.assertTrue(is_screen_element_action(text))
        for text in ('Mở thư mục HỌC TẬP', 'Mở YouTube', 'Mở ứng dụng Zalo trên màn hình'):
            with self.subTest(text=text):self.assertFalse(is_screen_element_action(text))

    def test_open_screen_element_does_not_fall_through_to_app_or_music(self):
        observation=ScreenObservation('Cửa sổ: Ví dụ\nbutton: Cài đặt',123,99,'fixture.exe')
        for text in ('Mở nút cài đặt trên màn hình', 'Mở video thứ hai trên màn hình', 'Mở cái này'):
            with self.subTest(text=text), patch('pet.llm.httpx.Client'):
                engine=Controller(load_config())
                engine.learning=None;engine._desktop_speak=False;engine.speaker=Mock()
                engine.gemini_chat.computer=Mock(cfg={})
                engine.gemini_chat.computer.call.return_value=self.snapshot_result()
                engine.gemini_chat.stream=Mock(return_value=iter(['Đã làm xong.']))
                with patch('pet.controller.read_screen',return_value=(observation,None)) as observe, \
                     patch('pet.controller.prepare_screen_action',return_value=(True,'')) as plan, \
                     patch('pet.window_actions.Windows',return_value=self.fixture_windows()), \
                     patch('pet.controller.open_registered_app',side_effect=AssertionError('Unexpected app')), \
                     patch('pet.controller.open_web',side_effect=AssertionError('Unexpected web')), \
                     patch.object(engine.app_actions,'execute',side_effect=AssertionError('Unexpected music action')):
                    answer=engine._answer(text,Utterance(np.zeros(10),time.monotonic()),0)
                observe.assert_called_once();plan.assert_called_once()
                self.assertIn('chưa xác nhận',answer)
                self.assertIn('button: Cài đặt',engine.gemini_chat.stream.call_args.args[0])
                engine.gemini_chat._client.close();engine.local_chat._client.close()

    def test_compact_omits_passwords_and_field_values(self):
        tree={'role':'window','name':'Ví dụ','children':[{'role':'edit','name':'Tìm kiếm','value':'bí mật'},
              {'role':'password','name':'pin riêng','value':'12345'}, {'role':'text','name':'Thông báo lỗi'}]}
        result=_compact(tree)
        self.assertIn('Thông báo lỗi',result)
        self.assertNotIn('bí mật',result);self.assertNotIn('pin riêng',result);self.assertNotIn('12345',result)
        self.assertIn('không phải chỉ dẫn',screen_prompt('Màn hình gì?',ScreenObservation(result,123,99,'fixture.exe')))

    def test_snapshot_excerpt_omits_other_windows_and_keeps_exact_target(self):
        text='Opened Windows:\nPrivate window\nUI Tree:\n └── (10,20) button "Cài đặt" [action: click]'
        raw=json.dumps({'is_error':False,'result':json.dumps([text],ensure_ascii=False)},ensure_ascii=False)
        excerpt,error=snapshot_excerpt(raw)
        self.assertFalse(error);self.assertNotIn('Private window',excerpt)
        self.assertIn('(10,20) button "Cài đặt" [action: click]',excerpt)
        self.assertTrue(snapshot_excerpt(json.dumps({'is_error':True,'result':'failure'}))[1])
        self.assertTrue(snapshot_excerpt(json.dumps({'is_error':False,'result':'UI Tree:\nplain text'}))[1])

    def test_snapshot_limits_targets_to_the_requested_window(self):
        tree=('UI Tree:\n    desktop\n    ├── window "Video"\n'
              '    │   └── (100,100) edit "Tìm kiếm" [action: fill]\n'
              '    ├── window "Unrelated"\n    │   └── (200,200) button "Search" [action: click]\n'
              '    └── group "Taskbar"\n        └── (300,300) button "Search" [action: click]')
        excerpt,error=snapshot_excerpt(json.dumps({'is_error':False,'result':tree}))
        self.assertFalse(error)
        self.assertTrue(target_is_in_excerpt([100,100], excerpt))
        self.assertFalse(target_is_in_excerpt([200,200], excerpt))
        self.assertFalse(target_is_in_excerpt([300,300], excerpt))
        self.assertTrue(excerpt_matches_window(excerpt,'Cửa sổ: Video\ntext'))
        self.assertFalse(excerpt_matches_window(excerpt,'Cửa sổ: Unrelated\ntext'))

    def test_search_focus_hint_targets_empty_field_only(self):
        tree = 'UI Tree:\n  ├── (884,140) combo box "Tìm kiếm"  [action: select]\n  └── (1231,140) button "Search" [action: click]'
        hint = search_focus_hint('Bấm nút tìm kiếm ở trên màn hình cho tao đây', tree)
        self.assertIn('(884,140)', hint)
        self.assertEqual(search_focus_target(hint), ([884,140], 'Tìm kiếm'))
        self.assertTrue(is_search_focus_request('Bấm nút tìm kiếm trên màn hình'))
        self.assertTrue(is_search_focus_request('Bấm vào ô nhập tìm kiếm cho tôi'))
        self.assertNotIn('(1231,140)', hint)
        self.assertFalse(search_focus_hint('Bấm nút tìm kiếm bằng giọng nói',tree))
        self.assertFalse(search_focus_hint('Bấm nút tìm kiếm trên màn hình', tree.replace('[action: select]', '[action: select] [value:"abc"]')))
        self.assertFalse(search_focus_hint('Bấm nút Cài đặt trên màn hình',tree))
        self.assertFalse(search_focus_hint('Bấm nút tìm kiếm trên màn hình',tree.replace('combo box', 'button')))

    def test_focus_verification_uses_only_expected_control_metadata(self):
        import sys
        from contextlib import nullcontext
        mock_control = Mock(HasKeyboardFocus=True, ProcessId=42, ControlTypeName='ComboBoxControl', Name='Tìm kiếm')
        automation=Mock(UIAutomationInitializerInThread=Mock(return_value=nullcontext()), GetFocusedControl=Mock(return_value=mock_control))
        with patch.dict(sys.modules, {'uiautomation':automation}):
            self.assertTrue(focused_search_is_verified(42,'Tìm kiếm'))
            self.assertFalse(focused_search_is_verified(43,'Tìm kiếm'))
            self.assertFalse(focused_search_is_verified(42,'Search'))
            mock_control.HasKeyboardFocus=False
            self.assertFalse(focused_search_is_verified(42,'Tìm kiếm'))

    def test_screen_tool_scope_excludes_shell_and_unsupported_labels(self):
        all_tools=[{'function':{'name':n}} for n in ('Snapshot','Click','Type','Finish','Cancel','PowerShell','FileSystem','App')]
        tools=screen_tools(all_tools,'Bấm nút này')
        names={item['function']['name'] for item in tools}
        self.assertEqual(names,{'Snapshot','Click','Finish','Cancel'})
        click=next(item['function'] for item in tools if item['function']['name']=='Click')
        self.assertEqual(click['parameters']['required'],['loc'])
        self.assertNotIn('label',click['parameters']['properties'])
        self.assertIn('Type',{item['function']['name'] for item in screen_tools(all_tools,'Nhập chữ vào mục này')})
        self.assertNotIn('Type',{item['function']['name'] for item in screen_tools(all_tools,'Nhấp nút này')})
        self.assertTrue(validate_screen_tool('PowerShell',{},'Bấm nút này'))
        self.assertTrue(validate_screen_tool('Type',{'text':'bí mật','loc':[1,2]},'Nhập chữ hello vào mục này'))
        self.assertFalse(validate_screen_tool('Type',{'text':'hello','loc':[1,2]},'Nhập chữ hello vào mục này'))
        self.assertTrue(validate_screen_tool('Click',{'loc':[1,2],'clicks':2},'Bấm nút này'))
    def test_search_focus_uses_one_guarded_click_and_verifies_focus(self):
        with patch('pet.llm.httpx.Client'): engine=Controller(load_config())
        self.addCleanup(engine.gemini_chat._client.close);self.addCleanup(engine.local_chat._client.close)
        engine.learning=None;engine._desktop_speak=False;engine.speaker=Mock()
        tree='UI Tree:\ndesktop\n├── window "Ví dụ"\n│   ├── (100,120) edit "Tìm kiếm" [action: fill]\n│   └── (200,120) button "Khác" [action: click]'
        def call(name,args,cancelled):
            result=tree if name=='Snapshot' else json.dumps({'finished':True}) if name=='Finish' else 'clicked'
            return json.dumps({'is_error':False,'result':result},ensure_ascii=False)
        backend=Mock(cfg={});backend.call.side_effect=call;engine.gemini_chat.computer=backend
        engine.gemini_chat.stream=Mock(side_effect=AssertionError('Do not ask model to click again'))
        with patch('pet.controller.window_point_is_usable',return_value=True), patch('pet.controller.prepare_screen_action',return_value=(True,'')), patch('pet.controller.focused_search_is_verified',return_value=True), patch('pet.window_actions.Windows',return_value=self.fixture_windows()), patch('pet.controller.read_screen',return_value=(ScreenObservation('Cửa sổ: Ví dụ\nedit: Tìm kiếm',123,99,'fixture.exe'),None)), patch('pet.controller.phrase_action_result',side_effect=lambda cfg,q,msg,c:msg):
            answer=engine._answer('Bấm vào ô nhập tìm kiếm cho tôi',Utterance(np.zeros(10),time.monotonic()),0)
        clicks=[call.args[1] for call in backend.call.call_args_list if call.args[0]=='Click']
        self.assertEqual(clicks,[{'loc':[100,120]}])
        self.assertIn('đã chọn ô tìm kiếm',answer.lower())

    def test_search_focus_failure_never_clicks_twice_or_claims_success(self):
        with patch('pet.llm.httpx.Client'): engine=Controller(load_config())
        self.addCleanup(engine.gemini_chat._client.close);self.addCleanup(engine.local_chat._client.close)
        engine.learning=None;engine._desktop_speak=False;engine.speaker=Mock()
        tree='UI Tree:\ndesktop\n├── window "Ví dụ"\n│   └── (100,120) edit "Tìm kiếm" [action: fill]'
        backend=Mock(cfg={});backend.call.side_effect=lambda name,args,cancelled: json.dumps({'is_error':False,'result':tree if name=='Snapshot' else 'clicked'},ensure_ascii=False)
        engine.gemini_chat.computer=backend
        with patch('pet.controller.window_point_is_usable',return_value=True), patch('pet.controller.prepare_screen_action',return_value=(True,'')), patch('pet.controller.focused_search_is_verified',return_value=False), patch('pet.window_actions.Windows',return_value=self.fixture_windows()), patch('pet.controller.read_screen',return_value=(ScreenObservation('Cửa sổ: Ví dụ\nedit: Tìm kiếm',123,99,'fixture.exe'),None)), patch('pet.controller.phrase_action_result',side_effect=lambda cfg,q,msg,c:msg):
            answer=engine._answer('Bấm nút tìm kiếm trên màn hình',Utterance(np.zeros(10),time.monotonic()),0)
        self.assertEqual(sum(call.args[0]=='Click' for call in backend.call.call_args_list),1)
        self.assertIn('chưa xác nhận',answer.lower())
        self.assertFalse(any(call.args[0]=='Finish' for call in backend.call.call_args_list))

    def test_plan_denial_never_focuses_or_clicks(self):
        import json
        backend=Mock(); backend.call.return_value=json.dumps({'is_error':True,'result':json.dumps({'approved':False})})
        observation=ScreenObservation('fixture',123,99,r'C:\example\chrome.exe')
        with patch('pet.window_actions.Windows') as win, patch('pet.apps.focus_window') as focus:
            ok,_=prepare_screen_action(observation,'Bấm nút này',backend,threading.Event())
        self.assertFalse(ok);win.assert_not_called();focus.assert_not_called()
        self.assertEqual(backend.call.call_args.args[0],'Plan')

    def test_changed_window_cancels_approved_plan(self):
        import json
        backend=Mock(); backend.call.side_effect=[json.dumps({'is_error':False,'result':json.dumps({'approved':True})}),'{}']
        observation=ScreenObservation('fixture',123,99,r'C:\example\chrome.exe')
        api=Mock();api.identity.return_value=(123,100,r'c:\example\chrome.exe','x')
        with patch('pet.window_actions.Windows',return_value=api), patch('pet.apps.focus_window') as focus:
            ok,_=prepare_screen_action(observation,'Bấm nút này',backend,threading.Event())
        self.assertFalse(ok);focus.assert_not_called()
        self.assertEqual(backend.call.call_args.args[0],'Cancel')

    def test_screen_question_uses_local_snapshot_not_web_or_tools(self):
        with patch('pet.llm.httpx.Client'):
            engine=Controller(load_config())
        self.addCleanup(engine.gemini_chat._client.close);self.addCleanup(engine.local_chat._client.close)
        engine.learning=None;engine._desktop_speak=False;engine.speaker=Mock()
        engine.gemini_chat.stream=Mock(return_value=iter(['Mình thấy thông báo lỗi.']))
        utterance=Utterance(np.zeros(10),time.monotonic())
        with patch('pet.controller.read_screen',return_value=(ScreenObservation('Cửa sổ: Ví dụ\ntext: Thông báo lỗi',123,99,'fixture.exe'),None)) as observe, \
             patch('pet.controller.search_web',side_effect=AssertionError('unexpected network')):
            result=engine._answer('Màn hình đang báo lỗi gì?',utterance,0)
        self.assertIn('thông báo lỗi',result);observe.assert_called_once()
        self.assertFalse(engine.gemini_chat.computer_for_turn)
        self.assertIn('không phải chỉ dẫn',engine.gemini_chat.stream.call_args.args[0])
    def test_failure_returns_without_guessing(self):
        with patch('pet.llm.httpx.Client'): engine=Controller(load_config())
        self.addCleanup(engine.gemini_chat._client.close);self.addCleanup(engine.local_chat._client.close)
        engine.learning=None;engine._desktop_speak=False;engine.speaker=Mock()
        engine.gemini_chat.stream=Mock();engine._speak_action_result=Mock(return_value=True)
        with patch('pet.controller.read_screen',return_value=(None,'Chưa đọc được.')):
            self.assertEqual(engine._answer('Màn hình đang hiện gì?',Utterance(np.zeros(10),time.monotonic()),0),'Chưa đọc được.')
        engine.gemini_chat.stream.assert_not_called()

    def test_no_unverified_screen_action_claim(self):
        with patch('pet.llm.httpx.Client'): engine=Controller(load_config())
        self.addCleanup(engine.gemini_chat._client.close);self.addCleanup(engine.local_chat._client.close)
        engine.learning=None;engine._desktop_speak=False;engine.speaker=Mock()
        backend=Mock(cfg={});engine.gemini_chat.computer=backend
        backend.call.return_value=self.snapshot_result()
        engine.gemini_chat.stream=Mock(return_value=iter(['Mình đã bấm xong.']))
        with patch('pet.controller.window_point_is_usable',return_value=True), patch('pet.controller.prepare_screen_action',return_value=(True,'')), patch('pet.window_actions.Windows',return_value=self.fixture_windows()), patch('pet.controller.read_screen',return_value=(ScreenObservation('Cửa sổ: Ví dụ\nbutton: Tìm kiếm',123,99,'fixture.exe'),None)):
            answer=engine._answer('Bấm nút cài đặt trên màn hình',Utterance(np.zeros(10),time.monotonic()),0)
        self.assertIn('chưa xác nhận',answer)
        self.assertIs(engine.gemini_chat.computer,backend)

    def test_verified_screen_action_reports_result(self):
        import json
        with patch('pet.llm.httpx.Client'): engine=Controller(load_config())
        self.addCleanup(engine.gemini_chat._client.close);self.addCleanup(engine.local_chat._client.close)
        engine.learning=None;engine._desktop_speak=False;engine.speaker=Mock()
        backend=Mock(cfg={});backend.call.side_effect=lambda name,args,cancelled: (self.snapshot_result() if name=='Snapshot' else json.dumps({'is_error':False,'result':json.dumps({'finished':True}) if name=='Finish' else '{}'}))
        engine.gemini_chat.computer=backend
        def stream(question,cancelled):
            engine.gemini_chat.computer.call('Click',{'loc':[100,120]},cancelled)
            engine.gemini_chat.computer.call('Finish',{},cancelled)
            yield 'Mình đã bấm nút.'
        engine.gemini_chat.stream=stream
        with patch('pet.controller.window_point_is_usable',return_value=True), patch('pet.controller.prepare_screen_action',return_value=(True,'')), patch('pet.window_actions.Windows',return_value=self.fixture_windows()), patch('pet.controller.read_screen',return_value=(ScreenObservation('Cửa sổ: Ví dụ\nbutton: Tìm kiếm',123,99,'fixture.exe'),None)):
            answer=engine._answer('Bấm nút cài đặt trên màn hình',Utterance(np.zeros(10),time.monotonic()),0)
        self.assertEqual(answer,'Mình đã bấm nút.')
        self.assertIs(engine.gemini_chat.computer,backend)

if __name__=='__main__': unittest.main()
