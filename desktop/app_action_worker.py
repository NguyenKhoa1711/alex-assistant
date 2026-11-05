"""UIA adapters for Spotify, YouTube, and Zalo; invoked by the pet in a separate process."""
from __future__ import annotations
import gzip
import http.client
import json
import logging
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from _ctypes import COMError
from functools import wraps
import uiautomation as auto
from pet.app_actions import Action, folded, artist_matches
from pet.apps import app_windows, open_registered_app, open_web, focus_window
from pet.config import load_config


BROWSER_PROCESSES = ['chrome.exe', 'msedge.exe', 'browser.exe', 'firefox.exe', 'brave.exe', 'opera.exe']
YOUTUBE_SKIP_LINKS = {
    'trang chu', 'home', 'shorts', 'kenh dang ky', 'subscriptions', 'ban', 'you',
    'lich su', 'history', 'dang nhap', 'sign in', 'bo loc', 'filters', 'tim kiem',
    'search', 'xoa truy van tim kiem', 'clear search query', ' Bo qua va chuyen den noi dung chinh',
    'bo qua dieu huong', 'skip navigation', 'youtube', ' youtube trang chu',
}


def enable_accessibility_hwnd(hwnd: int) -> None:
    """Request Chromium accessibility after a normal/autostart launch."""
    import ctypes
    from ctypes import wintypes
    user = ctypes.WinDLL('user32')
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
        wintypes.LPARAM, wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
    @callback
    def visit(child_hwnd, _):
        name = ctypes.create_unicode_buffer(256)
        user.GetClassNameW(child_hwnd, name, 256)
        if name.value == 'Chrome_RenderWidgetHostHWND':
            result = ctypes.c_size_t()
            # Chromium's documented screen-reader detection object ID.
            user.SendMessageTimeoutW(child_hwnd, 0x003D, 0, 1, 2, 1000, ctypes.byref(result))
        return True
    user.EnumChildWindows.argtypes = [wintypes.HWND, callback, wintypes.LPARAM]
    user.EnumChildWindows(hwnd, visit, 0)


def invoke_control(control) -> None:
    if not control.IsEnabled or control.IsOffscreen:
        raise RuntimeError('Nút đích chưa sẵn sàng hoặc không nhìn thấy.')
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
        self.check()
        enable_accessibility_hwnd(self.hwnd)

    def check(self) -> None:
        if self.hwnd not in app_windows(self.entry):
            raise RuntimeError('Cửa sổ đích đã đóng hoặc thay đổi; mình đã dừng thao tác.')

    def invoke(self, control) -> None:
        self.check()
        invoke_control(control)

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


def nodes(root, depth: int = 32, limit: int = 4500, include_offscreen_containers: bool = False):
    stack = [(root, 0)]; started = time.monotonic(); seen = 0
    while stack and seen < limit and time.monotonic() - started < 7:
        control, level = stack.pop(); seen += 1
        yield control
        if level < depth:
            try:
                if control.AutomationId != 'chatView' and (include_offscreen_containers or not control.IsOffscreen):
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


