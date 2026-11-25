"""Pure, fail-closed parser for Messenger UIA message rows.

Reconstructs fragmented UIA text nodes, validates stable node IDs (never
ephemeral snapshot refs), and refuses to report outgoing messages unless
author and delivery status are explicitly verified.
"""
from __future__ import annotations

import re
import unicodedata

from pet.verified_adapter import OutgoingMessage

_SENDER_HINTS = ('you sent', 'sent by you', 'ban da gui')
_ACTION_CHROME = frozenset({
    'reply', 'react', 'more', 'forward', 'remove', 'unsend',
    'tra loi', 'bay to cam xuc', 'xem them', 'chuyen tiep', 'go',
})
_STATUS_MAP = {
    'sent': 'sent',
    'da gui': 'sent',
    'delivered': 'delivered',
    'da nhan': 'delivered',
    'da giao': 'delivered',
    'seen': 'seen',
    'da xem': 'seen',
    'sending': 'sending',
    'dang gui': 'sending',
    'failed': 'failed',
    'not sent': 'failed',
    'could not send': 'failed',
    "couldn't send": 'failed',
    'failed to send': 'failed',
    'khong gui duoc': 'failed',
    'gui that bai': 'failed',
    'loi gui': 'failed',
}
_TEXT_ROLES = frozenset({'text', 'statictext', 'label', 'link'})
_CHROME_ROLES = frozenset({'button', 'menuitem', 'toolbar', 'textbox', 'searchfield'})


def _fold(value: str) -> str:
    nfd = unicodedata.normalize('NFD', (value or '').casefold().replace('đ', 'd'))
    cleaned = ''.join(ch for ch in nfd if unicodedata.category(ch) != 'Mn')
    return re.sub(r'\s+', ' ', cleaned).strip()


def normalize_delivery_status(label: str) -> str | None:
    """Return canonical delivery status or None if label is not explicit."""
    key = _fold(label)
    if not key:
        return None
    if key in _STATUS_MAP:
        return _STATUS_MAP[key]
    for phrase, canonical in _STATUS_MAP.items():
        # Messenger also exposes exact relative-time labels, such as
        # "Đã gửi 3 giờ trước".  Require both a numeric duration and its
        # language-specific suffix; attachment captions are not evidence.
        relative = r'(?:\d+\s+(?:giay|phut|gio|ngay|tuan)\s+truoc|\d+\s+(?:seconds?|minutes?|hours?|days?|weeks?)\s+ago)'
        if re.fullmatch(rf'{re.escape(phrase)}\s+{relative}[.!?…]*', key):
            return canonical
        if re.fullmatch(
            rf'{re.escape(phrase)}(?:\s+(?:luc|at|vao)?\s*\d{{1,2}}[:.]\d{{2}}(?:\s*[ap]m)?)?[.!?…]*',
            key,
        ):
            return canonical
    return None


def is_user_sender_hint(label: str) -> bool:
    """Return True when a UIA label explicitly indicates the current user sent the message."""
    key = _fold(label)
    return (any(hint in key for hint in _SENDER_HINTS)
            or bool(re.search(r'(?:^|,\s*)tin nhan do ban gui luc\b', key)))


def extract_stable_node_id(node: dict) -> str:
    """Extract a non-ephemeral node ID; never fall back to @s... snapshot refs."""
    if not isinstance(node, dict):
        return ''
    native = node.get('native_id')
    if isinstance(native, dict):
        val = native.get('value')
        kind = str(native.get('kind') or 'native').strip()
        if isinstance(val, (list, tuple)) and val:
            joined = '.'.join(str(x) for x in val)
            return f'messenger:msg:{kind}:{joined}'
        if isinstance(val, str) and val.strip():
            return f'messenger:msg:{kind}:{val.strip()}'
    runtime_id = node.get('runtime_id')
    if isinstance(runtime_id, (list, tuple)) and runtime_id:
        return 'messenger:msg:rt:' + '.'.join(str(x) for x in runtime_id)
    if isinstance(runtime_id, str) and runtime_id.strip():
        return f'messenger:msg:rt:{runtime_id.strip()}'
    auto_id = node.get('automation_id')
    if isinstance(auto_id, str) and auto_id.strip():
        return f'messenger:msg:aid:{auto_id.strip()}'
    return ''


