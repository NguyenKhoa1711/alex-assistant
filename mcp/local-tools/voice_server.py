"""Vietnamese speech MCP for Bionic. Local Piper only; F8 interrupts playback."""
from __future__ import annotations

import ctypes
import json
import os
import re
import threading
import time
from pathlib import Path

os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
os.environ['DO_NOT_TRACK'] = '1'

import numpy as np
import onnxruntime as ort
import sounddevice as sd
from mcp.server.fastmcp import FastMCP
from piper import PiperVoice, SynthesisConfig
from piper.config import PiperConfig
from piper.phonemize_espeak import ESPEAK_DATA_DIR

ROOT = Path(__file__).resolve().parent
ort.disable_telemetry_events()
mcp = FastMCP('Vietnamese Voice')
_voice: PiperVoice | None = None
_lock = threading.Lock()
_stop = threading.Event()



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
        raise RuntimeError('Piper cần đường dẫn thư viện ASCII hoặc liên kết thư mục ASCII.')
    return Path(buffer.value)

def voice() -> PiperVoice:
    global _voice
    if _voice is None:
        path = ROOT / 'models/vi_VN-vais1000-medium.onnx'
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2
        opts.inter_op_num_threads = 1
        _voice = PiperVoice(
            session=ort.InferenceSession(str(path), sess_options=opts, providers=['CPUExecutionProvider']),
            config=PiperConfig.from_dict(json.loads(Path(str(path) + '.json').read_text(encoding='utf-8'))),
            download_dir=ROOT / 'models',
            espeak_data_dir=compatible_espeak_path(ESPEAK_DATA_DIR),
        )
    return _voice


@mcp.tool()
def speak_vietnamese(text: str) -> dict[str, object]:
    """Read a short Vietnamese reply aloud on the user's local speakers. Call for every final reply in voice mode. Use plain text, 1–3 sentences, no code or Markdown. F8 stops speech."""
    text = re.sub(r'```[\s\S]*?```', ' ', text)
    text = text.replace('[[', '').replace(']]', '')
    text = re.sub(r'[*#`_]', '', text).strip()[:800]
    if not text:
        return {'spoken': False, 'reason': 'empty text'}
    if not _lock.acquire(blocking=False):
        return {'spoken': False, 'reason': 'another reply is speaking'}
    try:
        _stop.clear()
        model = voice()
        cfg = json.loads((ROOT / 'voice_config.json').read_text(encoding='utf-8'))
        started = time.perf_counter()
        first_pcm: float | None = None
        for chunk in model.synthesize(text, syn_config=SynthesisConfig(length_scale=1 / cfg['speed'])):
            if _stop.is_set():
                break
            pcm = np.frombuffer(chunk.audio_int16_bytes, dtype=np.int16).astype(np.float32) / 32768
            if first_pcm is None:
                first_pcm = time.perf_counter() - started
            sd.play(pcm, chunk.sample_rate, device=cfg['output_device'], blocking=False)
            while sd.get_stream().active:
                pressed = bool(ctypes.windll.user32.GetAsyncKeyState(0x77) & 0x8000)
                if _stop.is_set() or pressed:
                    _stop.set()
                    sd.stop()
                    break
                time.sleep(0.02)
        return {'spoken': not _stop.is_set(), 'interrupted': _stop.is_set(),
                'first_pcm_seconds': first_pcm, 'total_seconds': time.perf_counter() - started}
    finally:
        _lock.release()


@mcp.tool()
def stop_speaking() -> dict[str, bool]:
    """Stop the local Vietnamese voice immediately."""
    _stop.set()
    sd.stop()
    return {'stopped': True}


if __name__ == '__main__':
    mcp.run(transport='stdio')
