"""Explicit voice intents and a bounded, app-scoped UI Automation worker."""
from __future__ import annotations
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import unicodedata
from .config import ROOT


@dataclass(frozen=True)
class Action:
    app: str
    operation: str
    query: str = ''
    artist: str = ''


@dataclass(frozen=True)
class ActionResult:
    message: str
    verified: bool = False
    seconds: float = 0
    followup: str = ''


def folded(text: str) -> str:
    return ' '.join(''.join(c for c in unicodedata.normalize('NFD', text.casefold().replace('đ', 'd'))
                           if unicodedata.category(c) != 'Mn').split())


def artist_matches(requested: str, actual: str) -> bool:
    return bool(re.search(r'(?<!\w)' + re.escape(folded(requested)) + r'(?!\w)', folded(actual)))


def parse_action(question: str, last_app: str = '') -> Action | None:
    from .device_actions import parse_device_action
    device_action = parse_device_action(question)
    if device_action is not None:
        return device_action
    raw = unicodedata.normalize('NFC', ' '.join(question.strip(' .!?').split()))
    # Preserve the user's accents in names while matching Vietnamese command words.
    chars: list[str] = []; positions: list[int] = []
    for index, char in enumerate(raw):
        for part in folded(char):
            chars.append(part); positions.append(index)
        if char == ' ':
            chars.append(' '); positions.append(index)
    text = ''.join(chars)
    if re.search(r'\b(?:dung|khong|khoan) (?:mo|phat|bat|tim|gui)|\b(?:roi|sau do|va gui|va xoa)\b', text):
        return None
    prefix = r'(?:(?:alex oi|alex|ban) )?(?:(?:hay|lam on|vui long) )?'
    help_me = r'(?:(?:cho|giup) (?:toi|minh) )?'
    suffix = r'(?: (?:giup|cho) (?:toi|minh))?(?: (?:di|nhe|voi|len))?'
    spotify = r'(?: (?:tren|trong|bang|o) (?:ung dung )?(?:spotify|suppotify|soptily))?'
    def match(pattern: str):
        return re.fullmatch(prefix + pattern + suffix, text)
    def original(m, group: str) -> str:
        start, end = m.span(group)
        return raw[positions[start]:positions[end-1]+1].strip() if end > start else ''
    tab = match(r'(?:dong|tat|close) (?:cai )?(?:tab|tap|the)(?: (?:nay|hien tai|dang xem|dang mo|dang dung))?'
                r'(?: (?:(?:tren|trong|cua) )?(?P<browser>chrome|google chrome|edge|microsoft edge|'
                r'firefox|coc coc))?')
    if tab:
        browser = tab.group('browser') or ''
        browser = {'google chrome': 'chrome', 'microsoft edge': 'edge'}.get(browser, browser)
        return Action('Tabs', 'close_current', browser)
    if match(r'(?:dong|tat|thoat|close) (?:cai )?(?:ung dung|phan mem|cua so|app)(?: (?:nay|hien tai|dang dung|dang mo|dang su dung))?'):
        return Action('Window', 'close_current')
    closing = match(r'(?:dong|close|thoat) (?:ung dung |phan mem |app )?(?P<app>.+?)')
    if closing and not re.search(r'\b(?:tab|tap|the|tat ca|het|may|nguon|va|roi|sau|file|tep|tai lieu|cua so)\b', closing.group('app')):
        return Action('Window', 'close_current', original(closing, 'app'))
    if last_app == 'Spotify':
        if match(r'(?:dung lai|tam dung|ngung lai|tat di|dung phat)'):
            return Action('Spotify', 'pause')
        if match(r'(?:tiep tuc|phat tiep|bat lai|mo tiep|nghe tiep)'):
            return Action('Spotify', 'play')
        if match(r'(?:bai khac|bai nua|bai ke tiep|sang bai khac)'):
            return Action('Spotify', 'next')
    if match(r'(?:mo|bat|phat|nghe|cho (?:toi|minh) nghe|tiep tuc phat|tiep tuc) ' + help_me + r'(?:nhac|bai hat)' + spotify):
        return Action('Spotify', 'play')
    if match(r'(?:tam dung|dung|ngung|tat) (?:nhac|phat nhac|bai hat)' + spotify):
        return Action('Spotify', 'pause')
    if match(r'(?:bai tiep(?: theo)?|chuyen bai(?: hat)?(?: tiep theo)?|qua bai|doi bai)' + spotify):
        return Action('Spotify', 'next')
    if match(r'(?:bai truoc|quay lai bai truoc)' + spotify):
        return Action('Spotify', 'previous')
    song = match(r'(?:mo|phat|bat|nghe|cho (?:toi|minh) nghe|toi muon nghe|minh muon nghe|tim va phat) ' + help_me +
                 r'(?:bai(?: hat| nhac)?|nhac) (?P<title>.+?)(?: cua (?P<artist>.+?))?' + spotify)
    if song:
        return Action('Spotify', 'song', original(song, 'title'),
                      original(song, 'artist') if song.group('artist') else '')
    zalo = r'(?:zalo|ra lo|gia lo|za lo)'
    if match(r'(?:mo|vao(?: trong)?|xem) ' + help_me + r'(?:tin nhan|chat|cuoc tro chuyen)(?: (?:(?:tren|trong|o) )?' + zalo + r')?'):
        return Action('Zalo', 'ask_contact')
    contact = match(r'(?:mo|tim(?: va mo)?|vao) ' + help_me +
        r'(?:tin nhan|doan tin nhan|cuoc tro chuyen|doan chat|chat|lien he|nhom)(?: (?:voi|cua|ten))? (?P<name>.+?)(?: (?:tren|trong|o) ' + zalo + r')?')
    if not contact:
        contact = match(r'(?:mo|tim(?: va mo)?|vao) ' + help_me + r'(?P<name>.+?) (?:tren|trong|o) ' + zalo)
    if contact:
        return Action('Zalo', 'chat', original(contact, 'name'))
    if match(r'(?:mo|vao|xem) ' + help_me + r'(?:tin nhan|chat|cuoc tro chuyen)(?: (?:tren|trong|o) ' + zalo + r')?'):
        return Action('Zalo', 'ask_contact')
    if last_app == 'Zalo':
        # A bare "mở X" may name another app, so only "tìm X" uses Zalo context.
        contact = match(r'tim ' + help_me + r'(?P<name>.+)')
        if contact:
            return Action('Zalo', 'chat', original(contact, 'name'))
    return None


