"""Package generated transparent PNG frames without changing their pixels."""
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile
import json

assets = Path(__file__).resolve().parent.parent / 'assets/robot-heads'
info = json.loads((assets / 'manifest.json').read_text(encoding='utf-8'))
with ZipFile(assets / 'circle-teal.zip', 'w', compression=ZIP_STORED) as archive:
    for state in info['states']:
        for index in range(info['count']):
            name = f'{state}/{index:03}.png'
            archive.write(assets / 'frames' / name, name)
print(f"Packaged {len(info['states']) * info['count']} frames; "
      f"{(assets / 'circle-teal.zip').stat().st_size / 1024**2:.1f} MiB")
