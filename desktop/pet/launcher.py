"""Keep Bionic in the background for Alex; show it only on explicit request."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import json
import os
import subprocess
import urllib.request
import time
from pathlib import Path
from .config import ROOT
from .apps import focus_window


def bionic_executable() -> Path:
    paths = [ROOT.parents[1] / 'Bionic/Bionic.exe',
             Path.home() / 'AppData/Local/Programs/Bionic/Bionic.exe']
    for path in paths:
        if path.is_file():
            return path
    raise FileNotFoundError('Không tìm thấy Bionic.exe trong bộ trợ lý.')


def show_existing_window() -> bool:
    user = ctypes.WinDLL('user32', use_last_error=True)
    try:
        hDesk = user.OpenDesktopW('Default', 0, False, 0x1ff)
        if hDesk:
            user.SetThreadDesktop(hDesk)
    except Exception:
        pass
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                               wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user.SetForegroundWindow.argtypes = [wintypes.HWND]
    expected = bionic_executable()
    found = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def visit(hwnd: int, _: int) -> bool:
        title = ctypes.create_unicode_buffer(512)
        user.GetWindowTextW(hwnd, title, len(title))
        if title.value != 'Bionic' and not title.value.startswith('Bionic - '):
            return True
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = kernel.OpenProcess(0x1000, False, pid.value)
        if not handle:
            return True
        try:
            size = wintypes.DWORD(32768)
            path = ctypes.create_unicode_buffer(size.value)
            if not kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
                return True
            if not expected.samefile(path.value):
                return True
            # focus_window intentionally rejects invisible windows. Restore the
            # background bridge first when the user explicitly opens Bionic.
            user.ShowWindow(hwnd, 9)  # SW_RESTORE
            focus_window(hwnd)
            found.append(hwnd)
        except OSError:
            pass
        finally:
            kernel.CloseHandle(handle)
        return True

    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user.EnumWindows(visit, 0)
    return bool(found)


def is_bionic_cdp_ready(port: int = 9223) -> bool:
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list', timeout=1) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return any('/Bionic/resources/app/.webpack-bionic/renderer/index.html' in p.get('url', '') for p in data)
    except Exception:
        return False


def open_bionic(port: int = 9223, *, show: bool = True) -> None:
    # A pet request must not change visibility or focus of an existing window.
    if show and show_existing_window():
        return
    if is_bionic_cdp_ready(port):
        return
    environment = os.environ.copy()
    environment['NODE_USE_SYSTEM_CA'] = '1'
    startup = subprocess.STARTUPINFO()
    if not show:
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0  # SW_HIDE; CREATE_NO_WINDOW only hides consoles.
    subprocess.Popen([str(bionic_executable()), '--disable-gpu',
                      '--force-renderer-accessibility', '--remote-debugging-address=127.0.0.1',
                      f'--remote-debugging-port={port}'], env=environment,
                     startupinfo=startup,
                     creationflags=subprocess.CREATE_NO_WINDOW)
    # A cold start on this laptop may need more than 20 seconds. Poll a bounded
    # deadline without forcing the UI visible just to make it initialize.
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if show and show_existing_window():
            return
        if not show and is_bionic_cdp_ready(port):
            return
        time.sleep(0.25)
    raise RuntimeError('Bionic chưa sẵn sàng sau 60 giây. Xem log của Bionic.')
