from __future__ import annotations
import logging
import os
import re
import sys
import unicodedata
from pathlib import Path
import time
from dataclasses import dataclass
from collections.abc import Callable
import numpy as np
from faster_whisper import WhisperModel
from .config import local_path

_DLL_HANDLES: list[object] = []

DEFAULT_PROMPT = ('Tiếng Việt. Trợ lý Alex. Lệnh điều khiển: mở ứng dụng, mở thư mục, '
                  'mở trang web, lướt web, dừng lướt web, tìm kiếm. Nhận đúng lời người nói, kể cả tên phần mềm.')


@dataclass(frozen=True)
class RecognitionDiagnostic:
    raw_text: str = ''
    reason: str = ''
    audio_seconds: float = 0.0
    language: str = ''
    language_probability: float = 0.0
    detected_language: str = ''
    response_language: str = ''


_EN_WORDS = frozenset(('hello hey hi how are you your what where when why who which '
    'thank thanks please today good morning evening night my name is the am '
    'tell could would should can does do have help want speak english').split())


def response_language_for_text(text: str) -> str:
    """Identify clear text only; never translate or infer an uncertain language."""
    if re.search(r'[\u3400-\u4dbf\u4e00-\u9fff]', text):
        return 'zh'
    # Vietnamese diacritics are stronger evidence than English-looking words.
    if any(unicodedata.category(c) == 'Mn' for c in unicodedata.normalize('NFD', text)) or re.search(r'[đĐ]', text):
        return 'vi'
    words = re.findall(r'[a-z]+', text.casefold())
    matches = sum(word in _EN_WORDS for word in words)
    if matches >= 2 or (words and words[0] in ('hello', 'hi', 'hey') and len(words) <= 3):
        return 'en'
    if words and words[0] in ('open', 'close', 'play', 'pause') and len(words) >= 2:
        return 'en'
    return ''


def recognition_config(config: dict) -> dict:
    """Add canonical names, not past STT mistakes, to a bounded vocabulary hint."""
    stt = dict(config['stt'])
    # Keep the original user configuration and rejection thresholds. This is
    # only a short vocabulary hint, never a forced transcript or second decode.
    prompt = (str(stt.get('initial_prompt') or '').strip() or DEFAULT_PROMPT)
    if 'phóng to' not in prompt.casefold() or 'thu nhỏ' not in prompt.casefold():
        prompt += ' phóng to, thu nhỏ, khôi phục cửa sổ.'
    if 'lướt web' not in prompt.casefold():
        prompt += ' Lướt web, dừng lướt web.'
    stt['initial_prompt'] = prompt
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
        if len(', '.join([*kept, name])) > 180:
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