def select_spotify_match(controls, query: str, artist: str = ''):
    """Select the best matching playable item from Spotify search results."""
    q_fold = folded(query)
    combined_fold = folded(f'{query} của {artist}') if artist else q_fold
    q_words = [w for w in q_fold.split() if w]
    ranked = []
    seen_labels = set()
    for idx, c in enumerate(controls):
        if getattr(c, 'ControlTypeName', '') != 'ButtonControl' or getattr(c, 'IsOffscreen', False):
            continue
        label = getattr(c, 'Name', '') or ''
        title = label[5:].strip() if label.startswith(('Phát ', 'Play ')) else ''
        if not title or folded(label) in seen_labels:
            continue
        separator = ' của ' if ' của ' in title else ' by ' if ' by ' in title else None
        if separator is not None:
            title_only, row_artist = title.split(separator, 1)
            t_fold = folded(title_only)
            full_fold = folded(title)
            title_has_cua = bool(artist and (t_fold == combined_fold or combined_fold in t_fold))
            if artist and not title_has_cua and not artist_matches(artist, row_artist):
                continue
            if t_fold in (q_fold, combined_fold):
                tier = 0
            elif title_has_cua or (q_fold and (t_fold.startswith(q_fold + ' ') or q_fold in t_fold or t_fold in q_fold)):
                tier = 1
            elif artist_matches(query, row_artist) or (q_words and all(w in full_fold for w in q_words)):
                tier = 2
            elif not artist:
                tier = 3
            else:
                continue
            seen_labels.add(folded(label))
            ranked.append((tier, idx, c, title_only.strip(), row_artist.strip()))
        elif not artist:
            t_fold = folded(title)
            tier = 4 if (q_fold and q_fold in t_fold) else 5
            seen_labels.add(folded(label))
            ranked.append((tier, idx, c, title, ''))
    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], item[1]))
    _, _, best_control, expected_title, expected_artist = ranked[0]
    return best_control, expected_title, expected_artist


def _window_title(hwnd: int) -> str:
    import ctypes
    user = ctypes.WinDLL('user32')
    buf = ctypes.create_unicode_buffer(512)
    user.GetWindowTextW(hwnd, buf, len(buf))
    return buf.value


def _spotify_entry() -> dict | None:
    try:
        return next((x for x in load_config()['apps']['entries'] if x['name'] == 'Spotify'), None)
    except Exception:
        return None


def is_spotify_open() -> bool:
    if not isinstance(Ui, type):
        # Unit tests patching Ui expect Spotify UI path to be exercised directly.
        return True
    entry = _spotify_entry()
    return bool(entry and app_windows(entry))


def is_youtube_open() -> bool:
    if not isinstance(Ui, type):
        return False
    hwnds = app_windows({'processes': BROWSER_PROCESSES})
    return any('youtube' in folded(_window_title(h)) for h in hwnds)


def clean_youtube_title(title: str) -> str:
    cleaned = re.sub(
        r'(?i)\s*[\(\[\{][^)\]\}]*\b(?:official|music\s+video|mv|audio|lyrics?|visualizer|prod\.?|4k|hd)\b[^)\]\}]*[\)\]\}]',
        '',
        title,
    )
    parts = [p.strip() for p in cleaned.split('|') if p.strip()]
    kept = [
        p for p in parts
        if not re.fullmatch(
            r'(?i)(?:official\s*(?:music\s*video|mv|video|audio|lyric\s*video|visualizer)?|mv(?:\s+official)?|lyrics?\s*video|audio)',
            p,
        )
    ]
    result = ' - '.join(kept if kept else parts)
    # Emoji / pictographs make TTS stumble; keep letters, digits and punctuation only.
    result = ''.join(ch for ch in result if ord(ch) < 0x2190 or 0x3000 <= ord(ch) < 0xD800)
    return ' '.join(result.split()).strip(' -|') or title.strip()


