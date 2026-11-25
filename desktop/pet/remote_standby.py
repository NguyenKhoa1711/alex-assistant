"""Keep Alex's AC power requests scoped to the current Windows session.

Power requests are process-owned and released on battery, unknown power state,
or exit. They do not override Windows' explicit Sleep/lid/power-button actions.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import threading
import time


class _SystemPowerStatus(ctypes.Structure):
    _fields_ = [('ACLineStatus', wintypes.BYTE), ('BatteryFlag', wintypes.BYTE),
                ('BatteryLifePercent', wintypes.BYTE), ('SystemStatusFlag', wintypes.BYTE),
                ('BatteryLifeTime', wintypes.DWORD), ('BatteryFullLifeTime', wintypes.DWORD)]


class _DetailedReason(ctypes.Structure):
    _fields_ = [('Module', wintypes.HMODULE), ('Id', wintypes.ULONG),
                ('Count', wintypes.ULONG), ('Strings', ctypes.POINTER(wintypes.LPWSTR))]


class _ReasonUnion(ctypes.Union):
    _fields_ = [('SimpleReasonString', wintypes.LPWSTR), ('Detailed', _DetailedReason)]


class _ReasonContext(ctypes.Structure):
    _fields_ = [('Version', wintypes.ULONG), ('Flags', wintypes.DWORD),
                ('Reason', _ReasonUnion)]


class _SessionHead(ctypes.Structure):
    _fields_ = [('SessionId', wintypes.DWORD), ('SessionState', ctypes.c_int32),
                ('SessionFlags', ctypes.c_int32)]


class _SessionData(ctypes.Union):
    # WTSINFOEX_LEVEL1 contains 64-bit times; the union is 8-byte aligned.
    _fields_ = [('level1', _SessionHead), ('alignment', ctypes.c_int64)]


class _SessionInfo(ctypes.Structure):
    _fields_ = [('level', wintypes.DWORD), ('data', _SessionData)]


class WindowsPowerRequest:
    def __init__(self) -> None:
        self.api = ctypes.WinDLL('kernel32', use_last_error=True)
        self.api.GetSystemPowerStatus.argtypes = (ctypes.POINTER(_SystemPowerStatus),)
        self.api.GetSystemPowerStatus.restype = wintypes.BOOL
        self.api.PowerCreateRequest.argtypes = (ctypes.POINTER(_ReasonContext),)
        self.api.PowerCreateRequest.restype = wintypes.HANDLE
        for name in ('PowerSetRequest', 'PowerClearRequest'):
            fn = getattr(self.api, name)
            fn.argtypes = (wintypes.HANDLE, ctypes.c_int)
            fn.restype = wintypes.BOOL
        self.api.CloseHandle.argtypes = (wintypes.HANDLE,)
        self.api.CloseHandle.restype = wintypes.BOOL

    def on_ac(self) -> bool:
        status = _SystemPowerStatus()
        if not self.api.GetSystemPowerStatus(ctypes.byref(status)):
            raise ctypes.WinError(ctypes.get_last_error())
        return status.ACLineStatus == 1  # 255 (unknown) must never keep a battery awake.

    def session_unlocked(self) -> bool:
        """Accept only the active, explicitly unlocked current Windows session."""
        wts = ctypes.WinDLL('wtsapi32', use_last_error=True)
        query = wts.WTSQuerySessionInformationW
        query.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.c_int,
                          ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD))
        query.restype = wintypes.BOOL
        wts.WTSFreeMemory.argtypes = (ctypes.c_void_p,)
        data, size = ctypes.c_void_p(), wintypes.DWORD()
        if not query(None, 0xffffffff, 25, ctypes.byref(data), ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not data or size.value < ctypes.sizeof(_SessionInfo):
                return False
            info = ctypes.cast(data, ctypes.POINTER(_SessionInfo)).contents
            # WTSActive == 0 and WTS_SESSIONSTATE_UNLOCK == 1 on Windows 10/11.
            return info.level == 1 and info.data.level1.SessionState == 0 and info.data.level1.SessionFlags == 1
        finally:
            if data:
                wts.WTSFreeMemory(data)

    def _acquire(self, kinds: tuple[int, ...], reason_text: str) -> int:
        reason = _ReasonContext(0, 1, _ReasonUnion(
            SimpleReasonString=reason_text))
        handle = self.api.PowerCreateRequest(ctypes.byref(reason))
        if not handle or handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        applied = []
        try:
            for kind in kinds:
                if not self.api.PowerSetRequest(handle, kind):
                    raise ctypes.WinError(ctypes.get_last_error())
                applied.append(kind)
            return handle
        except BaseException:
            for kind in reversed(applied):
                self.api.PowerClearRequest(handle, kind)
            self.api.CloseHandle(handle)
            raise

    def acquire(self) -> int:
        # The network request remains separate from the display request.
        return self._acquire((1, 3), 'Alex: cho mo khoa tu xa khi cam sac')

    def acquire_display(self) -> int:
        return self._acquire((0,), 'Alex: giu man hinh sang khi cam sac va mo khoa')

    def release(self, handle: int) -> None:
        try:
            for kind in (3, 1):
                self.api.PowerClearRequest(handle, kind)
        finally:
            self.api.CloseHandle(handle)

    def release_display(self, handle: int) -> None:
        try:
            self.api.PowerClearRequest(handle, 0)
        finally:
            self.api.CloseHandle(handle)


class RemoteStandby:
    def __init__(self, enabled: bool, backend=None, *, display_enabled: bool = False) -> None:
        self.enabled = enabled
        self.display_enabled = display_enabled
        self.backend = backend if backend is not None else WindowsPowerRequest()
        self._handle = None
        self._display_handle = None
        self._display_suspended = False
        self._saw_locked = False
        self._session_failed = False
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._failed = False
        self._resume = threading.Event()

    def wants_remote_wait(self) -> bool:
        return self.enabled and not self._stop.is_set() and self.backend.on_ac()

    def update(self) -> bool:
        with self._lock:
            if self._resume.is_set():
                # Windows cancels power requests on explicit Sleep. Recreate
                # the lease after resume instead of trusting the old handle.
                self._resume.clear()
                self._release()
                self._release_display()
            try:
                on_ac = (self.enabled or self.display_enabled) and not self._stop.is_set() and self.backend.on_ac()
            except OSError:
                self._release()
                self._release_display()
                raise
            needed = self.enabled and on_ac
            if needed and self._handle is None:
                self._handle = self.backend.acquire()
                logging.info('REMOTE_WAIT active on AC; display may turn off')
            elif not needed:
                self._release()
            unlocked = False
            session_known = False
            if self.display_enabled and on_ac:
                try:
                    unlocked = self.backend.session_unlocked()
                    session_known = True
                    self._session_failed = False
                except OSError:
                    if not self._session_failed:
                        logging.warning('DISPLAY_AWAKE session state unavailable; request released')
                    self._session_failed = True
            if self._display_suspended:
                if session_known and not unlocked:
                    self._saw_locked = True
                elif session_known and unlocked and self._saw_locked:
                    self._display_suspended = False
                    self._saw_locked = False
            if self.display_enabled and on_ac and unlocked and not self._display_suspended:
                if self._display_handle is None:
                    self._display_handle = self.backend.acquire_display()
                    logging.info('DISPLAY_AWAKE active on AC while session unlocked')
            else:
                self._release_display()
            return self._handle is not None

    def _release(self) -> None:
        if self._handle is not None:
            handle, self._handle = self._handle, None
            self.backend.release(handle)
            logging.info('REMOTE_WAIT released; normal sleep policy applies')

    def _release_display(self) -> None:
        if self._display_handle is not None:
            handle, self._display_handle = self._display_handle, None
            self.backend.release_display(handle)
            logging.info('DISPLAY_AWAKE released')

    def prepare_lock(self) -> None:
        with self._lock:
            self._display_suspended = True
            self._saw_locked = False
            self._release_display()

    def confirm_locked(self) -> None:
        with self._lock:
            if self._display_suspended:
                self._saw_locked = True

    def cancel_lock(self) -> None:
        with self._lock:
            self._display_suspended = False
            self._saw_locked = False
        self.update()

    def require_active(self) -> None:
        if not self.update():
            raise OSError('Chế độ chờ mở khóa từ xa chỉ hoạt động khi cắm sạc.')

    def notify_resume(self) -> None:
        self._resume.set()

    def start(self) -> None:
        if not (self.enabled or self.display_enabled) or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name='Alex-remote-wait', daemon=True)
        try:
            self.update()
        finally:
            self._thread.start()

    def _run(self) -> None:
        last_tick = time.monotonic()
        while not self._stop.wait(2):
            now = time.monotonic()
            if now - last_tick > 10:
                # Some S0 resumes do not deliver WM_POWERBROADCAST to Qt.
                # Recreate cancelled requests after a paused worker resumes.
                self.notify_resume()
            last_tick = now
            try:
                self.update()
                self._failed = False
            except OSError:
                if not self._failed:
                    logging.exception('REMOTE_WAIT power request unavailable')
                self._failed = True

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
        with self._lock:
            self._release()
            self._release_display()


_guard: RemoteStandby | None = None


def start_remote_wait(enabled: bool, *, display_enabled: bool = False) -> None:
    global _guard
    stop_remote_wait()
    _guard = RemoteStandby(enabled, display_enabled=display_enabled)
    _guard.start()


def stop_remote_wait() -> None:
    global _guard
    from .display_priority import cancel_display_priority
    cancel_display_priority()
    if _guard is not None:
        _guard.close()
        _guard = None


def wants_remote_wait() -> bool:
    try:
        return _guard is not None and _guard.wants_remote_wait()
    except OSError:
        return False


def require_remote_wait() -> None:
    if _guard is None:
        raise OSError('Chế độ chờ mở khóa từ xa chưa bật.')
    _guard.require_active()


def prepare_display_for_lock() -> None:
    if _guard is not None:
        _guard.prepare_lock()


def confirm_display_locked() -> None:
    if _guard is not None:
        _guard.confirm_locked()


def cancel_display_lock() -> None:
    if _guard is not None:
        _guard.cancel_lock()


def notify_resume() -> None:
    if _guard is not None:
        _guard.notify_resume()
