"""TLS-pinned LAN bridge for the Alex Android companion."""
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
from queue import Full, Queue
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
                 bind_host: str = '0.0.0.0', allowed_client_ip: str | None = None) -> None:
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
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    def pairing_link(self) -> str:
        with self._lock:
            self._code = secrets.token_hex(16)
            self._code_until = time.monotonic() + 300
            code = self._code
        host = (socket.gethostbyname(socket.gethostname()) if self.bind_host == '0.0.0.0'
                else self.bind_host)
        if not ipaddress.ip_address(host).is_private:
            raise RuntimeError('Máy tính cần địa chỉ Wi-Fi nội bộ để ghép nối.')
        return f'alexphone://pair?host={host}&port={self.port}&fp={self.fingerprint}&code={code}'

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
        self.token_hash_path.unlink(missing_ok=True)

    def start(self) -> None:
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: object) -> None:
                logging.info('Phone bridge: ' + fmt, *args)

            def _json(self, status: int, payload: dict) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:
                try:
                    client = ipaddress.ip_address(self.client_address[0])
                    if not client.is_private:
                        return self._json(403, {'error': 'Chỉ mạng nội bộ.'})
                    if bridge.allowed_client_ip and str(client) != bridge.allowed_client_ip:
                        return self._json(403, {'error': 'Điện thoại này không được phép kết nối.'})
                    length = int(self.headers.get('Content-Length', '-1'))
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
                    if self.path != '/turn':
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
                    job = MobileJob(samples)
                    try:
                        bridge.jobs.put_nowait(job)
                    except Full:
                        return self._json(429, {'error': 'Alex đang bận, thử lại sau.'})
                    if not job.done.wait(240):
                        job.abandoned.set()
                        return self._json(504, {'error': 'Alex xử lý quá lâu. Kiểm tra Bionic trên PC trước khi hỏi lại.'})
                    if job.error:
                        return self._json(500, {'error': job.error})
                    return self._json(200, {'transcript': job.transcript, 'reply': job.reply,
                        'sample_rate': job.sample_rate,
                        'audio': base64.b64encode(job.audio).decode('ascii')})
                except Exception:
                    logging.exception('Phone request failed')
                    try:
                        self._json(500, {'error': 'Kết nối Alex gặp lỗi; xem nhật ký PC.'})
                    except OSError:
                        pass

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(str(self.cert), str(self.key))
        self.server = _PhoneHTTPServer((self.bind_host, self.port), Handler, context)
        self.thread = threading.Thread(target=self.server.serve_forever, name='Alex-phone-HTTPS', daemon=True)
        self.thread.start()
        logging.info('Phone bridge ready: TLS port %d', self.port)

    def close(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
