"""UIA adapters for Spotify and Zalo; invoked by the pet in a separate process."""
from __future__ import annotations
import json
import sys
import threading
import time
from _ctypes import COMError
from functools import wraps
from windows_mcp import uia as auto
from pet.app_actions import Action, folded, artist_matches
from pet.apps import app_windows, open_registered_app, focus_window
from pet.config import load_config


class Ui:
    def __init__(self, app: str) -> None:
        self.entry = next(x for x in load_config()['apps']['entries'] if x['name'] == app)
        opened = open_registered_app(self.entry, threading.Event())
        if not opened.verified:
            raise RuntimeError(f'Chưa mở được cửa sổ {app}.')
        self.hwnd = app_windows(self.entry)[0]
        self.enable_accessibility()
        self.root = auto.ControlFromHandle(self.hwnd)

    def enable_accessibility(self) -> None:
        """Request Chromium accessibility after a normal/autostart launch."""
        import ctypes
        from ctypes import wintypes
        self.check()
        user = ctypes.WinDLL('user32')
        callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
            wintypes.LPARAM, wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
        @callback
        def visit(hwnd, _):
            name = ctypes.create_unicode_buffer(256)
            user.GetClassNameW(hwnd, name, 256)
            if name.value == 'Chrome_RenderWidgetHostHWND':
                result = ctypes.c_size_t()
                # Chromium's documented screen-reader detection object ID.
                user.SendMessageTimeoutW(hwnd, 0x003D, 0, 1, 2, 1000, ctypes.byref(result))
            return True
        user.EnumChildWindows.argtypes = [wintypes.HWND, callback, wintypes.LPARAM]
        user.EnumChildWindows(self.hwnd, visit, 0)

    def check(self) -> None:
        if self.hwnd not in app_windows(self.entry):
            raise RuntimeError('Cửa sổ đích đã đóng hoặc thay đổi; mình đã dừng thao tác.')

    def invoke(self, control) -> None:
        self.check()
        if not control.IsEnabled or control.IsOffscreen:
            raise RuntimeError('Nút đích chưa sẵn sàng hoặc không nhìn thấy.')
        # UIA operates on the exact observed control, without global clicks or typing.
        try:
            pattern = control.GetInvokePattern()
        except (AttributeError, LookupError):
            pattern = None
        if pattern is not None:
            pattern.Invoke()
        else:
            legacy = control.GetLegacyIAccessiblePattern()
            if not legacy or not legacy.DefaultAction:
                raise RuntimeError('Ứng dụng chưa cho thao tác nút này qua UI Automation.')
            legacy.DoDefaultAction()

    def set_search(self, control, value: str) -> None:
        self.check()
        if not value or len(value) > 150 or '\n' in value:
            raise ValueError('Tên cần tìm phải ngắn và nằm trên một dòng.')
        try:
            control.GetValuePattern().SetValue(value)
        except Exception:
            # Chromium may report an event error after accepting the input.
            pass
        for _ in range(10):
            time.sleep(.1)
            try:
                if folded(control.GetValuePattern().Value) == folded(value):
                    return
            except Exception:
                pass
        raise RuntimeError('Chưa nhập được tên vào ô tìm kiếm.')

    def submit_spotify_search(self, control) -> None:
        import ctypes
        from ctypes import wintypes
        self.check()
        if self.entry['name'] != 'Spotify' or control.Name not in ('Bạn muốn phát nội dung gì?', 'What do you want to play?'):
            raise RuntimeError('Chỉ gửi Enter trong ô tìm bài Spotify đã xác định.')
        focus_window(self.hwnd)
        control.SetFocus()
        user = ctypes.WinDLL('user32'); user.GetForegroundWindow.restype = wintypes.HWND
        if user.GetForegroundWindow() != self.hwnd or not control.HasKeyboardFocus:
            raise RuntimeError('Bạn đưa Spotify lên trước rồi thử lại; mình chưa gửi phím vào cửa sổ khác.')
        auto.SendKeys('{Enter}', waitTime=.1)


def nodes(root, depth: int = 32, limit: int = 4500):
    stack = [(root, 0)]; started = time.monotonic(); seen = 0
    while stack and seen < limit and time.monotonic() - started < 7:
        control, level = stack.pop(); seen += 1
        yield control
        if level < depth:
            try:
                if control.AutomationId != 'chatView' and not control.IsOffscreen:
                    stack.extend((c, level+1) for c in reversed(control.GetChildren()))
            except Exception:
                continue


def texts(root, depth: int = 6) -> list[str]:
    return [c.Name for c in nodes(root, depth) if c.ControlTypeName in
            ('TextControl', 'HyperlinkControl') and c.Name]


def success(message: str) -> dict:
    return {'message': message, 'verified': True}


def song_is_playing(now: str, query: str, artist: str, state: str) -> bool:
    separator = ' của ' if ' của ' in now else ' by ' if ' by ' in now else None
    if separator is None or state != 'playing':
        return False
    title, current_artist = now.split(separator, 1)
    return folded(title) == folded(query) and artist_matches(artist, current_artist)


