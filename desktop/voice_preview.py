"""Generate an offline Vietnamese voice sample without changing the pet's active TTS."""
from __future__ import annotations

import os
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("HF_HOME", str(ROOT / "models" / "huggingface"))
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

import truststore

truststore.inject_into_ssl()

from vieneu import Vieneu


def main() -> None:
    output = ROOT / "voice_samples"
    output.mkdir(exist_ok=True)
    started = time.perf_counter()
    tts = Vieneu(mode="v3nano", threads=4)
    loaded = time.perf_counter()
    print(f"Nạp giọng: {loaded - started:.2f} giây", flush=True)
    print(f"Giọng có sẵn: {tts.list_preset_voices()}", flush=True)
    sentences = {
        "gioi_thieu": "Chào bạn, mình là A lếch. Hôm nay bạn muốn mình giúp gì nào?",
        "tra_loi": "Mình đã mở nhạc cho bạn rồi. Nếu muốn nghe bài khác, cứ nói mình nhé.",
    }
    for name, sentence in sentences.items():
        started = time.perf_counter()
        audio = tts.infer(sentence, voice="Adam", speed=1.0, apply_watermark=False)
        elapsed = time.perf_counter() - started
        path = output / f"alex-adam-{name}.wav"
        tts.save(audio, str(path))
        duration = len(audio) / tts.sample_rate
        print(f"{path}: {elapsed:.2f} giây xử lý / {duration:.2f} giây tiếng", flush=True)
    tts.close()


if __name__ == "__main__":
    main()