def repeated_prompt_echo(text: str, prompt: str) -> bool:
    """Reject a whole transcript that only repeats a fragment of a hint."""
    words = re.findall(r'\w+', text.casefold())
    hint_words = re.findall(r'\w+', (prompt + ' Điều khiển cửa sổ.').casefold())
    for width in range(3, len(words) // 2 + 1):
        if len(words) % width:
            continue
        block = words[:width]
        if words == block * (len(words) // width) and any(
                hint_words[i:i + width] == block
                for i in range(len(hint_words) - width + 1)):
            return True
    return False


def correct_command_prefix(text: str) -> str:
    """Repair a common Vietnamese opening-command error without changing ordinary speech."""
    if (re.match(r'^(?:(?:hãy|bạn)\s+)*bởi\s+(?!vì\b)', text, re.IGNORECASE) and re.search(
            r'\b(?:cho|giúp)\s+(?:tôi|mình)\b|\b(?:ở\s+)?trong\s+(?:google|chrome)\b',
            text, re.IGNORECASE)):
        if re.match(r'^bởi\s+', text, re.IGNORECASE):
            text = re.sub(r'^bởi\b', 'Mở', text, count=1, flags=re.IGNORECASE)
        else:
            text = re.sub(r'\bbởi\b', 'mở', text, count=1, flags=re.IGNORECASE)
    text = re.sub(
        r'(?i)\b(?:look|loop|loot|load|log|lúc|lước|nướt|lượt|luốt|lươt)\s+'
        r'(?=(?:web|quép|quét|ghép|guép|wep|trang\s+web|trình\s+duyệt|tiktok|tik\s*tok|facebook|youtube|xuống|lên|tiếp)\b)',
        'lướt ',
        text,
    )
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
            if type(self.model).__name__ == 'WhisperModel':
                try:
                    list(self.model.transcribe(
                        np.zeros(4800, dtype=np.float32),
                        language='vi',
                        beam_size=1,
                        without_timestamps=True,
                        vad_filter=False,
                    )[0])
                except Exception:
                    pass
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
        work_samples = samples
        if samples.size > 8000:
            floor = float(self.cfg.get('silence_floor', 0.0015))
            active_idx = np.flatnonzero(np.abs(samples) >= floor)
            if active_idx.size > 0:
                end_i = min(samples.size, int(active_idx[-1]) + 2400)
                # Keep the full pre-roll: quiet initial syllables can be below
                # the amplitude floor even though later speech crosses it.
                if end_i >= 3200:
                    work_samples = samples[:end_i]
        def decode() -> str:
            mode = str(self.cfg.get('language_mode', 'vi')).lower()
            language, probability, detected = 'vi', 0.0, ''
            if mode == 'auto':
                detect_res = self.model.detect_language(audio=work_samples, vad_filter=False)
                all_probs: object = ()
                if isinstance(detect_res, (tuple, list)) and len(detect_res) >= 2:
                    detected = str(detect_res[0] or '')
                    probability = float(detect_res[1] or 0.0)
                    all_probs = detect_res[2] if len(detect_res) >= 3 else ()
                vi_prob = 0.0
                if isinstance(all_probs, (list, tuple)):
                    for item in all_probs:
                        if isinstance(item, (list, tuple)) and len(item) >= 2 and item[0] == 'vi':
                            vi_prob = float(item[1])
                            break
                # Keep Vietnamese as the primary default; only switch to English or
                # Chinese when detection confidence is clear, never on noisy/low scores.
                has_full_probs = bool(isinstance(all_probs, (list, tuple)) and len(all_probs) > 0)
                if has_full_probs:
                    if (detected == 'vi' and probability >= 0.40) or (detected == 'zh' and probability >= 0.70):
                        language = detected
                    elif detected == 'en' and probability >= 0.72 and vi_prob < 0.10:
                        language = 'en'
                else:
                    if (detected in ('vi', 'zh') and probability >= 0.35) or (detected == 'en' and probability >= 0.35):
                        language = detected
            elif mode in ('vi', 'en', 'zh'):
                language = mode
                detected, probability = mode, 1.0
            vad_enabled = bool(self.cfg.get('vad_filter', False))

            def _run_transcribe(target_lang: str) -> list:
                is_vi = target_lang == 'vi'
                transcribe_kwargs = dict(
                    language=target_lang, task='transcribe',
                    beam_size=self.cfg['beam_size'], condition_on_previous_text=False,
                    without_timestamps=True,
                    temperature=float(self.cfg.get('temperature', 0.0)),
                    hotwords=self.cfg.get('hotwords') if is_vi else None,
                    vad_filter=vad_enabled, no_speech_threshold=0.6,
                    initial_prompt=((self.cfg.get('initial_prompt') or '').strip() or DEFAULT_PROMPT) if is_vi else None,
                )
                if vad_enabled:
                    transcribe_kwargs['vad_parameters'] = {
                        'threshold': 0.28,
                        'min_speech_duration_ms': 80,
                        'min_silence_duration_ms': 450,
                        'speech_pad_ms': 420,
                    }
                segments, _ = self.model.transcribe(work_samples, **transcribe_kwargs)
                return list(segments)

            def _extract_text(decoded_segs: list) -> tuple[str, str]:
                raw_out = ' '.join(s.text.strip() for s in decoded_segs).strip()
                kept_out = ' '.join(
                    s.text.strip() for s in decoded_segs
                    if (s.no_speech_prob < 0.75 and s.avg_logprob > -1.2)
                    or (s.no_speech_prob < 0.60 and s.avg_logprob > -1.45)
                ).strip()
                return raw_out, kept_out

            decoded = _run_transcribe(language)
            raw, text = _extract_text(decoded)
            if not text and mode == 'auto' and language != 'vi' and float(probability) < 0.65:
                vi_decoded = _run_transcribe('vi')
                vi_raw, vi_text = _extract_text(vi_decoded)
                if vi_text:
                    language, raw, text = 'vi', vi_raw, vi_text
            response_language = (response_language_for_text(text) or
                                 (language if detected == language and
                                  ((language in ('vi', 'zh') and probability >= .55) or
                                   (language == 'en' and probability >= .22)) else ''))
            self.last_diagnostic = RecognitionDiagnostic(raw, '' if text else 'low_confidence', duration,
                                                         language, float(probability), detected, response_language)
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
        if text and repeated_prompt_echo(
                text, (self.cfg.get('initial_prompt') or '').strip() or DEFAULT_PROMPT):
            text, reason = '', 'repeated_prompt_echo'
        if text and excessive_repetition(text):
            text, reason = '', 'repetition'
        if text:
            low = text.lower()
            if any(h in low for h in (
                'hãy subscribe cho kênh',
                'la la school',
                'để không bỏ lỡ những video hấp dẫn',
                'ghiền mì gõ',
                'cảm ơn các bạn đã theo dõi video',
            )):
                text, reason = '', 'whisper_hallucination'
        if text and not re.search(r'\w', text, re.UNICODE):
            text, reason = '', 'no_words'
        diag = self.last_diagnostic
        self.last_diagnostic = RecognitionDiagnostic(diag.raw_text, reason, duration,
                                                     diag.language, diag.language_probability,
                                                     diag.detected_language, diag.response_language)
        use_vi_repairs = diag.language == 'vi' and diag.response_language not in ('en', 'zh')
        return (correct_command_prefix(text) if use_vi_repairs else text), time.monotonic() - started

