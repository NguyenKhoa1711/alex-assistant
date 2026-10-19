"""Local, explicit teaching of phrases to verified app actions."""
from __future__ import annotations
from contextlib import closing
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import sqlite3
import time
import unicodedata
from urllib.parse import urlparse
from .app_actions import Action, folded, parse_action
from .apps import requested_app, requested_web


@dataclass(frozen=True)
class Lesson:
    operation: str
    phrase: str = ''
    target: str = ''


def clean_phrase(text: str) -> str:
    return unicodedata.normalize('NFC', ' '.join(text.split())).strip(' .!?“”"')


def phrase_key(text: str) -> str:
    return folded(clean_phrase(text))


def web_requested(question: str) -> bool:
    text = folded(question)
    prefix = r'^(?:(?:hay|ban|vui long|lam on) )*(?:(?:giup|cho) (?:toi|minh) )?'
    project = re.match(prefix + r'(?:lam|tao|xay dung|phat trien|trien khai|thuc hien)\b', text)
    if project and re.search(r'\b(?:project|du an)\b', text[project.end():project.end() + 100]):
        return True
    command = re.match(prefix + r'(?:tim(?: kiem)?|tra(?: cuu)?|kiem tra|xem|doc|mo)\b', text)
    if not command:
        return False
    remainder = text[command.end():]
    return bool(re.search(r'\b(?:tren mang|tren web|internet|google|tren trang)\b', remainder)
                or re.search(r'https?://', remainder))


def teachable_phrase(text: str) -> bool:
    key = phrase_key(text)
    return bool(key) and len(text) <= 180 and not any(c in text for c in '\n?') and not re.search(
        r'\b(?:dung|khong|khoan) (?:mo|bat|chay|phat|tim|gui|xoa)|'
        r'^(?:cach |lam sao |tai sao |vi sao |toi dang |minh dang |neu )|'
        r'\b(?:roi|sau do|va gui|va xoa)\b', key)


def parse_lesson(question: str) -> Lesson | None:
    raw = clean_phrase(question)
    chars: list[str] = []; positions: list[int] = []
    for i, char in enumerate(raw):
        for part in (folded(char) if char != ' ' else ' '):
            chars.append(part); positions.append(i)
    text = ''.join(chars)
    def original(match: re.Match[str], group: str) -> str:
        start, end = match.span(group)
        return clean_phrase(raw[positions[start]:positions[end - 1] + 1])
    prefix = r'(?:(?:hay|ban) )?'
    teach = re.fullmatch(prefix + r'(?:(?:nho|ghi nho|hoc)(?: rang)?[:,]? )?'
        r'khi (?:toi|minh) noi (?P<phrase>.+?) (?:thi|nghia la|y (?:toi|minh) la) (?P<target>.+)', text)
    if not teach:
        teach = re.fullmatch(prefix + r'(?:hoc|day) (?:cach noi|lenh)[:,]? (?P<phrase>.+?) (?:nghia la|la) (?P<target>.+)', text)
    if teach:
        return Lesson('teach', original(teach, 'phrase'), original(teach, 'target'))
    forget = re.fullmatch(prefix + r'(?:quen|xoa) (?:cach noi|lenh da hoc)[:,]? (?P<phrase>.+)', text)
    if forget:
        return Lesson('forget', original(forget, 'phrase'))
    if re.fullmatch(prefix + r'(?:xem (?:cac )?lenh da hoc|ban da hoc (?:nhung )?lenh nao|xem cac cach noi da hoc)', text):
        return Lesson('list')
    correction = re.fullmatch(r'(?:khong phai[, ]+)?y (?:toi|minh) la[:,]? (?P<target>.+)', text)
    if correction:
        return Lesson('correct', target=original(correction, 'target'))
    return None


def resolve_target(text: str, entries: list[dict], sites: list[dict] | None = None) -> Action | None:
    entry = requested_app(text, entries)
    if entry:
        return Action(entry['name'], 'launch')
    website = requested_web(text, sites)
    if website:
        return Action('Web', 'open', website[0])
    action = parse_action(text)
    return action if action and action.operation not in ('ask_contact', 'cancel') else None


def valid_target(action: Action, entries: list[dict]) -> bool:
    if action.app == 'Web' and action.operation == 'open' and not action.artist:
        url = urlparse(action.query)
        return (url.scheme in ('http', 'https') and bool(url.hostname) and
                not url.username and not url.password and len(action.query) <= 2000)
    if action.app == 'Desktop' and action.operation == 'task':
        return bool(action.query.strip()) and len(action.query) <= 1200 and not action.artist
    if action.app not in {entry['name'] for entry in entries}:
        return False
    if action.operation == 'launch':
        return not action.query and not action.artist
    if action.app == 'Spotify' and action.operation in ('play', 'pause', 'next', 'previous'):
        return not action.query and not action.artist
    if (action.app, action.operation) not in (('Spotify', 'song'), ('Zalo', 'chat')):
        return False
    return bool(action.query) and len(action.query) <= 150 and len(action.artist) <= 150 and not any(
        c in action.query + action.artist for c in '\r\n')