def select_youtube_match(
    candidates: list[tuple[str, str, str]],
    query: str,
    artist: str = '',
) -> tuple[str, str] | None:
    """Rank YouTube search results by title, artist/channel, and official MV/audio signals."""
    if not candidates:
        return None
    q_fold = folded(query)
    a_fold = folded(artist) if artist else ''
    q_words = [w for w in q_fold.split() if len(w) > 1] or [w for w in q_fold.split() if w]
    wants_karaoke = 'karaoke' in q_fold

    def rank_pool(require_artist: bool):
        ranked = []
        for idx, (vid, title, channel) in enumerate(candidates):
            t_fold = folded(title)
            c_fold = folded(channel)
            full_fold = f'{t_fold} {c_fold}'.strip()
            has_artist = bool(
                artist and (
                    artist_matches(artist, title)
                    or artist_matches(artist, channel)
                    or a_fold in full_fold
                )
            )
            if require_artist and artist and not has_artist:
                continue
            is_official = bool(re.search(r'\b(?:official|mv|music video|audio)\b', full_fold))
            karaoke_penalty = 4 if (not wants_karaoke and 'karaoke' in full_fold) else 0
            # Compilations, remixes and covers are not "the song" unless explicitly requested.
            for noisy in ('playlist', 'tong hop', 'lien khuc', 'remix', 'cover', 'beat', 'live', 'nightcore', 'speed up', '8d'):
                if re.search(r'\b' + noisy + r'\b', t_fold) and noisy not in q_fold:
                    karaoke_penalty += 2
                    break
            word_hits = sum(1 for w in q_words if w in full_fold)
            if q_fold and q_fold in t_fold and (is_official or has_artist):
                tier = 0
            elif q_fold and q_fold in t_fold:
                tier = 1
            elif q_words and word_hits == len(q_words):
                tier = 1 if is_official else 2
            elif q_words and (word_hits >= max(2, int(len(q_words) * 0.6)) or (len(q_words) == 1 and word_hits == 1)):
                tier = 2 if is_official else 3
            else:
                tier = 4
            ranked.append((tier + karaoke_penalty, idx, vid, title))
        return ranked

    ranked = rank_pool(require_artist=True) if artist else []
    if not ranked:
        ranked = rank_pool(require_artist=False)
    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], item[1]))
    _, _, best_vid, best_title = ranked[0]
    return best_vid, clean_youtube_title(best_title)


def close_previous_youtube_tabs() -> None:
    """Close unselected YouTube tabs in the active browser window so old videos stop playing."""
    try:
        from pet.tab_actions import chrome_tabs
        hwnds = app_windows({'processes': BROWSER_PROCESSES})
        for hwnd in hwnds:
            try:
                root = auto.ControlFromHandle(hwnd)
                tabs = chrome_tabs(root)
                if len(tabs) <= 1:
                    continue
                for tab in tabs:
                    try:
                        if tab.GetSelectionItemPattern().IsSelected:
                            continue
                        if 'youtube' not in folded(getattr(tab, 'Name', '') or ''):
                            continue
                        buttons = [
                            c for c in tab.GetChildren()
                            if c.ControlTypeName == 'ButtonControl'
                            and folded(c.Name) in {'close', 'close tab', 'dong', 'dong tab', 'dong the'}
                            and c.IsEnabled and not c.IsOffscreen
                        ]
                        if len(buttons) == 1:
                            invoke_control(buttons[0])
                    except Exception:
                        continue
            except Exception:
                continue
    except Exception:
        pass


