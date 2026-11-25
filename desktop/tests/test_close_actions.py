import threading,time,unittest
from types import SimpleNamespace as NS
from unittest.mock import MagicMock,patch
import numpy as np
from pet.app_actions import Action,ActionResult,parse_action
from pet.controller import Controller
from pet.config import load_config
from pet.audio import Utterance
from pet.tab_actions import close_browser_tab,chrome_tabs,prepare_tab_close
from pet.window_actions import close_app_window


class ParsingTests(unittest.TestCase):
    def test_explicit_commands(self):
        for text,expected in {
            'Đóng tab':Action('Tabs','close_current'),
            'Tắt tab này đi':Action('Tabs','close_current'),
            'Hãy đóng tab hiện tại trên Chrome cho tôi':Action('Tabs','close_current','chrome'),
            'Đóng tab Edge':Action('Tabs','close_current','edge'),
            'Đóng ứng dụng này':Action('Window','close_current'),
            'Close Zalo':Action('Window','close_current','Zalo'),
            'Bạn hãy đóng cái tab này đi':Action('Tabs','close_current'),
            'Đóng táp hiện tại':Action('Tabs','close_current'),
            'Tắt ứng dụng hiện tại cho tôi':Action('Window','close_current'),
            'Đóng cửa sổ đang mở':Action('Window','close_current'),
            'Đóng phần mềm hiện tại':Action('Window','close_current'),
            'Thoát phần mềm hiện tại':Action('Window','close_current'),
            'Alex đóng app này':Action('Window','close_current'),
        }.items():
            self.assertEqual(parse_action(text),expected,text)

    def test_negations_compounds_and_other_intents(self):
        for text in ['Đừng đóng tab','Không đóng Zalo','Đóng tất cả tab','Đóng hết phần mềm',
                     'Đóng tab rồi mở Zalo','Đóng Zalo và Chrome','Đóng file bài tập',
                     'Cách đóng tab','Tôi đang đóng tab','Tắt máy','Tắt nguồn','Đóng tab Bionic']:
            self.assertIsNone(parse_action(text),text)
        self.assertEqual(parse_action('Tắt nhạc'),Action('Spotify','pause', auto_media=True))


class BrowserTests(unittest.TestCase):
    def tab(self,ident,selected):
        tab=MagicMock();tab.GetRuntimeId.return_value=[ident]
        tab.GetSelectionItemPattern.return_value.IsSelected=selected
        button=MagicMock();button.ControlTypeName='ButtonControl';button.Name='Close'
        button.IsOffscreen=False;button.IsEnabled=True
        tab.GetChildren.return_value=[button]
        return tab,button

    def run_close(self, sets, focus_change=False, invoke_error=False):
        a,button=self.tab(1,True);b,_=self.tab(2,False)
        target={'app':'chrome','hwnd':3,'pid':4,'executable':'C:/Chrome/chrome.exe'}
        window=NS(hwnd=3,pid=4,executable=target['executable'])
        if invoke_error: button.GetInvokePattern.return_value.Invoke.side_effect=RuntimeError('event error')
        mapping={'two':[a,b],'one':[a],'remaining':[b],'changed':[a,b]}
        sequences=[mapping[s] for s in sets]
        if sets[-1]=='changed':
            c,_=self.tab(3,True);sequences[-1]=[b,c]
        with patch('pet.desktop_guard.current_window',side_effect=[window,window,NS(hwnd=99,pid=4,executable=window.executable)] if focus_change else None,return_value=window), \
             patch('pet.tab_actions.chrome_tabs',side_effect=sequences), \
             patch('pet.tab_actions.time.sleep'):
            result=close_browser_tab(MagicMock(),target)
        return result,button

    def test_one_selected_tab_closed_and_verified(self):
        result,button=self.run_close(['two','two','remaining'])
        self.assertTrue(result['verified'])
        button.GetInvokePattern.return_value.Invoke.assert_called_once()

    def test_last_tab_keeps_browser_open_without_invoking_close(self):
        result,button=self.run_close(['one'])
        self.assertFalse(result['verified'])
        self.assertIn('tab cuối',result['message'])
        button.GetInvokePattern.assert_not_called()
        button.GetLegacyIAccessiblePattern.assert_not_called()

    def test_tab_save_prompt_is_not_dismissed(self):
        a,button=self.tab(1,True); b,_=self.tab(2,False)
        target={'app':'chrome','hwnd':3,'pid':4,'executable':'C:/Chrome/chrome.exe'}
        window=NS(hwnd=3,pid=4,executable=target['executable'])
        with patch('pet.desktop_guard.current_window',return_value=window), \
             patch('pet.tab_actions.chrome_tabs',return_value=[a,b]), \
             patch('pet.tab_actions.time.sleep'),patch('pet.window_actions.Windows') as windows:
            windows.return_value.identity.return_value=(3,4,target['executable'].casefold(),'BrowserWindow')
            windows.return_value.visible.return_value=True
            result=close_browser_tab(MagicMock(),target)
        self.assertFalse(result['verified']);button.GetInvokePattern.return_value.Invoke.assert_called_once()

    def test_tab_count_falls_to_one_before_action_nothing_is_closed(self):
        result,button=self.run_close(['two','one'])
        self.assertFalse(result['verified'])
        button.GetInvokePattern.assert_not_called()

    def test_event_error_never_retries_click(self):
        result,button=self.run_close(['two','two','remaining'],invoke_error=True)
        self.assertTrue(result['verified']);button.GetInvokePattern.return_value.Invoke.assert_called_once()

    def test_changed_tab_is_not_closed(self):
        result,button=self.run_close(['two','changed'])
        self.assertFalse(result['verified']);button.GetInvokePattern.assert_not_called()

    def test_changed_window_is_not_closed(self):
        with self.assertRaisesRegex(RuntimeError,'đã đổi'):
            self.run_close(['two','two'],focus_change=True)

    def test_web_page_tab_widgets_are_excluded(self):
        root=MagicMock();root.ControlTypeName='WindowControl';root.IsOffscreen=False
        doc=MagicMock();doc.ControlTypeName='DocumentControl';doc.IsOffscreen=False
        root.GetChildren.return_value=[doc]
        with self.assertRaises(RuntimeError): chrome_tabs(root)
        doc.GetChildren.assert_not_called()

    def test_other_foreground_app_not_treated_as_browser(self):
        with patch('pet.desktop_guard.current_window',return_value=NS(hwnd=1,pid=2,executable='C:/Zalo.exe')):
            self.assertIsInstance(prepare_tab_close(''),ActionResult)

    def test_named_browser_can_be_resolved_behind_bionic(self):
        with patch('pet.desktop_guard.current_window',return_value=NS(hwnd=1,pid=2,executable='C:/Bionic.exe')), \
             patch('pet.apps.app_windows',return_value=[3]),patch('pet.window_actions.Windows') as windows:
            windows.return_value.identity.return_value=(3,4,'c:/chrome.exe','Chrome_WidgetWin_1')
            target=prepare_tab_close('chrome')
        self.assertEqual(target['hwnd'],3)
        self.assertFalse(target['require_foreground'])

    def test_multiple_named_browser_windows_not_guessed(self):
        with patch('pet.desktop_guard.current_window',return_value=NS(hwnd=1,pid=2,executable='C:/Bionic.exe')), \
             patch('pet.apps.app_windows',return_value=[3,5]),patch('pet.window_actions.Windows') as windows:
            windows.return_value.identity.side_effect=[(3,4,'c:/chrome.exe','Browser'),(5,4,'c:/chrome.exe','Browser')]
            self.assertIsInstance(prepare_tab_close('chrome'),ActionResult)

    def test_background_target_identity_is_checked_without_global_keys(self):
        a,button=self.tab(1,True);b,_=self.tab(2,False)
        target={'app':'chrome','hwnd':3,'pid':4,'executable':'c:/chrome.exe','require_foreground':False}
        with patch('pet.desktop_guard.current_window') as current,patch('pet.window_actions.Windows') as windows, \
             patch('pet.tab_actions.chrome_tabs',side_effect=[[a,b],[a,b],[b]]),patch('pet.tab_actions.time.sleep'):
            windows.return_value.identity.return_value=(3,4,'c:/chrome.exe','Browser')
            self.assertTrue(close_browser_tab(MagicMock(),target)['verified'])
            current.assert_not_called()
        button.GetInvokePattern.return_value.Invoke.assert_called_once()


