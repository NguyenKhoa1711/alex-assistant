import threading
import time
import unittest
from unittest.mock import MagicMock, patch
import numpy as np
from pet.app_actions import Action, ActionResult, AppActions, parse_action
from pet.device_actions import execute_device_action, percentage
from pet.audio import Utterance
from pet.controller import Controller
from pet.config import load_config


class ParsingTests(unittest.TestCase):
    def test_natural_commands(self):
        cases = {
            'Tăng âm lượng': Action('Volume', 'up', '10'),
            'Bạn giảm âm lượng giúp tôi': Action('Volume', 'down', '10'),
            'Hãy tăng âm lượng thêm 15 phần trăm cho tôi': Action('Volume', 'up', '15'),
            'Tăng âm lượng lên 50%': Action('Volume', 'set', '50'),
            'Giảm âm lượng xuống hai mươi phần trăm': Action('Volume', 'set', '20'),
            'Âm lượng 50 phần trăm': Action('Volume', 'set', '50'),
            'giảm 40 phần trăm âm lượng cho tôi': Action('Volume', 'down', '40'),
            'âm lượng 40 phần trăm': Action('Volume', 'set', '40'),
            'Tăng thêm mười phần trăm độ sáng màn hình': Action('Brightness', 'up', '10'),
            'Giảm xuống 30 phần trăm ánh sáng laptop': Action('Brightness', 'set', '30'),
            'Chỉnh âm thanh về năm mươi lăm phần trăm': Action('Volume', 'set', '55'),
            'Tăng loa một chút': Action('Volume', 'up', '10'),
            'Tắt tiếng': Action('Volume', 'mute'),
            'Bật lại tiếng': Action('Volume', 'unmute'),
            'Giảm độ sáng': Action('Brightness', 'down', '10'),
            'Tăng ánh sáng laptop lên': Action('Brightness', 'up', '10'),
            'Tăng độ sáng màn hình thêm mười phần trăm': Action('Brightness', 'up', '10'),
            'Đặt độ sáng màn hình 70%': Action('Brightness', 'set', '70'),
            'Giảm độ sáng màn hình xuống 30%': Action('Brightness', 'set', '30'),
            'Âm lượng hiện tại bao nhiêu phần trăm': Action('Volume', 'read'),
            'Độ sáng màn hình là bao nhiêu': Action('Brightness', 'read'),
        }
        for phrase, wanted in cases.items():
            self.assertEqual(parse_action(phrase), wanted, phrase)

    def test_no_actions_from_questions_negation_or_other_targets(self):
        for phrase in ['Đừng tăng âm lượng', 'Không giảm độ sáng', 'Cách tăng âm lượng',
                       'Nếu tăng âm lượng thì sao', 'Tăng âm lượng và tắt máy',
                       'Tăng âm lượng micro', 'Tắt máy', 'Tắt nguồn',
                       'Giảm âm lượng trong video', 'Tăng âm lượng YouTube']:
            self.assertIsNone(parse_action(phrase), phrase)
        self.assertEqual(parse_action('Tắt nhạc'), Action('Spotify', 'pause'))
        self.assertEqual(parse_action('Đóng tab'), Action('Tabs', 'close_current'))

    def test_invalid_percentages_are_local_clarifications(self):
        for phrase in ['Âm lượng 150%', 'Đặt độ sáng -10%', 'Âm lượng 2,5%',
                       'Tăng âm lượng thêm 200%']:
            action = parse_action(phrase)
            self.assertIsNotNone(action, phrase)
            self.assertEqual(action.operation, 'invalid')
        self.assertEqual(percentage('mot tram'), 100)
        self.assertEqual(percentage('chin muoi chin'), 99)


class FakeDevice:
    def __init__(self, level=50, muted=False, brightness=False, levels=None):
        self.state = {'level': level}
        if not brightness: self.state['muted'] = muted
        self.levels = levels
        self.writes = []
    def current(self): return dict(self.state)
    def supported_level(self, level):
        return min(self.levels, key=lambda v: abs(v-level)) if self.levels else level
    def set_level(self, value):
        self.writes.append(('level', value)); self.state['level'] = value
    def set_muted(self, muted):
        self.writes.append(('muted', muted)); self.state['muted'] = muted