def browser_youtube_action(operation: str) -> dict | None:
    """Control an active YouTube or web media player inside open browser windows via UIA."""
    hwnds = app_windows({'processes': BROWSER_PROCESSES})
    if not hwnds:
        return None
    hwnds.sort(key=lambda h: (0 if 'youtube' in folded(_window_title(h)) else 1))
    play_names = {'phat (k)', 'play (k)', 'phat', 'play', 'phat video', 'play video'}
    pause_names = {'tam dung (k)', 'pause (k)', 'tam dung', 'pause', 'tam dung video', 'pause video'}
    next_names = {'tiep theo (shift+n)', 'next (shift+n)', 'tiep theo', 'next'}
    prev_names = {'truoc', 'previous', 'video truoc', 'previous video'}

    for hwnd in hwnds:
        try:
            enable_accessibility_hwnd(hwnd)
            root = auto.ControlFromHandle(hwnd)
            docs = [c for c in nodes(root, 12, 1200)
                    if getattr(c, 'ControlTypeName', '') == 'DocumentControl' and not getattr(c, 'IsOffscreen', False)]
            if not docs:
                continue
            for doc in docs:
                buttons = [c for c in nodes(doc, 18, 2500)
                           if getattr(c, 'ControlTypeName', '') == 'ButtonControl'
                           and not getattr(c, 'IsOffscreen', False) and getattr(c, 'Name', '')]
                play_btn = next((b for b in buttons if folded(b.Name) in play_names), None)
                pause_btn = next((b for b in buttons if folded(b.Name) in pause_names), None)
                next_btn = next((b for b in buttons if folded(b.Name) in next_names or folded(b.Name).startswith(('tiep theo ', 'next '))), None)
                prev_btn = next((b for b in buttons if folded(b.Name) in prev_names), None)
                if not any((play_btn, pause_btn, next_btn)):
                    continue
                if operation == 'pause':
                    if pause_btn is None and play_btn is not None:
                        return success('Nhạc trên YouTube đã tạm dừng rồi.')
                    if pause_btn is None:
                        continue
                    try:
                        invoke_control(pause_btn)
                    except COMError:
                        pass
                    for _ in range(10):
                        time.sleep(.2)
                        fresh = [folded(c.Name) for c in nodes(doc, 18, 2500)
                                 if getattr(c, 'ControlTypeName', '') == 'ButtonControl' and getattr(c, 'Name', '')]
                        if any(n in play_names for n in fresh) or not any(n in pause_names for n in fresh):
                            return success('Mình đã tạm dừng nhạc đang phát trên YouTube.')
                    return {'message': 'Đã bấm tạm dừng nhưng trình duyệt chưa xác nhận dừng phát.', 'verified': False}
                if operation == 'play':
                    if play_btn is None and pause_btn is not None:
                        return success('YouTube đang phát nhạc rồi.')
                    if play_btn is None:
                        continue
                    try:
                        invoke_control(play_btn)
                    except COMError:
                        pass
                    for _ in range(10):
                        time.sleep(.2)
                        fresh = [folded(c.Name) for c in nodes(doc, 18, 2500)
                                 if getattr(c, 'ControlTypeName', '') == 'ButtonControl' and getattr(c, 'Name', '')]
                        if any(n in pause_names for n in fresh):
                            return success('Mình đang phát tiếp nhạc trên YouTube.')
                    return {'message': 'Đã bấm phát nhưng trình duyệt chưa xác nhận đang phát.', 'verified': False}
                if operation in ('next', 'previous'):
                    target_btn = next_btn if operation == 'next' else prev_btn
                    if target_btn is None:
                        continue
                    before_title = _window_title(hwnd)
                    try:
                        invoke_control(target_btn)
                    except COMError:
                        pass
                    for _ in range(12):
                        time.sleep(.25)
                        after_title = _window_title(hwnd)
                        if after_title and after_title != before_title:
                            clean_title = re.sub(r'\s*-\s*YouTube.*$', '', after_title, flags=re.IGNORECASE).strip()
                            return success(f'Mình đã chuyển sang {clean_title} trên YouTube.')
                    return success('Mình đã chuyển bài trên YouTube.')
        except Exception:
            continue
    return None


def find_youtube_video(query: str, artist: str = '', timeout: float = 3.5) -> tuple[str, str] | None:
    """Resolve and rank the best matching YouTube video (video_id, clean_title) via HTTP."""
    search_text = (query + (' ' + artist if artist else '')).strip()
    encoded = urllib.parse.quote_plus(search_text)
    url = f'https://www.youtube.com/results?search_query={encoded}'
    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept-Language': 'vi-VN,vi;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip',
        },
    )
    buf = b''
    encoding = ''
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            encoding = (resp.headers.get('Content-Encoding') or '').lower()
            while len(buf) < 1_500_000:
                try:
                    chunk = resp.read(65536)
                except http.client.IncompleteRead as exc:
                    buf += exc.partial
                    break
                if not chunk:
                    break
                buf += chunk
    except http.client.IncompleteRead as exc:
        buf += exc.partial
    except Exception:
        return None
    if not buf:
        return None
    if encoding == 'gzip' or buf[:2] == b'\x1f\x8b':
        try:
            buf = gzip.decompress(buf)
        except Exception:
            pass
    html = buf.decode('utf-8', 'ignore')
    candidates: list[tuple[str, str, str]] = []
    seen_ids: set[str] = set()
    for blk in html.split('"videoRenderer":{"videoId":"')[1:25]:
        vid = blk[:11]
        if not re.fullmatch(r'[a-zA-Z0-9_-]{11}', vid) or vid in seen_ids:
            continue
        tm = re.search(r'"title":\{"runs":\[\{"text":"((?:\\.|[^"\\])+)"', blk[:4000])
        if not tm:
            continue
        om = re.search(r'"(?:ownerText|longBylineText)":\{"runs":\[\{"text":"((?:\\.|[^"\\])+)"', blk[:8000])
        try:
            title = json.loads(f'"{tm.group(1)}"').strip()
        except Exception:
            title = tm.group(1).strip()
        channel = ''
        if om:
            try:
                channel = json.loads(f'"{om.group(1)}"').strip()
            except Exception:
                channel = om.group(1).strip()
        if title:
            seen_ids.add(vid)
            candidates.append((vid, title, channel))
    return select_youtube_match(candidates, query, artist)


