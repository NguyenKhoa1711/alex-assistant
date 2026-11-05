"""Exercise the real TLS ingress using synthetic pairing data, never user PINs."""
import hashlib
import json
from pathlib import Path
from queue import Queue
import socket
import ssl
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from test_unlock import mobile


class RemoteBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = patch.object(mobile, 'ROOT', Path(self.temp.name))
        self.root.start()
        self.bridge = mobile.MobileBridge(Queue(), 0, '127.0.0.1',
            allowed_client_ip='192.168.42.151', remote_proxy_port=0)
        self.bridge.start()
        self.remote = self.bridge.data_dir / 'phone-remote-host.txt'
        self.token = self.bridge.pair(self.bridge.pairing_link().split('code=')[1])

    def tearDown(self):
        self.bridge.close()
        self.root.stop()
        self.temp.cleanup()

    def post(self, server, path='/status', token='', body=b'', headers=None):
        req = Request('https://127.0.0.1:%d%s' % (server.server_address[1], path),
            body, {'Authorization': 'Bearer ' + token, **(headers or {})}, method='POST')
        try:
            with urlopen(req, context=ssl._create_unverified_context(), timeout=4) as reply:
                return reply.status, json.load(reply)
        except HTTPError as error:
            return error.code, json.load(error)

    def test_proxy_disabled_until_configured(self):
        self.assertEqual(self.post(self.bridge.proxy_server, token=self.token)[0], 403)
        self.remote.write_text('8.8.8.8', encoding='ascii')
        self.assertEqual(self.post(self.bridge.proxy_server, token=self.token)[0], 403)

    def test_private_proxy_keeps_auth_and_lan_ip_restriction(self):
        self.remote.write_text('100.80.10.1', encoding='ascii')
        self.assertEqual(self.post(self.bridge.proxy_server)[0], 401)
        self.assertEqual(self.post(self.bridge.proxy_server, token=self.token),
                         (200, {'status': 'ready'}))
        self.assertEqual(self.post(self.bridge.server, token=self.token,
            headers={'X-Forwarded-For': '192.168.42.151'})[0], 403)
        self.assertFalse(self.bridge.client_allowed('100.80.10.2'))
        self.assertFalse(self.bridge.client_allowed('8.8.8.8', proxy=True))
        self.assertFalse(self.bridge.client_allowed('192.168.42.151', proxy=True))

    def test_proxy_uses_original_certificate_and_revocation(self):
        self.remote.write_text('100.80.10.1', encoding='ascii')
        port = self.bridge.proxy_server.server_address[1]
        with ssl._create_unverified_context().wrap_socket(
                socket.create_connection(('127.0.0.1', port), timeout=3),
                server_hostname='localhost') as connection:
            cert_bytes = connection.getpeercert(binary_form=True)
            actual = hashlib.sha256(cert_bytes).hexdigest()
        issuer = mobile.x509.load_der_x509_certificate(cert_bytes).issuer.rfc4514_string()
        self.assertEqual(actual, self.bridge.fingerprint,
                         'TLS certificate changed in transit; received issuer: ' + issuer)
        self.bridge.revoke()
        self.assertEqual(self.post(self.bridge.proxy_server, token=self.token)[0], 401)

    def test_missing_service_reports_unavailable_without_pin(self):
        self.remote.write_text('100.80.10.1', encoding='ascii')
        self.bridge.unlock.backend = lambda: 'service_unavailable'
        for route in ('/unlock/status', '/unlock/challenge'):
            status, data = self.post(self.bridge.proxy_server, path=route, token=self.token)
            self.assertEqual(status, 200)
            self.assertEqual(data['status'], 'service_unavailable')
            self.assertNotIn('challenge', data)

    def test_busy_local_port_does_not_stop_lan(self):
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1', 0))
            occupied.listen()
            other = mobile.MobileBridge(Queue(), 0, '127.0.0.1',
                remote_proxy_port=occupied.getsockname()[1])
            try:
                with self.assertLogs(level='WARNING'):
                    other.start()
                self.assertIsNone(other.proxy_server)
                self.assertNotIn('100.80.10.1', other.pairing_link())
                self.assertEqual(self.post(other.server)[0], 401)
            finally:
                other.close()

    def test_close_releases_both_ports(self):
        ports = [s.server_address[1] for s in (self.bridge.server, self.bridge.proxy_server)]
        self.bridge.close()
        for port in ports:
            with self.assertRaises(OSError):
                socket.create_connection(('127.0.0.1', port), timeout=.5)


if __name__ == '__main__':
    unittest.main(verbosity=2)
