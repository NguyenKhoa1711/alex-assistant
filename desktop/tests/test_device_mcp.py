import unittest
from unittest.mock import patch
from pet.app_actions import Action,ActionResult
from desktop_mcp import device_control,special_tools


class DeviceMcpTests(unittest.TestCase):
    def test_tool_available_to_bionic_with_narrow_schema(self):
        tools={t.name:t for t in special_tools()}
        self.assertIn('DeviceControl',tools)
        schema=tools['DeviceControl'].inputSchema
        self.assertEqual(schema['required'],['command'])
        self.assertFalse(schema['additionalProperties'])

    def test_original_command_routes_to_real_worker(self):
        with patch('desktop_mcp.AppActions') as actions:
            actions.return_value.execute.return_value=ActionResult('Âm lượng đang ở 40 phần trăm.',True)
            result=device_control('âm lượng 40 phần trăm',{})
            self.assertTrue(result['verified'])
            self.assertEqual(actions.return_value.execute.call_args.args[0],Action('Volume','set','40'))

    def test_number_before_target_is_understood(self):
        with patch('desktop_mcp.AppActions') as actions:
            actions.return_value.execute.return_value=ActionResult('Âm lượng đang ở 60 phần trăm.',True)
            device_control('giảm 40 phần trăm âm lượng cho tôi',{})
            self.assertEqual(actions.return_value.execute.call_args.args[0],Action('Volume','down','40'))

    def test_unverified_result_never_claims_success(self):
        with patch('desktop_mcp.AppActions') as actions:
            actions.return_value.execute.return_value=ActionResult('Chưa chỉnh được.',False)
            self.assertFalse(device_control('giảm độ sáng',{})['verified'])

    def test_invalid_negated_compound_and_nondevice_requests_do_not_execute(self):
        with patch('desktop_mcp.AppActions') as actions:
            for command in ['mở Chrome','đừng giảm âm lượng','giảm 40 phần trăm âm lượng rồi tắt máy',
                            'x'*301,{'command':'âm lượng 40%'}]:
                with self.assertRaises(ValueError):device_control(command,{})
            actions.assert_not_called()

    def test_disabled_settings_do_not_execute(self):
        with patch('desktop_mcp.AppActions') as actions:
            self.assertFalse(device_control('độ sáng 70%',{'actions':{'enabled':False}})['verified'])
            actions.assert_not_called()