def click_first_youtube_result(query: str) -> dict:
    """Use UI Automation on the browser's YouTube search results page to click the first video."""
    q_fold = folded(query)
    q_words = [w for w in q_fold.split() if len(w) > 1]
    for _ in range(18):
        time.sleep(.35)
        hwnds = app_windows({'processes': BROWSER_PROCESSES})
        hwnds.sort(key=lambda h: (0 if 'youtube' in folded(_window_title(h)) else 1))
        for hwnd in hwnds:
            try:
                enable_accessibility_hwnd(hwnd)
                root = auto.ControlFromHandle(hwnd)
                doc = next((c for c in nodes(root, 12, 1200)
                            if getattr(c, 'ControlTypeName', '') == 'DocumentControl'
                            and not getattr(c, 'IsOffscreen', False)
                            and ('youtube' in folded(getattr(c, 'Name', '') or '')
                                 or 'youtube' in folded(_window_title(hwnd)))), None)
                if doc is None:
                    continue
                candidates = []
                for idx, c in enumerate(nodes(doc, 24, 3500, include_offscreen_containers=True)):
                    if getattr(c, 'ControlTypeName', '') != 'HyperlinkControl' or getattr(c, 'IsOffscreen', False):
                        continue
                    name = (getattr(c, 'Name', '') or '').strip()
                    n_fold = folded(name)
                    if len(name) < 4 or n_fold in YOUTUBE_SKIP_LINKS:
                        continue
                    if re.fullmatch(r'[\d:]+', name) or n_fold.startswith(('bo loc', 'filter', 'dang nhap', 'sign in', 'kenh ')):
                        continue
                    score = 0 if (q_fold and q_fold in n_fold) else 1 if (q_words and any(w in n_fold for w in q_words)) else 2
                    candidates.append((score, idx, c, name))
                if not candidates:
                    continue
                candidates.sort(key=lambda item: (item[0], item[1]))
                _, _, best_link, best_title = candidates[0]
                focus_window(hwnd)
                try:
                    invoke_control(best_link)
                except Exception:
                    try:
                        best_link.Click(simulateMove=False)
                    except Exception:
                        pass
                clean_title = clean_youtube_title(best_title.split(' bởi ', 1)[0].split(' by ', 1)[0].strip())
                return success(f'Mình đang phát {clean_title} trên YouTube.')
            except Exception:
                continue
    return {'message': f'Mình đã mở tìm kiếm {query} trên YouTube; bạn chọn video muốn nghe nhé.', 'verified': True}


