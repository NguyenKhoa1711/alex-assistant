"""Short-lived opening context; no model calls or persisted conversation text."""
from __future__ import annotations

import re
import time
import unicodedata
from .apps import normalized


def natural_open(text: str) -> str:
    """Remove polite wrappers only when the remainder is an opening command."""
    original = unicodedata.normalize('NFC', text).strip()
    if '\n' in original or '\r' in original or len(original) > 200:
        return text
    candidate = original
    prefix = (r'^(?:alex oi[, ]+|alex[, ]+|ban oi[, ]+|may oi[, ]+|'
              r'tiep toi[, ]+|tiep theo[, ]+|sau do[, ]+|bay gio[, ]+|gio thi[, ]+|gio[, ]+|the thi[, ]+|vay thi[, ]+|xong roi[, ]+|'
              r'ban co the |may co the |ban giup (?:minh|toi|tao) |may giup tao |'
              r'(?:minh|toi|tao) (?:muon|can) |nho ban |nho may |lam on |vui long |ban |may |hay )')
    for _ in range(4):
        found = re.match(prefix, normalized(candidate))
        if not found:
            break
        candidate = candidate[found.end():]
    if not re.match(r'^(?:mo|bat|chay|khoi dong|vao|truy cap)\b', normalized(candidate)):
        return text
    # Preserve accents and URL/path casing; do not rewrite the destination.
    suffix = re.search(r'(?:[, ]+(?:duoc khong|duoc ko|nha|nhe|nhe ban|voi nhe|di nhe))[.!?…]*$',
                       normalized(candidate))
    if suffix:
        candidate = candidate[:suffix.start()].rstrip()
    return candidate


def _target(text: str) -> bool:
    key = normalized(text).strip(' .!')
    if not key or len(key.split()) > 10 or len(key) > 160:
        return False
    if any(c in text for c in '\n\r?;|<>'):
        return False
    # A conversational answer or another action must not become an app name.
    if re.search(r'\b(?:khong|dung|huy|thoi|cam on|biet|muon|nghi|tai sao|la gi|toi|minh|ban|dang|'
                 r'gui|xoa|tat|dong|ngu|khoi dong lai|tang|giam|roi|sau do|va)\b', key):
        return False
    return key not in {'ok', 'vang', 'uh', 'uhm', 'ung dung', 'phan mem', 'app', 'thu muc'}


class OpeningContext:
    """One bounded context per input channel, consumed by the next turn."""
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.clear()

    def clear(self):
        self.kind = ''
        self.awaiting = False
        self.at = 0.0

    def remember(self, kind: str, *, awaiting=False):
        self.kind, self.awaiting, self.at = kind, awaiting, self.clock()

    def resolve(self, text: str) -> tuple[str, bool]:
        fresh = bool(self.kind and 0 <= self.clock() - self.at < 45)
        kind, awaiting = self.kind, self.awaiting
        self.clear()
        value = natural_open(text)
        key = normalized(value).strip(' .!?')
        if not fresh:
            return value, False
        if awaiting and key in {'huy', 'thoi', 'khong can', 'bo qua', 'thoi khong can'}:
            return value, True
        if re.match(r'^(?:mo|bat|chay|khoi dong|vao|truy cap)\b', key):
            return value, False
        correction = re.match(r'^(?:khong[, ]+)?(?:y (?:minh|toi) la|(?:minh|toi) noi la)\s+',
                              normalized(value))
        if correction:
            value = value[correction.end():].strip(' .!')
            if re.match(r'^(?:mo|bat|chay|vao|truy cap) ', normalized(value)):
                return natural_open(value), False
        if (awaiting or correction) and _target(value):
            noun = 'thư mục ' if kind == 'folder' else 'file ' if kind == 'file' else ''
            return 'Mở ' + noun + value, False
        return natural_open(text), False