def _walk(node: dict | None):
    if not isinstance(node, dict):
        return
    yield node
    for child in node.get('children') or ():
        yield from _walk(child)


def _join_fragments(parts: list[str]) -> str:
    out = ''
    for part in parts:
        if not part:
            continue
        if not out:
            out = part
        elif out[-1].isspace() or part[0].isspace() or part[0] in ',.!?:;)]}':
            out += part
        else:
            out += ' ' + part
    return out.strip()


def reconstruct_message_text(row_node: dict) -> str:
    """Reconstruct message text across split UIA child text nodes inside a row."""
    fragments: list[str] = []
    for node in _walk(row_node):
        role = str(node.get('role') or '').casefold()
        if role in _CHROME_ROLES:
            continue
        children = node.get('children') or ()
        if role not in _TEXT_ROLES and children:
            continue
        raw = str(node.get('name') or node.get('value') or '')
        if not raw.strip():
            continue
        key = _fold(raw)
        if key in _ACTION_CHROME or is_user_sender_hint(raw) or normalize_delivery_status(raw):
            continue
        fragments.append(raw)
    return _join_fragments(fragments)


def _find_status_in_subtree(node: dict) -> str | None:
    found: set[str] = set()
    for sub in _walk(node):
        if is_user_sender_hint(str(sub.get('name') or '')):
            continue
        for field in ('name', 'help_text', 'item_status', 'aria_properties'):
            val = sub.get(field)
            if isinstance(val, str) and val.strip():
                st = normalize_delivery_status(val)
                if st:
                    found.add(st)
    return next(iter(found)) if len(found) == 1 else None


def _row_has_sender_button(row: dict) -> dict | None:
    buttons = [
        n for n in _walk(row)
        if str(n.get('role') or '').casefold() == 'button'
        and is_user_sender_hint(str(n.get('name') or ''))
    ]
    return buttons[0] if len(buttons) == 1 else None


def parse_outgoing_messages(tree: dict | None) -> list[OutgoingMessage] | None:
    """Parse verified outgoing messages from a Messenger main container snapshot.

    Returns None (fail-closed) if `main` is missing, if any outgoing row lacks
    a stable ID, or if delivery status cannot be verified unambiguously.
    """
    if not isinstance(tree, dict):
        return None
    mains = [n for n in _walk(tree) if str(n.get('role') or '').casefold() == 'main']
    if len(mains) != 1:
        return None
    main = mains[0]

    candidate_rows = [
        n for n in _walk(main)
        if str(n.get('role') or '').casefold() in ('row', 'listitem', 'group', 'gridcell')
        and _row_has_sender_button(n) is not None
    ]
    # Keep innermost row containers (exclude ancestors that wrap multiple sender buttons).
    outgoing_rows = [
        r for r in candidate_rows
        if sum(1 for n in _walk(r)
               if str(n.get('role') or '').casefold() == 'button'
               and is_user_sender_hint(str(n.get('name') or ''))) == 1
        and not any(other is not r and other in list(_walk(r)) for other in candidate_rows)
    ]
    if not outgoing_rows:
        return None

    results: list[OutgoingMessage] = []
    has_verified_status = False
    for row in outgoing_rows:
        btn = _row_has_sender_button(row)
        stable_id = extract_stable_node_id(row) or (extract_stable_node_id(btn) if btn else '')
        if not stable_id:
            return None
        status = _find_status_in_subtree(row)
        if status is not None:
            has_verified_status = True
        else:
            # Older messages in a group often omit delivery labels; keep them in
            # baseline with 'unknown' so they never match a verified post-send check.
            status = 'unknown'
        text = reconstruct_message_text(row)
        if not text:
            return None
        results.append(OutgoingMessage(id=stable_id, text=text, status=status, sender_is_user=True))
    return results if has_verified_status else None