def youtube(action: Action) -> dict:
    if action.operation in ('play', 'pause', 'next', 'previous'):
        result = browser_youtube_action(action.operation)
        if result is not None:
            return result
        if action.operation == 'pause' and is_spotify_open():
            return spotify(Action('Spotify', 'pause'))
        return {'message': 'Chưa tìm thấy trình phát YouTube đang mở trên trình duyệt.', 'verified': False}
    if action.operation != 'song':
        raise ValueError('Chưa hỗ trợ thao tác YouTube này.')
    query_text = (action.query + (' ' + action.artist if action.artist else '')).strip()
    if not query_text:
        raise ValueError('Thiếu tên bài hát hoặc nhạc cần tìm trên YouTube.')
    found = find_youtube_video(action.query, action.artist)
    if found is not None:
        video_id, video_title = found
        had_youtube = is_youtube_open()
        opened = open_web(f'https://www.youtube.com/watch?v={video_id}', 'YouTube')
        if not opened.verified:
            return {'message': 'Mình chưa mở được YouTube trên trình duyệt.', 'verified': False}
        if had_youtube:
            time.sleep(.45)
            close_previous_youtube_tabs()
        return success(f'Mình đang phát {video_title} trên YouTube.')
    search_url = f'https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query_text)}'
    opened = open_web(search_url, 'YouTube')
    if not opened.verified:
        return {'message': 'Mình chưa mở được YouTube trên trình duyệt.', 'verified': False}
    return click_first_youtube_result(query_text)


def spotify(action: Action) -> dict:
    if not is_spotify_open() and is_youtube_open():
        return youtube(Action('YouTube', action.operation, action.query, action.artist))
    if action.operation == 'pause' and not is_spotify_open():
        yt_res = browser_youtube_action('pause')
        if yt_res is not None:
            return yt_res
        return success('Hiện không có nhạc nào đang phát.')
    if action.operation == 'play' and not is_spotify_open():
        yt_res = browser_youtube_action('play')
        if yt_res is not None and yt_res.get('verified'):
            return yt_res
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
        chosen = None
        for _ in range(12):
            time.sleep(.25)
            chosen = select_spotify_match(list(nodes(document())), action.query, action.artist)
            if chosen is not None:
                break
        if chosen is None:
            return {'message': f'Mình chưa tìm thấy bài {action.query} trên Spotify. Bạn thử tên khác hoặc nói phát trên YouTube nhé.',
                    'verified': False, 'followup': 'artist'}
        best_button, expected_title, expected_artist = chosen
        def verify_song():
            now = track()
            current_state = state()
            if expected_artist and song_is_playing(now, expected_title, expected_artist, current_state):
                return success(f'Mình đang phát {now} trên Spotify.')
            if current_state == 'playing' and now:
                now_title = now.split(' của ', 1)[0].split(' by ', 1)[0]
                if (folded(expected_title) in folded(now) or folded(now_title) in folded(expected_title)
                        or (expected_artist and artist_matches(expected_artist, now))):
                    return success(f'Mình đang phát {now} trên Spotify.')
        return invoke_and_verify(ui, best_button, verify_song) or {
            'message': 'Đã bấm bài tìm được, nhưng Spotify chưa xác nhận đang phát đúng bài.', 'verified': False}
    parent, controls = player()
    wanted = {'play': ('Phát', 'Play'), 'pause': ('Tạm dừng', 'Pause'),
              'next': ('Tiếp', 'Next'), 'previous': ('Trước', 'Previous')}[action.operation]
    before = track() if action.operation in ('next', 'previous') else ''
    button = next((c for c in controls if c.Name in wanted), None)
    if button is None and action.operation in ('play', 'pause'):
        if action.operation == 'pause':
            yt_res = browser_youtube_action('pause')
            if yt_res is not None and yt_res.get('verified'):
                return yt_res
        return success('Spotify đang phát nhạc rồi.' if action.operation == 'play' else 'Spotify đã tạm dừng rồi.')
    if button is None:
        raise RuntimeError('Chưa tìm được nút điều khiển Spotify.')
    def verify_player():
        if action.operation in ('play', 'pause'):
            if state() == ('playing' if action.operation == 'play' else 'paused'):
                if action.operation == 'pause':
                    browser_youtube_action('pause')
                return success('Mình đang phát nhạc trên Spotify.' if action.operation == 'play' else 'Mình đã tạm dừng nhạc Spotify.')
        else:
            now = track()
            if now and now != before:
                return success(f'Mình đã chuyển bài trên Spotify sang {now}.')
    return invoke_and_verify(ui, button, verify_player) or {
        'message': 'Spotify chưa xác nhận thay đổi; mình chưa thể báo đã xong.', 'verified': False}


