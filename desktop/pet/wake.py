from __future__ import annotations
import re
import unicodedata

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
    text = re.sub(rf'\b{re.escape(name)}\b', spoken_name, text, flags=re.I)
    text = ''.join(c for c in text if unicodedata.category(c) not in {'So', 'Cs'})
    return re.sub(r'\s+', ' ', text).strip()

class SentenceBuffer:
    def __init__(self) -> None:
        self.pending = ''

    def add(self, text: str, final: bool = False) -> list[str]:
        self.pending += text
        result = []
        while True:
            match = re.search(r'[.!?;](?:\s|$)', self.pending)
            if not match and len(self.pending) >= 42:
                match = re.search(r'[,:]\s', self.pending[20:])
                if match:
                    end_idx = 20 + match.end()
                    sentence = self.pending[:end_idx].strip()
                    self.pending = self.pending[end_idx:]
                    if sentence:
                        result.append(sentence)
                    continue
            if not match:
                break
            sentence = self.pending[:match.end()].strip()
            self.pending = self.pending[match.end():]
            if sentence:
                result.append(sentence)
        if final and self.pending.strip():
            result.append(self.pending.strip())
            self.pending = ''
        return result
