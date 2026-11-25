"""Pet approval dialogs exposed only through an authenticated local Windows pipe."""
from __future__ import annotations
import json
import re
from multiprocessing import AuthenticationError
from multiprocessing.connection import Client, Listener
from pathlib import Path
import secrets
import threading
import time
import unicodedata
from typing import Callable
from .computer import Decision
from .config import ROOT

ENDPOINT = ROOT / 'data/desktop-permissions.json'


def _plain(value: str) -> str:
    letters = unicodedata.normalize('NFD', value.casefold().replace('đ', 'd'))
    return re.sub(r'\s+', ' ', ''.join(c for c in letters if unicodedata.category(c) != 'Mn').strip(' .!?…'))


def _has_phrase(text: str, phrase: str) -> bool:
    return bool(re.search(r'(?<!\w)' + re.escape(phrase) + r'(?!\w)', text))


def plan_matches_request(description: str, request: str) -> bool:
    """Never auto-grant a model plan unless its goal is the user's current request."""
    lines = [line.strip() for line in description.splitlines() if line.strip()]
    intent = _plain(request)
    if not (intent and len(lines) >= 2 and lines[0] == 'KẾ HOẠCH THAO TÁC'
            and _plain(lines[1]) == intent) or _negates_sensitive_action(intent):
        return False
    steps = ' '.join(_plain(line) for line in lines[2:] if re.match(r'^\d+\.', line))
    classes = ((('gui', 'send', 'publish', 'dang bai'), ('gui', 'send', 'dang', 'publish')),
               (('xoa', 'delete', 'remove', 'uninstall', 'go cai dat'), ('xoa', 'delete', 'remove', 'go cai dat')),
               (('mua', 'buy', 'pay', 'thanh toan'), ('mua', 'buy', 'pay', 'thanh toan')),
               (('cai dat', 'install'), ('cai dat', 'install')),
               (('powershell', 'command prompt', 'chay lenh'), ('powershell', 'command prompt', 'chay lenh')))
    for steps_words, intent_words in classes:
        if any(re.search(r'\b'+re.escape(word)+r'\b', steps) for word in steps_words):
            if not any(re.search(r'\b'+re.escape(word)+r'\b', intent) for word in intent_words):
                return False
    paths = next((line.partition(':')[2].strip() for line in lines if line.startswith('Đường dẫn:')), '')
    if paths and any(path.strip().casefold() not in request.casefold() for path in paths.split(',')):
        return False
    return True


def _negates_sensitive_action(intent: str) -> bool:
    return bool(re.search(r'\b(?:dung|khong|chua|thoi|huy|ngung)\s+'
                          r'(?:\w+\s+){0,2}(?:gui|dang|xoa|mua|thanh toan|cai dat|'
                          r'chay|ghi de|mo|bat|tat|dong|bam|nhap|delete|send|install|buy|open|close)\b', intent))


def action_matches_request(description: str, request: str) -> bool:
    """Allow a sensitive action without a prompt only when its details are explicit."""
    lines = description.splitlines()
    if not lines or not request.strip():
        return False
    heading = _plain(lines[0])
    intent = _plain(request)
    raw_intent = request.casefold()
    if _negates_sensitive_action(intent):
        return False
    if 'vi tri chua co nhan' in heading:
        return False
    if heading.startswith('chay lenh powershell'):
        command = lines[2].strip() if len(lines) > 2 else ''
        return bool(command and ('powershell' in intent or 'lenh' in intent)
                    and command.casefold() in raw_intent)
    if heading.startswith('chay chuong trinh cu the'):
        try:
            raw = description.split('\n', 1)[1].split('\n\nCửa sổ hiện tại:', 1)[0]
            args = json.loads(raw)
            executable = Path(str(args.get('executable', ''))).stem
            extra = args.get('args') or []
            if isinstance(extra, str):
                extra = [extra]
            return bool(executable and _has_phrase(intent, _plain(executable)) and
                        isinstance(extra, list) and
                        all(str(part).casefold() in raw_intent for part in extra))
        except (ValueError, TypeError, IndexError):
            return False
    if heading.startswith('thao tac file:') or heading.startswith('ghi de dich:'):
        if len(lines) < 2:
            return False
        path = lines[1].strip() if heading.startswith('thao tac file:') else lines[0].split(':', 1)[-1].strip()
        name = Path(path).name
        operations = {'delete': ('xoa', 'delete'), 'move': ('di chuyen', 'move'),
                      'write': ('ghi de', 'viet', 'write')}
        allowed = next((keywords for key, keywords in operations.items() if key in heading), ())
        if heading.startswith('ghi de dich:'):
            allowed = ('ghi de', 'overwrite')
        if not (name and _has_phrase(intent, _plain(name)) and any(_has_phrase(intent, word) for word in allowed)):
            return False
        if 'write' in heading or 'ghi de' in heading:
            content = '\n'.join(lines[3:]).split('\n\nCửa sổ hiện tại:', 1)[0].strip()
            return bool(content and content.casefold() in raw_intent)
        return True
    if heading.startswith('xac nhan nut co the'):
        target = _plain(' '.join(lines[1:2]))
        categories = ((('send', 'gui', 'submit', 'publish', 'dang'), ('gui', 'dang', 'send', 'publish')),
                      (('delete', 'remove', 'xoa', 'uninstall', 'go cai dat'), ('xoa', 'go cai dat', 'delete', 'remove')),
                      (('buy', 'mua', 'pay', 'thanh toan'), ('mua', 'thanh toan', 'buy', 'pay')),
                      (('run', 'execute', 'chay', 'install', 'cai dat'), ('chay', 'cai dat', 'run', 'install')),
                      (('ok', 'yes', 'confirm', 'xac nhan', 'allow', 'cho phep'), ('ok', 'xac nhan', 'dong y', 'cho phep')))
        return any(any(re.search(r'\b' + re.escape(word) + r'\b', target) for word in labels)
                   and any(_has_phrase(intent, word) for word in requested) for labels, requested in categories)
    if heading.startswith(('nhap va gui trong', 'nhap noi dung co xuong dong')):
        content = lines[1].strip() if len(lines) > 1 else ''
        return bool(content and content.casefold() in raw_intent
                    and any(_has_phrase(intent, word) for word in ('gui', 'nhan', 'dang', 'send')))
    if heading.startswith('thao tac luu/dan/thay doi tai lieu'):
        checks = {'ctrl+s': ('luu', 'save'), 'ctrl+v': ('dan', 'paste'),
                  'ctrl+z': ('hoan tac', 'undo'), 'ctrl+y': ('lam lai', 'redo')}
        return any(shortcut in heading and any(_has_phrase(intent, word) for word in keywords)
                   for shortcut, keywords in checks.items())
    return False


