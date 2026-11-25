from __future__ import annotations
import ctypes
import json
import os
from pathlib import Path
import threading
import time
from collections.abc import Callable
import numpy as np
import onnxruntime as ort
from piper import PiperVoice, SynthesisConfig
from piper.config import PiperConfig
from piper.phonemize_espeak import ESPEAK_DATA_DIR
import sounddevice as sd
from .config import local_path
from . import voice_motion


def compatible_espeak_path(path: Path) -> Path:
    """espeak on Windows requires an ASCII path; the files stay in place."""
    if os.name != 'nt' or str(path).isascii():
        return path
    get_short_path = ctypes.WinDLL('kernel32', use_last_error=True).GetShortPathNameW
    get_short_path.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    get_short_path.restype = ctypes.c_uint32
    buffer = ctypes.create_unicode_buffer(32768)
    length = get_short_path(str(path), buffer, len(buffer))
    if not 0 < length < len(buffer) or not buffer.value.isascii():
        raise RuntimeError('Piper cần tts.espeak_data_dir là đường dẫn ASCII hoặc liên kết thư mục ASCII.')
    return Path(buffer.value)

class Speaker:
    engine_label = 'Piper'

    def __init__(self, config: dict, output_device: int | str | None) -> None:
        path = local_path(config['voice'])
        espeak_path = local_path(config['espeak_data_dir']) if config.get('espeak_data_dir') else ESPEAK_DATA_DIR
        ort.disable_telemetry_events()
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        self.voice = PiperVoice(session=ort.InferenceSession(str(path), sess_options=options,
            providers=['CPUExecutionProvider']),
            config=PiperConfig.from_dict(json.loads(local_path(str(path) + '.json').read_text(encoding='utf-8'))),
            download_dir=path.parent, espeak_data_dir=compatible_espeak_path(espeak_path))
        self.speed = config['speed']
        self.device = output_device

    def render_pcm(self, text: str, cancelled: threading.Event) -> tuple[int, bytes] | None:
        chunks: list[bytes] = []
        sample_rate = 0
        for chunk in self.voice.synthesize(text, syn_config=SynthesisConfig(length_scale=1 / self.speed)):
            if cancelled.is_set():
                return None
            sample_rate = chunk.sample_rate
            chunks.append(chunk.audio_int16_bytes)
        return (sample_rate, b''.join(chunks)) if chunks else None

    def speak(self, text: str, cancelled: threading.Event,
              on_play: Callable[[float], None]) -> float | None:
        start = time.monotonic()
        first = None
        for chunk in self.voice.synthesize(text, syn_config=SynthesisConfig(length_scale=1 / self.speed)):
            if cancelled.is_set():
                break
            pcm = np.frombuffer(chunk.audio_int16_bytes, dtype=np.int16)
            with sd.OutputStream(samplerate=chunk.sample_rate, channels=1, dtype='int16',
                                 device=self.device, blocksize=512) as stream:
                if first is None:
                    first = time.monotonic() - start
                    on_play(first)
                for offset in range(0, len(pcm), 512):
                    if cancelled.is_set():
                        stream.abort()
                        break
                    block = pcm[offset:offset + 512]
                    voice_motion.feed_pcm(block)
                    stream.write(block)
        voice_motion.clear()
        return first

    def close(self) -> None:
        pass