def retry_uia_read(read):
    """Re-read after Chromium replaces an accessibility element."""
    @wraps(read)
    def wrapped(*args, **kwargs):
        for attempt in range(4):
            try:
                return read(*args, **kwargs)
            except COMError:
                if attempt == 3:
                    raise
                time.sleep(.12 * (attempt + 1))
    return wrapped


def invoke_and_verify(ui, button, verify, attempts: int = 12) -> dict | None:
    try:
        ui.invoke(button)
    except COMError:
        # The action may already have happened; never click a toggle twice.
        pass
    for _ in range(attempts):
        time.sleep(.2)
        try:
            result = verify()
            if result:
                return result
        except (COMError, RuntimeError):
            continue
    return None


def spotify(action: Action) -> dict:
    ui = Ui('Spotify')
    @retry_uia_read
    def document():
        doc = None
        for _ in range(12):
            doc = next((c for c in nodes(ui.root, 15) if c.ControlTypeName == 'DocumentControl'
                        and c.AutomationId == 'RootWebArea'), None)
            if doc is not None:
                break
            time.sleep(.2)
        if doc is None:
            raise RuntimeError('Chưa đọc được giao diện Spotify; bạn kiểm tra đăng nhập hoặc kết nối của Spotify.')
        return doc
    @retry_uia_read
    def player():
        for c in nodes(document()):
            if c.ControlTypeName == 'ButtonControl' and c.Name in ('Phát', 'Tạm dừng', 'Play', 'Pause'):
                parent = c.GetParentControl(); children = parent.GetChildren()
                names = {x.Name for x in children}
                if names.intersection({'Trước', 'Previous'}) and names.intersection({'Tiếp', 'Next'}):
                    return parent, children
        raise RuntimeError('Chưa tìm thấy thanh phát nhạc của Spotify.')
    @retry_uia_read
    def state() -> str:
        _, controls = player()
        return 'playing' if any(c.Name in ('Tạm dừng', 'Pause') for c in controls) else 'paused'
    @retry_uia_read
    def track() -> str:
        for c in nodes(document()):
            if c.ControlTypeName == 'HyperlinkControl' and c.Name.startswith(('Đang phát: ', 'Now playing: ')):
                return c.Name.split(': ', 1)[1]
        # The title link lives next to the player, outside the search result list.
        parent, _ = player()
        for _ in range(3):
            parent = parent.GetParentControl()
            links = [c.Name for c in nodes(parent, 5) if c.ControlTypeName == 'HyperlinkControl' and c.Name]
            if links:
                return links[0]
        return ''
    if action.operation == 'song':
        doc = document()
        search = next((c for c in nodes(doc) if c.ControlTypeName in ('ComboBoxControl', 'EditControl')
                       and c.Name in ('Bạn muốn phát nội dung gì?', 'What do you want to play?')), None)
        if search is None:
            button = next((c for c in nodes(doc) if c.ControlTypeName == 'ButtonControl' and c.Name in ('Tìm kiếm', 'Search')), None)
            if button is None:
                raise RuntimeError('Chưa tìm thấy ô tìm bài của Spotify.')
            ui.invoke(button); time.sleep(.3)
            search = next((c for c in nodes(document()) if c.ControlTypeName in ('ComboBoxControl', 'EditControl')
                           and c.Name in ('Bạn muốn phát nội dung gì?', 'What do you want to play?')), None)
        if search is None:
            raise RuntimeError('Spotify chưa hiện ô tìm bài.')
        ui.set_search(search, action.query + (' ' + action.artist if action.artist else ''))
        ui.submit_spotify_search(search)
        time.sleep(.6)
        song_filter = next((c for c in nodes(document()) if c.ControlTypeName == 'HyperlinkControl'
                            and c.Name in ('Bài hát', 'Songs') and not c.IsOffscreen), None)
        if song_filter is not None:
            ui.invoke(song_filter)
            time.sleep(.5)
        matches = []
        for _ in range(12):
            time.sleep(.25); matches = []; labels = set()
            for c in nodes(document()):
                if c.ControlTypeName != 'ButtonControl' or c.IsOffscreen:
                    continue
                label = c.Name
                title = label[5:] if label.startswith('Phát ') else label[5:] if label.startswith('Play ') else ''
                if not title:
                    continue
                # Song rows expose artist names; album/playlist play buttons do not.
                separator = ' của ' if ' của ' in title else ' by ' if ' by ' in title else None
                if separator is None:
                    continue
                title_only = title.split(' của ', 1)[0].split(' by ', 1)[0]
                if folded(title_only) != folded(action.query):
                    continue
                artist = title.split(separator, 1)[1]
                if action.artist and not artist_matches(action.artist, artist):
                    continue
                if folded(label) in labels:
                    continue
                labels.add(folded(label))
                matches.append(c)
            if matches:
                break
        if len(matches) != 1:
            reason = 'Có nhiều bản trùng tên; bạn nói thêm tên ca sĩ nhé.' if matches else f'Mình chưa tìm thấy đúng bài {action.query}. Bạn nói thêm tên ca sĩ hoặc tên đầy đủ nhé.'
            return {'message': reason, 'verified': False, 'followup': 'artist'}
        selected = matches[0].Name[5:]
        expected_artist = selected.split(' của ' if ' của ' in selected else ' by ', 1)[1]
        def verify_song():
            now = track()
            if song_is_playing(now, action.query, expected_artist, state()):
                return success(f'Mình đang phát {now} trên Spotify.')
        return invoke_and_verify(ui, matches[0], verify_song) or {
            'message': 'Đã bấm bài tìm được, nhưng Spotify chưa xác nhận đang phát đúng bài.', 'verified': False}
    parent, controls = player()
    wanted = {'play': ('Phát', 'Play'), 'pause': ('Tạm dừng', 'Pause'),
              'next': ('Tiếp', 'Next'), 'previous': ('Trước', 'Previous')}[action.operation]
    before = track() if action.operation in ('next', 'previous') else ''
    button = next((c for c in controls if c.Name in wanted), None)
    if button is None and action.operation in ('play', 'pause'):
        return success('Spotify đang phát nhạc rồi.' if action.operation == 'play' else 'Spotify đã tạm dừng rồi.')
    if button is None:
        raise RuntimeError('Chưa tìm được nút điều khiển Spotify.')
    def verify_player():
        if action.operation in ('play', 'pause'):
            if state() == ('playing' if action.operation == 'play' else 'paused'):
                return success('Mình đang phát nhạc trên Spotify.' if action.operation == 'play' else 'Mình đã tạm dừng nhạc Spotify.')
        else:
            now = track()
            if now and now != before:
                return success(f'Mình đã chuyển bài trên Spotify sang {now}.')
    return invoke_and_verify(ui, button, verify_player) or {
        'message': 'Spotify chưa xác nhận thay đổi; mình chưa thể báo đã xong.', 'verified': False}


