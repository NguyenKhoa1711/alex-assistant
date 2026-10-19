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
            for decision in self.pending:
                decision.allowed = False
                decision.done.set()

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
                    if is_launch_only_plan(description):
                        allowed = True
                    else:
                        allowed = bool(description) and self.request(description)
                    with self.lock:
                        allowed = allowed and epoch == self.epoch
                        grant = secrets.token_hex(24) if allowed else ''
                        if grant:
                            self.grants[grant] = time.monotonic() + 1200
                    response = {'allowed': allowed, 'grant': grant}
                elif operation in ('check', 'approve_action', 'finish'):
                    with self.lock:
                        allowed = self.grants.get(grant, 0) > time.monotonic()
                    if operation == 'approve_action' and allowed:
                        description = str(request.get('description', ''))
                        allowed = len(description) <= 16000 and self.request(description)
                        with self.lock:
                            allowed = allowed and self.grants.get(grant, 0) > time.monotonic()
                            if not allowed:
                                self.grants.pop(grant, None)
                    if operation == 'finish':
                        with self.lock:
                            self.grants.pop(grant, None)
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
