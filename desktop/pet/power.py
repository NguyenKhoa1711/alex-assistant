"""Explicit Windows power commands; never infer them from general chat."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import os
import re
import subprocess
import sys
import time
from typing import Literal

from .app_actions import folded
from .remote_standby import wants_remote_wait, require_remote_wait
from .unlock import UnlockGate
from .display_priority import begin_display_priority, confirm_display_priority, cancel_display_priority

PowerAction = Literal['sleep', 'shutdown', 'wake', 'remote_wait']

DEFAULT_SLEEP_PHRASES = ('tắt máy', 'tắt máy tính', 'cho máy ngủ',
                         'cho máy tính ngủ', 'đưa máy vào chế độ ngủ')
DEFAULT_SHUTDOWN_PHRASES = ('tắt nguồn', 'tắt nguồn máy tính', 'shutdown máy')
DEFAULT_WAKE_PHRASES = (
    'bật máy', 'bật máy lên', 'bật máy tính', 'bật máy tính lên',
    'mở máy', 'mở máy lên', 'mở nguồn', 'mở nguồn máy', 'mở nguồn máy tính',
    'bật nguồn', 'bật nguồn máy', 'bật nguồn máy tính',
    'đánh thức máy', 'đánh thức máy tính', 'cho máy thức dậy',
    'bật màn hình', 'bật màn hình lên', 'mở màn hình', 'mở màn hình lên',
    'sáng màn hình', 'sáng màn hình lên',
)


def _key(text: str) -> str:
    return ' '.join(re.sub(r'[^a-z0-9 ]+', ' ', folded(text)).split())


def _command_key(text: str) -> str:
    key = _key(text)
    prefixes = ('alex oi ', 'alex ', 'a lech ', 'ban oi ', 'ban ', 'hay ',
                'vui long ', 'lam on ', 'giup toi ', 'giup minh ',
                'cho toi ', 'cho minh ', 'toi muon ', 'minh muon ')
    suffixes = (' cho toi', ' cho minh', ' giup toi', ' giup minh',
                ' tren may tinh', ' tren me tinh', ' tren laptop', ' tren pc',
                ' di', ' nhe', ' ngay', ' len', ' voi')
    for _ in range(4):
        prefix = next((part for part in prefixes if key.startswith(part)), None)
        if prefix is None:
            break
        key = key[len(prefix):]
    for _ in range(4):
        suffix = next((part for part in suffixes if key.endswith(part)), None)
        if suffix is None:
            break
        key = key[:-len(suffix)]
    return key.strip()


def parse_power_request(text: str, config: dict | None = None) -> PowerAction | None:
    """Accept one complete imperative only; quoted or compound requests stay in chat."""
    config = config or {}
    key = _command_key(text)
    sleep = {_key(part) for part in config.get('sleep_phrases', DEFAULT_SLEEP_PHRASES)}
    shutdown = {_key(part) for part in config.get('shutdown_phrases', DEFAULT_SHUTDOWN_PHRASES)}
    wake = {_key(part) for part in config.get('wake_phrases', DEFAULT_WAKE_PHRASES)}
    if key in sleep and key not in shutdown and key not in wake:
        return 'sleep'
    if key in shutdown and key not in sleep and key not in wake:
        return 'shutdown'
    if key in wake and key not in sleep and key not in shutdown:
        return 'wake'
    return None


class _Luid(ctypes.Structure):
    _fields_ = [('LowPart', wintypes.DWORD), ('HighPart', wintypes.LONG)]


class _LuidAndAttributes(ctypes.Structure):
    _fields_ = [('Luid', _Luid), ('Attributes', wintypes.DWORD)]


class _TokenPrivileges(ctypes.Structure):
    _fields_ = [('PrivilegeCount', wintypes.DWORD),
                ('Privileges', _LuidAndAttributes * 1)]


def _monitor_target_hwnd(user: object) -> int:
    """Return a single top-level HWND; never use HWND_BROADCAST (0xFFFF) for sleep."""
    for name in ('GetShellWindow', 'GetForegroundWindow', 'GetDesktopWindow'):
        fn = getattr(user, name, None)
        if fn is None:
            continue
        fn.argtypes = ()
        fn.restype = wintypes.HWND
        hwnd = fn()
        if hwnd and int(hwnd) != 0xFFFF:
            return int(hwnd)
    return 0


def _turn_off_display_for_s0() -> None:
    """On Modern Standby, turning the display off starts the S0 idle transition."""
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.SendMessageTimeoutW.argtypes = (
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t))
    user.SendMessageTimeoutW.restype = ctypes.c_size_t
    target = _monitor_target_hwnd(user)
    result = ctypes.c_size_t()
    ctypes.set_last_error(0)
    # Target a single window instead of HWND_BROADCAST (0xFFFF) so user32 does not
    # resume iterating remaining top-level windows and re-blank the screen upon wake.
    sent = user.SendMessageTimeoutW(target, 0x0112, 0xF170, 2,
                                    0x0002, 1000, ctypes.byref(result))
    if not sent:
        error = ctypes.get_last_error()
        raise ctypes.WinError(error) if error else OSError('Windows không tắt được màn hình.')


def _enable_shutdown_privilege() -> None:
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    advapi.OpenProcessToken.argtypes = (wintypes.HANDLE, wintypes.DWORD,
                                       ctypes.POINTER(wintypes.HANDLE))
    advapi.LookupPrivilegeValueW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR,
                                            ctypes.POINTER(_Luid))
    advapi.AdjustTokenPrivileges.argtypes = (
        wintypes.HANDLE, wintypes.BOOL, ctypes.POINTER(_TokenPrivileges),
        wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p)
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x28,
                                  ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        luid = _Luid()
        if not advapi.LookupPrivilegeValueW(None, 'SeShutdownPrivilege',
                                            ctypes.byref(luid)):
            raise ctypes.WinError(ctypes.get_last_error())
        privileges = _TokenPrivileges(1, (_LuidAndAttributes(luid, 0x2),))
        ctypes.set_last_error(0)
        if not advapi.AdjustTokenPrivileges(token, False,
                                            ctypes.byref(privileges), 0, None, None):
            raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error():
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.CloseHandle(token)


def _wake_display() -> None:
    """Wake display from S0 Modern Standby / monitor power-off."""
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    user = ctypes.WinDLL('user32', use_last_error=True)
    kernel.SetThreadExecutionState.argtypes = (wintypes.DWORD,)
    kernel.SetThreadExecutionState.restype = wintypes.DWORD
    kernel.SetThreadExecutionState(0x00000003)
    user.SendMessageTimeoutW.argtypes = (
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t))
    user.SendMessageTimeoutW.restype = ctypes.c_size_t
    target = _monitor_target_hwnd(user)
    result = ctypes.c_size_t()
    user.SendMessageTimeoutW(target, 0x0112, 0xF170, -1,
                             0x0002, 1000, ctypes.byref(result))
    user.mouse_event.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.DWORD, ctypes.c_size_t)
    user.mouse_event(0x0001, 0, 1, 0, 0)


def resolve_power_action(action: PowerAction) -> PowerAction:
    return 'remote_wait' if action == 'sleep' and wants_remote_wait() else action


def _lock_and_wait_remotely() -> None:
    require_remote_wait()
    ticket = begin_display_priority()
    try:
        user = ctypes.WinDLL('user32', use_last_error=True)
        user.LockWorkStation.argtypes = ()
        user.LockWorkStation.restype = wintypes.BOOL
        if not user.LockWorkStation():
            raise ctypes.WinError(ctypes.get_last_error())
        deadline = time.monotonic() + 3
        gate = UnlockGate()
        while time.monotonic() < deadline:
            if gate.status().get('status') == 'locked':
                # Automatic display idle only. The privileged helper restores
                # Antigravity's display request and timeout after unlock.
                require_remote_wait()
                confirm_display_priority(ticket)
                logging.info('REMOTE_WAIT locked; temporary display priority; no monitor-power command')
                return
            time.sleep(0.1)
        raise OSError('Chưa xác nhận Windows đã khóa; giữ màn hình để kiểm tra.')
    except BaseException:
        cancel_display_priority()
        raise


def execute_power(action: PowerAction) -> None:
    """Execute one explicitly routed power action; never force-close applications."""
    if sys.platform != 'win32':
        raise OSError('Lệnh nguồn chỉ hỗ trợ Windows.')
    if action == 'wake':
        _wake_display()
        return
    if action == 'remote_wait':
        _lock_and_wait_remotely()
        return
    if action == 'shutdown':
        program = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'),
                               'System32', 'shutdown.exe')
        subprocess.run([program, '/s', '/t', '0'], check=True, timeout=10,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        return
    if action != 'sleep':
        raise ValueError('Lệnh nguồn không hợp lệ.')
    _enable_shutdown_privilege()
    power = ctypes.WinDLL('PowrProf', use_last_error=True)
    power.SetSuspendState.argtypes = (wintypes.BOOLEAN, wintypes.BOOLEAN,
                                      wintypes.BOOLEAN)
    power.SetSuspendState.restype = wintypes.BOOLEAN
    if not power.SetSuspendState(False, False, False):
        error = ctypes.get_last_error()
        if error != 50:  # ERROR_NOT_SUPPORTED: common on S0 Modern Standby.
            raise ctypes.WinError(error)
        logging.info('SetSuspendState unsupported (WinError 50); requesting S0 display off')
        _turn_off_display_for_s0()