class WindowTests(unittest.TestCase):
    def api(self):
        api=MagicMock();api.foreground.return_value=10
        api.identity.return_value=(10,12345,'C:/example.exe','AppWindow')
        api.visible.return_value=True;api.enabled.return_value=True;api.post_close.return_value=True
        return api

    def test_normal_close_only_once(self):
        api=self.api();api.visible.side_effect=[True,False]
        result=close_app_window('',{},threading.Event(),api)
        self.assertTrue(result.verified);api.post_close.assert_called_once_with(10)

    def test_unsaved_data_prompt_is_not_dismissed_or_forced(self):
        api=self.api();cancel=MagicMock();cancel.is_set.return_value=False;cancel.wait.return_value=False
        result=close_app_window('',{},cancel,api)
        self.assertFalse(result.verified);self.assertIn('lưu dữ liệu',result.message)
        api.post_close.assert_called_once()

    def test_cancelled_and_protected_windows_not_closed(self):
        for cls in ['Progman','WorkerW','Shell_TrayWnd','#32770']:
            api=self.api();api.identity.return_value=(10,12345,'C:/example.exe',cls)
            self.assertFalse(close_app_window('',{},threading.Event(),api).verified)
            api.post_close.assert_not_called()
        api=self.api();event=threading.Event();event.set()
        self.assertFalse(close_app_window('',{},event,api).verified);api.post_close.assert_not_called()

    def test_multiple_named_windows_require_selection(self):
        api=self.api()
        with patch('pet.window_actions.resolve_close_entry',return_value={'name':'Test'}), \
             patch('pet.window_actions.app_windows',return_value=[11,12]):
            result=close_app_window('Test',{},threading.Event(),api)
        self.assertFalse(result.verified);api.post_close.assert_not_called()

    def test_replaced_window_handle_not_closed(self):
        api=self.api();api.identity.side_effect=[(10,12345,'C:/example.exe','AppWindow'),None]
        self.assertFalse(close_app_window('',{},threading.Event(),api).verified)
        api.post_close.assert_not_called()


class ControllerTests(unittest.TestCase):
    def test_local_once_even_when_bionic_busy_and_privacy_off(self):
        cfg=load_config();cfg['learning']['enabled']=False;cfg['privacy']['save_transcripts']=False
        engine=Controller(cfg);engine.chat = engine.gemini_chat = MagicMock();engine.speaker=MagicMock();engine.app_actions=MagicMock()
        engine.chat.check_ready.side_effect=RuntimeError('busy')
        engine.app_actions.execute.return_value=ActionResult('Đã đóng tab.',True)
        for question in ['Đóng tab','Đóng tab']:
            with self.assertLogs(level='INFO') as logs:
                engine._answer(question,Utterance(np.zeros(100),time.monotonic()),.1)
            self.assertNotIn('"text"', '\n'.join(logs.output))
        engine.app_actions.execute.assert_called_once()
        engine.chat.check_ready.assert_not_called();engine.chat.stream.assert_not_called()


if __name__=='__main__': unittest.main()
