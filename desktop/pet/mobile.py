"""TLS-pinned LAN bridge, with an optional loopback Tailscale TCP ingress."""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import logging
from pathlib import Path
from queue import Empty, Full, Queue
import secrets
import socket
import ssl
import threading
import time

import numpy as np
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from .config import ROOT
from .unlock import UnlockGate


@dataclass
class MobileJob:
    samples: np.ndarray
    received_at: float = field(default_factory=time.monotonic)
    done: threading.Event = field(default_factory=threading.Event)
    transcript: str = ''
    reply: str = ''
    audio: bytearray = field(default_factory=bytearray)
    sample_rate: int = 0
    error: str = ''
    abandoned: threading.Event = field(default_factory=threading.Event)
    # Streaming phones receive each rendered sentence as soon as it is ready.
    events: Queue | None = None

    def set_transcript(self, text: str) -> None:
        self.transcript = text
        if self.events is not None and text:
            self.events.put({'transcript': text})

    def add_audio(self, sample_rate: int, pcm: bytes) -> None:
        if not self.sample_rate:
            self.sample_rate = sample_rate
        self.audio.extend(pcm)
        if self.events is not None and pcm:
            self.events.put({'sample_rate': sample_rate,
                             'audio': base64.b64encode(pcm).decode('ascii')})


def _certificate(directory: Path) -> tuple[Path, Path, str]:
    directory.mkdir(parents=True, exist_ok=True)
    cert_path, key_path = directory / 'phone-cert.pem', directory / 'phone-key.pem'
    if not cert_path.exists() or not key_path.exists():
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Alex trên máy tính')])
        now = datetime.now(timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(minutes=5))
                .not_valid_after(now + timedelta(days=3650))
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .sign(key, hashes.SHA256()))
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    return cert_path, key_path, cert.fingerprint(hashes.SHA256()).hex()


def _pc_unlocked() -> bool:
    """Fail closed if this process cannot verify the input desktop."""
    if __import__('os').name != 'nt':
        return True  # Unit tests run outside Windows.
    import ctypes
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.OpenInputDesktop.restype = ctypes.c_void_p
    user.OpenInputDesktop.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
    user.GetUserObjectInformationW.argtypes = [ctypes.c_void_p, ctypes.c_int,
        ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)]
    user.CloseDesktop.argtypes = [ctypes.c_void_p]
    desktop = user.OpenInputDesktop(0, False, 0x0001)
    if not desktop:
        return False
    try:
        buffer = ctypes.create_unicode_buffer(128)
        needed = ctypes.c_ulong()
        if not user.GetUserObjectInformationW(desktop, 2, buffer,
                ctypes.sizeof(buffer), ctypes.byref(needed)):
            return False
        return buffer.value == 'Default'
    finally:
        user.CloseDesktop(desktop)


class _PhoneHTTPServer(ThreadingHTTPServer):
    """Do TLS handshakes in bounded workers, never in the accept loop."""
    daemon_threads = True

    def __init__(self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler],
                 context: ssl.SSLContext) -> None:
        self.tls_context = context
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(address, handler)

    def process_request(self, request: socket.socket, client_address: tuple[str, int]) -> None:
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request: socket.socket,
                               client_address: tuple[str, int]) -> None:
        secure: ssl.SSLSocket | None = None
        try:
            request.settimeout(5)
            secure = self.tls_context.wrap_socket(request, server_side=True)
            secure.settimeout(15)
            self.finish_request(secure, client_address)
        except OSError:
            # Discovery probes intentionally close without sending TLS/HTTP.
            logging.debug('Phone connection closed or timed out')
        except Exception:
            self.handle_error(request, client_address)
        finally:
            try:
                self.shutdown_request(secure if secure is not None else request)
            finally:
                self.slots.release()


