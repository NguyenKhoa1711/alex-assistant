"""Remove redundant parenthesized Pinyin from streamed Chinese replies."""
from __future__ import annotations
import re
import unicodedata
from .multilang_tts import segment_pinyin_word

_HANZI = re.compile(r'[\u3400-\u9fff]')
_ADJACENT_HANZI = re.compile(r'[\u3400-\u9fff][\s，。！？!?,.：:；;]*$')
_WORD = re.compile(r'[A-Za-z\u00c0-\u024f\u1e00-\u1eff]+[1-5]?')


def pinyin_requested(question: str) -> bool:
    folded = ''.join(c for c in unicodedata.normalize('NFD', question.casefold().replace('đ', 'd'))
                     if unicodedata.category(c) != 'Mn')
    if re.search(r'\b(?:khong|dung|bo|khong can)\s+(?:them\s+|viet\s+|kem\s+)?(?:phien am|pinyin)\b', folded):
        return False
    return bool(re.search(r'\b(?:phien am|pinyin|romanization)\b|拼音', folded))


def _is_pinyin(value: str) -> bool:
    if len(value) > 180 or _HANZI.search(value):
        return False
    words = _WORD.findall(value)
    if any(word.isupper() and len(word) > 1 for word in words):
        return False
    residue = _WORD.sub('', value)
    return bool(words and not re.search(r'[^\s,，.!?！？;；:：\-]', residue)
                and all(segment_pinyin_word(word) is not None for word in words))


class PinyinFilter:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.recent = ''
        self.group = ''
        self.pending = ''
        self.closing = ''
        self.adjacent = False

    def feed(self, chunk: str, *, final: bool = False) -> str:
        if not self.enabled:
            return chunk
        out = []
        def emit(value):
            if value:
                out.append(value)
                self.recent = (self.recent + value)[-100:]
        for ch in chunk:
            if self.pending:
                if ch.isspace() and len(self.pending) < 220:
                    self.pending += ch
                    continue
                if _HANZI.match(ch):
                    self.pending = ''
                else:
                    emit(self.pending)
                    self.pending = ''
            if self.group:
                self.group += ch
                if ch == self.closing:
                    group, self.group = self.group, ''
                    if _is_pinyin(group[1:-1]):
                        if not self.adjacent:
                            self.pending = group
                    else:
                        emit(group)
                elif len(self.group) > 200 or ch == '\n':
                    emit(self.group); self.group = ''
                continue
            if ch in '(（[':
                self.adjacent = bool(_ADJACENT_HANZI.search(self.recent))
                self.group = ch
                self.closing = {'(': ')', '（': '）', '[': ']'}[ch]
            else:
                emit(ch)
        if final:
            emit(self.pending); self.pending = ''
            emit(self.group); self.group = ''
        return ''.join(out)


def filtered_chunks(chunks, question: str):
    filt = PinyinFilter(enabled=not pinyin_requested(question))
    for chunk in chunks:
        visible = filt.feed(chunk)
        if visible:
            yield visible
    last = filt.feed('', final=True)
    if last:
        yield last
