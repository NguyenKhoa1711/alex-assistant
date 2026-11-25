import json
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from pet.permissions import PermissionBroker, plan_matches_request, action_matches_request


def plan(goal, steps=('Mở Spotify',), app='Spotify', paths=''):
    return ('KẾ HOẠCH THAO TÁC\n\n'+goal+'\n\n'+
            '\n'.join(f'{i}. {s}' for i,s in enumerate(steps,1))+
            f'\n\nỨng dụng: {app}\nĐường dẫn: {paths}\n\nAlex sẽ hỏi riêng trước khi gửi.')


class Connection:
    def __init__(self, value): self.value=value;self.result=None
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def poll(self,timeout):return True
    def recv_bytes(self,size):return json.dumps(self.value,ensure_ascii=False).encode()
    def send_bytes(self,data):self.result=json.loads(data)


def broker():
    obj=object.__new__(PermissionBroker)
    obj.lock=threading.Lock();obj.closed=threading.Event();obj.epoch=0
    obj.pending=[];obj.grants={};obj.grant_turns={};obj.active_turn=None
    obj.request=MagicMock(side_effect=AssertionError('User confirmation should not be requested'))
    return obj


class NoConfirmTests(unittest.TestCase):
    def test_plan_is_bound_to_current_request(self):
        self.assertTrue(plan_matches_request(plan('Mở Spotify'), 'Mở Spotify'))
        self.assertFalse(plan_matches_request(plan('Mở Spotify'), 'Mở Zalo'))
        self.assertFalse(plan_matches_request(plan('Mở Spotify',('Mở Spotify','Xóa tệp')), 'Mở Spotify'))
        self.assertFalse(plan_matches_request(plan('Đừng gửi tin nhắn',('Gửi tin nhắn',)), 'Đừng gửi tin nhắn'))
        self.assertFalse(plan_matches_request(plan('Đừng mở Zalo',('Mở Zalo',),app='Zalo'), 'Đừng mở Zalo'))
        self.assertFalse(plan_matches_request(plan('Mở Spotify',paths=r'C:\private'), 'Mở Spotify'))

    def test_sensitive_actions_require_matching_details_without_dialog(self):
        self.assertTrue(action_matches_request('Nhập và gửi trong Zalo:\nChào bạn', 'Gửi tin nhắn Chào bạn'))
        self.assertFalse(action_matches_request('Nhập và gửi trong Zalo:\nSai nội dung', 'Gửi tin nhắn Chào bạn'))
        self.assertFalse(action_matches_request('Nhập và gửi trong Zalo:\nChào bạn', 'Đừng gửi tin nhắn Chào bạn'))
        self.assertFalse(action_matches_request('Thao tác vị trí chưa có nhãn trong Zalo', 'Bấm nút đó'))
        self.assertTrue(action_matches_request('Thao tác file: delete\nC:\\work\\test.txt\nĐích: ', 'Xóa test.txt'))
        self.assertFalse(action_matches_request('Thao tác file: delete\nC:\\work\\test.txt\nĐích: ', 'Mở test.txt'))
        self.assertFalse(action_matches_request('Thao tác file: delete\nC:\\work\\test.txt\nĐích: ', 'Xóa test.txt2'))
        self.assertFalse(action_matches_request('Xác nhận nút có thể gửi, xóa, mua hoặc chạy lệnh:\nbutton "OK"', 'Mở pokemon'))

    def test_broker_no_dialog_and_grant_expires_at_turn_end(self):
        obj=broker();token=obj.begin_turn('Mở Spotify')
        c=Connection({'operation':'approve_plan','description':plan('Mở Spotify')});obj._handle(c)
        self.assertTrue(c.result['allowed']);grant=c.result['grant']
        check=Connection({'operation':'check','grant':grant});obj._handle(check)
        self.assertTrue(check.result['allowed'])
        obj.end_turn(token)
        check=Connection({'operation':'check','grant':grant});obj._handle(check)
        self.assertFalse(check.result['allowed'])
        obj.request.assert_not_called()

    def test_wrong_plan_and_unrelated_action_are_denied_without_dialog(self):
        obj=broker();obj.begin_turn('Mở Spotify')
        wrong=Connection({'operation':'approve_plan','description':plan('Xóa dữ liệu')});obj._handle(wrong)
        self.assertFalse(wrong.result['allowed'])
        good=Connection({'operation':'approve_plan','description':plan('Mở Spotify')});obj._handle(good)
        action=Connection({'operation':'approve_action','grant':good.result['grant'],
                           'description':'Thao tác file: delete\nC:\\work\\test.txt\nĐích: '})
        obj._handle(action);self.assertFalse(action.result['allowed'])
        obj.request.assert_not_called()

    def test_desktop_plan_and_send_button_use_current_intent_without_dialog(self):
        from pet.desktop_guard import DesktopGuard, Window
        obj=broker();obj.begin_turn('Gửi tin nhắn Chào bạn qua Zalo')
        def approve(operation, grant='', description=''):
            connection=Connection({'operation':operation,'grant':grant,'description':description})
            obj._handle(connection)
            return connection.result
        window=Window(123,456,r'C:\Apps\Zalo.exe','Zalo')
        guard=DesktopGuard(approve,lambda:window,lambda _:True)
        result=guard.plan('Gửi tin nhắn Chào bạn qua Zalo', ['Mở Zalo','Gửi tin nhắn'], ['Zalo'], [])
        self.assertTrue(result['approved'])
        snapshot='└── (200,200) button "Send"  [action: click]'
        guard.after('Snapshot',{},window,snapshot,False)
        args,_=guard.before('Click',{'loc':[200,200]})
        self.assertEqual(args['loc'],[200,200])
        guard.finish()
        obj.request.assert_not_called()

    def test_desktop_refuses_unrequested_send_without_dialog(self):
        from pet.desktop_guard import DesktopGuard, Window
        obj=broker();obj.begin_turn('Xem Zalo')
        def approve(operation, grant='', description=''):
            connection=Connection({'operation':operation,'grant':grant,'description':description})
            obj._handle(connection)
            return connection.result
        window=Window(123,456,r'C:\Apps\Zalo.exe','Zalo')
        guard=DesktopGuard(approve,lambda:window,lambda _:True)
        self.assertTrue(guard.plan('Xem Zalo',['Mở Zalo','Xem cửa sổ'],['Zalo'],[])['approved'])
        guard.after('Snapshot',{},window,'└── (200,200) button "Send"  [action: click]',False)
        with self.assertRaisesRegex(ValueError,'chưa khớp'):
            guard.before('Click',{'loc':[200,200]})
        obj.request.assert_not_called()

    def test_controller_opens_unique_suggestion_without_question(self):
        import numpy as np
        from pet.apps import AppSuggestion, LaunchResult
        from pet.audio import Utterance
        from pet.config import load_config
        from pet.controller import Controller
        from pet.llm import LocalChat
        with patch('pet.llm.httpx.Client'):
            engine=Controller(load_config())
        self.addCleanup(engine.local_chat._client.close)
        self.addCleanup(engine.gemini_chat._client.close)
        engine.chat=MagicMock(spec=LocalChat);engine.speaker=MagicMock()
        entry={'name':'Claude','app_id':'Claude.App!Main','title_contains':'Claude'}
        with patch('pet.controller.suggest_installed_app',return_value=AppSuggestion(entry,.76,False)), \
             patch('pet.controller.open_registered_app',return_value=LaunchResult('Claude',True,True,.1)) as launch:
            reply=engine._answer('Mở Closier Desktop cho tôi',Utterance(np.zeros(100),time.monotonic()),0)
        self.assertEqual(reply,'Tao đã mở Claude.')
        self.assertEqual(launch.call_count,1)
        self.assertIsNone(engine.pending_app)


if __name__=='__main__':unittest.main()
