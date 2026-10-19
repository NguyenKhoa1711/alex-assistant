"""Explicit Windows power commands; never infer them from general chat."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import os
import re
import subprocess
import sys
from typing import Literal

from .app_actions import folded

PowerAction = Literal['sleep', 'shutdown']

DEFAULT_SLEEP_PHRASES = ('tắt máy', 'tắt máy tính', 'cho máy ngủ',
                         'cho máy tính ngủ', 'đưa máy vào chế độ ngủ')
DEFAULT_SHUTDOWN_PHRASES = ('tắt nguồn', 'tắt nguồn máy tính', 'shutdown máy')


def _key(text: str) -> str:
    return ' '.join(re.sub(r'[^a-z0-9 ]+', ' ', folded(text)).split())


def _command_key(text: str) -> str:
    key = _key(text)
    prefixes = ('alex ', 'a lech ', 'ban ', 'hay ', 'vui long ', 'lam on ',
                'giup toi ', 'giup minh ', 'toi muon ', 'minh muon ')
    suffixes = (' cho toi', ' cho minh', ' giup toi', ' giup minh',
                ' di', ' nhe', ' ngay')
    for _ in range(4):
        prefix = next((part for part in prefixes if key.startswith(part)), None)
        if prefix is None:
            break
        key = key[len(prefix):]
    for _ in range(3):
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
    if key in sleep and key not in shutdown:
        return 'sleep'
    if key in shutdown and key not in sleep:
        return 'shutdown'
    return None


class _Luid(ctypes.Structure):
    _fields_ = [('LowPart', wintypes.DWORD), ('HighPart', wintypes.LONG)]


class _LuidAndAttributes(ctypes.Structure):
    _fields_ = [('Luid', _Luid), ('Attributes', wintypes.DWORD)]


class _TokenPrivileges(ctypes.Structure):
    _fields_ = [('PrivilegeCount', wintypes.DWORD),
                ('Privileges', _LuidAndAttributes * 1)]


def _turn_off_display_for_s0() -> None:
    """On Modern Standby, turning the display off starts the S0 idle transition."""
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.SendMessageTimeoutW.argtypes = (
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t))
    user.SendMessageTimeoutW.restype = ctypes.c_size_t
    result = ctypes.c_size_t()
    ctypes.set_last_error(0)
    # Broadcast WM_SYSCOMMAND/SC_MONITORPOWER with lParam=2 (display off).
    sent = user.SendMessageTimeoutW(0xFFFF, 0x0112, 0xF170, 2,
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


def execute_power(action: PowerAction) -> None:
    """Run only after local voice confirmation has completed."""
    if sys.platform != 'win32':
        raise OSError('Lệnh nguồn chỉ hỗ trợ Windows.')
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
