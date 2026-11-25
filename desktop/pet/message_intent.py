"""Parse a narrow, explicit send request without modifying the message."""
from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


@dataclass(frozen=True)
class SendIntent:
    service: str
    recipient: str
    content: str


@dataclass(frozen=True)
class ParsedMessageRequest:
    # A recognized but incomplete/ambiguous request must not fall through to
    # an unrestricted LLM sender.
    recognized: bool
    intent: SendIntent | None = None


def _fold_with_offsets(value: str):
    chars, offsets = [], []
    for index, ch in enumerate(value):
        for c in unicodedata.normalize('NFD', ch.casefold().replace('đ', 'd')):
            if unicodedata.category(c) != 'Mn':
                chars.append(c)
                offsets.append(index)
    return ''.join(chars), offsets


def _unresolved_recipient(value: str) -> bool:
    """Do not guess who a pronoun refers to; preserve accents in names."""
    words = unicodedata.normalize('NFC', value).strip().split()
    if not words:
        return True
    first = words[0].strip('.,!?…:;')
    if first == 'Minh':
        return False
    return first.casefold() in {
        'tôi', 'toi', 'mình', 'minh', 'tao', 'tui', 'ta',
        'nó', 'no', 'mày', 'may',
    }


def parse_send_intent(question: str) -> SendIntent | None:
    raw = unicodedata.normalize('NFC', question.strip())
    if not raw or len(raw) > 1200 or any(c in raw for c in '\r\n'):
        return None
    key, offsets = _fold_with_offsets(raw)
    prefix = r'(?:(?:alex|a lech|ban|may)(?:\s+oi)?[,\s]+)?(?:hay\s+|lam on\s+|vui long\s+|alex\s+|may\s+)*'
    suffix = r'(?:\s+(?:giup|cho)\s+(?:toi|minh|tao|tui))?(?:\s+(?:di|nhe|nha|voi|ngay|luon))?[.!?…]*'
    # Keep matching deliberately narrow: a recipient, service and message are
    # all mandatory and are sliced from the original string, not normalized.
    patterns = (
        prefix + r'gui (?:tin nhan|tin(?! nhan\b)) (?P<message>.+?) cho (?P<recipient>.+?) (?:tren|qua|bang) (?P<service>zalo|messenger)' + suffix,
        prefix + r'(?:gui tin nhan|nhan tin|nhan) cho (?P<recipient>.+?) (?:tren|qua|bang) (?P<service>zalo|messenger) (?:noi dung(?: (?:la|rang))?|rang|la) (?P<message>.+)',
        prefix + r'(?:gui tin nhan|nhan tin|nhan) cho (?P<recipient>.+?) (?:noi dung(?: (?:la|rang))?|rang|la) (?P<message>.+?) (?:tren|qua|bang) (?P<service>zalo|messenger)' + suffix,
        prefix + r'gui cho (?P<recipient>.+?) (?:tren|qua|bang) (?P<service>zalo|messenger) (?:tin nhan|tin) (?:noi dung (?:la |rang )?|rang |la )?(?P<message>.+)',
    )
    matches = [m for p in patterns if (m := re.fullmatch(p, key))]
    if len(matches) != 1:
        return None
    match = matches[0]

    def original(name: str) -> str:
        start, end = match.span(name)
        return raw[offsets[start]:offsets[end - 1] + 1].strip()

    service, recipient, content = original('service'), original('recipient'), original('message')
    if len(content) > 1000 or len(recipient) > 100 or len(content) < 1 or len(recipient) < 1:
        return None
    if _unresolved_recipient(recipient):
        return None
    # Prevent a second spoken instruction being swallowed as a recipient.
    recipient_key, _ = _fold_with_offsets(recipient)
    if re.search(r'\b(?:cho|tren|qua|bang|roi|sau do|va gui|va xoa)\b', recipient_key):
        return None
    if len(content) >= 2 and (content[0], content[-1]) in (("'", "'"), ('"', '"'), ('“', '”')):
        content = content[1:-1]
    if not content.strip():
        return None
    return SendIntent('Zalo' if service.casefold() == 'zalo' else 'Messenger', recipient, content)


def classify_message_request(question: str) -> ParsedMessageRequest:
    intent = parse_send_intent(question)
    if intent is not None:
        return ParsedMessageRequest(True, intent)
    key, _ = _fold_with_offsets(question)
    # A direct request to send a message is still a messaging request when
    # the service is missing. Do not let an incomplete command fall through
    # to a general-purpose agent that might guess the service or recipient.
    direct = re.match(r'^(?:(?:alex|a lech|ban|may)(?:\s+oi)?[,\s]+)?'
                      r'(?:(?:hay|vui long|lam on)\s+)*'
                      r'(?:gui\s+(?:tin nhan|tin)|nhan\s+tin|nhan\s+cho)\b', key)
    if direct:
        # A negation inside an incomplete message is not an instruction to
        # bypass the messaging flow; ask for missing information instead.
        return ParsedMessageRequest(True)
    if re.search(r'\b(?:dung|khong|chua|thoi|huy|ngung)\s+(?:\w+\s+){0,3}(?:gui|nhan tin)\b', key):
        return ParsedMessageRequest(False)
    recognized = bool(direct or (re.search(r'\b(?:gui (?:tin nhan|tin|cho)|nhan tin|nhan cho)\b', key)
                                 and re.search(r'\b(?:zalo|messenger)\b', key)))
    return ParsedMessageRequest(recognized)


_CANCEL_REPLIES = frozenset({
    'khong', 'khong phai', 'thoi', 'huy', 'dung', 'dung gui', 'khong gui', 'bo di', 'cancel',
})
_CONFIRM_REPLIES = frozenset({
    'ok', 'ok het', 'ok het roi', 'u', 'uh', 'duoc', 'vang', 'da',
    'dung', 'dung roi', 'phai', 'phai roi', 'gui di', 'gui', 'lam di', 'tiep tuc',
})


