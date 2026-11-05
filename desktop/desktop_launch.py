"""Small standard-library bootstrap for the Windows desktop shortcut."""
from pathlib import Path
import subprocess
import sys
root = Path(__file__).resolve().parent
flags = ['--show-muted'] if '--show-muted' in sys.argv[1:] else []
subprocess.Popen([str(root / '.venv/Scripts/pythonw.exe'), str(root / 'launch.py'), *flags],
                 cwd=root, creationflags=subprocess.CREATE_NO_WINDOW)
