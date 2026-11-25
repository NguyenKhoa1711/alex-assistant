import copy
import types
import unittest
from unittest.mock import MagicMock, patch
from pet.agent_input_observation import observe_inputs, rematch
from pet.messaging_driver import _bind_messenger_composer_identity


def snapshot():
    return {'complete': True, 'tree': {'role': 'document', 'children': [{
        'role': 'textfield', 'name': 'Nhắn tin', 'ref_id': '@s1:e1',
        'bounds': {'x': 10, 'y': 20, 'width': 100, 'height': 40},
        'available_actions': ['SetFocus', 'SetValue'],
    }]}}


class MessengerComposeIdentityTests(unittest.TestCase):
    def setUp(self):
        self.node=MagicMock(ControlTypeName='EditControl',ProcessId=9,Name='Nhắn tin')
        self.node.GetRuntimeId.return_value=[1,42,7]
        self.uia=types.SimpleNamespace(ControlFromPoint=lambda *args:self.node)
        self.patches=[patch.dict('sys.modules', {'uiautomation': self.uia}),
                      patch('pet.messaging_driver.current_window',return_value=types.SimpleNamespace(hwnd=12,pid=9)),
                      patch('pet.messaging_driver.window_point_is_usable',return_value=True)]
        for p in self.patches:p.start()
        self.addCleanup(lambda:[p.stop() for p in reversed(self.patches)])

    def test_binds_and_rematches_same_native_identity(self):
        one=_bind_messenger_composer_identity(snapshot(),12)
        before=observe_inputs(one,include_standard_roles=True)
        self.assertEqual(len(before),1)
        fresh=_bind_messenger_composer_identity(snapshot(),12)
        self.assertIsNotNone(rematch(before[0],fresh,include_standard_roles=True))
        self.node.GetRuntimeId.return_value=[1,42,8]
        changed=_bind_messenger_composer_identity(snapshot(),12)
        self.assertIsNone(rematch(before[0],changed,include_standard_roles=True))

    def test_rejects_wrong_process_or_name(self):
        for attr,value in [('ProcessId',10),('Name','Tìm kiếm'),('ControlTypeName','ButtonControl')]:
            with self.subTest(attr=attr):
                old=getattr(self.node,attr);setattr(self.node,attr,value)
                self.assertEqual(observe_inputs(_bind_messenger_composer_identity(snapshot(),12),include_standard_roles=True),[])
                setattr(self.node,attr,old)

    def test_rejects_ambiguous_or_incomplete_snapshot(self):
        partial=snapshot();partial['complete']=False
        self.assertEqual(observe_inputs(_bind_messenger_composer_identity(partial,12),include_standard_roles=True),[])
        ambiguous=snapshot();ambiguous['tree']['children'].append(copy.deepcopy(ambiguous['tree']['children'][0]))
        self.assertEqual(observe_inputs(_bind_messenger_composer_identity(ambiguous,12),include_standard_roles=True),[])