class AppActions:
    def __init__(self, config: dict) -> None:
        self.cfg = config

    def execute(self, action: Action, cancelled: threading.Event) -> ActionResult:
        if action.operation == 'ask_contact':
            return ActionResult('Bạn muốn mở cuộc trò chuyện với ai trên Zalo?', followup='contact')
        if action.operation == 'cancel':
            return ActionResult('Mình đã hủy tìm cuộc trò chuyện.' if action.app == 'Zalo' else 'Mình đã hủy tìm bài hát.')
        if cancelled.is_set():
            return ActionResult('Đã dừng theo yêu cầu của bạn.')
        request_data = asdict(action)
        if action.app == 'Window' and action.operation == 'close_current':
            from .window_actions import close_app_window
            return close_app_window(action.query, self.cfg, cancelled)
        if action.app == 'Tabs' and action.operation == 'close_current':
            from .tab_actions import prepare_tab_close
            prepared = prepare_tab_close(action.query)
            if isinstance(prepared, ActionResult):
                return prepared
            request_data['target_window'] = prepared
        is_device = action.app in ('Volume', 'Brightness')
        executable = (ROOT / '.venv' / 'Scripts' / 'python.exe' if is_device else
                      Path(self.cfg['computer']['command']).resolve().with_name('python.exe'))
        if not executable.is_file():
            raise RuntimeError('Chưa có bộ điều khiển Windows của pet.')
        started = time.monotonic()
        worker = 'device_action_worker.py' if is_device else 'app_action_worker.py'
        process = subprocess.Popen([str(executable), str(ROOT / worker)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            encoding='utf-8', env={**os.environ, 'PYTHONIOENCODING': 'utf-8',
                                  'ANONYMIZED_TELEMETRY': 'false', 'DO_NOT_TRACK': '1'},
            creationflags=subprocess.CREATE_NO_WINDOW)
        request: str | None = json.dumps(request_data, ensure_ascii=False)
        timeout = 10 if is_device else self.cfg.get('actions', {}).get('timeout_seconds', 35)
        try:
            while True:
                try:
                    output, _ = process.communicate(request, timeout=.1)
                    break
                except subprocess.TimeoutExpired:
                    request = None
                    if cancelled.is_set() or time.monotonic() - started > timeout:
                        process.terminate(); process.communicate(timeout=3)
                        return ActionResult('Đã dừng chờ thao tác. Bạn kiểm tra cửa sổ ứng dụng trước khi thử lại.')
            if process.returncode:
                raise RuntimeError('Không chạy được bộ điều khiển ứng dụng.')
            result = json.loads(output)
            return ActionResult(result['message'], bool(result.get('verified')), time.monotonic() - started,
                                result.get('followup', ''))
        finally:
            if process.poll() is None:
                process.terminate(); process.wait(timeout=3)
