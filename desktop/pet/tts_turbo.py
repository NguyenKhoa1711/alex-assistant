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
from collections.abc import Callable

import numpy as np
import sounddevice as sd

from .config import ROOT


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
        return sample_rate, pcm

    def speak(self, text: str, cancelled: threading.Event,
              on_play: Callable[[float], None]) -> float | None:
        started = time.monotonic()
        rendered = self.render_pcm(text, cancelled)
        if rendered is None or cancelled.is_set():
            return None
        sample_rate, raw = rendered
        pcm = np.frombuffer(raw, dtype=np.int16)
        with sd.OutputStream(samplerate=sample_rate, channels=1, dtype='int16',
                             device=self.device, blocksize=512) as stream:
            first = time.monotonic() - started
            on_play(first)
            for offset in range(0, len(pcm), 512):
                if cancelled.is_set():
                    stream.abort()
                    break
                stream.write(pcm[offset:offset + 512])
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
