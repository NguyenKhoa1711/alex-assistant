from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from queue import Empty, Full, Queue
import threading
import time
import numpy as np
import sounddevice as sd
import webrtcvad

FRAME_MS = 30

@dataclass
class Utterance:
    samples: np.ndarray
    ended_at: float

class Segmenter:
    """30 ms PCM frames, short preroll, silence end, bounded recording."""
    def __init__(self, config: dict) -> None:
        self.cfg = config
        self.vad = webrtcvad.Vad(config['vad_aggressiveness'])
        self.reset()

    def reset(self) -> None:
        self.preroll: deque[bytes] = deque(maxlen=10)
        self.frames: list[bytes] = []
        self.onsets: deque[bool] = deque(maxlen=5)
        self.speech_count = 0
        self.quiet_count = 0
        self.last_voice_at = 0.0

    def feed(self, frame: bytes, timestamp: float, voiced: bool | None = None) -> Utterance | None:
        pcm = np.frombuffer(frame, dtype=np.int16)
        if voiced is None:
            rms = float(np.sqrt(np.mean((pcm.astype(np.float32) / 32768) ** 2)))
            voiced = rms >= self.cfg['min_rms'] and self.vad.is_speech(frame, self.cfg['sample_rate'])
        if voiced:
            self.last_voice_at = timestamp
        if not self.frames:
            self.preroll.append(frame)
            self.onsets.append(voiced)
            if sum(self.onsets) < 3:
                return None
            self.frames = list(self.preroll)
            self.speech_count = sum(self.onsets)
        else:
            self.frames.append(frame)
            self.speech_count += int(voiced)
        self.quiet_count = 0 if voiced else self.quiet_count + 1
        at_end = self.quiet_count * FRAME_MS >= self.cfg['silence_ms']
        at_limit = len(self.frames) * FRAME_MS >= self.cfg['max_utterance_seconds'] * 1000
        if not (at_end or at_limit):
            return None
        valid = self.speech_count * FRAME_MS >= self.cfg['min_speech_ms']
        audio = np.frombuffer(b''.join(self.frames), dtype=np.int16).astype(np.float32) / 32768
        ended = self.last_voice_at
        self.reset()
        return Utterance(audio, ended) if valid else None

class Microphone:
    def __init__(self, config: dict) -> None:
        self.cfg = config
        self.frames: Queue[tuple[bytes, float]] = Queue(maxsize=1100)
        self.enabled = threading.Event()
        self.overruns = 0
        self.input_overflows = 0
        self.stream: sd.RawInputStream | None = None

    def _callback(self, data: bytes, frames: int, timing: object, status: object) -> None:
        if not self.enabled.is_set():
            return
        if status and getattr(status, 'input_overflow', False):
            self.input_overflows += 1
        try:
            self.frames.put_nowait((bytes(data), time.monotonic()))
        except Full:
            self.overruns += 1

    def start(self) -> None:
        device = sd.query_devices(self.cfg['input_device'], 'input')
        host = sd.query_hostapis(device['hostapi'])['name']
        extra = sd.WasapiSettings(auto_convert=True) if host == 'Windows WASAPI' else None
        self.stream = sd.RawInputStream(
            samplerate=self.cfg['sample_rate'], channels=1, dtype='int16',
            blocksize=self.cfg['sample_rate'] * FRAME_MS // 1000,
            device=self.cfg['input_device'], callback=self._callback, extra_settings=extra,
        )
        self.stream.start()

    def gate(self, enabled: bool) -> None:
        self.enabled.clear()
        self.flush()
        if enabled:
            self.enabled.set()

    def flush(self) -> None:
        while True:
            try:
                self.frames.get_nowait()
            except Empty:
                break

    def close(self) -> None:
        self.enabled.clear()
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        self.flush()
