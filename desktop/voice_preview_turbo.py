"""Create offline-ready VieNeu Turbo voice previews; never changes the active pet."""
from __future__ import annotations

import os
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parent
os.environ.setdefault('HF_HOME', str(ROOT / 'models' / 'huggingface'))
os.environ.setdefault('HF_HUB_DISABLE_TELEMETRY', '1')

import truststore

truststore.inject_into_ssl()
from vieneu import Vieneu


def main() -> None:
    destination = ROOT / 'voice_samples'
    destination.mkdir(exist_ok=True)
    start = time.perf_counter()
    tts = Vieneu(mode='v3turbo', device='cpu', precision='int8', threads=4)
    print(f'Turbo loaded in {time.perf_counter() - start:.2f}s', flush=True)
    sentence = 'Chào bạn, mình là A lếch. Hôm nay bạn muốn mình giúp gì nào?'
    for voice, stem in [('Thái Sơn', 'thai_son'), ('Minh Triết', 'minh_triet')]:
        start = time.perf_counter()
        audio = tts.infer(sentence, voice=voice, apply_watermark=False)
        path = destination / f'alex-turbo-{stem}.wav'
        tts.save(audio, str(path))
        print(f'{voice}: {time.perf_counter() - start:.2f}s synthesis; '
              f'{len(audio) / tts.sample_rate:.2f}s audio; {path}', flush=True)
    tts.close()


if __name__ == '__main__':
    main()
