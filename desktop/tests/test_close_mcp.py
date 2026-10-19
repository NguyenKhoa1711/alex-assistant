import unittest
from unittest.mock import patch
from types import SimpleNamespace
from pet.app_actions import Action,ActionResult
from desktop_mcp import close_local,special_tools

class CloseMcpTests(unittest.TestCase):
    def test_narrow_tool_is_exposed(self):
        tool=next(t for t in special_tools() if t.name=='CloseLocal')
        self.assertEqual(tool.inputSchema['required'],['command'])
        self.assertFalse(tool.inputSchema['additionalProperties'])

    def test_named_tab_and_app_execute_once(self):
        for text,action in [('Đóng tab Chrome',Action('Tabs','close_current','chrome')),
                            ('Đóng Notepad',Action('Window','close_current','Notepad'))]:
            with patch('desktop_mcp.AppActions') as actions:
                actions.return_value.execute.return_value=ActionResult('Đã đóng.',True)
                self.assertTrue(close_local(text,{})['verified'])
                self.assertEqual(actions.return_value.execute.call_args.args[0],action)
                actions.return_value.execute.assert_called_once()

    def test_negation_compound_and_power_never_close(self):
        with patch('desktop_mcp.AppActions') as actions:
            for text in ['Đừng đóng tab','Không tắt ứng dụng này','Đóng tất cả tab',
                         'Đóng Chrome rồi mở Zalo','Tắt máy','Tắt nguồn','x'*301,{}]:
                with self.assertRaises(ValueError):close_local(text,{})
            actions.assert_not_called()

    def test_current_from_bionic_asks_for_target(self):
        with patch('pet.desktop_guard.current_window',return_value=SimpleNamespace(executable='C:/Bionic.exe')), \
             patch('desktop_mcp.AppActions') as actions:
            self.assertFalse(close_local('Đóng cửa sổ này',{})['verified'])
            actions.assert_not_called()

    def test_disabled_and_unverified_never_claim_success(self):
        with patch('desktop_mcp.AppActions') as actions:
            self.assertFalse(close_local('Đóng tab Chrome',{'actions':{'enabled':False}})['verified'])
            actions.assert_not_called()
            actions.return_value.execute.return_value=ActionResult('Đang hỏi lưu dữ liệu.')
            self.assertFalse(close_local('Đóng Notepad',{})['verified'])

if __name__=='__main__':unittest.main()
