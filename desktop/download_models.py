"""Run explicitly during setup; the pet never downloads models at runtime."""
import argparse
import hashlib
import json
import os
from pathlib import Path
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
os.environ['HF_HUB_DISABLE_XET'] = '1'
import truststore
truststore.inject_into_ssl()
from huggingface_hub import snapshot_download
import yaml

if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    cfg = yaml.safe_load((root / 'config.yaml').read_text(encoding='utf-8'))['stt']
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', default=cfg.get('model_repo', 'Systran/faster-whisper-' + cfg['model_size']))
    parser.add_argument('--revision', default=cfg.get('model_revision'))
    parser.add_argument('--destination', default=cfg['model_path'])
    args = parser.parse_args()
    destination = Path(args.destination)
    if not destination.is_absolute():
        destination = root / destination
    snapshot_download(args.repo, revision=args.revision, local_dir=destination,
                      allow_patterns=['model.bin', 'config.json', 'tokenizer.json',
                                      'vocabulary.txt', 'vocabulary.json', 'preprocessor_config.json',
                                      'README.md', 'LICENSE'])
    hashes = {}
    for path in destination.iterdir():
        if path.is_file() and path.name != 'download-manifest.json':
            with path.open('rb') as source:
                hashes[path.name] = hashlib.file_digest(source, 'sha256').hexdigest()
    (destination / 'download-manifest.json').write_text(json.dumps(
        {'repo': args.repo, 'revision': args.revision, 'sha256': hashes}, indent=2), encoding='utf-8')
    print(f'Model ready: {destination}')