def zalo_find(root, automation_id: str, kind: str = 'GroupControl'):
    """Native UIA lookup stays inside Zalo; avoids Python's slow whole-tree DFS."""
    try:
        from uiautomation.uiautomation import _AutomationClient
        client = _AutomationClient.instance().IUIAutomation
        condition = client.CreatePropertyCondition(auto.PropertyId.AutomationIdProperty, automation_id)
        element = root.Element.FindFirst(4, condition)  # TreeScope_Descendants
        return auto.Control.CreateControlFromElement(element) if element else None
    except (COMError, AttributeError, ImportError):
        # Compatibility with a UIA library/provider without native lookup support.
        control = getattr(root, kind)(AutomationId=automation_id, searchDepth=18)
        return control if control.Exists(.2) else None


def zalo_contact_name(row) -> str:
    """Read the first textual title branch, never labels or member-match snippets.

    Zalo 26.10 rows contain avatar, highlighted name, badges and category/member
    metadata as separate sibling branches. Flattening the whole row changes
    e.g. "Đại ca" into "Đại ca<icon>Gia đình" and rejects the right contact.
    """
    for child in row.GetChildren():
        parts = texts(child, 5)
        title = ''.join(parts).strip()
        # Avatar/status icon glyphs are not contact names. Do not concatenate
        # following siblings: those can be labels or matched group members.
        if any(char.isalnum() for char in title):
            return title
    return ''


def zalo_matches(area, query: str):
    matches = []
    seen = set()
    pending = [(area, 0)]
    deadline = time.monotonic() + 5
    visited = 0
    while pending and visited < 1200 and time.monotonic() < deadline:
        row, level = pending.pop()
        visited += 1
        if row.IsOffscreen:
            continue
        aid = row.AutomationId
        if aid.startswith(('friend-item-', 'group-item-')):
            if aid not in seen:
                seen.add(aid)
                name = zalo_contact_name(row)
                exact = bool(name and folded(name) == folded(query))
                if exact:
                    matches.append((row, name))
            # No need to scan labels/member snippets under a contact twice.
            continue
        if seen and row.ControlTypeName == 'TextControl' and re.fullmatch(
                r'(?:tin nhan|messages)(?: ?\(.*\))?', folded(row.Name)):
            # Contact results come before the message-result section. Its
            # contents cannot establish contact identity; do not traverse it.
            logging.getLogger('alex.zalo').info('scan contacts_complete=True matches=%d', len(matches))
            return matches
        children = row.GetChildren()
        if children and level >= 24:
            return None
        pending.extend((child, level + 1) for child in reversed(children))
    # An incomplete scan cannot rule out duplicate names; never select from it.
    logging.getLogger('alex.zalo').info('scan visited=%d complete=%s matches=%d', visited, not pending, len(matches))
    return None if pending else matches


def zalo_header_matches(root, name: str) -> bool:
    # The native Control view exposes chatViewContainer, but Zalo's inner
    # 'header' is only present in the Raw view on recent versions.
    header = zalo_find(root, 'chatViewContainer')
    if header is None:
        return False
    for text in texts(header, 6):  # nodes() never descends into chatView messages
        if any(char.isalnum() for char in text):
            return folded(text) == folded(name)
    return False