def describe(action: Action) -> str:
    if action.app == 'Web' and action.operation == 'open':
        return f'mở {action.query}'
    if action.app == 'Desktop' and action.operation == 'task':
        return action.query
    if action.operation == 'launch':
        return f'mở {action.app}'
    if action.operation == 'chat':
        return f'mở tin nhắn với {action.query} trên Zalo'
    if action.operation == 'song':
        return f'phát bài {action.query}' + (f' của {action.artist}' if action.artist else '') + ' trên Spotify'
    return {'play': 'phát nhạc Spotify', 'pause': 'tạm dừng nhạc Spotify',
            'next': 'chuyển bài tiếp theo trên Spotify', 'previous': 'quay lại bài trước trên Spotify'}[action.operation]


class LearningStore:
    def __init__(self, path: Path, entries: list[dict], limit: int = 200,
                 sites: list[dict] | None = None) -> None:
        self.path, self.entries, self.limit = path, entries, limit
        self.sites = sites or []

    def _create(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=2)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS phrases ('
                'key TEXT PRIMARY KEY, phrase TEXT NOT NULL, action TEXT NOT NULL, '
                'successes INTEGER NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0, updated REAL NOT NULL)')

    def put(self, phrase: str, action: Action, verified: bool = False) -> None:
        if not teachable_phrase(phrase) or not valid_target(action, self.entries):
            raise ValueError('Cách nói hoặc thao tác này chưa phù hợp để ghi nhớ.')
        builtin = resolve_target(phrase, self.entries, self.sites) or parse_action(phrase, 'Spotify')
        if builtin is not None and builtin != action:
            raise ValueError('Câu này đã có nghĩa rõ ràng. Bạn chọn một cách nói riêng để tránh đổi nhầm lệnh cũ nhé.')
        self._create()
        with closing(sqlite3.connect(self.path, timeout=2)) as db, db:
            exists = db.execute('SELECT 1 FROM phrases WHERE key=?', (phrase_key(phrase),)).fetchone()
            if not exists and db.execute('SELECT count(*) FROM phrases').fetchone()[0] >= self.limit:
                raise ValueError('Bộ nhớ cách nói đã đầy; bạn quên một lệnh cũ trước nhé.')
            db.execute('INSERT INTO phrases(key,phrase,action,successes,updated) VALUES(?,?,?,?,?) '
                'ON CONFLICT(key) DO UPDATE SET phrase=excluded.phrase, action=excluded.action, '
                'successes=excluded.successes, failures=0, updated=excluded.updated',
                (phrase_key(phrase), clean_phrase(phrase), json.dumps(asdict(action), ensure_ascii=False),
                 int(verified), time.time()))

    def lookup(self, phrase: str) -> Action | None:
        if not self.path.exists() or not teachable_phrase(phrase):
            return None
        with closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
            row = db.execute('SELECT action FROM phrases WHERE key=?', (phrase_key(phrase),)).fetchone()
        if row:
            try:
                action = Action(**json.loads(row[0]))
                return action if valid_target(action, self.entries) else None
            except (TypeError, ValueError):
                return None
        return None

    def record_result(self, phrase: str, verified: bool) -> None:
        if not self.path.exists():
            return
        column = 'successes' if verified else 'failures'
        with closing(sqlite3.connect(self.path, timeout=2)) as db, db:
            db.execute(f'UPDATE phrases SET {column}={column}+1, updated=? WHERE key=?',
                       (time.time(), phrase_key(phrase)))

    def forget(self, phrase: str) -> bool:
        if not self.path.exists():
            return False
        with closing(sqlite3.connect(self.path, timeout=2)) as db, db:
            return bool(db.execute('DELETE FROM phrases WHERE key=?', (phrase_key(phrase),)).rowcount)

    def rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        with closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
            data = db.execute('SELECT phrase,action,successes,failures FROM phrases ORDER BY updated DESC LIMIT ?',
                              (self.limit,)).fetchall()
        result = []
        for phrase, encoded, successes, failures in data:
            try:
                action = Action(**json.loads(encoded))
                if valid_target(action, self.entries):
                    result.append({'phrase': phrase, 'target': describe(action), 'successes': successes, 'failures': failures})
            except (TypeError, ValueError):
                continue
        return result
