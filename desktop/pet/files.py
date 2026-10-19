"""Find explicitly requested local files and folders without reading their contents."""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import time

from .apps import focus_window, normalized


_REQUEST = re.compile(
    r'^(?:hay |ban |giup (?:toi|minh) |vui long )*'
    r'(?:mo|tim|tim va mo|vao) '
    r'(?:(thu muc|folder|tep|file|tai lieu|duong dan) )?(.+?)'
    r'(?: (?:trong|bang) (?:file )?explorer)?'
    r'(?: (?:cho|giup) (?:toi|minh)|nhe|di)?$', re.IGNORECASE)


def requested_file(question: str) -> tuple[str, str] | None:
    """Require an explicit file/folder noun, Explorer, or absolute path."""
    value = normalized(question).strip(' .!?')
    if len(value) > 200 or any(c in question for c in '\r\n;|*?"<>'):
        return None
    match = _REQUEST.fullmatch(value)
    if not match:
        return None
    kind, name = match.groups()
    if not kind and 'explorer' not in value and not re.match(r'^[a-z]:[\\/]', name):
        return None
    name = name.strip()
    direct = re.search(r'([A-Za-z]:[\\/].+)', question)
    if direct:
        name = re.sub(r'(?i)\s+(?:cho tôi|cho mình|giúp tôi|giúp mình|nhé|đi)$',
                      '', direct.group(1)).strip(' .!?')
    if not name or re.search(r'\b(?:roi|sau do|va|xoa|gui|doi ten)\b', name):
        return None
    return ('folder' if kind in ('thu muc', 'folder', 'duong dan') else
            'file' if kind in ('tep', 'file', 'tai lieu') else 'either', name)


def _key(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', normalized(value)).strip()


def find_paths(name: str, kind: str, roots: list[Path], *, seconds: float = 3.0,
               limit: int = 6) -> list[Path]:
    """Search path names on demand; never traverse links or read file contents."""
    absolute = Path(os.path.expandvars(name)).expanduser()
    if absolute.is_absolute():
        return [absolute] if absolute.exists() and (kind == 'either' or
            (absolute.is_dir() if kind == 'folder' else absolute.is_file())) else []
    qualified = re.fullmatch(r'(.+?) trong (?:thu muc|folder) (.+)', normalized(name))
    parent = _key(qualified.group(2)) if qualified else ''
    target = _key(qualified.group(1) if qualified else name)
    if not target or len(target) < 2:
        return []
    matches: list[Path] = []
    started = time.monotonic()
    seen: set[str] = set()
    for root in roots:
        root = root.expanduser()
        if not root.is_dir() or root.is_symlink():
            continue
        if _key(root.name) == target and kind in ('folder', 'either'):
            matches.append(root)
        for directory, dirs, files in os.walk(root, followlinks=False):
            if time.monotonic() - started >= seconds or len(matches) >= limit:
                return matches
            dirs[:] = [d for d in dirs if not d.startswith('.') and
                       not (Path(directory) / d).is_symlink()]
            items = (dirs if kind == 'folder' else files if kind == 'file' else dirs + files)
            for item in items:
                path = Path(directory) / item
                parent_matches = not parent or any(_key(ancestor.name) == parent
                                                   for ancestor in path.parents)
                if parent_matches and (_key(item) == target or _key(path.stem) == target):
                    identity = str(path).casefold()
                    if identity not in seen:
                        seen.add(identity)
                        matches.append(path)
                        if len(matches) >= limit:
                            return matches
    return matches


def search_roots(values: list[str]) -> list[Path]:
    return [Path(os.path.expandvars(value)).expanduser() for value in values]


def _explorer_window_for(path: Path) -> int | None:
    """Find the Explorer window at this exact directory in the current desktop."""
    try:
        import pythoncom
        from win32com.client import Dispatch

        pythoncom.CoInitialize()
        try:
            for window in Dispatch('Shell.Application').Windows():
                try:
                    current = Path(window.Document.Folder.Self.Path)
                    if current.samefile(path):
                        return int(window.HWND)
                except (AttributeError, OSError, TypeError):
                    continue
        finally:
            pythoncom.CoUninitialize()
    except Exception:
        return None
    return None


def open_path(path: Path) -> bool:
    """Ask Explorer to show a verified local path; no shell or command execution."""
    if not path.exists() or path.is_symlink():
        return False
    if path.is_dir():
        # Ask the existing Windows shell to show it; survive a short-lived MCP.
        os.startfile(str(path))
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            hwnd = _explorer_window_for(path)
            if hwnd:
                focus_window(hwnd)
                return True
            time.sleep(.1)
        return False
    else:
        subprocess.Popen(['explorer.exe', '/select,', str(path)], close_fds=True)
    return True
