"""Explicit voice intents and a bounded, app-scoped UI Automation worker."""
from __future__ import annotations
from dataclasses import asdict, dataclass
import json
import os
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
    from .window_state import parse_window_state
    window_action = parse_window_state(question)
    if window_action is not None:
        return window_action
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
    if re.search(r'\bđừng\b', raw.casefold()) or re.search(
            r'\b(?:dung|khong|khoan) (?:mo|bat|tim|kiem|gui|tat|tam dung)\b|'
            r'\b(?:khong|khoan) (?:phat|dung|ngung)\b', text):
        return None
    autoplay_clause = (
        r' (?:va|roi) (?:tu(?: dong)? )?(?:phat|mo|bat)'
        r'(?: (?:nhac|bai hat|bai|vua kiem|vua tim|luon|ngay)){0,3}'
        r'(?=$| (?:tren|trong|bang|o|giup|cho|di|nhe|voi|len)\b)'
    )
    guarded = re.sub(autoplay_clause, '', text)
    # This one bounded chain only opens Zalo and searches a contact. Other
    # compound actions (especially send/delete/call) remain outside this router.
    guarded = re.sub(r'\b((?:mo|vao|len) (?:ung dung )?(?:zalo|ra lo|gia lo|za lo)) (?:roi|va) (?=tim(?: kiem)?\b)', r'\1 ', guarded)
    if re.search(r'\b(?:roi|sau do|va gui|va xoa)\b', guarded):
        return None
    prefix = r'(?:(?:vang|da|u|uh|a|o|oi|nay|e|oke|ok|duoc roi)[,\s]+)*(?:(?:alex oi|alex|a lech oi|a lech|ban oi|ban)[,\s]+)*(?:(?:hay|lam on|vui long)[,\s]+)*'
    help_me = r'(?:(?:cho|giup) (?:toi|minh) )?'
    suffix = r'(?: (?:giup|cho) (?:toi|minh))?(?: (?:di|nhe|nha|voi|len|luon|ngay))?'
    platform_names = (
        r'spotify|suppotify|soptily|spot ti phai|so pot ti phai|'
        r'youtube|you tube|du tup|iu tup|diu tup'
    )
    platform = r'(?: (?:tren|trong|bang|o) (?:trang |ung dung |web )?(?P<platform>' + platform_names + r'))?'
    explicit_platform = r' (?:tren|trong|bang|o) (?:trang |ung dung |web )?(?P<platform>' + platform_names + r')'
    autoplay_tail = (
        r'(?: (?:va|roi) (?:tu(?: dong)? )?(?:phat|mo|bat)'
        r'(?: (?:nhac|bai hat|bai|vua kiem|vua tim|luon|ngay)){0,3})?'
    )
    playing_now = r'(?: (?:dang|vua) (?:chay|phat|mo|hat|nghe|bat|kiem|tim))?'
    def match(pattern: str):
        return re.fullmatch(prefix + pattern + suffix, text)
    def original(m, group: str) -> str:
        start, end = m.span(group)
        return raw[positions[start]:positions[end-1]+1].strip() if end > start else ''
    default_music_app = 'YouTube' if last_app == 'YouTube' else 'Spotify'
    def app_of(m, default: str = '') -> str:
        plat = (m.groupdict().get('platform') or m.groupdict().get('lead_platform') or '').strip()
        if plat in ('youtube', 'you tube', 'du tup', 'iu tup', 'diu tup'):
            return 'YouTube'
        if plat:
            return 'Spotify'
        if m.groupdict().get('noun') in ('video', 'video nhac', 'video ca nhac', 'mv', 'clip'):
            return 'YouTube'
        return default or default_music_app
    tab = match(r'(?:dong|tat|close) (?:cai )?(?:tab|tap|the)(?: (?:nay|hien tai|dang xem|dang mo|dang dung))?'
                r'(?: (?:(?:tren|trong|cua) )?(?P<browser>chrome|google chrome|edge|microsoft edge|'
                r'firefox|coc coc))?')
    if tab:
        browser = tab.group('browser') or ''
        browser = {'google chrome': 'chrome', 'microsoft edge': 'edge'}.get(browser, browser)
        return Action('Tabs', 'close_current', browser)
    if match(r'(?:dong|tat|thoat|close) (?:cai )?(?:trang web|website|web|trinh duyet)(?: (?:nay|hien tai|dang xem|dang mo|dang dung|dang su dung))?'):
        return Action('Window', 'close_current', 'trình duyệt')
    if match(r'(?:dong|tat|thoat|close) (?:cai )?(?:ung dung|phan mem|cua so|app|chuong trinh)(?: (?:nay|hien tai|dang dung|dang mo|dang su dung|dang xem))?'):
        return Action('Window', 'close_current')
    closing = match(r'(?:dong|tat|close|thoat) (?:cai )?(?:cua so |ung dung |phan mem |app |trang web |website |web |trinh duyet )?(?P<app>.+?)')
    if closing and not re.search(
            r'\b(?:tab|tap|the|tat ca|het|may|nguon|man hinh|tieng|am|loa|nhac|bai hat|video|luot|cuon|pet|alex|a lech|mic|va|roi|sau|file|tep|tai lieu)\b',
            closing.group('app')):
        target_app = re.sub(r'\s+(?:nay|hien tai|dang dung|dang mo|dang xem|dang chay)$', '', original(closing, 'app'), flags=re.IGNORECASE).strip()
        return Action('Window', 'close_current', target_app)
    if last_app in ('Spotify', 'YouTube', 'Trình duyệt'):
        target_media_app = 'Spotify' if last_app == 'Spotify' else 'YouTube'
        if match(r'(?:dung lai|tam dung|ngung lai|tat di|dung phat(?: video| nhac)?|tam dung (?:video|nhac)|dung (?:video|nhac))'):
            return Action(target_media_app, 'pause')
        if match(r'(?:tiep tuc|phat tiep(?: video| nhac)?|bat lai|mo tiep|nghe tiep|tiep tuc phat(?: video| nhac)?)'):
            return Action(target_media_app, 'play')
        if last_app in ('Spotify', 'YouTube') and match(r'(?:bai khac|bai nua|bai ke tiep|sang bai khac)'):
            return Action(last_app, 'next')
    play_cmd = match(
        r'(?:mo|bat|phat|nghe|cho (?:toi|minh) nghe|tiep tuc phat|tiep tuc|phat tiep|bat tiep|mo tiep) '
        + help_me + r'(?P<noun>nhac|bai hat|bai nhac|video(?: nhac)?|mv|clip)(?: (?:tiep|lai|dang dung|dang tam dung))?' + platform
    )
    if play_cmd:
        return Action(app_of(play_cmd), 'play')
    pause_cmd = match(
        r'(?:tam dung|dung|ngung|tat) ' + help_me +
        r'(?:phat )?(?P<noun>nhac|bai hat|bai nhac|bai|video(?: nhac)?|mv|clip)' +
        playing_now + r'(?: (?:lai|di))?' + platform
    )
    if pause_cmd:
        return Action(app_of(pause_cmd), 'pause')
    pause_app = match(
        r'(?:tam dung|dung|ngung) ' + help_me +
        r'(?:video |phat |nhac )?(?P<platform>' + platform_names + r')' + playing_now
    )
    if pause_app:
        return Action(app_of(pause_app), 'pause')
    next_cmd = match(
        r'(?:bai tiep(?: theo)?|chuyen (?:sang )?bai(?: hat| nhac)?(?: tiep theo| khac| moi)?|'
        r'qua bai(?: tiep theo| khac)?|doi bai(?: khac)?|sang bai (?:tiep(?: theo)?|khac))' + platform
    )
    if next_cmd:
        return Action(app_of(next_cmd), 'next')
    prev_cmd = match(r'(?:bai truoc(?: do)?|quay lai bai truoc|chuyen ve bai truoc|lui bai)' + platform)
    if prev_cmd:
        return Action(app_of(prev_cmd), 'previous')
    zalo = r'(?:zalo|ra lo|gia lo|za lo)'
    zalo_location = r'(?:tren|trong|o) (?:ung dung )?' + zalo
    contact_noun = r'(?:doan tin nhan|cuoc tro chuyen|doan chat|tin nhan|lien he|nhom|chat|nguoi)'
    contact_prefix = r'(?:(?:' + contact_noun + r')(?: (?:voi|cua|ten))? |ten )?'
    contact_verb = r'(?:mo|vao|tim(?: kiem)?(?: va mo)?)'
    # Ask locally for an omitted target instead of spending an LLM turn.
    if match(r'(?:mo|vao(?: trong)?|xem|tim(?: kiem)?) ' + help_me + contact_noun + r'(?: ten)?(?: (?:(?:tren|trong|o) )?(?:ung dung )?' + zalo + r')?'):
        return Action('Zalo', 'ask_contact')
    if match(r'(?:mo|vao|tim(?: kiem)?) ' + help_me + r'ten (?:' + zalo_location + r')'):
        return Action('Zalo', 'ask_contact')
    contact = match(contact_verb + r' ' + help_me + contact_prefix +
                    r'(?P<name>.+?)(?: (?:giup|cho) (?:toi|minh))? ' + zalo_location)
    if not contact:
        contact = match(r'(?:mo|vao|len) (?:ung dung )?' + zalo + r' (?:roi |va )?'
                        r'tim(?: kiem)? ' + help_me + contact_prefix + r'(?P<name>.+?)')
    if not contact:
        contact = match(contact_verb + r' ' + help_me + contact_noun +
                        r'(?: (?:voi|cua|ten))? (?P<name>.+?)')
    if not contact and last_app == 'Zalo':
        contact = match(r'tim(?: kiem)? ' + help_me + contact_prefix + r'(?P<name>.+?)')
        if contact and re.search(r'\b(?:tren google|tren mang|tren web|tren internet|file|tep|thu muc|ung dung|phan mem|bai hat|video)\b', contact.group('name')):
            contact = None
    if contact:
        target = original(contact, 'name').strip(' \"“”')
        if folded(target) in ('', 'ten', 'ai', 'lien he', 'nguoi', 'tin nhan', 'nhom'):
            return Action('Zalo', 'ask_contact')
        return Action('Zalo', 'chat', target)
    song_verbs = (
        r'(?:(?:mo|vao|len) (?:ung dung |trang |web )?(?P<lead_platform>' + platform_names + r') '
        r'(?:roi |va )?)?'
        r'(?:mo|phat|bat|nghe|cho (?:toi|minh) nghe|toi muon nghe|minh muon nghe|'
        r'tim(?: kiem)?(?: (?:va|roi) (?:tu(?: dong)? )?(?:phat|mo|bat)(?: luon| ngay)?)?|'
        r'kiem(?: (?:va|roi) (?:tu(?: dong)? )?(?:phat|mo|bat)(?: luon| ngay)?)?)'
    )
    song_nouns = r'(?:(?P<noun>bai(?: hat| nhac)?|ca khuc|ban nhac|nhac|video(?: nhac| ca nhac)?|mv|clip)(?: cua)?)'
    tail_clauses = r'(?: (?:giup|cho) (?:toi|minh))?' + autoplay_tail + platform + autoplay_tail
    song = match(
        song_verbs + r' ' + help_me + song_nouns +
        r' (?P<title>.+?)(?: cua (?P<artist>.+?))?' + tail_clauses
    )
    if not song:
        song = match(
            r'(?:tim(?: kiem)?|kiem) (?:va|roi) (?:tu(?: dong)? )?phat(?: luon| ngay)? '
            + help_me + r'(?P<title>.+?)(?: cua (?P<artist>.+?))?' + tail_clauses
        )
    if not song:
        song = match(
            r'(?:mo|phat|bat|nghe|cho (?:toi|minh) nghe|tim(?: kiem)?|kiem) '
            + help_me + r'(?P<title>.+?)(?: cua (?P<artist>.+?))?'
            + r'(?: (?:giup|cho) (?:toi|minh))?' + autoplay_tail + explicit_platform + autoplay_tail
        )
    if not song:
        song = match(
            r'(?:mo|vao|len) (?:ung dung |trang |web )?(?P<lead_platform>' + platform_names + r') '
            r'(?:roi |va )?(?:mo|phat|bat|nghe|tim(?: kiem)?|kiem) '
            + help_me + r'(?P<title>.+?)(?: cua (?P<artist>.+?))?' + tail_clauses
        )
    if song:
        title_val = original(song, 'title')
        if folded(title_val) not in ('', 'nhac', 'bai hat', 'bai nhac', 'video', 'mv', 'clip', 'dang chay', 'dang phat'):
            return Action(app_of(song), 'song', title_val,
                          original(song, 'artist') if song.group('artist') else '')
    if last_app in ('Spotify', 'YouTube'):
        ctx_song = match(
            r'(?:tim(?: kiem)?|kiem|phat|nghe|cho (?:toi|minh) nghe) '
            + help_me + r'(?P<title>.+?)(?: cua (?P<artist>.+?))?' + tail_clauses
        )
        if ctx_song:
            title_val = original(ctx_song, 'title')
            t_fold = folded(title_val)
            if (t_fold not in ('', 'nhac', 'bai hat', 'bai nhac', 'video', 'mv', 'clip', 'youtube', 'spotify', 'zalo', 'dang chay', 'dang phat')
                    and not re.search(r'\b(?:tren google|tren mang|tren web|tren internet|file|tep|thu muc|ung dung|phan mem|my documents|tai lieu)\b', t_fold)):
                return Action(last_app, 'song', title_val,
                              original(ctx_song, 'artist') if ctx_song.group('artist') else '')
    return None


