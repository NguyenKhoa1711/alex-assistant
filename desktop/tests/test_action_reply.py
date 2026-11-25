import threading
import time
import unittest
from unittest.mock import MagicMock, patch
import httpx
import numpy as np
from pet.action_reply import safe_action_reply, phrase_action_result, style_action_result
from pet.apps import LaunchResult
from pet.audio import Utterance
from pet.config import load_config
from pet.controller import Controller
from pet.audio_jobs import AudioJob as MobileJob

class ActionReplyTests(unittest.TestCase):

    def test_boilerplate_address_does_not_change_names_or_status(self):
        cases = [('Mình đã mở ứng dụng Bạn của Tôi.', 'Tao đã mở ứng dụng Bạn của Tôi.'), ('Mình chưa mở được C:\\Bạn\\Mình.txt.', 'Tao chưa mở được C:\\Bạn\\Mình.txt.'), ('Bạn muốn mở ứng dụng nào?', 'Mày muốn mở ứng dụng nào?'), ('Ứng dụng Bạn chưa mở.', 'Ứng dụng Bạn chưa mở.'), ('Mình chưa xác nhận. Bạn thử lại nhé.', 'Tao chưa xác nhận. Mày thử lại nhé.')]
        for original, expected in cases:
            with self.subTest(original=original):
                self.assertEqual(style_action_result(original), expected)

    def test_accepts_faithful_rephrasing(self):
        for source, answer in [('Mình đã mở Notion.', 'Notion đã được mở.'), ('Mình chưa xác nhận được cửa sổ Notion đã mở.', 'Chưa xác nhận cửa sổ Notion đã mở.'), ('Mình đã gửi địa chỉ Portal UT tới trình duyệt.', 'Địa chỉ Portal UT đã được gửi tới trình duyệt.'), ('Đã dừng.', 'Đã dừng rồi nhé.')]:
            with self.subTest(answer=answer):
                self.assertTrue(safe_action_reply(source, answer))

    def test_rejects_invented_actions_or_changed_numbers(self):
        for source, answer in [('Mình chưa xác nhận được cửa sổ Notion đã mở.', 'Mình đã mở Notion.'), ('Mình chưa xác nhận được cửa sổ Notion đã mở.', 'Chưa chưa xác nhận cửa sổ Notion đã mở.'), ('Mình chưa xác nhận được cửa sổ Notion đã mở.', 'Chưa mở Notion đã xác nhận được cửa sổ.'), ('Mình đã mở Notion.', 'Mình đã mở Zalo.'), ('Mình đã gửi địa chỉ Portal UT tới trình duyệt.', 'Mình đã mở trang Portal UT.'), ('Âm lượng đang ở 40 phần trăm.', 'Âm lượng đang ở 90 phần trăm.'), ('Tăng từ 20 lên 30.', 'Tăng từ 30 lên 20.'), ('Mình đã mở Notion.', 'Mình đã mở Notion. Mình xóa file rồi.'), ('Bạn muốn mở ứng dụng nào?', 'Mình đã mở ứng dụng.')]:
            with self.subTest(answer=answer):
                self.assertFalse(safe_action_reply(source, answer))

    def test_model_response_is_stateless_local_and_tool_free(self):
        response = MagicMock()
        response.json.return_value = {'choices': [{'finish_reason': 'stop', 'message': {'content': 'Notion đã được mở.'}}]}
        client = MagicMock()
        client.__enter__.return_value = client
        client.post.return_value = response
        config = {'base_url': 'http://127.0.0.1:18440', 'model': 'alex-gemma'}
        with patch('pet.action_reply.httpx.Client', return_value=client):
            self.assertEqual(phrase_action_result(config, 'Mở Notion', 'Mình đã mở Notion.', threading.Event()), 'Notion đã được mở.')
        payload = client.post.call_args.kwargs['json']
        self.assertNotIn('tools', payload)
        self.assertIn('xưng tao', payload['messages'][0]['content'])
        self.assertEqual(len(payload['messages']), 2)
        self.assertIn('Mình đã mở Notion.', payload['messages'][1]['content'])

    def test_timeout_unsafe_or_unfinished_answer_falls_back_to_fact(self):
        config = {'base_url': 'http://127.0.0.1:18440', 'model': 'alex-gemma'}
        evidence = 'Mình chưa xác nhận được cửa sổ Notion đã mở.'
        for response_value in [httpx.ReadTimeout('slow'), {'choices': [{'finish_reason': 'stop', 'message': {'content': 'Mình đã mở Notion.'}}]}, {'choices': [{'finish_reason': 'length', 'message': {'content': 'Chưa xác nhận cửa sổ Notion đã mở.'}}]}]:
            client = MagicMock()
            client.__enter__.return_value = client
            if isinstance(response_value, Exception):
                client.post.side_effect = response_value
            else:
                client.post.return_value.json.return_value = response_value
            with patch('pet.action_reply.httpx.Client', return_value=client):
                self.assertEqual(phrase_action_result(config, 'Mở Notion', evidence, threading.Event()), evidence)
        event = threading.Event()
        event.set()
        with patch('pet.action_reply.httpx.Client') as client:
            self.assertEqual(phrase_action_result(config, 'Mở Notion', evidence, event), evidence)
            client.assert_not_called()

    def test_action_is_executed_once_and_model_reply_is_used(self):
        with patch('pet.llm.httpx.Client'):
            engine = Controller(load_config())
        self.addCleanup(engine.local_chat._client.close)
        self.addCleanup(engine.gemini_chat._client.close)
        engine.speaker = MagicMock()
        engine.gemini_chat.stream = MagicMock()
        with patch('pet.controller.open_registered_app', return_value=LaunchResult('Spotify', True, True, 0.1)) as launch, patch('pet.controller.phrase_action_result', return_value='Spotify đã được mở.') as model:
            answer = engine._answer('Mở Spotify', Utterance(np.zeros(100), time.monotonic()), 0)
        self.assertEqual(answer, 'Spotify đã được mở.')
        launch.assert_called_once()
        model.assert_called_once()
        self.assertEqual(model.call_args.args[2], 'Tao đã mở Spotify.')
        engine.gemini_chat.stream.assert_not_called()
        self.assertEqual(engine.gemini_chat.history[-1], ('Mở Spotify', 'Spotify đã được mở.'))

    def test_phone_text_and_audio_use_the_same_rephrased_result(self):
        with patch('pet.llm.httpx.Client'):
            engine = Controller(load_config())
        self.addCleanup(engine.local_chat._client.close)
        self.addCleanup(engine.gemini_chat._client.close)
        engine.speaker = MagicMock()
        engine.speaker.render_pcm.return_value = (48000, b'\x00\x00' * 100)
        job = MobileJob(np.zeros(100))
        utterance = Utterance(np.zeros(100), time.monotonic())
        with patch('pet.controller.open_registered_app', return_value=LaunchResult('Spotify', True, True, 0.1)), patch('pet.controller.phrase_action_result', return_value='Spotify đã được mở.'):
            answer = engine._answer('Mở Spotify', utterance, 0, job)
        self.assertEqual(answer, 'Spotify đã được mở.')
        self.assertEqual(job.sample_rate, 48000)
        self.assertGreater(len(job.audio), 0)
        self.assertEqual(engine.speaker.render_pcm.call_args.args[0], 'Spotify đã được mở.')

    def test_verified_failure_and_mobile_audio_keep_status_and_address(self):
        with patch('pet.llm.httpx.Client'):
            engine = Controller(load_config())
        self.addCleanup(engine.local_chat._client.close)
        self.addCleanup(engine.gemini_chat._client.close)
        engine.speaker = MagicMock()
        engine.speaker.render_pcm.return_value = (48000, b'\x00\x00' * 100)
        job = MobileJob(np.zeros(100))
        utterance = Utterance(np.zeros(100), time.monotonic())
        evidence = 'Mình chưa xác nhận được cửa sổ Spotify đã mở.'
        with patch('pet.controller.open_registered_app', return_value=LaunchResult('Spotify', False, False, 0.1)), patch('pet.controller.phrase_action_result', side_effect=lambda cfg, q, result, c: result):
            answer = engine._answer('Mở Spotify', utterance, 0, job)
        self.assertEqual(answer, style_action_result(evidence))
        self.assertEqual(engine.speaker.render_pcm.call_args.args[0], answer)

    def test_power_action_skips_model(self):
        with patch('pet.llm.httpx.Client'):
            engine = Controller(load_config())
        self.addCleanup(engine.local_chat._client.close)
        self.addCleanup(engine.gemini_chat._client.close)
        engine.speaker = MagicMock()
        engine._action_reply_question = 'Tắt nguồn'
        with patch('pet.controller.phrase_action_result') as model:
            emitted = []
            engine.reply.connect(emitted.append)
            engine._speak_action_result('Mình sẽ tắt nguồn bây giờ.', Utterance(np.zeros(10), time.monotonic()), 0, None, 'lệnh nguồn')
        model.assert_not_called()
        self.assertEqual(emitted[-1], 'Tao sẽ tắt nguồn bây giờ.')
if __name__ == '__main__':
    unittest.main()
