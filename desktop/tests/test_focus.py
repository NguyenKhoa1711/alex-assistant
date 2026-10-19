import itertools
import threading
import unittest
from unittest.mock import MagicMock, patch
from pet.apps import focus_window, matches_app_window, open_registered_app, _app_window_processes


class FocusTests(unittest.TestCase):
    def test_uwp_frame_uses_actual_child_process_not_just_title(self):
        u=MagicMock();k=MagicMock()
        u.GetWindowThreadProcessId.side_effect=lambda h,p:setattr(p._obj,'value',h)
        k.OpenProcess.side_effect=lambda flags,inherit,pid:pid
        def process_name(handle,flags,buf,size):
            buf.value={10:r'C:\Windows\ApplicationFrameHost.exe',20:r'C:\Apps\CalculatorApp.exe'}[handle]
            return True
        k.QueryFullProcessImageNameW.side_effect=process_name
        u.GetClassNameW.side_effect=lambda h,buf,size:setattr(buf,'value','Windows.UI.Core.CoreWindow')
        u.EnumChildWindows.side_effect=lambda h,cb,arg:cb(20,arg)
        names=_app_window_processes(10,'ApplicationFrameWindow',u,k)
        self.assertEqual(names,{'applicationframehost.exe','calculatorapp.exe'})
        self.assertTrue(any(matches_app_window({'processes':['calculatorapp.exe']},'Calculator',p,'ApplicationFrameWindow') for p in names))
        self.assertFalse(any(matches_app_window({'processes':['zalo.exe']},'Calculator',p,'ApplicationFrameWindow') for p in names))
        self.assertEqual(k.CloseHandle.call_count,2)

    def user32(self):
        u=MagicMock()
        u.IsWindow.return_value=True
        u.IsWindowVisible.return_value=True
        u.IsIconic.return_value=False
        u.GetForegroundWindow.return_value=10
        u.GetWindowThreadProcessId.side_effect=lambda h,p: {10:2,20:3}.get(h,0)
        return u

    def test_ime_windows_never_count_as_app(self):
        entry={'processes':['calculatorapp.exe']}
        for cls in ('IME','MSCTFIME UI','tooltips_class32'):
            self.assertFalse(matches_app_window(entry,'Default IME','calculatorapp.exe',cls))
        self.assertTrue(matches_app_window(entry,'Calculator','calculatorapp.exe','Windows.UI.Core.CoreWindow'))

    def test_hidden_surface_never_restored(self):
        u=self.user32(); u.IsWindowVisible.return_value=False
        with patch('pet.apps.ctypes.WinDLL',return_value=u):
            self.assertFalse(focus_window(20))
        u.ShowWindowAsync.assert_not_called()
        u.SetForegroundWindow.assert_not_called()

    def test_cloaked_surface_never_activated(self):
        u=self.user32()
        with patch('pet.apps.ctypes.WinDLL',return_value=u), patch('pet.apps._window_cloaked',return_value=True):
            self.assertFalse(focus_window(20))
        u.SetForegroundWindow.assert_not_called()

    def test_verified_activation_preserves_maximized_window(self):
        u=self.user32()
        u.SetForegroundWindow.side_effect=lambda h:setattr(u.GetForegroundWindow,'return_value',h)
        with patch('pet.apps.ctypes.WinDLL',return_value=u), patch('pet.apps._window_cloaked',return_value=False):
            self.assertTrue(focus_window(20))
        u.ShowWindowAsync.assert_not_called()

    def test_failed_focus_is_not_reported_as_success_and_detaches(self):
        u=self.user32(); k=MagicMock();k.GetCurrentThreadId.return_value=1
        ticks=itertools.count(0,.2)
        with patch('pet.apps.ctypes.WinDLL',side_effect=lambda name,**kw:u if name=='user32' else k), \
             patch('pet.apps._window_cloaked',return_value=False), \
             patch('pet.apps.time.monotonic',side_effect=lambda:next(ticks)),patch('pet.apps.time.sleep'):
            self.assertFalse(focus_window(20))
        self.assertEqual(u.AttachThreadInput.call_args_list[-2].args,(1,3,False))
        self.assertEqual(u.AttachThreadInput.call_args_list[-1].args,(1,2,False))

    def test_attachment_detaches_even_on_exception(self):
        u=self.user32();k=MagicMock();k.GetCurrentThreadId.return_value=1
        u.SetForegroundWindow.side_effect=[False,RuntimeError('activation failed')]
        with patch('pet.apps.ctypes.WinDLL',side_effect=lambda name,**kw:u if name=='user32' else k), \
             patch('pet.apps._window_cloaked',return_value=False):
            with self.assertRaises(RuntimeError):focus_window(20)
        self.assertEqual(sum(c.args[-1] is False for c in u.AttachThreadInput.call_args_list),2)

    def launch_mocks(self, focus):
        u=self.user32()
        event=MagicMock();event.is_set.return_value=False;event.wait.return_value=False
        ticks=itertools.count(0,.2)
        entry={'name':'Calculator','app_id':'Microsoft.WindowsCalculator_8wekyb3d8bbwe!App'}
        with patch('pet.apps.os.startfile') as start,patch('pet.apps.ctypes.WinDLL',return_value=u), \
             patch('pet.apps.app_windows',return_value=[20]),patch('pet.apps.focus_window',side_effect=focus) as activated, \
             patch('pet.apps.time.monotonic',side_effect=lambda:next(ticks)):
            result=open_registered_app(entry,event)
        return result,start.call_count,activated.call_count

    def test_new_window_gets_bounded_focus_retry(self):
        result,launches,attempts=self.launch_mocks([False,True])
        self.assertTrue(result.verified and result.foreground)
        self.assertEqual(launches,1);self.assertEqual(attempts,2)

    def test_windows_focus_denial_stays_honest(self):
        result,launches,attempts=self.launch_mocks(lambda h:False)
        self.assertTrue(result.verified);self.assertFalse(result.foreground)
        self.assertEqual(launches,1);self.assertLess(attempts,10)


if __name__=='__main__':unittest.main(verbosity=2)