def is_launch_only_plan(description: str) -> bool:
    """Only skip the plan dialog for one app launch with read-only verification."""
    if not description:
        return False
    lines = [line.strip() for line in description.splitlines() if line.strip()]
    if len(lines) < 5 or lines[0] != 'KẾ HOẠCH THAO TÁC':
        return False
    app_lines = [i for i, line in enumerate(lines) if line.startswith('Ứng dụng:')]
    if len(app_lines) != 1:
        return False
    app_index = app_lines[0]
    if app_index < 3 or app_index + 2 >= len(lines) or lines[app_index + 1] != 'Đường dẫn:':
        return False
    if len(lines) != app_index + 3 or not lines[-1].startswith('Alex sẽ hỏi riêng'):
        return False
    app = lines[app_index].removeprefix('Ứng dụng:').strip()
    if not app or ',' in app or len(app) > 100:
        return False

    def plain(value: str) -> str:
        letters = unicodedata.normalize('NFD', value.casefold().replace('đ', 'd'))
        return re.sub(r'\s+', ' ', ''.join(c for c in letters if unicodedata.category(c) != 'Mn').strip(' .'))

    name = plain(app)
    launch = {f'mo {name}', f'bat {name}', f'khoi dong {name}',
              f'mo ung dung {name}', f'chuyen sang {name}'}
    verify = {'kiem tra cua so', 'xem cua so', 'xac nhan ung dung da mo',
              f'kiem tra cua so {name}', f'xem cua so {name}',
              f'xac nhan {name} da mo'}
    if plain(lines[1]) not in launch:
        return False
    steps = lines[2:app_index]
    if not 1 <= len(steps) <= 3:
        return False
    for index, step in enumerate(steps, 1):
        match = re.fullmatch(rf'{index}\. (.+)', step)
        if not match or plain(match.group(1)) not in launch | verify:
            return False
    return any(plain(step.split('. ', 1)[1]) in launch for step in steps)