def zalo(action: Action) -> dict:
    logging.getLogger('alex.zalo').info('start')
    ui = Ui('Zalo')
    logging.getLogger('alex.zalo').info('window ready')
    search = None
    for _ in range(12):
        search = zalo_find(ui.root, 'contact-search-input', 'EditControl')
        if search is not None:
            break
        time.sleep(.25)  # cold launches publish Chromium accessibility asynchronously
    if search is None:
        raise RuntimeError('Zalo chưa hiện ô tìm liên hệ; bạn kiểm tra đã đăng nhập chưa.')
    ui.set_search(search, action.query)
    logging.getLogger('alex.zalo').info('search set')
    matches = []
    previous = None
    # Search only the result panel. Repeated whole-window scans used to take
    # 20-30 seconds, and unnecessarily traversed unrelated conversations.
    deadline = time.monotonic() + 15
    stable = False
    for _ in range(15):
        if time.monotonic() >= deadline:
            break
        time.sleep(.2)
        area = zalo_find(ui.root, 'searchResultList')
        if area is None:
            continue
        current = zalo_matches(area, action.query)
        if current is None:
            previous = None
            continue
        matches = current
        signature = tuple((row.AutomationId, folded(name)) for row, name in matches)
        if signature and signature == previous:
            stable = True
            break
        previous = signature
    # Never choose a contact by fuzzy name, a group-member hit, message contents,
    # or the first result. Wait for a stable exact match, and reject duplicates.
    if len(matches) != 1 or not stable:
        return {'message': ('Có nhiều liên hệ trùng tên; bạn nói tên đầy đủ hoặc tên nhóm riêng nhé.' if len(matches) > 1
                            else f'Mình chưa thấy liên hệ hoặc nhóm có đúng tên {action.query} trên Zalo. Bạn đọc tên như đang lưu trong Zalo nhé.'),
                'verified': False, 'followup': 'contact'}
    # If the user changed the search while Alex waited, do not open a stale row.
    if folded(search.GetValuePattern().Value) != folded(action.query):
        return {'message': 'Ô tìm kiếm Zalo đã thay đổi. Mình đã dừng thao tác để tránh mở nhầm.', 'verified': False}
    row, name = matches[0]
    result = invoke_and_verify(ui, row,
        lambda: success(f'Mình đã mở cuộc trò chuyện với {name} trên Zalo.')
        if zalo_header_matches(ui.root, name) else None)
    return result or {'message': 'Zalo chưa hiện đúng tiêu đề cuộc trò chuyện; mình chưa xác nhận đã mở đúng người.', 'verified': False}


if __name__ == '__main__':
    # Technical diagnostics only: no contact names, queries, identifiers or messages.
    from pathlib import Path
    log_dir = Path(__file__).parent / 'logs'
    log_dir.mkdir(exist_ok=True)
    trace = logging.getLogger('alex.zalo')
    trace.setLevel(logging.INFO)
    trace.propagate = False
    from logging.handlers import RotatingFileHandler
    handler = RotatingFileHandler(log_dir / 'zalo-actions.log', maxBytes=65536, backupCount=1, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
    trace.addHandler(handler)
    try:
        payload = json.load(sys.stdin)
        target_window = payload.pop('target_window', None)
        action = Action(**payload)
        if action.app == 'Tabs' and action.operation == 'close_current':
            from pet.tab_actions import close_browser_tab
            result = close_browser_tab(auto, target_window)
        elif action.app == 'Spotify' and action.operation in ('play', 'pause', 'next', 'previous', 'song'):
            result = spotify(action)
        elif action.app == 'YouTube' and action.operation in ('play', 'pause', 'next', 'previous', 'song'):
            result = youtube(action)
        elif action.app == 'Zalo' and action.operation == 'chat':
            result = zalo(action)
        else:
            raise ValueError('Chưa hỗ trợ thao tác ứng dụng này.')
    except Exception as exc:
        result = {'message': str(exc)[:240] if isinstance(exc, (RuntimeError, ValueError)) else
                  'Giao diện ứng dụng vừa thay đổi hoặc chưa sẵn sàng. Mình đã dừng; bạn thử lại nhé.',
                  'verified': False, 'error_type': type(exc).__name__}
    print(json.dumps(result, ensure_ascii=False), flush=True)
