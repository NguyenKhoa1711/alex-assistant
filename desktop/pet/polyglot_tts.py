"""Keep the Vietnamese voice and route foreign-language spans to local voices."""
from __future__ import annotations

import logging
import re
import threading
import time
from pathlib import Path

import numpy as np
import sounddevice as sd

from .config import ROOT
from . import voice_motion
from .speech_pcm import trim_speech_edges
from .multilang_tts import (
    _HANZI_WITH_PAREN_RE,
    _UNMISTAKABLE_EN_WORDS,
    _WORD_TOKEN_RE,
    is_unmistakable_pinyin_token,
    segment_pinyin_word,
    tag_english_for_vieneu,
)
from .wake import speech_text

# Private markers remain internal and are stripped before any voice worker sees text.
_OPEN, _SEP, _CLOSE = '\ue100', '\ue101', '\ue102'
_TAG = re.compile(r'\ue100(en|zh)\ue101(.*?)\ue102', re.DOTALL)
_HANZI = re.compile(r'[\u3400-\u9fff]+(?:[，。！？；、\s]+[\u3400-\u9fff]+)*[，。！？；、]?')
_EN_TAG = re.compile(r'<en>(.*?)</en>', re.IGNORECASE | re.DOTALL)
_ASCII_WORD = re.compile(r"(?<![\w])([A-Za-z]+(?:'[A-Za-z]+)?)(?![\w])")
_PINYIN_BEFORE_HANZI = re.compile(
    r"(?P<before>[A-Za-z\u00c0-\u024f\u1e00-\u1eff'\u2019 ]+)"
    r"\s*[（(](?P<hanzi>[\u3400-\u9fff]+)[)）]"
)
_MODELS = {'en': 'en_US-joe-medium.onnx', 'zh': 'zh_CN-huayan-medium.onnx'}


def _model_dir() -> Path:
    for ancestor in (ROOT, *ROOT.parents):
        path = ancestor / 'Alex-data' / 'voices' / 'native'
        if path.is_dir():
            return path
    return ROOT / 'models' / 'native-voices'


def _mark(language: str, text: str) -> str:
    return f'{_OPEN}{language}{_SEP}{text}{_CLOSE}'


def _keep_hanzi(match: re.Match) -> str:
    words = re.findall(r"[A-Za-z\u00c0-\u024f'\u2019]+", match.group('inner'))
    if words and all(segment_pinyin_word(word) is not None for word in words):
        return match.group('hanzi')
    return match.group(0)


def _keep_parenthesized_hanzi(match: re.Match) -> str:
    # Only remove unmistakable Pinyin suffixes, not ordinary Vietnamese words
    # which may appear just before the foreign phrase.
    before = match.group('before')
    words = list(re.finditer(r"[A-Za-z\u00c0-\u024f\u1e00-\u1eff'\u2019]+", before))
    start = len(before)
    for word in reversed(words):
        if not is_unmistakable_pinyin_token(word.group(0)):
            break
        start = word.start()
    if start == len(before):
        return match.group(0)
    return before[:start] + match.group('hanzi')


