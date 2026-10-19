"""Isolated offline VieNeu Turbo worker; JSON lines in/out, no transcripts on disk."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
os.environ['HF_HOME'] = str(ROOT / 'models' / 'huggingface')
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
os.environ['DO_NOT_TRACK'] = '1'

import numpy as np
from vieneu import Vieneu


def send(message: dict) -> None:
    sys.stdout.buffer.write((json.dumps(message, ensure_ascii=False) + '\n').encode('utf-8'))
    sys.stdout.buffer.flush()


def main() -> None:
    try:
        tts = Vieneu(mode='v3turbo', device='cpu', precision='int8', threads=4)
    except Exception as exc:
        send({'error': f'Không nạp được giọng Thái Sơn offline: {type(exc).__name__}'})
        return
    send({'ready': True, 'sample_rate': tts.sample_rate})
    try:
        for raw in sys.stdin.buffer:
            try:
                request = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                continue
            if request.get('quit'):
                break
            request_id = request.get('id')
            text = request.get('text')
            voice = request.get('voice', 'Thái Sơn')
            if not isinstance(request_id, int) or not isinstance(text, str) or not 0 < len(text) <= 600:
                send({'id': request_id, 'error': 'Câu nói không hợp lệ.'})
                continue
            try:
                audio = tts.infer(text, voice=voice, apply_watermark=False)
                pcm = (np.clip(audio, -1, 1) * 32767).astype('<i2').tobytes()
                send({'id': request_id, 'sample_rate': tts.sample_rate,
                      'audio': base64.b64encode(pcm).decode('ascii')})
            except Exception as exc:
                send({'id': request_id, 'error': f'Tạo giọng thất bại: {type(exc).__name__}'})
    finally:
        tts.close()


if __name__ == '__main__':
    main()
