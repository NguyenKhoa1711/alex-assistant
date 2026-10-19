"""Open the selected Minecraft version from the verified TLauncher window."""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
import threading
import time

import win32api
import win32con
import win32gui
import pywintypes

from .apps import (LaunchResult, app_windows, focus_window, launch_name,
                   normalized, open_registered_app)

_last_clicked_at = 0.0
_launch_lock = threading.Lock()


def wants_minecraft_game(question: str) -> bool:
    name = launch_name(question)
    return name in {'minecraft', 'minecraft launcher', 'minecraft trong tlauncher'}


def _running_game_window() -> int | None:
    found: list[int] = []

    def visit(hwnd: int, _: object) -> None:
        try:
            if (win32gui.IsWindowVisible(hwnd) and
                    win32gui.GetClassName(hwnd) == 'GLFW30' and
                    normalized(win32gui.GetWindowText(hwnd)).startswith('minecraft')):
                found.append(hwnd)
        except pywintypes.error:
            pass

    win32gui.EnumWindows(visit, None)
    return found[0] if found else None


@contextmanager
def _physical_dpi():
    user = ctypes.windll.user32
    user.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    previous = user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    try:
        yield
    finally:
        if previous:
            user.SetThreadDpiAwarenessContext(previous)


def _is_play_yellow(color: int) -> bool:
    if color < 0:
        return False
    red, green, blue = color & 255, (color >> 8) & 255, (color >> 16) & 255
    return 225 <= red <= 248 and 178 <= green <= 210 and 40 <= blue <= 90


def find_play_button(hwnd: int) -> tuple[int, int] | None:
    """Locate TLauncher's yellow button in its bottom bar, in client coordinates."""
    with _physical_dpi():
        return _find_play_button_physical(hwnd)


def _find_play_button_physical(hwnd: int) -> tuple[int, int] | None:
    dc = 0
    try:
        if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd):
            return None
        _, _, width, height = win32gui.GetClientRect(hwnd)
        if width < 760 or height < 420:
            return None
        xs = range(int(width * .45), int(width * .84), 4)
        ys = range(max(0, height - 85), height - 8, 4)
        x_votes: dict[int, int] = {}
        y_votes: dict[int, int] = {}
        dc = win32gui.GetDC(hwnd)
        for y in ys:
            for x in xs:
                if _is_play_yellow(win32gui.GetPixel(dc, x, y)):
                    x_votes[x] = x_votes.get(x, 0) + 1
                    y_votes[y] = y_votes.get(y, 0) + 1
    except pywintypes.error:
        return None
    finally:
        if dc:
            try:
                win32gui.ReleaseDC(hwnd, dc)
            except pywintypes.error:
                pass
    button_x = [x for x, count in x_votes.items() if count >= 6]
    button_y = [y for y, count in y_votes.items() if count >= 20]
    if not button_x or not button_y:
        return None
    left, right = min(button_x), max(button_x)
    top, bottom = min(button_y), max(button_y)
    if not (width * .08 <= right - left <= width * .32 and
            height * .025 <= bottom - top <= height * .13 and
            width * .53 <= (left + right) / 2 <= width * .80 and
            bottom >= height - 28):
        return None
    return (left + right) // 2, (top + bottom) // 2


def _click_client_point(hwnd: int, point: tuple[int, int]) -> bool:
    with _physical_dpi():
        if not focus_window(hwnd):
            return False
        previous = win32api.GetCursorPos()
        try:
            screen_point = win32gui.ClientToScreen(hwnd, point)
            win32api.SetCursorPos(screen_point)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(.08)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            time.sleep(.08)
        except pywintypes.error:
            return False
        finally:
            win32api.SetCursorPos(previous)
        return True


def launch_minecraft(entry: dict, cancelled: threading.Event) -> LaunchResult:
    """Start TLauncher if needed, then click its currently selected game version."""
    global _last_clicked_at
    started = time.monotonic()
    with _launch_lock:
        running = _running_game_window()
        if running:
            foreground = focus_window(running)
            return LaunchResult('Minecraft', True, foreground,
                                time.monotonic() - started, 'minecraft_running')
        if time.monotonic() - _last_clicked_at < 90:
            return LaunchResult('Minecraft', True, False,
                                time.monotonic() - started, 'minecraft_start')
        windows = app_windows(entry)
        if not windows:
            opened = open_registered_app(entry, cancelled)
            if not opened.verified:
                return LaunchResult('Minecraft', False, False,
                                    time.monotonic() - started, 'minecraft_start')
        # TLauncher first shows a small splash window; wait for its main UI.
        wait_seconds = max(20.0, min(90.0, float(entry.get('launch_timeout_seconds', 60))))
        deadline = time.monotonic() + wait_seconds
        while not cancelled.is_set() and time.monotonic() < deadline:
            for hwnd in app_windows(entry):
                if not focus_window(hwnd):
                    continue
                point = find_play_button(hwnd)
                if point and _click_client_point(hwnd, point):
                    for _ in range(20):
                        if _running_game_window() or find_play_button(hwnd) is None:
                            _last_clicked_at = time.monotonic()
                            return LaunchResult('Minecraft', True, True,
                                                time.monotonic() - started, 'minecraft_start')
                        if cancelled.wait(.25):
                            break
                    return LaunchResult('Minecraft', False, True,
                                        time.monotonic() - started, 'minecraft_start')
            cancelled.wait(.3)
        return LaunchResult('Minecraft', False, False,
                            time.monotonic() - started, 'minecraft_start')
