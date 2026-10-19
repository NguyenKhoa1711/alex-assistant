from __future__ import annotations
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pet.bionic import BionicChat, finished_answer, turn_error, active_session, read_entries, context_tokens, model_permitted


def message(role: str, text: str, **extra: object) -> dict:
    return {'type': 'message', 'message': {'role': role, 'parts': [{'type': 'text', 'text': text}]}, **extra}


class BionicTests(unittest.TestCase):
    def test_rotation_accepts_new_temporary_chat_in_same_project(self) -> None:
        chat = BionicChat({'bridge_port': 9223})
        with patch('pet.bionic.Renderer'), patch('pet.bionic.active_session', return_value=('p', 'new')):
            chat._start_fresh_chat(('p', 'old'))

    def test_rotation_rejects_project_switch_before_sending(self) -> None:
        chat = BionicChat({'bridge_port': 9223})
        with patch('pet.bionic.Renderer'), patch('pet.bionic.active_session', return_value=('other', 'new')):
            with self.assertRaisesRegex(RuntimeError, 'đổi Project'):
                chat._start_fresh_chat(('p', 'old'))

    def test_cloud_model_only_in_authorized_project(self) -> None:
        cfg = {'require_local_model': True, 'cloud_project_ids': ['cloud-project']}
        cloud = {'type': 'cloudInference', 'model': 'moonshotai/Kimi-K3'}
        local = {'type': 'indexed', 'indexedModelIdentifier': 'qwen/qwen3.5-4b@q4_k_m'}
        self.assertTrue(model_permitted(cloud, 'cloud-project', cfg))
        self.assertFalse(model_permitted(cloud, 'ordinary-chat', cfg))
        self.assertTrue(model_permitted(local, 'ordinary-chat', cfg))
        self.assertFalse(model_permitted({'type': 'cloudInference'}, 'cloud-project', cfg))

    def test_login_required_never_inserts_or_submits(self) -> None:
        chat = BionicChat({'bridge_port': 9223})
        with patch('pet.bionic.Renderer') as renderer:
            instance = renderer.return_value
            instance.evaluate.return_value = True
            with self.assertRaisesRegex(RuntimeError, 'đăng nhập lại'):
                chat.check_ready()
            instance.call.assert_not_called()
            instance.close.assert_called_once()

    def test_cancel_does_not_stop_a_turn_pet_did_not_submit(self) -> None:
        chat = BionicChat({'bridge_port': 9223})
        chat.target = ('project', 'session')
        with patch('pet.bionic.Renderer') as renderer:
            chat.cancel()
            renderer.assert_not_called()

    def test_interrupt_button_marks_chat_busy(self) -> None:
        chat = BionicChat({'bridge_port': 9223, 'require_local_model': False})
        with patch('pet.bionic.Renderer') as renderer, patch('pet.bionic.active_session', return_value=('p', 's')):
            instance = renderer.return_value
            instance.evaluate.side_effect = [False, 1, 'busy']
            with self.assertRaisesRegex(RuntimeError, 'đang xử lý'):
                chat.check_ready()
            self.assertIn('Interrupt', instance.evaluate.call_args.args[0])

    def test_waits_for_native_turn_end(self) -> None:
        entries = [message('user', 'Xin chào'), message('assistant', 'Mình đang kiểm tra.')]
        self.assertEqual(finished_answer(entries, 'Xin chào'), (False, ''))
        entries += [message('assistant', 'Chào bạn!'), {'type': 'turnSummary'}]
        self.assertEqual(finished_answer(entries, 'Xin chào'), (True, 'Chào bạn!'))

    def test_does_not_read_unrelated_answer(self) -> None:
        entries = [message('user', 'Khác'), message('assistant', 'Câu khác'), {'type': 'turnSummary'}]
        self.assertEqual(finished_answer(entries, 'Xin chào'), (False, ''))

    def test_tool_claim_not_spoken_as_final(self) -> None:
        assistant = message('assistant', 'Đã mở rồi')
        assistant['message']['parts'].append({'type': 'toolCallRequest'})
        self.assertEqual(finished_answer([message('user', 'Mở máy tính'), assistant,
                                         {'type': 'turnSummary'}], 'Mở máy tính'), (True, ''))

    def test_context_error_is_reported_for_submitted_turn(self) -> None:
        entries = [message('user', 'Xin chào'),
                   {'type': 'error', 'errorCode': 'local_model_context_length_insufficient'}]
        self.assertIn('Chat Bionic hiện quá dài', turn_error(entries, 'Xin chào'))
        self.assertIsNone(turn_error(entries, 'Câu hỏi khác'))

    def test_compaction_model_index_error_explains_long_chat(self) -> None:
        entries = [message('user', 'Mở Portal UT'),
                   {'type': 'error', 'message': 'Indexed model not found: qwen/qwen3.5-4b',
                    'source': {'ngModule': 'lmstudio/context-compaction-v1'}}]
        self.assertIn('thu gọn chat dài', turn_error(entries, 'Mở Portal UT'))

    def test_reads_bionic_context_estimate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'chat.sqlite'
            with closing(sqlite3.connect(path)) as conn, conn:
                conn.execute('CREATE TABLE sessions(session_id TEXT, session_json TEXT)')
                conn.execute('INSERT INTO sessions VALUES(?,?)',
                             ('s', json.dumps({'contextEstimation': {'total': 18814}})))
            self.assertEqual(context_tokens(path, 's'), 18814)

    def test_resolves_selected_tab(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            project = 'd49037d8-47f4-5808-9028-c707de117f8f'
            session = '49627c44-94b6-4a14-b5ab-afded8a16b6d'
            doc = {'tabLayouts': {'bionic.sessions': {'type': 'pane', 'active': 0,
                    'tabs': [f'bionicSession:v2:{project}:lmstudio%2Fbionic-omni:{session}']}}}
            (path / 'window-1.json').write_text(json.dumps(doc))
            self.assertEqual(active_session(path), (project, session))
            doc['tabLayouts']['bionic.sessions']['type'] = 'split'
            (path / 'window-1.json').write_text(json.dumps(doc))
            with self.assertRaises(RuntimeError):
                active_session(path)

    def test_reads_only_entries_after_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'chat.sqlite'
            with sqlite3.connect(path) as conn:
                conn.execute('CREATE TABLE sessions(session_id TEXT, committed_head_entry_id TEXT)')
                conn.execute('CREATE TABLE chat_entries(id TEXT, previous_id TEXT, entry_json TEXT)')
                conn.execute('INSERT INTO sessions VALUES(?,?)', ('s', 'b'))
                conn.execute('INSERT INTO chat_entries VALUES(?,?,?)', ('a', None, json.dumps(message('user', 'Cũ'))))
                conn.execute('INSERT INTO chat_entries VALUES(?,?,?)', ('b', 'a', json.dumps(message('assistant', 'Mới'))))
            conn.close()
            before = path.read_bytes()
            head, entries = read_entries(path, 's', 'a')
            self.assertEqual(head, 'b')
            self.assertEqual(len(entries), 1)
            self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