def prepare_text(text: str, name: str, spoken_name: str, preferred_language: str | None = None) -> str:
    """Prepare for local speech while preserving Chinese and explicit English spans."""
    text = text.translate({ord(_OPEN): None, ord(_SEP): None, ord(_CLOSE): None})
    if (preferred_language == 'en' and re.search(r'[A-Za-z]', text)
            and not re.search(r'[\u3400-\u9fff\u00c0-\u024f\u1e00-\u1eff]', text)):
        # For an English voice turn, keep the whole English sentence on the
        # native voice rather than switching voices around unrecognized words.
        clean = speech_text(text, name, name)
        clean = _EN_TAG.sub(r'\1', clean)
        return _mark('en', clean) if clean else ''
    text = _HANZI_WITH_PAREN_RE.sub(_keep_hanzi, text)
    text = _PINYIN_BEFORE_HANZI.sub(_keep_parenthesized_hanzi, text)
    language_lesson = bool(re.search(r'\b(?:tiếng\s+anh|từ|chữ|cụm|english)\b', text, re.IGNORECASE))
    pieces: list[str] = []
    last = 0

    def vietnamese_and_english(value: str) -> str:
        # Existing cleanup still handles markdown, name pronunciation and Pinyin.
        cleaned = speech_text(value, name, spoken_name)
        tagged = tag_english_for_vieneu(cleaned)
        out: list[str] = []
        pos = 0
        for match in _EN_TAG.finditer(tagged):
            out.append(_tag_single_words(tagged[pos:match.start()], language_lesson))
            out.append(_mark('en', match.group(1)))
            pos = match.end()
        out.append(_tag_single_words(tagged[pos:], language_lesson))
        return ''.join(out)

    def vietnamese_english_and_pinyin(value: str) -> str:
        tokens = list(_WORD_TOKEN_RE.finditer(value))
        out: list[str] = []
        pos = 0
        i = 0
        while i < len(tokens):
            token = tokens[i]
            if not is_unmistakable_pinyin_token(token.group(0)):
                i += 1
                continue
            j = i
            while (j + 1 < len(tokens)
                   and value[tokens[j].end():tokens[j + 1].start()].isspace()
                   and is_unmistakable_pinyin_token(tokens[j + 1].group(0))):
                j += 1
            before = value[pos:token.start()]
            if before.strip():
                out.append(vietnamese_and_english(before))
            syllables = []
            for candidate in tokens[i:j + 1]:
                for base, tone in segment_pinyin_word(candidate.group(0)) or []:
                    syllables.append(base.replace('v', 'ü') + str(tone))
            out.append(_mark('zh', ' '.join(syllables)))
            pos = tokens[j].end()
            i = j + 1
        after = value[pos:]
        if after.strip():
            out.append(vietnamese_and_english(after))
        return ' '.join(piece for piece in out if piece)

    for match in _HANZI.finditer(text):
        before = text[last:match.start()]
        if before:
            pieces.append(vietnamese_english_and_pinyin(before))
        pieces.append(_mark('zh', match.group(0)))
        last = match.end()
    if last < len(text):
        pieces.append(vietnamese_english_and_pinyin(text[last:]))
    return ' '.join(part for part in pieces if part).strip()


def _tag_single_words(text: str, lesson: bool = False) -> str:
    # A single product name in an otherwise Vietnamese sentence should keep
    # the familiar voice; isolated words and explicit language lessons can
    # switch to the English voice for pronunciation practice.
    standalone = bool(re.fullmatch(r"\s*[A-Za-z]+(?:'[A-Za-z]+)?[.,!?;:]*\s*", text))
    teaching = bool(re.search(r'\b(?:tiếng\s+anh|từ|chữ|cụm|english)\b', text, re.IGNORECASE))
    if not (standalone or teaching or lesson):
        return text
    def replace(match: re.Match) -> str:
        word = match.group(1)
        return _mark('en', word) if word.lower() in _UNMISTAKABLE_EN_WORDS else word
    return _ASCII_WORD.sub(replace, text)


def split_text(text: str) -> list[tuple[str, str]]:
    parts: list[tuple[str, str]] = []
    def add(language: str, value: str) -> None:
        value = value.strip()
        if not value:
            return
        if parts and re.fullmatch(r'[.,!?;:，。！？；、]+', value):
            previous_language, previous_text = parts[-1]
            parts[-1] = (previous_language, previous_text + value)
        elif parts and language != 'vi' and parts[-1][0] == language:
            previous_language, previous_text = parts[-1]
            parts[-1] = (previous_language, previous_text + ' ' + value)
        else:
            parts.append((language, value))
    pos = 0
    for match in _TAG.finditer(text):
        add('vi', text[pos:match.start()])
        add(match.group(1), match.group(2))
        pos = match.end()
    add('vi', text[pos:])
    return parts


