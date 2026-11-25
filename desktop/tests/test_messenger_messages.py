import unittest

from unittest.mock import MagicMock

from pet.messaging_driver import MessengerUiDriver
from pet.messenger_messages import (
    extract_stable_node_id,
    normalize_delivery_status,
    parse_outgoing_messages,
    reconstruct_message_text,
)


def _row(sender_name, fragments, *, status=None, runtime_id=None, ref_id='@s1'):
    children = [
        {'role': 'button', 'name': sender_name, 'ref_id': f'{ref_id}-btn',
         **({'runtime_id': runtime_id} if runtime_id else {})},
    ]
    for idx, frag in enumerate(fragments):
        children.append({'role': 'text', 'name': frag, 'ref_id': f'{ref_id}-t{idx}'})
    if status is not None:
        children.append({'role': 'text', 'name': status, 'ref_id': f'{ref_id}-st'})
    return {'role': 'row', 'ref_id': ref_id, 'children': children}


class MessengerMessagesTests(unittest.TestCase):
    def test_normalizes_english_and_vietnamese_delivery_statuses(self):
        self.assertEqual(normalize_delivery_status('Sent'), 'sent')
        self.assertEqual(normalize_delivery_status('Đã gửi'), 'sent')
        self.assertEqual(normalize_delivery_status('Đã nhận'), 'delivered')
        self.assertEqual(normalize_delivery_status('Đã xem'), 'seen')
        self.assertEqual(normalize_delivery_status('Đang gửi'), 'sending')
        self.assertEqual(normalize_delivery_status("Couldn't send"), 'failed')
        self.assertIsNone(normalize_delivery_status('Bấm để xem thêm'))

    def test_extract_stable_node_id_rejects_ephemeral_ref_id(self):
        self.assertEqual(extract_stable_node_id({'ref_id': '@s12'}), '')
        self.assertEqual(
            extract_stable_node_id({'ref_id': '@s12', 'runtime_id': [42, 100, 7]}),
            'messenger:msg:rt:42.100.7',
        )

    def test_reconstructs_split_text_fragments_without_chrome(self):
        row = _row('Bạn đã gửi', ['alex', '1311'], status='Đã gửi', runtime_id=[1, 2, 3])
        self.assertEqual(reconstruct_message_text(row), 'alex 1311')

    def test_parse_outgoing_messages_succeeds_with_stable_id_and_status(self):
        tree = {
            'role': 'document',
            'children': [
                {
                    'role': 'main',
                    'children': [
                        {
                            'role': 'row',
                            'ref_id': '@s9',
                            'children': [
                                {'role': 'button', 'name': 'Anh Minh đã gửi', 'runtime_id': [9, 9]},
                                {'role': 'text', 'name': 'tin den'},
                            ],
                        },
                        _row('You sent', ['xin ', 'chào'], status='Delivered', runtime_id=[42, 7]),
                    ],
                }
            ],
        }
        msgs = parse_outgoing_messages(tree)
        self.assertIsNotNone(msgs)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].id, 'messenger:msg:rt:42.7')
        self.assertEqual(msgs[0].text, 'xin chào')
        self.assertEqual(msgs[0].status, 'delivered')
        self.assertTrue(msgs[0].sender_is_user)

    def test_parse_outgoing_messages_fails_closed_when_status_missing(self):
        tree = {
            'role': 'main',
            'children': [_row('Bạn đã gửi', ['alex', '1311'], status=None, runtime_id=[42, 8])],
        }
        self.assertIsNone(parse_outgoing_messages(tree))

    def test_parse_outgoing_messages_fails_closed_when_stable_id_missing(self):
        tree = {
            'role': 'main',
            'children': [_row('Bạn đã gửi', ['alex', '1311'], status='Đã gửi', runtime_id=None)],
        }
        self.assertIsNone(parse_outgoing_messages(tree))

    def test_normalize_delivery_status_accepts_timestamp_rejects_attachment_phrase(self):
        self.assertEqual(normalize_delivery_status('Đã gửi lúc 18:02'), 'sent')
        self.assertIsNone(normalize_delivery_status('Đã gửi 1 ảnh'))

    def test_messenger_driver_outgoing_messages_verifies_surface_and_parses(self):
        driver = MessengerUiDriver()
        driver.hwnd = 1234
        bridge = MagicMock()
        bridge.snapshot.return_value = {
            'complete': True,
            'tree': {
                'role': 'document',
                'url': 'https://www.messenger.com/t/10001',
                'children': [
                    {
                        'role': 'main',
                        'children': [_row('Bạn đã gửi', ['xin', 'chào'], status='Đã gửi lúc 18:02', runtime_id=[7, 9])],
                    }
                ],
            },
        }
        driver._ensure_bridge = MagicMock(return_value=bridge)
        msgs = driver.outgoing_messages()
        self.assertIsNotNone(msgs)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].text, 'xin chào')
        self.assertEqual(msgs[0].status, 'sent')

        bridge.snapshot.return_value = {'complete': False, 'tree': {}}
        self.assertIsNone(driver.outgoing_messages())

    def test_parse_outgoing_messages_allows_older_unknown_when_latest_has_status(self):
        tree = {
            'role': 'main',
            'children': [
                _row('Bạn đã gửi', ['tin', 'cũ'], status=None, runtime_id=[1, 1], ref_id='@s1'),
                _row('Bạn đã gửi', ['tin', 'mới'], status='Đã gửi', runtime_id=[1, 2], ref_id='@s2'),
            ],
        }
        msgs = parse_outgoing_messages(tree)
        self.assertIsNotNone(msgs)
        self.assertEqual([(m.text, m.status) for m in msgs], [('tin cũ', 'unknown'), ('tin mới', 'sent')])


if __name__ == '__main__':
    unittest.main()