def extract_partial_message(question: str) -> dict[str, str]:
    """Extract any explicit service, recipient, and content fragments from a message request."""
    raw = unicodedata.normalize('NFC', (question or '').strip())
    if not raw or len(raw) > 1200 or any(c in raw for c in '\r\n'):
        return {}
    key, offsets = _fold_with_offsets(raw)
    result: dict[str, str] = {}

    def original(start: int, end: int) -> str:
        return raw[offsets[start]:offsets[end - 1] + 1].strip() if end > start else ''

    svc = re.search(r'\b(zalo|messenger)\b', key)
    if svc:
        result['service'] = 'Zalo' if svc.group(1) == 'zalo' else 'Messenger'

    rec = re.search(
        r'\bcho\s+(?P<recipient>.+?)(?=\s+(?:tren|qua|bang|noi dung|rang|la)\b|[.!?…]*$)',
        key,
    )
    if rec:
        candidate = original(*rec.span('recipient'))
        rec_key, _ = _fold_with_offsets(candidate)
        if candidate and len(candidate) <= 100 and not _unresolved_recipient(candidate) and not re.search(
            r'\b(?:cho|tren|qua|bang|roi|sau do|va gui|va xoa)\b', rec_key
        ):
            result['recipient'] = candidate

    msg = re.search(
        r'\b(?:noi dung(?:\s+(?:la|rang))?|rang|la)\s+(?P<message>.+?)(?=\s+(?:tren|qua|bang)\s+(?:zalo|messenger)\b|$)',
        key,
    )
    if msg:
        content = original(*msg.span('message'))
        if len(content) >= 2 and (content[0], content[-1]) in (("'", "'"), ('"', '"'), ('“', '”')):
            content = content[1:-1]
        if content.strip() and len(content) <= 1000:
            result['content'] = content.strip()

    return result


def format_missing_message_prompt(pending: dict[str, str]) -> str:
    """Ask specifically for the missing parts while confirming what Alex already remembered."""
    missing = [label for field, label in (
        ('recipient', 'tên người nhận'),
        ('service', 'ứng dụng (Zalo hoặc Messenger)'),
        ('content', 'nội dung tin nhắn'),
    ) if not pending.get(field)]
    remembered = []
    if pending.get('service'):
        remembered.append(f"trên {pending['service']}")
    if pending.get('recipient'):
        remembered.append(f"cho {pending['recipient']}")
    if pending.get('content'):
        remembered.append(f"nội dung \"{pending['content']}\"")
    prefix = f"Tao đã nhớ gửi {' '.join(remembered)}. " if remembered else ''
    return prefix + f"Mày nói rõ {', '.join(missing)} giúp tao nhé."


def merge_message_followup(pending: dict[str, str], followup: str) -> tuple[str, dict[str, str]]:
    """Merge a user follow-up reply into a pending messaging request."""
    raw = unicodedata.normalize('NFC', (followup or '').strip())
    merged = {k: v for k, v in (pending or {}).items() if k in ('service', 'recipient', 'content') and v}
    if not raw or any(c in raw for c in '\r\n'):
        return 'ask', merged
    key, _ = _fold_with_offsets(raw)
    reply_key = re.sub(r'[.!?,…]+$', '', key).strip()
    labeled_content = bool(re.match(r'^(?:noi dung(?:\s+(?:la|rang))?|rang|la)\s+', reply_key))
    # Vietnamese "đúng" (yes) and "dừng/đừng" (stop) collapse to the same
    # accent-folded token. Resolve these from the original text first; when
    # accents are absent, do not guess and accidentally send or cancel.
    reply_original = re.sub(r'[.!?,…]+$', '', raw.casefold()).strip()
    if not labeled_content and re.match(r'^(?:dừng|đừng)(?:\s|$)', reply_original):
        return 'cancel', {}
    if reply_original in ('đúng', 'đúng rồi'):
        return ('execute' if all(merged.get(k) for k in ('service', 'recipient', 'content'))
                else 'ask'), merged
    if re.match(r'^dung(?:\s|$)', reply_key):
        return 'ask', merged
    if not labeled_content and (reply_key in _CANCEL_REPLIES or re.search(r'\b(?:dung|khong|thoi|huy)\s+(?:gui|nhan)\b', reply_key)):
        return 'cancel', {}

    full = parse_send_intent(raw)
    if full is not None:
        return 'execute', {'service': full.service, 'recipient': full.recipient, 'content': full.content}

    if reply_key in _CONFIRM_REPLIES:
        if all(merged.get(k) for k in ('service', 'recipient', 'content')):
            return 'execute', merged
        return 'ask', merged

    extracted = extract_partial_message(raw)
    for k, v in extracted.items():
        if v:
            merged[k] = v

    missing = [k for k in ('service', 'recipient', 'content') if not merged.get(k)]
    if len(missing) == 1 and not extracted:
        only_missing = missing[0]
        cleaned = raw.strip().strip('"\'“”')
        if only_missing == 'service':
            if 'zalo' in reply_key:
                merged['service'] = 'Zalo'
            elif 'messenger' in reply_key:
                merged['service'] = 'Messenger'
        elif only_missing == 'recipient' and 1 <= len(cleaned) <= 100 and not _unresolved_recipient(cleaned):
            merged['recipient'] = cleaned
        elif only_missing == 'content' and 1 <= len(cleaned) <= 1000:
            merged['content'] = cleaned

    if all(merged.get(k) for k in ('service', 'recipient', 'content')):
        return 'execute', merged
    return 'ask', merged