class PermissionBroker:
    def __init__(self, confirm: Callable[[str, Decision], None]) -> None:
        self.confirm = confirm
        self.closed = threading.Event()
        self.lock = threading.Lock()
        self.pending: list[Decision] = []
        self.grants: dict[str, float] = {}
        self.grant_turns: dict[str, tuple[str, str]] = {}
        self.active_turn: tuple[str, str] | None = None
        self.epoch = 0
        key = secrets.token_bytes(32)
        address = r'\\.\pipe\AlexDesktop-' + secrets.token_hex(12)
        self.listener = Listener(address, family='AF_PIPE', authkey=key)
        ENDPOINT.parent.mkdir(parents=True, exist_ok=True)
        temporary = ENDPOINT.with_suffix('.tmp')
        temporary.write_text(json.dumps({'address': address, 'key': key.hex()}), encoding='utf-8')
        temporary.replace(ENDPOINT)
        self.address = address
        self.thread = threading.Thread(target=self._serve, daemon=True, name='Alex-permissions')
        self.thread.start()

    def invalidate(self) -> None:
        with self.lock:
            self.epoch += 1
            self.grants.clear()
            self.grant_turns.clear()
            self.active_turn = None
            for decision in self.pending:
                decision.allowed = False
                decision.done.set()

    def begin_turn(self, request: str) -> str:
        token = secrets.token_hex(16)
        with self.lock:
            self.active_turn = (token, request)
        return token

    def end_turn(self, token: str) -> None:
        with self.lock:
            if self.active_turn and self.active_turn[0] == token:
                self.active_turn = None
            for grant, turn in list(self.grant_turns.items()):
                if turn[0] == token:
                    self.grants.pop(grant, None)
                    self.grant_turns.pop(grant, None)

    def request(self, description: str, timeout: float = 120) -> bool:
        decision = Decision()
        with self.lock:
            epoch = self.epoch
            self.pending.append(decision)
        try:
            self.confirm(description, decision)
            decision.done.wait(timeout)
            with self.lock:
                return decision.done.is_set() and decision.allowed and epoch == self.epoch and not self.closed.is_set()
        finally:
            decision.done.set()
            with self.lock:
                self.pending.remove(decision)

    def _serve(self) -> None:
        while not self.closed.is_set():
            try:
                connection = self.listener.accept()
            except AuthenticationError:
                continue
            except (OSError, EOFError):
                break
            threading.Thread(target=self._handle, args=(connection,), daemon=True).start()

    def _handle(self, connection) -> None:
        with connection:
            try:
                if not connection.poll(5):
                    return
                request = json.loads(connection.recv_bytes(65536))
                operation, grant = request.get('operation'), request.get('grant', '')
                if operation == 'approve_plan':
                    description = str(request.get('description', ''))[:12000]
                    with self.lock:
                        epoch = self.epoch
                        turn = self.active_turn
                    if turn:
                        allowed = plan_matches_request(description, turn[1])
                    elif is_launch_only_plan(description):
                        allowed = True
                    else:
                        allowed = bool(description) and self.request(description)
                    with self.lock:
                        allowed = allowed and epoch == self.epoch and (not turn or self.active_turn == turn)
                        grant = secrets.token_hex(24) if allowed else ''
                        if grant:
                            self.grants[grant] = time.monotonic() + 1200
                            if turn:
                                self.grant_turns[grant] = turn
                    response = {'allowed': allowed, 'grant': grant}
                    if turn and not allowed:
                        response['error'] = 'Kế hoạch chưa khớp yêu cầu vừa nói; Alex đã dừng.'
                elif operation in ('check', 'approve_action', 'finish'):
                    with self.lock:
                        allowed = self.grants.get(grant, 0) > time.monotonic()
                        turn = self.grant_turns.get(grant)
                        if turn:
                            allowed = allowed and self.active_turn == turn
                    if operation == 'approve_action' and allowed:
                        description = str(request.get('description', ''))
                        allowed = (len(description) <= 16000 and
                                   (action_matches_request(description, turn[1]) if turn else self.request(description)))
                        with self.lock:
                            allowed = allowed and self.grants.get(grant, 0) > time.monotonic()
                            if not allowed:
                                self.grants.pop(grant, None)
                                self.grant_turns.pop(grant, None)
                    if operation == 'finish':
                        with self.lock:
                            self.grants.pop(grant, None)
                            self.grant_turns.pop(grant, None)
                    response = {'allowed': allowed}
                else:
                    response = {'allowed': False}
                connection.send_bytes(json.dumps(response).encode('utf-8'))
            except (OSError, ValueError, EOFError):
                return

    def close(self) -> None:
        self.closed.set(); self.invalidate(); self.listener.close()
        try:
            if json.loads(ENDPOINT.read_text(encoding='utf-8')).get('address') == self.address:
                ENDPOINT.unlink()
        except (OSError, ValueError):
            pass


def ask_pet(operation: str, grant: str = '', description: str = '') -> dict:
    try:
        endpoint = json.loads(ENDPOINT.read_text(encoding='utf-8'))
        if not str(endpoint['address']).startswith(r'\\.\pipe\AlexDesktop-'):
            raise ValueError('Unexpected pipe')
        with Client(endpoint['address'], family='AF_PIPE', authkey=bytes.fromhex(endpoint['key'])) as connection:
            connection.send_bytes(json.dumps({'operation': operation, 'grant': grant,
                                              'description': description}, ensure_ascii=False).encode('utf-8'))
            if not connection.poll(125):
                return {'allowed': False, 'error': 'Hết thời gian chờ bạn cấp phép.'}
            return json.loads(connection.recv_bytes(65536))
    except (OSError, ValueError, EOFError, KeyError, AuthenticationError):
        return {'allowed': False, 'error': 'Mở Alex để xem và cấp phép kế hoạch thao tác.'}
