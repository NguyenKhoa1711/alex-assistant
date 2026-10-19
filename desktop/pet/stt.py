from __future__ import annotations
import logging
import os
import re
import sys
from pathlib import Path
import time
from dataclasses import dataclass
from collections.abc import Callable
import numpy as np
from faster_whisper import WhisperModel
from .config import local_path

_DLL_HANDLES: list[object] = []

DEFAULT_PROMPT = ('Tiếng Việt. Trợ lý Alex. Lệnh điều khiển: mở ứng dụng, mở thư mục, '
                  'mở trang web, tìm kiếm. Nhận đúng lời người nói, kể cả tên phần mềm.')


@dataclass(frozen=True)
class RecognitionDiagnostic:
    raw_text: str = ''
    reason: str = ''
    audio_seconds: float = 0.0


def recognition_config(config: dict) -> dict:
    """Add canonical names, not past STT mistakes, to a bounded vocabulary hint."""
    stt = dict(config['stt'])
    names = str(stt.get('hotwords') or '').split(',')
    names += [str(entry.get('name', '')) for entry in config.get('apps', {}).get('entries', [])]
    names += [str(entry.get('name', '')) for entry in config.get('web', {}).get('sites', [])]
    kept: list[str] = []
    seen: set[str] = set()
    for name in names:
        name = ' '.join(name.split()).strip(' .')[:60]
        key = name.casefold()
        if not name or key in seen:
            continue
        if len(', '.join([*kept, name])) > 500:
            continue
        seen.add(key)
        kept.append(name)
    stt['hotwords'] = ', '.join(kept)
    return stt


def excessive_repetition(text: str) -> bool:
    """Reject long, dominant consecutive loops, but keep ordinary emphasis."""
    words = re.findall(r'\w+', text.casefold())
    if len(words) < 12:
        return False
    for width in range(1, 7):
        for start in range(len(words) - width * 4 + 1):
            block = words[start:start + width]
            end = start + width
            while words[end:end + width] == block:
                end += width
            repeated = end - start
            if repeated >= max(12, width * 4) and repeated / len(words) >= 0.65:
                return True
    return False


def correct_command_prefix(text: str) -> str:
    """Repair a common Vietnamese opening-command error without changing ordinary speech."""
    if re.match(r'^bởi\s+', text, re.IGNORECASE) and re.search(
            r'\b(?:cho|giúp)\s+(?:tôi|mình)\b|\b(?:ở\s+)?trong\s+(?:google|chrome)\b',
            text, re.IGNORECASE):
        return re.sub(r'^bởi\b', 'Mở', text, count=1, flags=re.IGNORECASE)
    return text


def prepare_cuda_libraries() -> None:
    """Load private NVIDIA DLLs without changing the system PATH."""
    if os.name != 'nt' or _DLL_HANDLES:
        return
    directories = [Path(sys.prefix) / 'Lib/site-packages/nvidia' / name / 'bin'
                   for name in ('cublas', 'cudnn', 'cuda_nvrtc')]
    for directory in directories:
        if directory.is_dir():
            _DLL_HANDLES.append(os.add_dll_directory(str(directory)))
            os.environ['PATH'] = str(directory) + os.pathsep + os.environ.get('PATH', '')


class SpeechToText:
    def __init__(self, config: dict, notify: Callable[[str], None]) -> None:
        self.cfg = config
        self.notify = notify
        self.device = config['device']
        self.last_diagnostic = RecognitionDiagnostic()
        if self.device == 'cuda':
            prepare_cuda_libraries()
        try:
            self.model = self._load(self.device, config['compute_type'])
        except Exception:
            if self.device != 'cuda':
                raise
            self._fallback()

    def _load(self, device: str, compute: str) -> WhisperModel:
        path = local_path(self.cfg['model_path'])
        if not (path / 'model.bin').exists():
            raise FileNotFoundError('Chưa có Whisper. Chạy setup.bat trước.')
        return WhisperModel(str(path), device=device, compute_type=compute,
                            cpu_threads=self.cfg['cpu_threads'], local_files_only=True)

    def _fallback(self) -> None:
        logging.warning('CUDA failed; falling back to CPU int8', exc_info=True)
        previous = getattr(self, 'model', None)
        if previous is not None:
            try:
                previous.model.unload_model()
            except Exception:
                logging.debug('Could not release failed CUDA model', exc_info=True)
        self.device = 'cpu'
        self.model = self._load('cpu', 'int8')
        self.notify('CUDA lỗi: đã chuyển Whisper sang CPU int8.')

    def transcribe(self, samples: np.ndarray) -> tuple[str, float]:
        started = time.monotonic()
        duration = samples.size / 16000.0
        self.last_diagnostic = RecognitionDiagnostic(audio_seconds=duration)
        if samples.size == 0 or float(np.sqrt(np.mean(samples.astype(np.float32) ** 2))) < float(
                self.cfg.get('silence_floor', 0.0015)):
            self.last_diagnostic = RecognitionDiagnostic(reason='quiet_audio', audio_seconds=duration)
            return '', time.monotonic() - started
        def decode() -> str:
            segments, _ = self.model.transcribe(samples, language='vi',
                beam_size=self.cfg['beam_size'], condition_on_previous_text=False,
                temperature=float(self.cfg.get('temperature', 0.0)),
                hotwords=self.cfg.get('hotwords'),
                vad_filter=False, no_speech_threshold=0.6,
                initial_prompt=(self.cfg.get('initial_prompt') or '').strip() or DEFAULT_PROMPT)
            decoded = list(segments)
            raw = ' '.join(s.text.strip() for s in decoded).strip()
            text = ' '.join(s.text.strip() for s in decoded
                            if s.no_speech_prob < 0.75 and s.avg_logprob > -1.2).strip()
            self.last_diagnostic = RecognitionDiagnostic(raw, '' if text else 'low_confidence', duration)
            return text
        try:
            text = decode()
        except Exception:
            if self.device != 'cuda':
                raise
            self._fallback()
            text = decode()
        reason = self.last_diagnostic.reason
        if duration >= 1.0 and len(text) / duration > float(
                self.cfg.get('max_chars_per_second', 45)):
            logging.info('STT rejected implausibly long transcript: %d chars in %.2fs',
                         len(text), duration)
            text = ''
            reason = 'text_density'
        if text and excessive_repetition(text):
            text, reason = '', 'repetition'
        if text and not re.search(r'\w', text, re.UNICODE):
            text, reason = '', 'no_words'
        self.last_diagnostic = RecognitionDiagnostic(self.last_diagnostic.raw_text, reason, duration)
        return correct_command_prefix(text), time.monotonic() - started

