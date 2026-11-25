"""Recognize complete computer goals before a one-step opener consumes them.

This is routing only: it never derives an action or executes quoted/retrieved text.
"""
from __future__ import annotations

import re
import unicodedata


def _key(text: str) -> str:
    value = unicodedata.normalize('NFD', text.casefold().replace('đ', 'd'))
    return ''.join(c for c in value if unicodedata.category(c) != 'Mn')


def _without_quotes(text: str) -> str:
    # Song titles, search strings and text to type can contain "rồi mở ...".
    return re.sub(r'"[^"\n]*"|“[^”\n]*”|‘[^’\n]*’|`[^`\n]*`', ' ', text)


_HEAD = re.compile(
    r'^(?:(?:alex(?: oi)?|a lech(?: oi)?|may|ban|hay|lam on|vui long|'
    r'toi muon|minh muon|tao muon|giup tao|giup toi|giup minh|nho may)[,\s]+)*'
    r'(?:mo|vao|truy cap|chay|bat|tim|tao|sao chep|copy|doi ten|di chuyen|'
    r'luu|doc|liet ke|nhap|go|dien|chon|bam|nhan|open|find|create|copy|rename|move|read|list)\b')
_THEN_ACTION = re.compile(
    r'(?:[,;]\s*|\s+(?:roi|xong(?: roi)?|sau do|tiep theo|va|de)\s+)'
    r'(?:(?:hay|may|ban|giup (?:tao|toi|minh))\s+)*'
    r'(?:mo|vao|tim|kiem|tao|sao chep|copy|doi ten|di chuyen|luu|doc|liet ke|'
    r'nhap|go|dien|chon|bam|nhan|cuon|keo|phong to|thu nho|'
    r'open|search|find|create|copy|rename|move|save|read|list|type|click)\b')
_FILE_WORK = re.compile(
    r'\b(?:sao chep|copy|doi ten|di chuyen|liet ke|doc|tao|luu|rename|move|create|read|list)\b'
    r'.{0,100}\b(?:tep|file|thu muc|folder|tai lieu|\.txt|\.md|\.csv)\b')


def is_goal_task(question: str) -> bool:
    """Only route explicit imperative work, never ordinary questions or titles."""
    if not isinstance(question, str) or not question.strip():
        return False
    text = _key(_without_quotes(question)).strip()
    if not _HEAD.match(text):
        return False
    # Keep teaching, missing target, power and negative requests with their
    # existing handlers. No task execution from "how do I ..." questions.
    if re.search(r'\b(?:huong dan|cach nao|lam sao|nghia la|'
                 r'khi toi noi|khi tao noi|tat nguon|tat may|cho may ngu)\b', text):
        return False
    return bool(_THEN_ACTION.search(text) or _FILE_WORK.search(text))
