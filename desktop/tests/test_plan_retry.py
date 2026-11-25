"""A model's printed plan can trigger a bounded request for real tool calls."""
import importlib.util
import json
from pathlib import Path
import threading
import unittest

from pet import gemini


class Response:
    status_code = 200
    def __init__(self, delta, finish='stop'):
        self.delta, self.finish = delta, finish
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def iter_lines(self):
        yield 'data: ' + json.dumps({'choices': [{'delta': self.delta, 'finish_reason': self.finish}]})
        yield 'data: [DONE]'


class FakeComputer:
    cfg = {'max_steps': 5}
    def __init__(self): self.calls = []
    def tools(self, _): return [{'type': 'function', 'function': {'name': 'Plan'}}]
    def call(self, name, args, _):
        self.calls.append((name, args))
        return json.dumps({'result': 'mocked', 'is_error': False})


class Client:
    def __enter__(self): return self
    def __exit__(self, *_): return False


class FakeChat:
    _computer_stream = gemini.GeminiChat._computer_stream
    def __init__(self, responses):
        self.responses, self.payloads = list(responses), []
        self.cfg = {'model': 'test'}
        self.computer = FakeComputer()
        self.history = []
        self.name = 'Alex'
    def _history_for(self, _): return []
    def _make_http_client(self, **_): return Client()
    def _retry_stream(self, _, payload, cancelled, **kwargs):
        self.payloads.append(json.loads(json.dumps(payload)))
        return self.responses.pop(0)


class PlanRetryTests(unittest.TestCase):
    def test_text_plan_retries_with_tools_then_dispatches_real_call(self):
        call = {'index': 0, 'id': 'test1', 'function': {'name': 'Plan',
                'arguments': json.dumps({'goal': 'test', 'steps': ['inspect'], 'apps': ['test']})}}
        chat = FakeChat([Response({'content': 'Plan:\nSteps:\n1. Mở ứng dụng.'}),
                         Response({'tool_calls': [call]}, 'tool_calls'),
                         Response({'content': 'Đã gọi công cụ thử.'})])
        self.assertEqual(list(chat._computer_stream('test', threading.Event())), ['Đã gọi công cụ thử.'])
        self.assertEqual(len(chat.computer.calls), 1)
        self.assertEqual(chat.computer.calls[0][0], 'Plan')
        self.assertIn('chỉ là văn bản', chat.payloads[1]['messages'][-1]['content'])

    def test_plan_retry_is_bounded(self):
        chat = FakeChat([Response({'content': 'Plan: lần đầu'}), Response({'content': 'Plan: lần hai'})])
        self.assertEqual(list(chat._computer_stream('test', threading.Event())), ['Plan: lần hai'])
        self.assertEqual(chat.computer.calls, [])
        self.assertEqual(len(chat.payloads), 2)

    def test_never_retries_plan_after_any_tool_call(self):
        call = {'index': 0, 'id': 'test1', 'function': {'name': 'Plan', 'arguments': '{}'}}
        chat = FakeChat([Response({'tool_calls': [call]}, 'tool_calls'), Response({'content': 'Plan: tiếp'})])
        self.assertEqual(list(chat._computer_stream('test', threading.Event())), ['Plan: tiếp'])
        self.assertEqual(len(chat.payloads), 2)
        self.assertEqual(len(chat.computer.calls), 1)

    def test_missing_details_response_is_not_forced(self):
        chat = FakeChat([Response({'content': 'Mày muốn gửi cho ai?'})])
        self.assertEqual(list(chat._computer_stream('test', threading.Event())), ['Mày muốn gửi cho ai?'])
        self.assertEqual(chat.computer.calls, [])
        self.assertEqual(len(chat.payloads), 1)

    def test_original_goal_is_supplied_separately_from_internal_prompt(self):
        chat = FakeChat([Response({'content': 'Cần thêm thông tin.'})])
        chat.computer_original_request = 'Mở trình duyệt cho tao'
        list(chat._computer_stream('Mở trình duyệt cho tao\n\nChỉ dẫn nội bộ.', threading.Event()))
        system = chat.payloads[0]['messages'][0]['content']
        self.assertNotIn('"Mở trình duyệt cho tao"', system)
        self.assertNotIn('Chỉ dẫn nội bộ.', system)
        self.assertIn('"Mở trình duyệt cho tao"', chat.payloads[0]['messages'][-1]['content'])
        self.assertEqual(chat.payloads[0]['messages'][-1]['role'], 'user')

    def test_screen_scoped_tools_do_not_request_unavailable_plan(self):
        chat = FakeChat([Response({'content': 'Plan: Quan sát màn hình.'}),
                         Response({'content': 'Chưa xác định được mục.'})])
        chat.computer.tools = lambda _: [{'type': 'function', 'function': {'name': 'Snapshot'}}]
        list(chat._computer_stream('test', threading.Event()))
        retry = chat.payloads[1]['messages'][-1]['content']
        self.assertIn('công cụ đang có', retry)
        self.assertNotIn('gọi công cụ Plan', retry)

    def test_no_retry_if_next_turn_cannot_call_tools(self):
        chat = FakeChat([Response({'content': 'Plan: dự định'})])
        chat.computer.cfg = {'max_steps': 1}
        self.assertEqual(list(chat._computer_stream('test', threading.Event())), ['Plan: dự định'])
        self.assertEqual(len(chat.payloads), 1)
