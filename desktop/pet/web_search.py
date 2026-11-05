"""Explicit browser searches, with the original Vietnamese query preserved."""
from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


@dataclass(frozen=True)
class WebSearchRequest:
    query: str
    open_site: bool = False
    explicit_web: bool = False


_PREFIX = (
    r'(?:(?:alex oi|alex|a lech oi|a lech|ban oi|hay giup toi|hay giup minh|'
    r'ban co the|co the|toi muon ban|minh muon ban|toi muon|minh muon|'
    r'vui long|lam on|hay|ban|cho toi|cho minh|giup toi|giup minh|'
    r'vang|da|oke|ok)[,\s]+){0,6}'
)
_HELP = r'(?:(?:cho|giup) (?:toi|minh) )?'
_POLITE = r'(?: (?:cho toi|cho minh|giup toi|giup minh|duoc khong|nhe|nha|di|voi|len|ngay|luon)){0,4}'
_ENGINE = r'(?:google(?: chrome)?|chrome|trinh duyet|mang|internet|web)'
_LOCATION = r'(?:(?:o )?(?:tren|trong|o|qua|bang) )' + _ENGINE
_SEARCH = r'(?:tim kiem|tim|tra cuu|tra|kiem)'
_OPEN = r'(?:mo|vao|truy cap)'
_SECOND_ACTION = re.compile(
    r'(?:[,;] *|\b(?:roi|sau do|xong|va) )'
    r'(?:(?:hay|ban|giup toi|cho toi) )?'
    r'(?:mo|bat|tat|dong|xoa|gui|goi|chay|cai|tim|luot|cuon|phong to|thu nho)\b'
)


def parse_web_search(question: str) -> WebSearchRequest | None:
    """Do not infer an Internet search merely from an unknown app/site name."""
    if not question or len(question) > 600 or any(c in question for c in '\r\n'):
        return None
    raw = unicodedata.normalize('NFC', ' '.join(question.split())).strip(' ,.!?…')
    chars: list[str] = []
    positions: list[int] = []
    for i, char in enumerate(raw):
        for part in unicodedata.normalize('NFD', char.casefold().replace('đ', 'd')):
            if unicodedata.category(part) != 'Mn':
                chars.append(part)
                positions.append(i)
    text = ''.join(chars)
    # The start must be an actual request, not a quotation, explanation or negation.
    patterns = (
        (_SEARCH + r' ' + _HELP + _LOCATION + r'(?: (?:ve|tu khoa))?(?: (?P<query>.*?))?', False, True),
        (_SEARCH + r' ' + _HELP + r'(?P<query>.*?)' + _POLITE + r' ' + _LOCATION, False, True),
        (_OPEN + r' ' + _ENGINE + r' (?:de )?' + _SEARCH + r'(?: ' + _HELP + r'(?P<query>.*?))?', False, True),
        (r'google ' + _HELP + r'(?P<query>.*?)', False, True),
        (_OPEN + r' ' + _HELP + r'(?P<query>.*?)' + _POLITE + r' ' + _LOCATION, True, True),
        (r'(?:tim kiem|tra cuu|tim) ' + _HELP + r'(?P<query>.*?)', False, False),
    )
    for pattern, open_site, explicit_web in patterns:
        match = re.fullmatch(_PREFIX + pattern + _POLITE, text)
        if not match:
            continue
        start, end = match.span('query')
        query = raw[positions[start]:positions[end - 1] + 1].strip() if end > start >= 0 else ''
        key = text[start:end].strip() if end > start >= 0 else ''
        if _SECOND_ACTION.search(key):
            return None
        if not explicit_web and (not query or key in ('google', 'tren google', 'tren mang', 'tren web')):
            return None
        return WebSearchRequest(query, open_site, explicit_web)
    return None
