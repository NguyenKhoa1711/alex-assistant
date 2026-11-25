from __future__ import annotations

import threading
import unittest

from pet.agent_input_observation import observe_inputs, rematch
from pet.desktop_guard import DesktopGuard, Window
from pet.message_flow import MessageResult
from pet.message_identity import Candidate
from pet.message_intent import SendIntent, classify_message_request, parse_send_intent
from pet.messaging_driver import execute_send_message, format_message_result
from pet.verified_adapter import Conversation, OutgoingMessage


class _FakeDriver:
    def __init__(self, *, candidates=None, complete=True, draft='', after_send_visible=True,
                 raise_on_submit=False, conv_name='Nguyễn Văn An') -> None:
        self.candidates = candidates if candidates is not None else [
            Candidate(id='friend-item-1', name='Nguyễn Văn An', kind='person', can_send=True),
        ]
        self.complete = complete
        self.draft = draft
        self.after_send_visible = after_send_visible
        self.raise_on_submit = raise_on_submit
        self.conv_name = conv_name
        self.opened_id = ''
        self.submit_calls = 0
        self.messages = [OutgoingMessage(id='m1', text='cũ', status='sent', sender_is_user=True)]

    def search_contacts(self, name: str):
        return self.candidates, self.complete

    def open_contact(self, contact_id: str) -> None:
        self.opened_id = contact_id

    def current_conversation(self):
        if not self.opened_id:
            return None
        return Conversation(service='Zalo', id=self.opened_id, name=self.conv_name, foreground=True)

    def read_draft(self):
        return self.draft

    def type_literal(self, value: str) -> None:
        self.draft = value

    def outgoing_messages(self):
        return list(self.messages)

    def submit_once(self, expected: Conversation, expected_text: str) -> None:
        self.submit_calls += 1
        if self.raise_on_submit:
            raise RuntimeError('uncertain delivery')
        self.draft = ''
        if self.after_send_visible:
            self.messages.append(OutgoingMessage(id='m2', text=expected_text, status='sent', sender_is_user=True))


