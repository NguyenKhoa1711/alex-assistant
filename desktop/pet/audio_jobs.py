from dataclasses import dataclass, field
import base64, threading, time
from queue import Queue
import numpy as np

@dataclass
class AudioJob:
    samples: np.ndarray
    received_at: float = field(default_factory=time.monotonic)
    done: threading.Event = field(default_factory=threading.Event)
    transcript: str = ''
    reply: str = ''
    audio: bytearray = field(default_factory=bytearray)
    sample_rate: int = 0
    error: str = ''
    abandoned: threading.Event = field(default_factory=threading.Event)
    events: Queue | None = None

    def set_transcript(self, text: str) -> None:
        self.transcript = text
        if self.events is not None and text:
            self.events.put({'transcript': text})

    def add_audio(self, sample_rate: int, pcm: bytes) -> None:
        if not self.sample_rate:
            self.sample_rate = sample_rate
        self.audio.extend(pcm)
        if self.events is not None and pcm:
            self.events.put({'sample_rate': sample_rate, 'audio': base64.b64encode(pcm).decode('ascii')})
