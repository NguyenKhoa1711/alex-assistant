"""Persistent offline VieNeu voice process so pet and model dependencies stay isolated."""
from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
from queue import Empty, Queue
import subprocess
import threading
import time
from collections import OrderedDict
from collections.abc import Callable

import numpy as np
import sounddevice as sd

from .config import ROOT
from . import voice_motion
from .speech_pcm import SpeechEdges, trim_speech_edges


class TurboSpeaker:
    engine_label = 'Thái Sơn'

    def __init__(self, config: dict, output_device: int | str | None) -> None:
        python = ROOT / '.venv-voice/Scripts/python.exe'
        worker = ROOT / 'voice_worker_turbo.py'
        if not python.exists():
            raise FileNotFoundError('Chưa cài môi trường giọng VieNeu trong .venv-voice.')
        env = os.environ.copy()
        env.update(HF_HOME=str(ROOT / 'models/huggingface'), HF_HUB_OFFLINE='1',
                   HF_HUB_DISABLE_TELEMETRY='1', DO_NOT_TRACK='1', PYTHONIOENCODING='utf-8')
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        self.proc = subprocess.Popen([str(python), '-u', str(worker)], cwd=ROOT,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, creationflags=flags)
        self.responses: Queue[dict] = Queue()
        self.write_lock = threading.Lock()
        self.render_lock = threading.Lock()
        self._cache_lock = threading.Lock()
        self._cache: OrderedDict[tuple[str, str], tuple[int, bytes]] = OrderedDict()
        self.sequence = 0
        self.voice = str(config.get('turbo_voice', 'Thái Sơn'))
        self.engine_label = self.voice
        self.device = output_device
        threading.Thread(target=self._read, daemon=True, name='VieNeu-results').start()
        threading.Thread(target=self._read_errors, daemon=True, name='VieNeu-errors').start()
        ready = self._await(None, None, 35)
        if not ready or not ready.get('ready'):
            self.close()
            raise RuntimeError((ready or {}).get('error', 'Giọng VieNeu không khởi động được.'))

    def _get_cached(self, text: str) -> tuple[int, bytes] | None:
        key = (self.voice, text)
        with self._cache_lock:
            value = self._cache.get(key)
            if value is not None:
                self._cache.move_to_end(key)
            return value

    def _put_cached(self, text: str, sample_rate: int, pcm: bytes) -> None:
        if len(text) > 240 or not pcm or len(pcm) > 2_400_000:
            return
        key = (self.voice, text)
        with self._cache_lock:
            self._cache[key] = (sample_rate, pcm)
            self._cache.move_to_end(key)
            while len(self._cache) > 64:
                self._cache.popitem(last=False)

    def _read(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            try:
                self.responses.put(json.loads(line))
            except ValueError:
                logging.warning('VieNeu worker returned an unreadable line')

    def _read_errors(self) -> None:
        assert self.proc.stderr is not None
        for raw in self.proc.stderr:
            line = raw.decode('utf-8', errors='replace').strip()
            if line:
                logging.warning('VieNeu worker: %s', line[:300])

    def _await(self, request_id: int | None, cancelled: threading.Event | None,
               timeout: float) -> dict | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if cancelled is not None and cancelled.is_set():
                return None
            try:
                response = self.responses.get(timeout=min(0.1, max(0.01, deadline - time.monotonic())))
            except Empty:
                if self.proc.poll() is not None:
                    raise RuntimeError('Giọng VieNeu đã dừng đột ngột.')
                continue
            if request_id is None and ('ready' in response or 'error' in response):
                return response
            if response.get('id') == request_id:
                return response
        raise TimeoutError('Giọng VieNeu phản hồi quá lâu.')

    def render_pcm(self, text: str, cancelled: threading.Event) -> tuple[int, bytes] | None:
        if cancelled.is_set():
            return None
        cached = self._get_cached(text)
        if cached is not None:
            return cached
        with self.render_lock:
            if cancelled.is_set():
                return None
            cached = self._get_cached(text)
            if cached is not None:
                return cached
            with self.write_lock:
                self.sequence += 1
                request_id = self.sequence
                if self.proc.poll() is not None or self.proc.stdin is None:
                    raise RuntimeError('Giọng VieNeu chưa sẵn sàng.')
                message = {'id': request_id, 'text': text, 'voice': self.voice}
                self.proc.stdin.write((json.dumps(message, ensure_ascii=False) + '\n').encode('utf-8'))
                self.proc.stdin.flush()
            response = self._await(request_id, cancelled, 90)
            if response is None:
                return None
            if response.get('error'):
                raise RuntimeError(str(response['error']))
            sample_rate = int(response['sample_rate'])
            pcm = base64.b64decode(response['audio'], validate=True)
            if sample_rate != 48000 or len(pcm) % 2 or len(pcm) > 12_000_000:
                raise RuntimeError('Dữ liệu âm thanh VieNeu không hợp lệ.')
            pcm=trim_speech_edges(pcm,sample_rate)
            self._put_cached(text, sample_rate, pcm)
            return sample_rate, pcm

    def prefetch(self, text: str, cancelled: threading.Event) -> None:
        if not text or cancelled.is_set() or self._get_cached(text) is not None:
            return
        def _worker() -> None:
            try:
                self.render_pcm(text, cancelled)
            except Exception:
                pass
        threading.Thread(target=_worker, daemon=True, name='VieNeu-prefetch').start()

    def speak(self, text: str, cancelled: threading.Event,
              on_play: Callable[[float], None]) -> float | None:
        return self.speak_sequence((text,), cancelled, on_play)

    # Pre-buffer before audio starts and after a dry queue. VieNeu on this CPU runs
    # at roughly real time (RTF 0.72-0.95), so streaming playback without a lead
    # underruns mid-sentence ("giật"), and synthesising the next sentence
    # only after the previous one finished playing leaves a long gap ("khựng").
    _PREBUFFER_SECONDS = 1.0
    _REBUFFER_SECONDS = 0.25

    def speak_sequence(self, texts, cancelled: threading.Event,
                       on_play: Callable[[float], None]) -> float | None:
        """Speak one or more sentences smoothly through a single continuous audio stream.

        All sentences stream while the preceding audio plays. Only excess quiet
        at utterance edges is shortened; internal pauses remain untouched.
        """
        started = time.monotonic()
        chunks: Queue = Queue()
        sentence_end = object()

        def producer() -> None:
            try:
                for idx, text in enumerate(texts):
                    if cancelled.is_set():
                        break
                    cached = self._get_cached(text)
                    if cached is not None:
                        chunks.put(cached[1])
                        chunks.put(sentence_end)
                        continue
                    collected: list[bytes] = []
                    completed = False
                    trim=SpeechEdges()
                    def emit(raw):
                        audio=trim.feed(raw)
                        if audio:
                            collected.append(audio)
                            chunks.put(audio)
                    use_stream = True
                    with self.render_lock:
                        with self.write_lock:
                            self.sequence += 1
                            request_id = self.sequence
                            if self.proc.poll() is not None or self.proc.stdin is None:
                                raise RuntimeError('Giọng VieNeu chưa sẵn sàng.')
                            message = {
                                'id': request_id,
                                'text': text,
                                'voice': self.voice,
                                'stream': use_stream,
                            }
                            self.proc.stdin.write((json.dumps(message, ensure_ascii=False) + '\n').encode('utf-8'))
                            self.proc.stdin.flush()
                        while not cancelled.is_set():
                            response = self._await(request_id, cancelled, 90)
                            if response is None:
                                break
                            if response.get('error'):
                                raise RuntimeError(str(response['error']))
                            if 'audio' in response:
                                raw = base64.b64decode(response['audio'], validate=True)
                                emit(raw)
                                completed = True
                                break
                            if 'chunk' in response:
                                raw = base64.b64decode(response['chunk'], validate=True)
                                if raw:
                                    emit(raw)
                            if response.get('done'):
                                completed = True
                                break
                    if completed and not cancelled.is_set():
                        tail=trim.finish()
                        if tail:
                            collected.append(tail)
                            chunks.put(tail)
                    if completed and collected and not cancelled.is_set():
                        self._put_cached(text, 48000, b''.join(collected))
                    chunks.put(sentence_end)
            except Exception as exc:  # surfaced to the caller below
                chunks.put(exc)
            finally:
                chunks.put(None)

        threading.Thread(target=producer, daemon=True, name='VieNeu-sequence').start()

        stream: sd.OutputStream | None = None
        first: float | None = None
        pending: list[np.ndarray] = []
        pending_samples = 0
        need = int(48000 * self._PREBUFFER_SECONDS)
        playing = False
        error: Exception | None = None

        def flush() -> None:
            nonlocal stream, first, pending_samples, playing
            if not pending or cancelled.is_set():
                return
            if stream is None:
                stream = sd.OutputStream(samplerate=48000, channels=1, dtype='int16',
                                         device=self.device, blocksize=2048, latency='high')
                stream.start()
            if first is None:
                first = time.monotonic() - started
                on_play(first)
            playing = True
            data = np.concatenate(pending) if len(pending) > 1 else pending[0]
            pending.clear()
            pending_samples = 0
            for offset in range(0, len(data), 2048):
                if cancelled.is_set():
                    return
                block = data[offset:offset + 2048]
                voice_motion.feed_pcm(block)
                stream.write(block)

        try:
            while not cancelled.is_set():
                try:
                    item = chunks.get(timeout=0.05)
                except Empty:
                    if playing and not pending:
                        # Device is about to run dry: rebuild a short lead rather
                        # than letting it stutter on every late chunk.
                        playing = False
                        need = int(48000 * self._REBUFFER_SECONDS)
                    continue
                if item is None:
                    break
                if isinstance(item, Exception):
                    error = item
                    continue
                if item is sentence_end:
                    # A short sentence may never reach the lead size; play what we have.
                    flush()
                    continue
                pcm = np.frombuffer(item, dtype=np.int16)
                if not len(pcm):
                    continue
                pending.append(pcm)
                pending_samples += len(pcm)
                if playing or pending_samples >= need:
                    flush()
            if not cancelled.is_set():
                flush()
        finally:
            if stream is not None:
                try:
                    if cancelled.is_set():
                        stream.abort()
                    else:
                        stream.stop()
                except Exception:
                    pass
                try:
                    stream.close()
                except Exception:
                    pass
            voice_motion.clear()
        if error is not None and not cancelled.is_set():
            raise error
        return first

    def close(self) -> None:
        if self.proc.poll() is not None:
            return
        try:
            if self.proc.stdin:
                self.proc.stdin.write(b'{"quit":true}\n')
                self.proc.stdin.flush()
            self.proc.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired):
            self.proc.terminate()
            try:
                self.proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.proc.kill()