class HybridSpeaker:
    """Use TurboSpeaker normally; switch only marked spans to local Piper voices."""

    def __init__(self, vietnamese_speaker, device, model_dir: Path | None = None):
        self.vietnamese = vietnamese_speaker
        self.device = device
        self.engine_label = vietnamese_speaker.engine_label
        self.model_dir = model_dir or _model_dir()
        self._voices = {}
        self._voice_lock = threading.Lock()
        self._playback_lock = threading.RLock()

    @staticmethod
    def prepare_text(text, name, spoken_name, preferred_language=None):
        return prepare_text(text, name, spoken_name, preferred_language)

    def _take_playback_slot(self, cancelled):
        while not cancelled.is_set():
            if self._playback_lock.acquire(timeout=.05):
                if cancelled.is_set():
                    self._playback_lock.release()
                    return False
                return True
        return False

    def _voice(self, language):
        if language not in self._voices:
            import onnxruntime as ort
            from piper import PiperVoice
            from piper.config import PiperConfig
            from piper.phonemize_espeak import ESPEAK_DATA_DIR
            from .tts import compatible_espeak_path
            import json
            path = self.model_dir / _MODELS[language]
            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            options.inter_op_num_threads = 1
            ort.disable_telemetry_events()
            self._voices[language] = PiperVoice(
                session=ort.InferenceSession(str(path), sess_options=options, providers=['CPUExecutionProvider']),
                config=PiperConfig.from_dict(json.loads(Path(str(path) + '.json').read_text(encoding='utf-8'))),
                download_dir=path.parent,
                espeak_data_dir=compatible_espeak_path(ESPEAK_DATA_DIR),
            )
        return self._voices[language]

    def _render_native(self, language, text, cancelled):
        with self._voice_lock:
            audio = []
            for chunk in self._voice(language).synthesize(text):
                if cancelled.is_set():
                    return None
                raw = np.frombuffer(chunk.audio_int16_bytes, dtype=np.int16)
                if chunk.sample_rate != 48000 and len(raw):
                    size = max(1, round(len(raw) * 48000 / chunk.sample_rate))
                    pos = np.arange(size, dtype=np.float64) * chunk.sample_rate / 48000
                    raw = np.interp(pos, np.arange(len(raw)), raw).astype(np.int16)
                audio.append(raw.tobytes())
        return b''.join(audio)

    def render_pcm(self, text, cancelled):
        if not _TAG.search(text):
            return self.vietnamese.render_pcm(text, cancelled)
        chunks = []
        for language, content in split_text(text):
            if cancelled.is_set():
                return None
            try:
                if language == 'vi':
                    rendered = self.vietnamese.render_pcm(content, cancelled)
                    audio = rendered[1] if rendered else None
                else:
                    audio = self._render_native(language, content, cancelled)
            except Exception as exc:
                # Fail closed to the existing offline voice if the native model is absent.
                logging.warning('Native voice %s unavailable: %s', language, type(exc).__name__)
                fallback = speech_text(content, '', '')
                rendered = self.vietnamese.render_pcm(fallback, cancelled)
                audio = rendered[1] if rendered else None
            if audio:
                audio=trim_speech_edges(audio)
                if chunks:
                    chunks.append(bytes(2 * int(48000 * 0.04)))
                chunks.append(audio)
        return (48000, b''.join(chunks)) if chunks and not cancelled.is_set() else None

    def speak(self, text, cancelled, on_play):
        if not self._take_playback_slot(cancelled):
            return None
        try:
            return self._speak_unlocked(text, cancelled, on_play)
        finally:
            self._playback_lock.release()

    def _speak_unlocked(self, text, cancelled, on_play):
        if not _TAG.search(text):
            return self.vietnamese.speak(text, cancelled, on_play)
        started = time.monotonic()
        rendered = self.render_pcm(text, cancelled)
        if not rendered or cancelled.is_set():
            return None
        sample_rate, raw = rendered
        pcm = np.frombuffer(raw, dtype=np.int16)
        with sd.OutputStream(samplerate=sample_rate, channels=1, dtype='int16',
                             device=self.device, blocksize=2048) as stream:
            first = time.monotonic() - started
            on_play(first)
            for offset in range(0, len(pcm), 2048):
                if cancelled.is_set():
                    stream.abort()
                    break
                block = pcm[offset:offset + 2048]
                voice_motion.feed_pcm(block)
                stream.write(block)
        voice_motion.clear()
        return first

    def speak_sequence(self, texts, cancelled, on_play):
        if not self._take_playback_slot(cancelled):
            return None
        try:
            return self._speak_sequence_unlocked(texts, cancelled, on_play)
        finally:
            self._playback_lock.release()

    def _speak_sequence_unlocked(self, texts, cancelled, on_play):
        iterator = iter(texts)
        pending = None
        start = time.monotonic()
        first = None
        def mark_play(_value):
            nonlocal first
            if first is None:
                first = time.monotonic() - start
                on_play(first)
        while not cancelled.is_set():
            try:
                text = pending if pending is not None else next(iterator)
            except StopIteration:
                break
            pending = None
            if _TAG.search(text):
                self.speak(text, cancelled, mark_play)
                continue
            def vietnamese_group():
                nonlocal pending
                yield text
                for following in iterator:
                    if cancelled.is_set():
                        return
                    if _TAG.search(following):
                        pending = following
                        return
                    yield following
            if hasattr(self.vietnamese, 'speak_sequence'):
                self.vietnamese.speak_sequence(vietnamese_group(), cancelled, mark_play)
            else:
                for item in vietnamese_group():
                    self.vietnamese.speak(item, cancelled, mark_play)
        return first

    def close(self):
        self.vietnamese.close()
