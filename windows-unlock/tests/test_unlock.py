import importlib.util
import json
import socket
from pathlib import Path
from queue import Queue
import ssl
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType('alex_test_pet')
package.__path__ = [str(ROOT / 'desktop')]
sys.modules['alex_test_pet'] = package
config = types.ModuleType('alex_test_pet.config')
config.ROOT = ROOT / 'unused'
sys.modules['alex_test_pet.config'] = config
from alex_test_pet import mobile, unlock


class GateTests(unittest.TestCase):
    def setUp(self):
        self.calls=[]
        self.now=0.0
        def backend(pin=None):
            if pin is None: return 'locked'
            self.calls.append(bytes(pin))
            return 'unlocked'
        self.gate=unlock.UnlockGate(backend,lambda:self.now)

    def send(self, token='phone', nonce=None, pin=b'1234'):
        nonce=nonce or self.gate.challenge('phone')['challenge']
        data=bytearray(pin)
        result=self.gate.submit(token,nonce,data)
        self.assertEqual(data,bytearray(len(pin)))
        return result['status']

    def test_one_shot_and_wipe(self):
        nonce=self.gate.challenge('phone')['challenge']
        self.assertEqual(self.send(nonce=nonce),'unlocked')
        self.assertEqual(self.send(nonce=nonce),'expired_challenge')
        self.assertEqual(len(self.calls),1)

    def test_wrong_token_expiry_and_revoke(self):
        nonce=self.gate.challenge('phone')['challenge']
        self.assertEqual(self.send('other',nonce),'expired_challenge')
        self.now=16
        self.assertEqual(self.send(nonce=nonce),'expired_challenge')
        nonce=self.gate.challenge('phone')['challenge']; self.gate.revoke()
        self.assertEqual(self.send(nonce=nonce),'expired_challenge')
        self.assertFalse(self.calls)

    def test_invalid_pin_consumes_challenge(self):
        for data in (b'123',b'1'*21,b'12x4',b'12\n4'):
            nonce=self.gate.challenge('phone')['challenge']
            self.assertEqual(self.send(nonce=nonce,pin=data),'invalid_pin')
            self.assertEqual(self.send(nonce=nonce),'expired_challenge')
        self.assertFalse(self.calls)

    def test_backend_exception_never_retries(self):
        nonce=self.gate.challenge('phone')['challenge']
        def fail(pin): raise RuntimeError('deliberately private diagnostic')
        self.gate.backend=fail
        self.assertEqual(self.send(nonce=nonce),'unknown_result')
        self.assertEqual(self.send(nonce=nonce),'expired_challenge')

    def test_parallel_submit_only_once(self):
        entered,release=threading.Event(),threading.Event()
        def backend(pin): entered.set(); release.wait(3); return 'unlocked'
        nonce=self.gate.challenge('phone')['challenge']; self.gate.backend=backend
        t=threading.Thread(target=lambda:self.send(nonce=nonce)); t.start()
        self.assertTrue(entered.wait(2))
        try:
            self.assertEqual(self.send(nonce=nonce),'busy')
            self.assertEqual(self.gate.challenge('phone')['status'],'busy')
        finally: release.set(); t.join(3)

    def test_unlocked_or_unavailable_never_issues_challenge(self):
        for state in ('unlocked','unavailable','service_unavailable'):
            self.gate.backend=lambda:state
            result=self.gate.challenge('phone')
            self.assertEqual(result['status'],state)
            self.assertNotIn('challenge',result)

    def test_later_challenge_invalidates_old_one(self):
        old=self.gate.challenge('phone')['challenge']
        fresh=self.gate.challenge('phone')['challenge']
        self.assertEqual(self.send(nonce=old),'expired_challenge')
        self.assertEqual(self.send(nonce=fresh),'unlocked')
        self.assertEqual(len(self.calls),1)


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.patch=patch.object(mobile,'ROOT',Path(self.directory.name)); self.patch.start()
        self.bridge=mobile.MobileBridge(Queue(),0,'127.0.0.1',remote_proxy_port=0)
        self.calls=[]
        def backend(pin=None):
            if pin is None: return 'locked'
            self.calls.append(len(pin)); return 'unlocked'
        self.bridge.unlock=unlock.UnlockGate(backend)
        self.bridge.start()
        self.token=self.bridge.pair(self.bridge.pairing_link().split('code=')[1])

    def tearDown(self):
        self.bridge.close(); self.patch.stop(); self.directory.cleanup()

    def post(self,path,body=b'',token=None,nonce=None,content='application/octet-stream'):
        headers={'Authorization':'Bearer '+(self.token if token is None else token),'Content-Type':content}
        if nonce: headers['X-Alex-Unlock-Challenge']=nonce
        req=Request('https://127.0.0.1:%d%s'%(self.bridge.server.server_address[1],path),body,headers,method='POST')
        try:
            with urlopen(req,context=ssl._create_unverified_context(),timeout=5) as r: return r.status,json.load(r)
        except HTTPError as e: return e.code,json.load(e)

    def test_auth_before_submission_and_exact_endpoint(self):
        self.assertEqual(self.post('/unlock/submit',b'1234',token='wrong')[0],401)
        self.assertEqual(self.post('/unlock/status?pin=1234')[0],400)
        self.assertEqual(self.post('/unlock/status',b'x')[0],400)
        self.assertFalse(self.calls)

    def test_tls_challenge_submit_replay_and_revoke(self):
        nonce=self.post('/unlock/challenge')[1]['challenge']
        self.assertEqual(self.post('/unlock/submit',b'1234',nonce=nonce)[1]['status'],'unlocked')
        self.assertEqual(self.post('/unlock/submit',b'1234',nonce=nonce)[1]['status'],'expired_challenge')
        self.assertEqual(self.calls,[4])
        self.bridge.revoke()
        self.assertEqual(self.post('/unlock/status')[0],401)

    def test_size_and_content_type_no_action(self):
        nonce=self.post('/unlock/challenge')[1]['challenge']
        for pin in (b'',b'123',b'1'*21): self.assertEqual(self.post('/unlock/submit',pin,nonce=nonce)[0],400)
        self.assertEqual(self.post('/unlock/submit',b'1234',nonce=nonce,content='application/json')[0],400)
        self.assertFalse(self.calls)

    def test_private_remote_host_and_legacy_pairing_persistence(self):
        remote=self.bridge.data_dir/'phone-remote-host.txt'
        remote.write_text('100.90.10.1',encoding='ascii')
        self.assertIn('host=100.90.10.1&',self.bridge.pairing_link())
        remote.write_text('8.8.8.8',encoding='ascii')
        self.assertEqual(self.bridge.remote_host(),'')
        clone=mobile.MobileBridge(Queue(),0,'127.0.0.1')
        self.assertTrue(clone.authorized(self.token))
        self.assertEqual(clone.fingerprint,self.bridge.fingerprint)

    def test_pin_exception_not_in_response_or_logs(self):
        nonce=self.post('/unlock/challenge')[1]['challenge']
        def fail(pin=None): raise RuntimeError('PRIVATE-FIXTURE-'+bytes(pin).decode())
        self.bridge.unlock.backend=fail
        with self.assertLogs(level='DEBUG') as logs:
            response=self.post('/unlock/submit',b'12349876',nonce=nonce)
        self.assertEqual(response[1]['status'],'unknown_result')
        for forbidden in ('12349876','PRIVATE-FIXTURE-',self.token):
            self.assertNotIn(forbidden,'\n'.join(logs.output)+repr(response))

    def test_lost_response_cannot_repeat_action(self):
        nonce=self.post('/unlock/challenge')[1]['challenge']
        entered,release=threading.Event(),threading.Event()
        def backend(pin=None):
            self.calls.append(len(pin)); entered.set(); release.wait(3); return 'unlocked'
        self.bridge.unlock.backend=backend
        request=('POST /unlock/submit HTTP/1.0\r\nHost: localhost\r\n'
                 'Authorization: Bearer '+self.token+'\r\nX-Alex-Unlock-Challenge: '+nonce+
                 '\r\nContent-Type: application/octet-stream\r\nContent-Length: 4\r\n\r\n1234').encode('ascii')
        connection=ssl._create_unverified_context().wrap_socket(socket.create_connection(('127.0.0.1',self.bridge.server.server_address[1]),timeout=3),server_hostname='localhost')
        try:
            connection.sendall(request); self.assertTrue(entered.wait(2)); connection.close(); release.set()
            replay=self.post('/unlock/submit',b'1234',nonce=nonce)
            self.assertIn(replay[1]['status'],('expired_challenge','busy'))
            self.assertEqual(self.calls,[4])
        finally: connection.close(); release.set()

    def test_parallel_network_submits_do_not_duplicate(self):
        nonce=self.post('/unlock/challenge')[1]['challenge']
        barrier=threading.Barrier(6)
        results=[]
        def submit():
            barrier.wait(timeout=3)
            results.append(self.post('/unlock/submit',b'1234',nonce=nonce)[1]['status'])
        workers=[threading.Thread(target=submit) for _ in range(6)]
        for worker in workers: worker.start()
        for worker in workers: worker.join(6)
        self.assertEqual(len(results),6)
        self.assertEqual(results.count('unlocked'),1)
        self.assertEqual(self.calls,[4])


if __name__=='__main__': unittest.main(verbosity=2)
