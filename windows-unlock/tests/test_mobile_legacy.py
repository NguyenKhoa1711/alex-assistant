from __future__ import annotations

import base64
from http.client import RemoteDisconnected
from queue import Queue
import ssl
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch
import json

from test_unlock import mobile


class MobileBridgeTests(unittest.TestCase):
    def test_pair_once_authenticate_and_revoke(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(mobile, 'ROOT', mobile.Path(directory)):
            jobs: Queue[mobile.MobileJob] = Queue(maxsize=1)
            bridge = mobile.MobileBridge(jobs, 0)
            bridge.start()
            port = bridge.server.server_address[1]
            context = ssl._create_unverified_context()

            def post(path: str, body: bytes, token: str = '') -> tuple[int, dict]:
                request = Request(f'https://127.0.0.1:{port}{path}', body,
                    headers={'Authorization': 'Bearer ' + token} if token else {}, method='POST')
                try:
                    with urlopen(request, context=context, timeout=5) as reply:
                        return reply.status, json.load(reply)
                except HTTPError as error:
                    return error.code, json.load(error)

            try:
                link = bridge.pairing_link()
                self.assertTrue(bridge.pairing_active())
                code = link.split('code=', 1)[1]
                self.assertEqual(post('/pair', b'{"code":"wrong"}')[0], 403)
                status, pair = post('/pair', json.dumps({'code': code}).encode())
                self.assertEqual(status, 200)
                token = pair['token']
                self.assertFalse(bridge.pairing_active())
                self.assertEqual(post('/pair', json.dumps({'code': code}).encode())[0], 403)
                self.assertEqual(post('/status', b'')[0], 401)
                self.assertEqual(post('/status', b'', token), (200, {'status': 'ready'}))
                self.assertEqual(post('/turn', b'\x00\x00' * 1600)[0], 401)
                self.assertEqual(post('/turn', b'\x00\x00' * 1000, token)[0], 400)
                with patch.object(mobile, '_pc_unlocked', return_value=False):
                    self.assertEqual(post('/turn', b'\x00\x00' * 2000, token)[0], 423)
                # A real 0.1-second PCM request is queued for the pet worker.
                def answer() -> None:
                    job = jobs.get(timeout=5)
                    job.transcript = 'Xin chào'
                    job.reply = 'Chào bạn.'
                    job.audio.extend(b'\x01\x00' * 100)
                    job.sample_rate = 22050
                    job.done.set()
                worker = threading.Thread(target=answer)
                worker.start()
                status, result = post('/turn', b'\x00\x00' * 2000, token)
                worker.join(5)
                self.assertEqual(status, 200)
                self.assertEqual(result['transcript'], 'Xin chào')
                self.assertEqual(base64.b64decode(result['audio']), b'\x01\x00' * 100)
                bridge.revoke()
                self.assertEqual(post('/status', b'', token)[0], 401)
                self.assertEqual(post('/turn', b'\x00\x00' * 2000, token)[0], 401)
            finally:
                bridge.close()

    def test_pairing_token_survives_bridge_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(mobile, 'ROOT', mobile.Path(directory)):
            first = mobile.MobileBridge(Queue(), 0)
            token = first.pair(first.pairing_link().split('code=', 1)[1])
            self.assertIsNotNone(token)
            second = mobile.MobileBridge(Queue(), 0)
            self.assertTrue(second.authorized(token))
            self.assertEqual(second.fingerprint, first.fingerprint)

    def test_other_phone_ip_cannot_pair(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(mobile, 'ROOT', mobile.Path(directory)):
            bridge = mobile.MobileBridge(Queue(), 0, bind_host='127.0.0.1',
                                         allowed_client_ip='192.168.42.151')
            bridge.start()
            try:
                self.assertEqual(bridge.server.server_address[0], '127.0.0.1')
                port = bridge.server.server_address[1]
                request = Request(f'https://127.0.0.1:{port}/pair', b'{"code":"test"}', method='POST')
                try:
                    with self.assertRaises(HTTPError) as error:
                        urlopen(request, context=ssl._create_unverified_context(), timeout=5)
                    self.assertEqual(error.exception.code, 403)
                except RemoteDisconnected:
                    # Windows may reset an unauthorised POST before the 403 is read.
                    pass
                self.assertFalse(bridge.token_hash_path.exists())
            finally:
                bridge.close()


if __name__ == '__main__':
    unittest.main()
