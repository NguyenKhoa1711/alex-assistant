"""One-shot, authenticated PIN delivery; never log or persist request bodies."""
from __future__ import annotations

import hashlib
import os
import secrets
import threading
import time


def _pipe_call(pin: bytearray | None = None) -> str:
    if os.name != 'nt':
        return 'service_unavailable'
    import pywintypes
    import win32event
    import win32file
    import win32pipe
    import win32service
    pipe = manager = service = None
    frame = bytearray([0]) if pin is None else bytearray([1, len(pin)]) + pin
    try:
        manager = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
        service = win32service.OpenService(manager, 'AlexUnlock', win32service.SERVICE_QUERY_STATUS | win32service.SERVICE_QUERY_CONFIG)
        config = win32service.QueryServiceConfig(service)
        if config[3].strip('"').lower() != r'd:\alexunlock-system\alexunlock.exe':
            return 'service_unavailable'
        state = win32service.QueryServiceStatusEx(service)
        if state['CurrentState'] != win32service.SERVICE_RUNNING:
            return 'service_unavailable'
        win32pipe.WaitNamedPipe(r'\\.\pipe\Alex.Unlock.v1', 1200)
        pipe = win32file.CreateFile(r'\\.\pipe\Alex.Unlock.v1', 0xC0000000, 0, None, 3,
                                   win32file.FILE_FLAG_OVERLAPPED, None)
        # Never release a PIN to an impersonating, user-owned named pipe.
        if win32pipe.GetNamedPipeServerProcessId(pipe) != state['ProcessId']:
            return 'service_unavailable'

        def io(write: bool):
            ov = pywintypes.OVERLAPPED()
            ov.hEvent = win32event.CreateEvent(None, True, False, None)
            try:
                _, data = win32file.WriteFile(pipe, frame, ov) if write else win32file.ReadFile(pipe, 64, ov)
                if win32event.WaitForSingleObject(ov.hEvent, 23000 if pin is not None else 2000) != 0:
                    win32file.CancelIoEx(pipe, ov)
                    # Let cancellation complete before releasing the OVERLAPPED buffer.
                    win32event.WaitForSingleObject(ov.hEvent, 2000)
                    raise TimeoutError()
                count = win32file.GetOverlappedResult(pipe, ov, False)
                return count if write else bytes(data[:count]).decode('ascii').strip()
            finally:
                ov.hEvent.Close()

        if io(True) != len(frame):
            return 'unknown_result'
        code = io(False)
        return code if code in {'locked', 'unlocked', 'unavailable', 'not_locked',
            'rate_limited', 'helper_unavailable', 'pin_field_unavailable', 'unknown_result'} else 'unknown_result'
    except Exception:
        return 'service_unavailable' if pin is None else 'unknown_result'
    finally:
        frame[:] = b'\0' * len(frame)
        if pipe is not None:
            pipe.Close()
        if service is not None:
            win32service.CloseServiceHandle(service)
        if manager is not None:
            win32service.CloseServiceHandle(manager)


class UnlockGate:
    """Short-lived challenge bound to pairing token. No retries after consumption."""
    def __init__(self, backend=_pipe_call, clock=time.monotonic):
        self.backend = backend
        self.clock = clock
        self.lock = threading.Lock()
        self.pending: tuple[str, bytes, float] | None = None
        self.busy = False

    def status(self) -> dict:
        return {'status': self.backend(), 'protocol': 1}

    def challenge(self, token: str) -> dict:
        with self.lock:
            if self.busy:
                return {'status': 'busy'}
            code = self.backend()
            if code != 'locked':
                return {'status': code}
            nonce = secrets.token_hex(16)
            self.pending = (nonce, hashlib.sha256(token.encode()).digest(), self.clock() + 15)
            return {'status': 'ready', 'challenge': nonce, 'expires_seconds': 15}

    def submit(self, token: str, nonce: str, pin: bytearray) -> dict:
        try:
            with self.lock:
                entry = self.pending
                if self.busy:
                    return {'status': 'busy'}
                if (entry is None or self.clock() > entry[2]
                        or not secrets.compare_digest(entry[0], nonce)
                        or not secrets.compare_digest(entry[1], hashlib.sha256(token.encode()).digest())):
                    return {'status': 'expired_challenge'}
                self.pending = None  # consume before validating or delivering the PIN
                if not 4 <= len(pin) <= 20 or any(b < 48 or b > 57 for b in pin):
                    return {'status': 'invalid_pin'}
                self.busy = True
            try:
                return {'status': self.backend(pin)}
            except Exception:
                return {'status': 'unknown_result'}
            finally:
                with self.lock:
                    self.busy = False
        finally:
            pin[:] = b'\0' * len(pin)

    def revoke(self):
        with self.lock:
            self.pending = None