def parse_contextual_song(question: str, last_app: str = '') -> Action | None:
    """Parse bare 'Mở <tên bài>' / 'Bật <tên bài>' as a song when Spotify/YouTube is active and no app/site matched."""
    if last_app not in ('Spotify', 'YouTube'):
        return None
    raw = unicodedata.normalize('NFC', ' '.join(question.strip(' .!?').split()))
    chars: list[str] = []; positions: list[int] = []
    for index, char in enumerate(raw):
        for part in folded(char):
            chars.append(part); positions.append(index)
        if char == ' ':
            chars.append(' '); positions.append(index)
    text = ''.join(chars)
    if re.search(r'\bđừng\b', raw.casefold()) or re.search(
            r'\b(?:dung|khong|khoan|ung dung|phan mem|app|chuong trinh|game|trang web|website|web|'
            r'file|tep|thu muc|tai lieu|cua so|tab|my documents|roi|sau do|va gui|va xoa)\b', text):
        return None
    prefix = r'(?:(?:vang|da|u|uh|a|o|oi|nay|e|oke|ok|duoc roi)[,\s]+)*(?:(?:alex oi|alex|a lech oi|a lech|ban oi|ban)[,\s]+)*(?:(?:hay|lam on|vui long)[,\s]+)*'
    help_me = r'(?:(?:cho|giup) (?:toi|minh) )?'
    suffix = r'(?: (?:giup|cho) (?:toi|minh))?(?: (?:di|nhe|nha|voi|len|luon|ngay))?'
    m = re.fullmatch(
        prefix + r'(?:mo|bat) ' + help_me + r'(?P<title>.+?)(?: cua (?P<artist>.+?))?' + suffix,
        text,
    )
    if not m:
        return None
    def original(group: str) -> str:
        start, end = m.span(group)
        return raw[positions[start]:positions[end-1]+1].strip() if end > start else ''
    title_val = original('title')
    t_fold = folded(title_val)
    if t_fold in ('', 'nhac', 'bai hat', 'bai nhac', 'video', 'mv', 'clip', 'youtube', 'spotify', 'zalo', 'google', 'tiktok', 'facebook'):
        return None
    return Action(last_app, 'song', title_val, original('artist') if m.group('artist') else '')


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
        if action.app == 'Window' and action.operation in ('maximize', 'minimize', 'restore'):
            from .window_state import change_window_state
            if action.query == 'browser':
                return change_window_state(action.operation, cancelled, browser_only=True)
            return change_window_state(action.operation, cancelled)
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
        # App/device workers belong to Alex and use its pinned dependencies.
        # computer.command is a separate MCP installation; it can be moved or
        # removed without breaking music, contacts, and browser-tab commands.
        executable = ROOT / '.venv' / 'Scripts' / 'python.exe'
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