def zalo(action: Action) -> dict:
    ui = Ui('Zalo')
    search = ui.root.EditControl(AutomationId='contact-search-input', searchDepth=16)
    if not search.Exists(.5):
        raise RuntimeError('Zalo chưa hiện ô tìm liên hệ; bạn kiểm tra đã đăng nhập chưa.')
    ui.set_search(search, action.query)
    matches = []
    for _ in range(12):
        time.sleep(.2); matches = []
        for c in nodes(ui.root, 28):
            if c.AutomationId.startswith(('friend-item-', 'group-item-')) and not c.IsOffscreen:
                name = ''.join(texts(c, 3)).strip()
                if name and folded(name) == folded(action.query):
                    matches.append((c, name))
        if matches:
            break
    # Never choose a contact by fuzzy name, message contents, or first search result.
    if len(matches) != 1:
        return {'message': ('Có nhiều liên hệ trùng tên; bạn nói tên đầy đủ hoặc tên nhóm riêng nhé.' if matches
                            else f'Mình chưa thấy liên hệ hoặc nhóm có đúng tên {action.query} trên Zalo. Bạn đọc tên như đang lưu trong Zalo nhé.'),
                'verified': False, 'followup': 'contact'}
    row, name = matches[0]
    ui.invoke(row)
    for _ in range(12):
        time.sleep(.2)
        header = ui.root.GroupControl(AutomationId='header', searchDepth=12)
        if header.Exists(.2) and any(folded(t) == folded(name) for t in texts(header, 6)):
            return success(f'Mình đã mở cuộc trò chuyện với {name} trên Zalo.')
    return {'message': 'Zalo chưa hiện đúng tiêu đề cuộc trò chuyện; mình chưa xác nhận đã mở đúng người.', 'verified': False}


if __name__ == '__main__':
    try:
        payload = json.load(sys.stdin)
        target_window = payload.pop('target_window', None)
        action = Action(**payload)
        if action.app == 'Tabs' and action.operation == 'close_current':
            from pet.tab_actions import close_browser_tab
            result = close_browser_tab(auto, target_window)
        elif action.app == 'Spotify' and action.operation in ('play', 'pause', 'next', 'previous', 'song'):
            result = spotify(action)
        elif action.app == 'Zalo' and action.operation == 'chat':
            result = zalo(action)
        else:
            raise ValueError('Chưa hỗ trợ thao tác ứng dụng này.')
    except Exception as exc:
        result = {'message': str(exc)[:240] if isinstance(exc, (RuntimeError, ValueError)) else
                  'Giao diện ứng dụng vừa thay đổi hoặc chưa sẵn sàng. Mình đã dừng; bạn thử lại nhé.',
                  'verified': False, 'error_type': type(exc).__name__}
    print(json.dumps(result, ensure_ascii=False), flush=True)
