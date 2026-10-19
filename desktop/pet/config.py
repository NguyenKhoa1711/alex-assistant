from __future__ import annotations
from pathlib import Path
from urllib.parse import urlparse
import yaml

ROOT = Path(__file__).resolve().parent.parent

def load_config() -> dict:
    config = yaml.safe_load((ROOT / 'config.yaml').read_text(encoding='utf-8'))
    url = urlparse(config['llm']['base_url'])
    if url.scheme != 'http' or url.hostname not in {'127.0.0.1', 'localhost', '::1'}:
        raise ValueError('Model phải chạy trên localhost.')
    if not 0.5 <= float(config['tts']['speed']) <= 2:
        raise ValueError('Tốc độ đọc phải từ 0.5 đến 2.')
    if config['tts'].get('engine', 'piper') not in {'piper', 'vieneu_turbo'}:
        raise ValueError('tts.engine phải là piper hoặc vieneu_turbo.')
    return config

def local_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path
