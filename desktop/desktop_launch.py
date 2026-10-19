"""Small standard-library bootstrap for the Windows desktop shortcut."""
from pathlib import Path
import subprocess
root = Path(__file__).resolve().parent
subprocess.Popen([str(root / '.venv/Scripts/pythonw.exe'), str(root / 'launch.py')],
                 cwd=root, creationflags=subprocess.CREATE_NO_WINDOW)
