"""Request a fixed, temporary display override; never elevate the pet itself."""
from __future__ import annotations

import logging
import os
from pathlib import Path
import secrets
import subprocess
import time

INSTALL = Path(r'D:\AlexPowerPriority-System')
REQUEST = INSTALL / 'requests' / 'request.txt'
TASK = 'Alex Display Priority'
_ticket: str | None = None


def _status(ticket: str) -> str:
    try:
        parts = (INSTALL / 'status.txt').read_text('utf-8-sig').strip().split('|')
        return parts[1] if len(parts) == 3 and parts[0] == ticket else ''
    except OSError:
        return ''


def _wait(ticket: str, expected: str, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        state = _status(ticket)
        if state == expected:
            return
        if state.startswith('error_') or state in {'cancelled', 'restore_failed', 'restored'}:
            raise OSError('Bộ ưu tiên màn hình chưa sẵn sàng: ' + state)
        time.sleep(0.05)
    raise OSError('Hết thời gian chờ bộ ưu tiên màn hình Alex.')


def begin_display_priority() -> str:
    global _ticket
    if not (INSTALL / 'AlexDisplayPriority.exe').is_file():
        raise OSError('Chưa cài bộ ưu tiên màn hình Alex.')
    cancel_display_priority()
    _ticket = secrets.token_hex(16)
    try:
        REQUEST.parent.mkdir(parents=True, exist_ok=True)
        temporary = REQUEST.with_suffix('.tmp')
        temporary.write_text(f'{_ticket}|{int(time.time() * 1000)}|{os.getpid()}', encoding='ascii')
        os.replace(temporary, REQUEST)
        subprocess.run([os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'schtasks.exe'),
                        '/Run', '/TN', TASK], check=True, timeout=8,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        _wait(_ticket, 'armed', 6)
        return _ticket
    except (OSError, subprocess.SubprocessError):
        cancel_display_priority()
        raise OSError('Không khởi động được bộ ưu tiên màn hình Alex.') from None


def confirm_display_priority(ticket: str) -> None:
    _wait(ticket, 'active', 6)
    logging.info('DISPLAY_PRIORITY active until Windows unlocks')


def cancel_display_priority() -> None:
    global _ticket
    ticket, _ticket = _ticket, None
    if ticket is None:
        return
    try:
        if REQUEST.read_text('ascii').startswith(ticket + '|'):
            REQUEST.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        logging.exception('Could not cancel display priority request')