class MobileBridge:
    def __init__(self, jobs: Queue[MobileJob], port: int = 8768,
                 bind_host: str = '0.0.0.0', allowed_client_ip: str | None = None,
                 remote_proxy_port: int | None = None) -> None:
        self.jobs = jobs
        self.port = port
        self.bind_host = socket.gethostbyname(socket.gethostname()) if bind_host == 'auto' else bind_host
        ipaddress.IPv4Address(self.bind_host)
        self.allowed_client_ip = (str(ipaddress.IPv4Address(allowed_client_ip))
                                  if allowed_client_ip else None)
        self.data_dir = ROOT / 'data'
        self.cert, self.key, self.fingerprint = _certificate(self.data_dir)
        self.token_hash_path = self.data_dir / 'phone-token.sha256'
        self._code = ''
        self._code_until = 0.0
        self._lock = threading.Lock()
        self.unlock = UnlockGate()
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.remote_proxy_port = remote_proxy_port
        self.proxy_server: ThreadingHTTPServer | None = None
        self.proxy_thread: threading.Thread | None = None

    def pairing_link(self) -> str:
        with self._lock:
            self._code = secrets.token_hex(16)
            self._code_until = time.monotonic() + 300
            code = self._code
        host = (socket.gethostbyname(socket.gethostname()) if self.bind_host == '0.0.0.0'
                else self.bind_host)
        remote_host = self.remote_host() if self.proxy_server else ''
        if remote_host:
            host = remote_host
        if not ipaddress.ip_address(host).is_private and not remote_host:
            raise RuntimeError('Máy tính cần địa chỉ Wi-Fi nội bộ để ghép nối.')
        return f'alexphone://pair?host={host}&port={self.port}&fp={self.fingerprint}&code={code}'

    def remote_host(self) -> str:
        try:
            address = ipaddress.IPv4Address((self.data_dir / 'phone-remote-host.txt').read_text(encoding='ascii').strip())
            return str(address) if address in ipaddress.IPv4Network('100.64.0.0/10') else ''
        except (OSError, ValueError):
            return ''

    def pair(self, code: str) -> str | None:
        with self._lock:
            if time.monotonic() > self._code_until or not self._code or not secrets.compare_digest(code, self._code):
                return None
            self._code = ''
            token = secrets.token_urlsafe(32)
            self.token_hash_path.write_text(hashlib.sha256(token.encode()).hexdigest(), encoding='ascii')
            return token

    def pairing_active(self) -> bool:
        with self._lock:
            return bool(self._code) and time.monotonic() <= self._code_until

    def authorized(self, token: str) -> bool:
        try:
            stored = self.token_hash_path.read_text(encoding='ascii').strip()
            return bool(token) and secrets.compare_digest(hashlib.sha256(token.encode()).hexdigest(), stored)
        except OSError:
            return False

    def revoke(self) -> None:
        self.unlock.revoke()
        self.token_hash_path.unlink(missing_ok=True)

    def client_allowed(self, address: str, *, proxy: bool = False) -> bool:
        try:
            client = ipaddress.ip_address(address)
        except ValueError:
            return False
        if proxy:
            # Only the separate localhost ingress is forwarded by Tailscale Serve.
            # Keep end-to-end TLS and pairing authentication; trust no HTTP headers.
            return client.is_loopback and bool(self.remote_host())
        return client.is_private and (
            not self.allowed_client_ip or str(client) == self.allowed_client_ip)

    def start(self) -> None:
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: object) -> None:
                # Do not log untrusted URLs, authentication headers or request bodies.
                logging.debug('Phone bridge HTTP response')

            def _json(self, status: int, payload: dict) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(body)
                self.wfile.flush()

            def do_POST(self) -> None:
                try:
                    request_started_at = time.monotonic()
                    if not bridge.client_allowed(self.client_address[0],
                            proxy=self.server is bridge.proxy_server):
                        return self._json(403, {'error': 'Điện thoại này không được phép kết nối.'})
                    length = int(self.headers.get('Content-Length', '-1'))
                    if self.path.startswith('/unlock/'):
                        return self._unlock(length)
                    if self.path == '/pair':
                        if length < 1 or length > 1024:
                            return self._json(403, {'error': 'Ghép nối khi PC đang mở khóa.'})
                        code = json.loads(self.rfile.read(length)).get('code', '')
                        if not _pc_unlocked():
                            return self._json(423, {'error': 'Mở khóa Windows trước khi ghép nối.'})
                        token = bridge.pair(code)
                        return self._json(200 if token else 403, {'token': token} if token else {'error': 'Mã ghép nối đã hết hạn.'})
                    if self.path == '/status':
                        if length != 0:
                            return self._json(400, {'error': 'Yêu cầu trạng thái không có nội dung.'})
                        token = self.headers.get('Authorization', '').removeprefix('Bearer ')
                        if not bridge.authorized(token):
                            return self._json(401, {'error': 'Điện thoại chưa ghép nối.'})
                        return self._json(200, {'status': 'ready'})
                    if self.path not in ('/turn', '/turn-stream'):
                        return self._json(404, {'error': 'Không có chức năng này.'})
                    if length < 0 or length > 640000:
                        return self._json(400, {'error': 'Âm thanh phải là PCM16 16 kHz, tối đa 20 giây.'})
                    pcm = self.rfile.read(length)
                    if len(pcm) != length:
                        return self._json(400, {'error': 'Âm thanh chưa đầy đủ.'})
                    token = self.headers.get('Authorization', '').removeprefix('Bearer ')
                    if not bridge.authorized(token):
                        return self._json(401, {'error': 'Điện thoại chưa ghép nối.'})
                    if not _pc_unlocked():
                        return self._json(423, {'error': 'Mở khóa Windows trước khi trò chuyện.'})
                    if length < 3200 or length > 640000 or length % 2:
                        return self._json(400, {'error': 'Âm thanh phải là PCM16 16 kHz, tối đa 20 giây.'})
                    samples = np.frombuffer(pcm, dtype='<i2').astype(np.float32) / 32768
                    job = MobileJob(samples, received_at=request_started_at)
                    streaming = self.path == '/turn-stream'
                    if streaming:
                        job.events = Queue()
                    try:
                        bridge.jobs.put_nowait(job)
                    except Full:
                        return self._json(429, {'error': 'Alex đang bận, thử lại sau.'})
                    if streaming:
                        return self._stream(job)
                    if not job.done.wait(240):
                        job.abandoned.set()
                        return self._json(504, {'error': 'Alex xử lý quá lâu. Kiểm tra Bionic trên PC trước khi hỏi lại.'})
                    if job.error:
                        return self._json(500, {'error': job.error})
                    return self._json(200, {'transcript': job.transcript, 'reply': job.reply,
                        'sample_rate': job.sample_rate,
                        'audio': base64.b64encode(job.audio).decode('ascii')})
                except Exception:
                    logging.error('Phone request failed')
                    try:
                        self._json(500, {'error': 'Kết nối Alex gặp lỗi; xem nhật ký PC.'})
                    except OSError:
                        pass

            def _stream(self, job: MobileJob) -> None:
                """Send NDJSON events: transcript, one audio chunk per sentence, then the final reply."""
                self.send_response(200)
                self.send_header('Content-Type', 'application/x-ndjson; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Connection', 'close')
                self.end_headers()
                self.close_connection = True

                def send(event: dict) -> None:
                    self.wfile.write(json.dumps(event, ensure_ascii=False).encode('utf-8') + b'\n')
                    self.wfile.flush()

                deadline = time.monotonic() + 240
                try:
                    while True:
                        try:
                            send(job.events.get(timeout=0.1))
                            continue
                        except Empty:
                            pass
                        if job.done.is_set() and job.events.empty():
                            break
                        if time.monotonic() > deadline:
                            job.abandoned.set()
                            send({'error': 'Alex xử lý quá lâu. Kiểm tra Alex trên PC trước khi hỏi lại.'})
                            return
                    if job.error:
                        send({'error': job.error})
                    else:
                        send({'done': True, 'transcript': job.transcript, 'reply': job.reply})
                except OSError:
                    # Phone left mid-answer; stop wasting work on it.
                    job.abandoned.set()

            def _unlock(self, length: int) -> None:
                pin = bytearray()
                try:
                    # Drain only a tiny bounded body before an error response, avoiding a
                    # TCP reset that would hide the status from Android. Never interpret
                    # its contents or reach the backend until authentication succeeds.
                    if 0 <= length <= 1024 and not self.headers.get('Transfer-Encoding'):
                        pin = bytearray(length)
                        offset = 0
                        while offset < length:
                            n = self.rfile.readinto(memoryview(pin)[offset:])
                            if not n:
                                return self._json(400, {'status': 'invalid_request'})
                            offset += n
                    token = self.headers.get('Authorization', '').removeprefix('Bearer ')
                    if not bridge.authorized(token):
                        return self._json(401, {'status': 'not_paired'})
                    if self.headers.get('Transfer-Encoding'):
                        return self._json(400, {'status': 'invalid_request'})
                    if self.path in ('/unlock/status', '/unlock/challenge'):
                        if length != 0:
                            return self._json(400, {'status': 'invalid_request'})
                        data = bridge.unlock.status() if self.path.endswith('/status') else bridge.unlock.challenge(token)
                        return self._json(200, data)
                    if self.path != '/unlock/submit' or not 4 <= length <= 20:
                        return self._json(400, {'status': 'invalid_request'})
                    if self.headers.get('Content-Type') != 'application/octet-stream':
                        return self._json(400, {'status': 'invalid_request'})
                    nonce = self.headers.get('X-Alex-Unlock-Challenge', '')
                    if len(nonce) != 32 or any(c not in '0123456789abcdef' for c in nonce):
                        return self._json(400, {'status': 'expired_challenge'})
                    return self._json(200, bridge.unlock.submit(token, nonce, pin))
                except Exception:
                    # No exception payload/traceback from the credential path.
                    try:
                        self._json(500, {'status': 'unknown_result'})
                    except OSError:
                        pass
                finally:
                    pin[:] = b'\0' * len(pin)

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(str(self.cert), str(self.key))
        self.server = _PhoneHTTPServer((self.bind_host, self.port), Handler, context)
        self.thread = threading.Thread(target=self.server.serve_forever, name='Alex-phone-HTTPS', daemon=True)
        self.thread.start()
        logging.info('Phone bridge ready: TLS port %d', self.port)
        if self.remote_proxy_port is not None:
            try:
                self.proxy_server = _PhoneHTTPServer(('127.0.0.1', self.remote_proxy_port), Handler, context)
                self.proxy_thread = threading.Thread(target=self.proxy_server.serve_forever,
                    name='Alex-phone-private-ingress', daemon=True)
                self.proxy_thread.start()
                logging.info('Phone private ingress ready on localhost port %d',
                             self.proxy_server.server_address[1])
            except OSError:
                self.proxy_server = None
                logging.warning('Phone private ingress unavailable; LAN remains active')

    def close(self) -> None:
        for server in (self.proxy_server, self.server):
            if server:
                server.shutdown()
                server.server_close()
        for thread in (self.proxy_thread, self.thread):
            if thread:
                thread.join(timeout=2)
        self.proxy_server = self.server = None
