from __future__ import annotations
import re
import unicodedata
from .multilang_tts import prepare_multilang_speech

def normalized(text: str) -> str:
    plain = ''.join(c for c in unicodedata.normalize('NFD', text.lower()) if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9 ]', ' ', plain.replace('đ', 'd'))

def extract_wake(text: str, aliases: list[str]) -> tuple[bool, str]:
    """Require the name near the beginning; keep original Vietnamese after it."""
    source_words = list(re.finditer(r'\w+', text, flags=re.UNICODE))
    words = [normalized(m.group()) for m in source_words]
    for alias in sorted(aliases, key=lambda x: len(x), reverse=True):
        target = normalized(alias).split()
        for start in range(min(4, len(words))):
            if words[start:start + len(target)] == target:
                end = source_words[start + len(target) - 1].end()
                rest = text[end:].lstrip(' ,.!?:;—-')
                rest = re.sub(r'^ơi\b[\s,.!?]*', '', rest, flags=re.I)
                return True, rest.strip()
    return False, ''

def speech_text(text: str, name: str, spoken_name: str) -> str:
    text = re.sub(r'<think>[\s\S]*?</think>', '', text)
    text = re.sub(r'```[\s\S]*?```', ' Phần mã nguồn nằm trong câu trả lời. ', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'[*#`_•]', '', text)
    text = ''.join(c for c in text if unicodedata.category(c) not in {'So', 'Cs'})
    text = prepare_multilang_speech(text, name, spoken_name)
    return re.sub(r'\s+', ' ', text).strip()

_SENTENCE_END = re.compile(r'[.!?;…](?:["\'”’)\]]*)(?:\s|$)|[\u3002\uff01\uff1f\uff1b]\s*')
_CLAUSE_END = re.compile(r'[,:]\s|[\uff0c\uff1a\u3001]\s*')


class SentenceBuffer:
    """Group streamed model text into chunks for the voice.

    The first chunk is cut early (low latency). Later chunks are kept to whole
    sentences of a reasonable length: each chunk is synthesised separately, so
    many tiny fragments sound robotic and add a pause at every cut.
    """
    # Give the first utterance enough context for natural intonation before
    # splitting on a comma. Complete sentences can still start immediately.
    FIRST_CLAUSE_MIN = 60
    LATER_MIN = 45
    LATER_CLAUSE_MAX = 140
    MAX_WITHOUT_BOUNDARY = 180

    def __init__(self) -> None:
        self.pending = ''
        self.emitted = 0

    def _cut(self, end_idx: int, result: list[str]) -> None:
        sentence = self.pending[:end_idx].strip()
        self.pending = self.pending[end_idx:]
        if sentence:
            result.append(sentence)
            self.emitted += 1

    def add(self, text: str, final: bool = False) -> list[str]:
        self.pending += text
        result: list[str] = []
        while True:
            if self.emitted == 0:
                match = _SENTENCE_END.search(self.pending)
                if match and match.end() <= self.MAX_WITHOUT_BOUNDARY:
                    self._cut(match.end(), result)
                    continue
                if len(self.pending) >= self.FIRST_CLAUSE_MIN:
                    clause = _CLAUSE_END.search(self.pending, 25, self.MAX_WITHOUT_BOUNDARY)
                    if clause:
                        self._cut(clause.end(), result)
                        continue
                if len(self.pending) >= self.MAX_WITHOUT_BOUNDARY:
                    cut = self.pending.rfind(' ', 80, self.MAX_WITHOUT_BOUNDARY)
                    if cut > 0:
                        self._cut(cut + 1, result)
                        continue
                    if match:
                        self._cut(match.end(), result)
                        continue
                break
            # Later chunks: last sentence end that keeps the chunk long enough.
            cut = None
            for match in _SENTENCE_END.finditer(self.pending):
                if self.LATER_MIN <= match.end() <= self.MAX_WITHOUT_BOUNDARY:
                    cut = match.end()
                    break
            if cut is None and len(self.pending) >= self.LATER_CLAUSE_MAX:
                clause = None
                for clause in _CLAUSE_END.finditer(self.pending, self.LATER_MIN, self.MAX_WITHOUT_BOUNDARY):
                    break
                if clause:
                    cut = clause.end()
            if cut is None and len(self.pending) >= self.MAX_WITHOUT_BOUNDARY:
                space = self.pending.rfind(' ', 80, self.MAX_WITHOUT_BOUNDARY)
                if space > 0:
                    cut = space + 1
            if cut is None:
                break
            self._cut(cut, result)
        if final and self.pending.strip():
            self._cut(len(self.pending), result)
        return result