class MessagingIntegrationTests(unittest.TestCase):
    def test_parse_send_intent_and_classification(self) -> None:
        intent = parse_send_intent('Alex ơi, gửi tin nhắn xin chào cho Nguyễn Văn An trên Zalo giúp tôi nhé')
        self.assertEqual(intent, SendIntent(service='Zalo', recipient='Nguyễn Văn An', content='xin chào'))

        msg_intent = parse_send_intent('Nhắn tin cho Minh trên Messenger là tối nay đi ăn nhé')
        self.assertEqual(msg_intent, SendIntent(service='Messenger', recipient='Minh', content='tối nay đi ăn nhé'))

        self.assertIsNone(parse_send_intent('Đừng gửi tin nhắn cho An trên Zalo'))
        neg = classify_message_request('Đừng gửi tin nhắn cho An trên Zalo')
        self.assertFalse(neg.recognized)

        incomplete = classify_message_request('Gửi tin nhắn cho An trên Zalo')
        self.assertTrue(incomplete.recognized)
        self.assertIsNone(incomplete.intent)

    def test_agent_input_observation_and_guard_binding(self) -> None:
        snap = {
            'complete': True,
            'tree': {
                'role': 'window',
                'children': [
                    {
                        'role': 'group',
                        'native_id': {'kind': 'automation_id', 'value': 'richInput'},
                        'ref_id': '@s1:e12',
                        'available_actions': ['SetValue', 'SetFocus'],
                        'bounds': {'x': 100, 'y': 200, 'width': 400, 'height': 40},
                    },
                    {
                        'role': 'edit',
                        'native_id': {'kind': 'automation_id', 'value': 'msgEdit'},
                        'ref_id': '@s1:e15',
                        'available_actions': ['SetFocus'],
                        'bounds': {'x': 100, 'y': 300, 'width': 400, 'height': 40},
                    },
                ],
            },
        }
        group_only = observe_inputs(snap)
        self.assertEqual(len(group_only), 1)
        self.assertEqual(group_only[0].point, (300, 220))

        both = observe_inputs(snap, include_standard_roles=True)
        self.assertEqual(len(both), 2)

        win = Window(hwnd=1234, pid=99, executable='Zalo.exe', title='Zalo')
        guard = DesktopGuard(approve=lambda *a, **k: {'allowed': True}, foreground=lambda: win)
        guard.register_agent_observation(win, group_only[0].identity, group_only[0].point)
        matched = guard.verify_agent_observation(win, group_only[0].point, snap)
        self.assertIsNotNone(matched)
        self.assertEqual(matched.ref, '@s1:e12')

        other_win = Window(hwnd=5678, pid=99, executable='Zalo.exe', title='Zalo')
        self.assertIsNone(guard.verify_agent_observation(other_win, group_only[0].point, snap))

    def test_execute_send_message_success_and_safety_guards(self) -> None:
        intent = SendIntent(service='Zalo', recipient='Nguyễn Văn An', content='xin chào')
        driver = _FakeDriver()
        res, reply = execute_send_message(intent, threading.Event(), driver_factory=lambda *_: driver)
        self.assertEqual(res, MessageResult('sent', True))
        self.assertEqual(driver.submit_calls, 1)
        self.assertIn('đã gửi tin nhắn', reply)

        # Duplicate / accent mismatch rejection (An vs Ân)
        dup_driver = _FakeDriver(candidates=[
            Candidate(id='1', name='Nguyễn Văn Ân', kind='person'),
        ])
        res_dup, _ = execute_send_message(intent, threading.Event(), driver_factory=lambda *_: dup_driver)
        self.assertEqual(res_dup.status, 'recipient_not_unique')
        self.assertEqual(dup_driver.submit_calls, 0)

        # Non-empty draft protection
        draft_driver = _FakeDriver(draft='chữ có sẵn')
        res_draft, _ = execute_send_message(intent, threading.Event(), driver_factory=lambda *_: draft_driver)
        self.assertEqual(res_draft.status, 'draft_unverified')
        self.assertEqual(draft_driver.submit_calls, 0)

        # Never retry on uncertain send
        uncertain_driver = _FakeDriver(raise_on_submit=True)
        res_unc, reply_unc = execute_send_message(intent, threading.Event(), driver_factory=lambda *_: uncertain_driver)
        self.assertEqual(res_unc.status, 'send_unverified')
        self.assertFalse(res_unc.sent)
        self.assertEqual(uncertain_driver.submit_calls, 1)
        self.assertIn('đừng gửi lại', reply_unc)
        self.assertIn('chưa đọc lại được', format_message_result(intent, res_unc))

    def test_unique_ref_accepts_group_rich_input_and_zalo_placeholder(self) -> None:
        from pet.agent_bridge import unique_ref_for_point
        from pet.messaging_driver import ZaloUiDriver

        snap = {
            'complete': True,
            'tree': {
                'role': 'window',
                'children': [
                    {
                        'role': 'group',
                        'name': 'Nhập @, tin nhắn tới Nguyễn Văn An',
                        'native_id': {'kind': 'automation_id', 'value': 'richInput'},
                        'ref_id': '@s1:e44',
                        'available_actions': ['SetValue', 'SetFocus'],
                        'bounds': {'x': 200, 'y': 500, 'width': 400, 'height': 40},
                    },
                ],
            },
        }
        ref = unique_ref_for_point(
            snap, [400, 520],
            '└── (400,520) group "Nhập @, tin nhắn tới Nguyễn Văn An" [action: SetFocus]',
            'type',
        )
        self.assertEqual(ref, '@s1:e44')

        class _FakeBridge:
            def snapshot(self, max_depth=30):
                return snap
            def get_value(self, r):
                return {'ok': True, 'data': {'value': 'Nhập @, tin nhắn tới Nguyễn Văn An'}}

        drv = ZaloUiDriver()
        drv._chosen_name = 'Nguyễn Văn An'
        drv._ensure_bridge = lambda: _FakeBridge()
        # Placeholder is NOT treated as empty without a dedicated UIA empty/placeholder property
        self.assertEqual(drv.read_draft(), 'Nhập @, tin nhắn tới Nguyễn Văn An')
        self.assertIsNone(drv.outgoing_messages())

        # Mismatched non-placeholder text is never treated as empty
        drv._ensure_bridge = lambda: type('B', (), {
            'snapshot': lambda s, max_depth=30: snap,
            'get_value': lambda s, r: {'ok': True, 'data': {'value': 'tin nháp đang dở'}},
        })()
        self.assertEqual(drv.read_draft(), 'tin nháp đang dở')

    def test_find_messenger_hwnd_requires_unique_process_bound_window(self) -> None:
        from pathlib import Path
        from unittest import mock
        from pet import messaging_driver

        seen_entries = []

        def fake_app_windows(entry):
            seen_entries.append(entry)
            return [4242]

        with mock.patch.object(messaging_driver, 'load_config', return_value={'apps': {'entries': []}}), \
                mock.patch.object(messaging_driver, 'requested_app', return_value=None), \
                mock.patch.object(messaging_driver, 'app_windows', side_effect=fake_app_windows):
            self.assertEqual(messaging_driver._find_messenger_hwnd(), 4242)

        self.assertEqual(len(seen_entries), 1)
        self.assertTrue(seen_entries[0].get('browser_app'))
        self.assertIn('chrome.exe', seen_entries[0].get('processes', []))

        with mock.patch.object(messaging_driver, 'load_config', return_value={'apps': {'entries': []}}), \
                mock.patch.object(messaging_driver, 'requested_app', return_value=None), \
                mock.patch.object(messaging_driver, 'app_windows', return_value=[111, 222]):
            self.assertIsNone(messaging_driver._find_messenger_hwnd())

        with mock.patch.object(messaging_driver, 'load_config', return_value={'apps': {'entries': []}}), \
                mock.patch.object(messaging_driver, 'requested_app', return_value=None), \
                mock.patch.object(messaging_driver, 'app_windows', return_value=[]):
            self.assertIsNone(messaging_driver._find_messenger_hwnd())

    def test_messenger_driver_surface_main_scope_and_textbox_compose(self) -> None:
        from pathlib import Path
        from unittest import mock
        from pet import messaging_driver
        from pet.agent_bridge import AgentBridgeError
        from pet.desktop_guard import Window

        drv = messaging_driver.MessengerUiDriver()
        drv.hwnd = 9001

        bad_snap = {
            'complete': True,
            'tree': {'role': 'document', 'url': 'https://www.google.com/search?q=messenger', 'children': []},
        }
        with self.assertRaises(RuntimeError):
            drv._verify_messenger_surface(bad_snap)

        good_snap = {
            'complete': True,
            'tree': {
                'role': 'document',
                'url': 'https://www.messenger.com/t/12345',
                'children': [
                    {'role': 'heading', 'name': 'Nguyễn Văn An', 'ref_id': '@s1:e2'},
                    {
                        'role': 'main',
                        'children': [
                            {
                                'role': 'heading',
                                'name': 'Nguyễn Văn An',
                                'ref_id': '@s1:e10',
                                'native_id': {'kind': 'uia', 'value': 'conv-header-123'},
                            },
                            {
                                'role': 'searchfield',
                                'name': 'Tìm kiếm trong Tin nhắn',
                                'ref_id': '@s1:e11',
                                'available_actions': ['SetFocus'],
                                'native_id': {'kind': 'uia', 'value': 'search-in-chat'},
                                'bounds': {'x': 10, 'y': 10, 'width': 100, 'height': 20},
                            },
                            {
                                'role': 'textbox',
                                'name': 'Tin nhắn',
                                'ref_id': '@s1:e12',
                                'available_actions': ['SetFocus'],
                                'native_id': {'kind': 'uia', 'value': 'msg-compose-box'},
                                'bounds': {'x': 100, 'y': 500, 'width': 300, 'height': 40},
                            },
                        ],
                    },
                ],
            },
        }

        class _FakeMessengerBridge:
            def snapshot(self, max_depth=30):
                return good_snap

        drv._ensure_bridge = lambda: _FakeMessengerBridge()
        with self.assertRaises(AgentBridgeError):
            drv.open_contact('@s1:e999')

        drv._chosen_name = 'Nguyễn Văn An'
        with mock.patch.object(messaging_driver, 'current_window', return_value=Window(9001, 'chrome.exe', 'Chrome_WidgetWin_1', 'Messenger')):
            conv = drv.current_conversation()
        self.assertIsNotNone(conv)
        self.assertEqual(conv.id, 'messenger:thread:12345')
        obs = drv._locate_compose_input(_FakeMessengerBridge())
        self.assertIsNotNone(obs)
        self.assertEqual(obs.ref, '@s1:e12')
        self.assertEqual(obs.role, 'textbox')

    def test_messenger_driver_thread_id_mapping_and_mismatch_fail_closed(self) -> None:
        from pathlib import Path
        from unittest import mock
        from pet import messaging_driver
        from pet.desktop_guard import Window
        from pet.verified_adapter import VerifiedMessageAdapter

        search_snap = {
            'complete': True,
            'tree': {
                'role': 'document',
                'url': 'https://www.messenger.com/',
                'children': [
                    {'role': 'searchfield', 'name': 'Tìm kiếm trên Messenger', 'ref_id': '@s1:e2'},
                    {
                        'role': 'link',
                        'name': 'Nguyễn Văn An',
                        'ref_id': '@s1:e5',
                        'url': 'https://www.messenger.com/t/12345',
                    },
                    {
                        'role': 'row',
                        'name': 'Trần Bình',
                        'ref_id': '@s1:e6',
                        'native_id': {'kind': 'uia', 'value': 'search-row-7'},
                    },
                ],
            },
        }
        opened_same_snap = {
            'complete': True,
            'tree': {
                'role': 'document',
                'url': 'https://www.messenger.com/t/12345',
                'children': [{
                    'role': 'main',
                    'children': [{
                        'role': 'heading',
                        'name': 'Nguyễn Văn An',
                        'native_id': {'kind': 'uia', 'value': 'conv-header-123'},
                    }],
                }],
            },
        }
        opened_wrong_thread_snap = {
            'complete': True,
            'tree': {
                'role': 'document',
                'url': 'https://www.messenger.com/t/99999',
                'children': [{
                    'role': 'main',
                    'children': [{
                        'role': 'heading',
                        'name': 'Nguyễn Văn An',
                        'native_id': {'kind': 'uia', 'value': 'conv-header-999'},
                    }],
                }],
            },
        }

        class _FakeBridge:
            def __init__(self, post_click_snap):
                self.clicked = []
                self.post_click = post_click_snap
                self.stage = 'search'

            def snapshot(self, max_depth=30):
                return self.post_click if self.stage == 'opened' else search_snap

            def focus_for_type(self, ref, text):
                return {'ok': True}

            def act(self, op, ref, text=''):
                if op == 'click':
                    self.clicked.append(ref)
                    self.stage = 'opened'
                return {'ok': True}

        with mock.patch.object(messaging_driver, 'current_window', return_value=Window(9001, 'chrome.exe', 'Chrome_WidgetWin_1', 'Messenger')):
            drv = messaging_driver.MessengerUiDriver()
            drv.hwnd = 9001
            fake_bridge = _FakeBridge(opened_same_snap)
            drv._ensure_bridge = lambda: fake_bridge
            adapter = VerifiedMessageAdapter('Messenger', drv)
            ids = adapter.find_exact_recipients('Nguyễn Văn An')
            self.assertEqual(ids, ['messenger:thread:12345'])
            self.assertTrue(adapter.open_and_verify_recipient('messenger:thread:12345', 'Nguyễn Văn An'))
            self.assertEqual(fake_bridge.clicked, ['@s1:e5'])

            # Thread URL mismatch must fail closed even when heading text matches
            drv2 = messaging_driver.MessengerUiDriver()
            drv2.hwnd = 9001
            drv2._ensure_bridge = lambda: _FakeBridge(opened_wrong_thread_snap)
            adapter2 = VerifiedMessageAdapter('Messenger', drv2)
            ids2 = adapter2.find_exact_recipients('Nguyễn Văn An')
            self.assertEqual(ids2, ['messenger:thread:12345'])
            self.assertFalse(adapter2.open_and_verify_recipient('messenger:thread:12345', 'Nguyễn Văn An'))

            # Search row without thread URL (only native_id) must fail closed, never fake-match heading
            drv3 = messaging_driver.MessengerUiDriver()
            drv3.hwnd = 9001
            drv3._ensure_bridge = lambda: _FakeBridge({
                'complete': True,
                'tree': {
                    'role': 'document',
                    'url': 'https://www.messenger.com/',
                    'children': [{'role': 'main', 'children': [{'role': 'heading', 'name': 'Trần Bình', 'native_id': {'kind': 'uia', 'value': 'hdr-7'}}]}],
                },
            })
            adapter3 = VerifiedMessageAdapter('Messenger', drv3)
            ids3 = adapter3.find_exact_recipients('Trần Bình')
            self.assertEqual(ids3, ['messenger:node:uia:search-row-7'])
            self.assertFalse(adapter3.open_and_verify_recipient('messenger:node:uia:search-row-7', 'Trần Bình'))

    def test_pending_message_followup_remembers_and_merges_turns(self) -> None:
        from pet.message_intent import (
            extract_partial_message,
            format_missing_message_prompt,
            merge_message_followup,
        )

        partial = extract_partial_message('nhắn cho Nguyễn Văn An')
        self.assertEqual(partial, {'recipient': 'Nguyễn Văn An'})
        prompt1 = format_missing_message_prompt(partial)
        self.assertIn('Nguyễn Văn An', prompt1)

        action2, state2 = merge_message_followup(partial, 'Zalo')
        self.assertEqual(action2, 'ask')
        self.assertEqual(state2, {'recipient': 'Nguyễn Văn An', 'service': 'Zalo'})

        action3, state3 = merge_message_followup(state2, 'tối nay 7 giờ nhé')
        self.assertEqual(action3, 'execute')
        self.assertEqual(state3, {
            'recipient': 'Nguyễn Văn An',
            'service': 'Zalo',
            'content': 'tối nay 7 giờ nhé',
        })

        action_ok, _ = merge_message_followup(state3, 'ok hết')
        self.assertEqual(action_ok, 'execute')

        action_cancel, state_cancel = merge_message_followup(state2, 'thôi hủy đi')
        action_cancel2, _ = merge_message_followup(state2, 'hủy')
        self.assertEqual(action_cancel2, 'cancel')
        self.assertEqual(state_cancel, state_cancel)

    def test_resolve_visible_target_matches_slightly_misheard_name(self) -> None:
        from pet.screen_context import resolve_visible_target

        evidence = (
            'Cửa sổ: Messenger\n'
            'link: Dũng Trần\n'
            'link: Bùi Đức Vũ · 1 giờ\n'
            'link: Thang Minh\n'
        )
        self.assertEqual(resolve_visible_target('Bấm vào Bùi Đứt Vũ', evidence), 'Bùi Đức Vũ')

        ambiguous_evidence = (
            'Cửa sổ: Messenger\n'
            'link: Bùi Đức Vũ\n'
            'link: Bùi Đức Vĩ\n'
        )
        self.assertIsNone(resolve_visible_target('Bấm vào Bùi Đức Vă', ambiguous_evidence))

    def test_find_deep_click_ref_prefers_clickable_role_and_dedups_nested(self) -> None:
        from pet.screen_context import find_deep_click_ref

        tree = {
            'role': 'main',
            'children': [
                {
                    'role': 'link',
                    'name': 'Bùi Đức Vũ · 1 giờ',
                    'ref_id': '@s1:e20',
                    'bounds': {'x': 100, 'y': 300, 'width': 200, 'height': 50},
                    'children': [{
                        'role': 'text',
                        'name': 'Bùi Đức Vũ',
                        'ref_id': '@s1:e21',
                        'bounds': {'x': 102, 'y': 302, 'width': 196, 'height': 46},
                    }],
                },
            ],
        }
        hit = find_deep_click_ref(tree, 'bui duc vu')
        self.assertIsNotNone(hit)
        self.assertEqual(hit[0], '@s1:e20')

        from pathlib import Path
        from unittest import mock
        from pet import screen_context, agent_bridge

        fake_bridge = mock.MagicMock()
        fake_bridge.snapshot.return_value = {'complete': True, 'tree': tree}
        fake_bridge.act.return_value = {'ok': True}
        with mock.patch.object(screen_context, '_binary', return_value=Path('agent-desktop.exe')), \
                mock.patch.object(agent_bridge, 'AgentDesktopBridge', return_value=fake_bridge), \
                mock.patch('pet.screen_tools.window_point_is_usable', side_effect=lambda _h, loc: isinstance(loc, list) and len(loc) == 2):
            ok, label = screen_context.click_deep_visible_target(
                9001, 'bui duc vu', lambda: True, threading.Event(),
            )
        self.assertTrue(ok)
        self.assertEqual(label, 'bui duc vu')
        fake_bridge.act.assert_called_once_with('click', '@s1:e20')

    def test_messenger_chrome_hidden_scheme_requires_verified_site_info_popup(self) -> None:
        from unittest import mock
        from pet import messaging_driver
        from pet.desktop_guard import Window

        chrome_snap = {
            'complete': True,
            'tree': {
                'role': 'window',
                'children': [{'role': 'toolbar', 'children': [
                    {
                        'role': 'button',
                        'name': 'View site information',
                        'ref_id': '@s1:e1',
                        'bounds': {'x': 120, 'y': 60, 'width': 24, 'height': 24},
                    },
                    {
                        'role': 'textfield',
                        'name': 'Address and search bar',
                        'ref_id': '@s1:e2',
                        'bounds': {'x': 160, 'y': 60, 'width': 400, 'height': 28},
                    },
                ]}],
            },
        }

        class _ChromeBridge:
            def snapshot(self, max_depth=30):
                return chrome_snap

            def get_value(self, ref):
                return {'ok': True, 'data': {'value': 'messenger.com/t/100082131192241'}}

            def act(self, op, ref, text=''):
                return {'ok': True}

        drv = messaging_driver.MessengerUiDriver()
        drv.hwnd = 9001
        drv.bridge = _ChromeBridge()
        browser_win = Window(9001, 'chrome.exe', 'Chrome_WidgetWin_1', 'Messenger')

        # 1. Popup NOT secure -> must fail closed
        with mock.patch.object(messaging_driver, 'current_window', return_value=browser_win), \
                mock.patch.object(messaging_driver, 'focus_window', return_value=True), \
                mock.patch.object(drv, '_address_focused_state', return_value=False), \
                mock.patch.object(drv, '_read_security_popup_is_https', return_value=False):
            with self.assertRaises(RuntimeError):
                drv._verify_messenger_surface(chrome_snap)

        # 2. Popup verifies HTTPS + address stays identical -> passes and records verified URL
        with mock.patch.object(messaging_driver, 'current_window', return_value=browser_win), \
                mock.patch.object(messaging_driver, 'focus_window', return_value=True), \
                mock.patch.object(drv, '_address_focused_state', return_value=False), \
                mock.patch.object(drv, '_read_security_popup_is_https', return_value=True):
            drv._verify_messenger_surface(chrome_snap)
        self.assertEqual(drv._verified_address_url, 'https://messenger.com/t/100082131192241')


if __name__ == '__main__':
    unittest.main()