class ExecutionTests(unittest.TestCase):
    def test_relative_increase_and_decrease_once_from_actual_level(self):
        device = FakeDevice(45)
        self.assertTrue(execute_device_action(Action('Volume', 'up', '10'), device)['verified'])
        self.assertEqual(device.writes, [('level', 55)])
        self.assertTrue(execute_device_action(Action('Volume', 'down', '20'), device)['verified'])
        self.assertEqual(device.state['level'], 35)

    def test_bounds_and_exact_levels(self):
        for start, op, amount, expected in [(95,'up',10,100),(5,'down',10,0),(80,'set',30,30)]:
            device = FakeDevice(start)
            self.assertTrue(execute_device_action(Action('Volume',op,str(amount)), device)['verified'])
            self.assertEqual(device.state['level'],expected)
            self.assertEqual(len(device.writes),1)

    def test_mute_and_unmute_preserve_volume(self):
        device = FakeDevice(37)
        execute_device_action(Action('Volume', 'mute'), device)
        self.assertEqual(device.state, {'level':37, 'muted':True})
        execute_device_action(Action('Volume', 'unmute'), device)
        self.assertEqual(device.state, {'level':37, 'muted':False})
        self.assertEqual(device.writes,[('muted',True),('muted',False)])

    def test_set_or_increase_audible_but_decrease_preserves_mute(self):
        for op, muted in [('up',False),('set',False),('down',True)]:
            device = FakeDevice(40, muted=True)
            execute_device_action(Action('Volume',op,'10'),device)
            self.assertEqual(device.state['muted'],muted)

    def test_driver_supported_brightness_level(self):
        device = FakeDevice(40,brightness=True,levels=[0,20,40,60,80,100])
        result = execute_device_action(Action('Brightness','set','53'),device)
        self.assertTrue(result['verified']); self.assertIn('60',result['message'])
        self.assertEqual(device.writes,[('level',60)])

    def test_failed_readback_does_not_retry_setting(self):
        device = FakeDevice(50)
        device.set_level = MagicMock()
        with patch('pet.device_actions.time.sleep'):
            result=execute_device_action(Action('Volume','up','10'),device)
        self.assertFalse(result['verified']);device.set_level.assert_called_once_with(60)

    def test_read_invalid_and_cancel_do_not_change_anything(self):
        device = FakeDevice(37)
        self.assertTrue(execute_device_action(Action('Volume','read'),device)['verified'])
        self.assertFalse(execute_device_action(Action('Volume','invalid'),device)['verified'])
        self.assertEqual(device.writes,[])
        with self.assertRaises(ValueError): execute_device_action(Action('Brightness','set','101'),device)
        event=threading.Event();event.set()
        with patch('pet.app_actions.subprocess.Popen') as popen:
            AppActions({}).execute(Action('Volume','up','10'),event)
        popen.assert_not_called()


class ControllerTests(unittest.TestCase):
    def test_device_command_stays_local_and_private(self):
        cfg=load_config(); cfg['learning']['enabled']=False; cfg['privacy']['save_transcripts']=False
        engine=Controller(cfg); engine.chat = engine.gemini_chat = MagicMock(); engine.speaker=MagicMock(); engine.app_actions=MagicMock()
        engine.chat.check_ready.side_effect=RuntimeError('busy')
        engine.app_actions.execute.return_value=ActionResult('Âm lượng đang ở 60 phần trăm.',True)
        with self.assertLogs(level='INFO') as logs:
            engine._answer('Tăng âm lượng',Utterance(np.zeros(100),time.monotonic()),.1)
        engine.app_actions.execute.assert_called_once_with(Action('Volume','up','10'),engine.cancelled)
        engine.chat.check_ready.assert_not_called();engine.chat.stream.assert_not_called()
        self.assertNotIn('"text"','\n'.join(logs.output))

    def test_disabled_actions_do_not_touch_device(self):
        cfg=load_config();cfg['learning']['enabled']=False;cfg['actions']['enabled']=False
        engine=Controller(cfg);engine.chat = engine.gemini_chat = MagicMock();engine.speaker=MagicMock();engine.app_actions=MagicMock()
        engine._answer('Giảm độ sáng',Utterance(np.zeros(100),time.monotonic()),.1)
        engine.app_actions.execute.assert_not_called();engine.chat.stream.assert_not_called()


class BrightnessDriverTests(unittest.TestCase):
    def test_missing_wmi_output_is_allowed_but_explicit_error_rejected(self):
        from pet.windows_controls import WindowsBrightness
        device=WindowsBrightness.__new__(WindowsBrightness)
        device.methods=MagicMock()
        device.methods.ExecMethod_.return_value=None
        device.set_level(70)
        device.methods.ExecMethod_.assert_called_once()
        output=MagicMock();output.Properties_.return_value.Value=1
        device.methods.ExecMethod_.return_value=output
        with self.assertRaises(RuntimeError):device.set_level(70)


if __name__ == '__main__': unittest.main()
