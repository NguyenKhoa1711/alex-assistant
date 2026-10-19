"""Only explicit, exact app-opening commands; no shell or generated arguments."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from difflib import SequenceMatcher
import ntpath
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import unicodedata
import urllib.parse
import webbrowser
import winreg


def normalized(text: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFD', text.lower().replace('đ', 'd'))
                   if unicodedata.category(c) != 'Mn').strip()


def incomplete_open_kind(question: str) -> str | None:
    """Recognize an opening request that lost its target, without guessing it."""
    text = normalized(question).strip(' .!?…')
    if not text or len(text) > 180 or any(c in text for c in '\r\n'):
        return None
    prefix = (r'(?:(?:hay giup toi|hay giup minh|ban co the|co the|toi muon ban|'
              r'minh muon ban|toi muon|minh muon|vui long|lam on|hay|ban|'
              r'cho toi|cho minh|giup toi|giup minh) ){0,3}')
    suffix = r'(?: (?:giup toi|giup minh|cho toi|cho minh|di|nhe|len|voi|ngay|duoc khong)){0,4}'
    match = re.fullmatch(prefix + r'(?:mo|bat|chay|khoi dong)'
                         r'(?: (?:cho|giup) (?:toi|minh))?'
                         r'(?: (?P<kind>ung dung(?: dung){0,2}|phan mem(?: mem){0,2}|'
                         r'app(?: app){0,2}|thu muc(?: muc){0,2}))?' + suffix, text)
    if match is None:
        return None
    return 'folder' if (match.group('kind') or '').startswith('thu muc') else 'app'


def launch_name(question: str) -> str | None:
    """Extract one explicit app-opening request from natural Vietnamese speech."""
    text = normalized(question).strip(' .!?')
    if not text or len(text) > 180 or any(char in text for char in '\r\n'):
        return None
    prefixes = ('hay giup toi ', 'hay giup minh ', 'ban co the ', 'co the ',
                'toi muon ban ', 'minh muon ban ', 'toi muon ', 'minh muon ',
                'vui long ', 'lam on ', 'hay ', 'ban ', 'cho toi ', 'cho minh ',
                'giup toi ', 'giup minh ')
    for _ in range(3):
        prefix = next((value for value in prefixes if text.startswith(value)), None)
        if prefix is None:
            break
        text = text[len(prefix):]
    text = re.sub(r' cao cho (toi|minh)$', r' cho \1', text)
    match = re.fullmatch(r'(?:mo|maa|mat|bat|chay|khoi dong|vao|vo|truy cap) (.+)', text)
    if match is None:
        return None
    name = match.group(1).strip()
    name = re.sub(r'^(?:(?:cho|giup) (?:toi|minh) )', '', name)
    for _ in range(3):
        old = name
        name = re.sub(r' (?:giup|cho) (?:toi|minh)$| (?:di|nhe|len|voi|ngay|duoc khong)$',
                      '', name).strip()
        if name == old:
            break
    name = re.sub(r'^(?:phan mem|ung dung|app|game|chuong trinh) ', '', name).strip()
    if not name or re.search(r'\b(?:roi|sau do|va|xoa|gui|tat|dung lai)\b|[\\/:;*?"<>|]', name):
        return None
    return name


def requested_app(question: str, entries: list[dict]) -> dict | None:
    text = normalized(question).strip(' .!?')
    for entry in entries:
        if text in {normalized(phrase).strip(' .!?')
                    for phrase in entry.get('spoken_commands', [])}:
            return entry
    # "Bơ" is ambiguous: only a complete explicit request with an exact known
    # app is accepted. Never use this repair for fuzzy discovery or multi-actions.
    repair = re.fullmatch(r'(?:(?:hay|ban) )?bo (.+?) (?:cho|giup) (?:toi|minh)', text)
    name = launch_name('mo ' + repair.group(1)) if repair else launch_name(question)
    if name is None:
        return None
    for entry in entries:
        if name in [normalized(alias) for alias in [entry['name'], *entry.get('aliases', [])]]:
            return entry
    return None


def _installed_shortcuts() -> tuple[Path, ...]:
    roots = [Path(os.environ[key]) / 'Microsoft/Windows/Start Menu/Programs'
             for key in ('APPDATA', 'PROGRAMDATA') if os.environ.get(key)]
    for key in ('USERPROFILE', 'PUBLIC', 'OneDrive'):
        if os.environ.get(key):
            roots.append(Path(os.environ[key]) / 'Desktop')
    if os.environ.get('APPDATA'):
        roots.append(Path(os.environ['APPDATA']) /
                     'Microsoft/Internet Explorer/Quick Launch/User Pinned/TaskBar')
    return tuple(path for root in roots if root.is_dir() for path in root.rglob('*.lnk'))


def _display_name_matches(asked: str, display_name: str) -> int:
    """Return exact or safe display-name match; never use fuzzy phonetics here."""
    stem = normalized(display_name)
    if re.search(r'\b(?:uninstall|remove|go cai dat|setup|installer|repair|install drivers)\b', stem):
        return 0
    key = re.sub(r'[^a-z0-9]+', ' ', stem).strip()
    asked_key = re.sub(r'[^a-z0-9]+', ' ', asked).strip()
    if key == asked_key:
        return 2
    if not asked_key or not key.startswith(asked_key + ' '):
        return 0
    suffix = key[len(asked_key) + 1:]
    allowed = {'desktop', 'app', 'application', 'english', 'vietnamese',
               'x64', 'x86', '64', '32', 'bit', 'demo', 'demonstration'}
    return 1 if all(part in allowed or re.fullmatch(r'\d{1,4}', part)
                    for part in suffix.split()) else 0


def requested_shortcut(question: str, roots: list[Path] | None = None) -> dict | None:
    """Find one installed shortcut by its display name, without executing dictation."""
    name = launch_name(question)
    if name is None:
        return None
    shortcuts = (_installed_shortcuts() if roots is None else
                 tuple(path for root in roots if root.is_dir() for path in root.rglob('*.lnk')))
    ranked = [(score, path) for path in shortcuts
              if (score := _display_name_matches(name, path.stem))]
    if not ranked:
        return None
    best_score = max(score for score, _ in ranked)
    matches = [path for score, path in ranked if score == best_score]
    # Two distinct display names are ambiguous, so do not guess.
    if len({normalized(path.stem) for path in matches}) != 1:
        return None
    return {'name': matches[0].stem, 'shortcut_path': str(matches[0])}


_APPS_CACHE: tuple[tuple[str, str], ...] = ()
_APPS_CACHE_AT = 0.0
_APPS_CACHE_LOCK = threading.Lock()


def _apps_folder() -> list[tuple[str, str]]:
    """Read Windows' app catalog, refreshing it every two minutes."""
    global _APPS_CACHE, _APPS_CACHE_AT
    with _APPS_CACHE_LOCK:
        if _APPS_CACHE and time.monotonic() - _APPS_CACHE_AT < 120:
            return list(_APPS_CACHE)
        apps = _read_apps_folder()
        if apps:
            _APPS_CACHE = tuple(apps)
            _APPS_CACHE_AT = time.monotonic()
        return apps


def _read_apps_folder() -> list[tuple[str, str]]:
    """Read Windows' registered app names and IDs without launching anything."""
    try:
        import pythoncom
        from win32com.client import Dispatch
        pythoncom.CoInitialize()
        try:
            shell = Dispatch('Shell.Application')
            folder = shell.NameSpace('shell:AppsFolder')
            if folder is None:
                return []
            apps = [(item.Name, item.Path) for item in folder.Items()]
            del folder, shell
            return apps
        finally:
            pythoncom.CoUninitialize()
    except Exception:
        return []


_BLOCKED_EXECUTABLES = {
    'cmd.exe', 'powershell.exe', 'pwsh.exe', 'python.exe', 'pythonw.exe',
    'wscript.exe', 'cscript.exe', 'mshta.exe', 'rundll32.exe',
    'regsvr32.exe', 'bash.exe', 'wt.exe',
}


def _safe_app_id(app_id: str) -> bool:
    """Accept a Windows shell identifier, including IDs containing spaces."""
    if '..' in app_id:
        return False
    if re.fullmatch(r'[A-Za-z0-9_.!{}\- ]+', app_id):
        return app_id not in {'.', '..'}
    match = re.fullmatch(r'\{[A-Fa-f0-9-]{36}\}\\([A-Za-z0-9_. ()+\\-]+\.exe)', app_id)
    if not match:
        return False
    executable = ntpath.basename(match.group(1)).lower()
    return (executable not in _BLOCKED_EXECUTABLES and
            not re.search(r'(?:uninstall|unins\d*|setup|installer|repair)', executable))


def _registered_entry(display: str, target: str) -> dict | None:
    """Windows AppsFolder exposes both shell IDs and direct executable paths."""
    path = Path(target)
    if path.is_absolute():
        if (path.suffix.lower() != '.exe' or not path.is_file() or
                path.name.lower() in _BLOCKED_EXECUTABLES or
                re.search(r'(?i)(?:uninstall|unins\d*|setup|installer|repair)', path.stem)):
            return None
        return {'name': display, 'executable_path': str(path),
                'processes': [path.name.lower()]}
    if _safe_app_id(target):
        if '\\' in target:
            return {'name': display, 'app_id': target,
                    'processes': [ntpath.basename(target).lower()]}
        return {'name': display, 'app_id': target, 'title_contains': display}
    return None


def requested_system_app(question: str, apps: list[tuple[str, str]] | None = None) -> dict | None:
    """Match one launchable Windows app by its registered display name."""
    name = launch_name(question)
    if name is None:
        return None
    ranked = [(score, entry) for display, target in (apps if apps is not None else _apps_folder())
              if (score := _display_name_matches(name, display)) and
              (entry := _registered_entry(display, target)) is not None]
    if not ranked:
        return None
    best = max(score for score, _ in ranked)
    matches = [entry for score, entry in ranked if score == best]
    if len({entry.get('app_id', entry.get('executable_path')) for entry in matches}) != 1:
        return None
    return matches[0]


_APP_PATH_CACHE: tuple[dict, ...] = ()
_APP_PATH_CACHE_AT = 0.0
_APP_PATH_CACHE_LOCK = threading.Lock()


def _app_paths() -> list[dict]:
    """Read registered executable paths without scanning entire drives."""
    global _APP_PATH_CACHE, _APP_PATH_CACHE_AT
    with _APP_PATH_CACHE_LOCK:
        if _APP_PATH_CACHE and time.monotonic() - _APP_PATH_CACHE_AT < 120:
            return [dict(entry) for entry in _APP_PATH_CACHE]
        found: list[dict] = []
        seen: set[str] = set()
        subkey = r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths'
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                try:
                    root = winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ | view)
                except OSError:
                    continue
                with root:
                    for index in range(winreg.QueryInfoKey(root)[0]):
                        name = winreg.EnumKey(root, index)
                        if not name.lower().endswith('.exe'):
                            continue
                        try:
                            with winreg.OpenKey(root, name) as item:
                                raw = winreg.QueryValueEx(item, '')[0]
                        except OSError:
                            continue
                        if not isinstance(raw, str):
                            continue
                        executable = Path(os.path.expandvars(raw.strip('"')))
                        process = executable.name.lower()
                        display = name[:-4]
                        path_text = str(executable).lower()
                        if (executable.suffix.lower() != '.exe' or
                                process in _BLOCKED_EXECUTABLES or
                                normalized(executable.stem) != normalized(display) or
                                re.search(r'(?i)(?:uninstall|unins\d*|setup|installer|repair|'
                                          r'helper|server|proxy|askpass|diagnostic|reporting)', display) or
                                path_text.startswith(
                                    os.environ.get('WINDIR', r'C:\Windows').lower() + '\\') or
                                '\\windowsapps\\' in path_text or not executable.is_file()):
                            continue
                        key = str(executable).lower()
                        if key not in seen:
                            seen.add(key)
                            found.append({'name': display, 'executable_path': str(executable),
                                          'processes': [process]})
        if found:
            _APP_PATH_CACHE = tuple(found)
            _APP_PATH_CACHE_AT = time.monotonic()
        return found


def requested_app_path(question: str, entries: list[dict] | None = None) -> dict | None:
    """Find a single installed app registered in Windows App Paths."""
    name = launch_name(question)
    if name is None:
        return None
    ranked = [(score, entry) for entry in (entries if entries is not None else _app_paths())
              if (score := _display_name_matches(name, entry['name']))]
    if not ranked:
        return None
    best = max(score for score, _ in ranked)
    matches = [entry for score, entry in ranked if score == best]
    return matches[0] if len({entry['executable_path'] for entry in matches}) == 1 else None


@dataclass(frozen=True)
class AppSuggestion:
    entry: dict
    score: float
    automatic: bool


def _phonetic_key(value: str) -> str:
    words = re.sub(r'[^a-z0-9]+', ' ', normalized(value)).split()
    # Real microphone trials on 2026-10-16 transcribed KiCad as "KitKat" twice.
    # Match the whole app name only; do not rewrite "kit" inside other names.
    if ' '.join(words) in {'kitkat', 'kit kat'}:
        return 'kicad'
    # Common Vietnamese transcriptions of English software names.
    words = [{'ghi': 'ki', 'key': 'ki', 'kia': 'ki',
              'card': 'cad', 'cat': 'cad', 'keycard': 'kicad',
              'ra': 'rar'}.get(word, word)
             for word in words]
    return ''.join(words)


def suggest_installed_app(question: str, configured: list[dict],
                          apps: list[tuple[str, str]] | None = None,
                          shortcuts: tuple[Path, ...] | None = None,
                          app_paths: list[dict] | None = None,
                          diagnostics: dict | None = None) -> AppSuggestion | None:
    """Use cautious name similarity only for a complete opening command."""
    asked = launch_name(question) or ''
    if len(_phonetic_key(asked)) < 4:
        return None
    candidates: list[dict] = list(configured)
    candidates.extend(entry for display, target in (apps if apps is not None else _apps_folder())
                      if (entry := _registered_entry(display, target)) is not None and
                      not re.search(r'\b(?:uninstall|remove|setup|installer|repair)\b',
                                    normalized(display)))
    candidates.extend(app_paths if app_paths is not None else _app_paths())
    paths = shortcuts if shortcuts is not None else _installed_shortcuts()
    candidates.extend({'name': path.stem, 'shortcut_path': str(path)} for path in paths
                      if not re.search(r'\b(?:uninstall|remove|setup|installer|repair)\b',
                                       normalized(path.stem)))
    canonical_names = {normalized(entry['name']) for entry in candidates}
    ranked: list[tuple[float, dict]] = []
    seen: set[str] = set()
    asked_key = _phonetic_key(asked)
    for entry in candidates:
        canonical = normalized(entry['name'])
        if canonical in seen:
            continue
        seen.add(canonical)
        variants = [entry['name'], *entry.get('aliases', [])]
        short_name = re.sub(r'(?:\s+\d+(?:\.\d+)*|\s+(?:desktop|app|english|demonstration))+$',
                            '', normalized(entry['name'])).strip()
        # An unversioned registration is the default app; its versioned shortcut
        # must not count as a second, competing application.
        if short_name != canonical and short_name in canonical_names:
            continue
        if short_name:
            variants.append(short_name)
        score = max((SequenceMatcher(None, asked_key, _phonetic_key(value)).ratio()
                     for value in variants if _phonetic_key(value)), default=0.0)
        if score >= 0.64:
            ranked.append((score, entry))
    ranked.sort(key=lambda item: item[0], reverse=True)
    if not ranked:
        return None
    top_score, top_entry = ranked[0]
    second_score = ranked[1][0] if len(ranked) > 1 else 0.0
    if diagnostics is not None:
        diagnostics.update(score=round(top_score, 4), runner_up=round(second_score, 4))
    if top_score < 0.72 or top_score - second_score < 0.10:
        return None
    return AppSuggestion(top_entry, top_score,
                         automatic=top_score >= 0.91 and top_score - second_score >= 0.18)


def _safe_shortcut_target(path: Path) -> tuple[str, bool] | None:
    """Resolve only a normal app shortcut, never a script or shell launcher."""
    try:
        import pythoncom
        from win32com.client import Dispatch
        pythoncom.CoInitialize()
        try:
            shell = Dispatch('WScript.Shell')
            shortcut = shell.CreateShortcut(str(path))
            target = Path(shortcut.TargetPath)
            arguments = shortcut.Arguments.lower()
            del shortcut, shell
        finally:
            pythoncom.CoUninitialize()
    except Exception:
        return None
    if target.suffix.lower() != '.exe' or not target.is_file():
        return None
    process = target.name.lower()
    if process in _BLOCKED_EXECUTABLES or re.search(r'(?i)(?:uninstall|/remove|/repair|/quiet|/silent)', arguments):
        return None
    browser_app = process in {'chrome.exe', 'msedge.exe'} and (
        '--app-id=' in arguments or '--app=' in arguments)
    if process in {'chrome.exe', 'msedge.exe'} and not browser_app:
        return None
    return process, browser_app


KNOWN_WEBSITES: dict[str, tuple[str, str]] = {
    'youtube': ('https://www.youtube.com', 'YouTube'),
    'facebook': ('https://www.facebook.com', 'Facebook'),
    'fb': ('https://www.facebook.com', 'Facebook'),
    'google': ('https://www.google.com', 'Google'),
    'chatgpt': ('https://chatgpt.com', 'ChatGPT'),
    'github': ('https://github.com', 'GitHub'),
    'gmail': ('https://mail.google.com', 'Gmail'),
    'tiktok': ('https://www.tiktok.com', 'TikTok'),
    'tik tok': ('https://www.tiktok.com', 'TikTok'),
    'tic toc': ('https://www.tiktok.com', 'TikTok'),
    'tich toc': ('https://www.tiktok.com', 'TikTok'),
    'tich tac': ('https://www.tiktok.com', 'TikTok'),
    'tuc tac': ('https://www.tiktok.com', 'TikTok'),
    'vnexpress': ('https://vnexpress.net', 'VnExpress'),
    'dan tri': ('https://dantri.com.vn', 'Dân Trí'),
    'dantri': ('https://dantri.com.vn', 'Dân Trí'),
    'reddit': ('https://www.reddit.com', 'Reddit'),
    'wikipedia': ('https://vi.wikipedia.org', 'Wikipedia'),
    'shopee': ('https://shopee.vn', 'Shopee'),
    'lazada': ('https://lazada.vn', 'Lazada'),
    'zalo web': ('https://chat.zalo.me', 'Zalo Web'),
}


def requested_web(question: str, sites: list[dict] | None = None) -> tuple[str, str] | None:
    text = normalized(question).strip(' .!?')
    text = re.sub(r'^(?:hay |ban |hay giup (?:toi|minh) )', '', text)

    search_match = re.fullmatch(r'(?:tim kiem|tra cuu|tim) (.+?)(?: tren (?:mang|web|internet|google))?', text)
    if search_match:
        query = search_match.group(1).strip()
        if query:
            encoded = urllib.parse.quote_plus(query)
            return f'https://www.google.com/search?q={encoded}', 'Tìm kiếm web'

    # Keep this narrow: noisy TikTok dictation must still contain an opening verb.
    if re.fullmatch(r'(?:(?:m|minh|ban|hay) ){0,3}(?:mo|m bo|manh ham) '
                    r'(?:trang web |web )?'
                    r'(?:tik tok|tiktok|tic toc|tich toc|tich tac|tuc tac)'
                    r'(?: (?:tren|o) (?:web|trinh duyet|google))?'
                    r'(?: (?:cho|giup) (?:toi|minh))?', text):
        return KNOWN_WEBSITES['tiktok']

    match = re.fullmatch(r'(?:mo|bat|vao|chay|truy cap) (.+)', text)
    if not match:
        return None
    target = match.group(1).strip()
    target = re.sub(r'^(?:cho|giup) (?:toi|minh) ', '', target)
    target = re.sub(r'(?: (?:giup|cho) (?:toi|minh))?(?: (?:di|nhe|len|voi))?$', '', target).strip()
    target = re.sub(r' (?:tren|trong|o) (?:web|trinh duyet|google)$', '', target).strip()
    if re.search(r'\b(?:roi|sau do|va gui|va xoa|va cai dat)\b', target):
        return None

    is_explicit_web = False
    for prefix in ('trang web ', 'website ', 'web ', 'trang '):
        if target.startswith(prefix):
            target = target[len(prefix):].strip()
            is_explicit_web = True
            break

    for site in sites or []:
        if target in {normalized(alias) for alias in [site['name'], *site.get('aliases', [])]}:
            return site['url'], site['name']

    for site_key, site_val in KNOWN_WEBSITES.items():
        if target == site_key or target.startswith(site_key + ' '):
            return site_val

    url_match = re.search(r'(https?://\S+)', question)
    if url_match:
        url = url_match.group(1).rstrip(' .!?')
        domain = urllib.parse.urlparse(url).netloc or url
        return url, domain

    domain_match = re.search(
        r'\b([a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*\.(?:com\.vn|edu\.vn|gov\.vn|com|vn|net|org|edu|io|gov))(?![\w.-])',
        question)
    if domain_match:
        domain = domain_match.group(1)
        return f'https://{domain}', domain

    return None


@dataclass(frozen=True)
class LaunchResult:
    name: str
    verified: bool
    foreground: bool
    seconds: float
    kind: str = 'app'

    @property
    def message(self) -> str:
        if self.kind == 'minecraft_running':
            return 'Minecraft đã mở rồi.'
        if self.kind == 'minecraft_start':
            return ('Mình đã bấm nút vào game. Minecraft đang khởi động.'
                    if self.verified else
                    'Mình chưa bấm được nút vào game trong TLauncher.')
        if self.kind == 'web':
            return (f'Mình đã gửi địa chỉ {self.name} tới trình duyệt.' if self.verified
                    else f'Mình chưa gửi được địa chỉ {self.name} tới trình duyệt.')
        if not self.verified:
            return f'Mình chưa xác nhận được cửa sổ {self.name} đã mở.'
        if not self.foreground:
            return f'{self.name} đang chạy; bạn có thể chọn ở thanh tác vụ.'
        return f'Mình đã mở {self.name}.'


def _app_window_processes(hwnd: int, window_class: str, user, kernel) -> set[str]:
    """Resolve UWP frame ownership through its child, not the shared frame host."""
    processes: set[str] = set()

    def collect(handle: int) -> None:
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(handle, ctypes.byref(pid))
        process_handle = kernel.OpenProcess(0x1000, False, pid.value)
        if not process_handle:
            return
        try:
            size = wintypes.DWORD(32768)
            path = ctypes.create_unicode_buffer(size.value)
            if kernel.QueryFullProcessImageNameW(process_handle, 0, path, ctypes.byref(size)):
                processes.add(path.value.rsplit('\\', 1)[-1].lower())
        finally:
            kernel.CloseHandle(process_handle)

    collect(hwnd)
    if window_class == 'ApplicationFrameWindow':
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        @callback_type
        def child(handle: int, _: int) -> bool:
            cls = ctypes.create_unicode_buffer(256)
            user.GetClassNameW(handle, cls, len(cls))
            if cls.value == 'Windows.UI.Core.CoreWindow':
                collect(handle)
            return True

        user.EnumChildWindows.argtypes = [wintypes.HWND, callback_type, wintypes.LPARAM]
        user.EnumChildWindows.restype = wintypes.BOOL
        user.EnumChildWindows(hwnd, child, 0)
    return processes


def app_windows(entry: dict) -> list[int]:
    user = ctypes.WinDLL('user32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
        wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.IsWindowVisible.restype = wintypes.BOOL
    handles: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    @callback_type
    def visit(hwnd: int, _: int) -> bool:
        # EnumWindows also includes hidden IME/helper windows owned by the app.
        # Never restore those or treat them as its working window.
        if not user.IsWindowVisible(hwnd) or _window_cloaked(hwnd):
            return True
        title = ctypes.create_unicode_buffer(512)
        user.GetWindowTextW(hwnd, title, len(title))
        if not title.value:
            return True
        cls = ctypes.create_unicode_buffer(256)
        user.GetClassNameW(hwnd, cls, len(cls))
        if any(matches_app_window(entry, title.value, process, cls.value)
               for process in _app_window_processes(hwnd, cls.value, user, kernel)):
            handles.append(hwnd)
        return True
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user.EnumWindows(visit, 0)
    return handles


def matches_app_window(entry: dict, title: str, process: str, window_class: str) -> bool:
    """Ignore installer/error dialogs when verifying a launched app."""
    if window_class in {'IME', 'MSCTFIME UI', 'tooltips_class32'}:
        return False
    if not title or (entry.get('window_classes') and
                     window_class not in entry['window_classes']):
        return False
    if entry.get('title_contains'):
        return (window_class != '#32770' and
                normalized(entry['title_contains']) in normalized(title) and
                (entry.get('browser_app') or process not in {
                    'chrome.exe', 'msedge.exe', 'firefox.exe', 'explorer.exe'}) and
                (not entry.get('processes') or process in entry['processes']))
    return process in entry.get('processes', [])


def _window_cloaked(hwnd: int) -> bool:
    """A cloaked UWP/virtual-desktop surface is not a visible app window."""
    try:
        dwm = ctypes.WinDLL('dwmapi', use_last_error=True)
        dwm.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD,
                                             ctypes.c_void_p, wintypes.DWORD]
        dwm.DwmGetWindowAttribute.restype = ctypes.c_long
        cloaked = wintypes.DWORD()
        result = dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked),
                                         ctypes.sizeof(cloaked))
        return result == 0 and bool(cloaked.value)
    except OSError:
        return False


def focus_window(hwnd: int) -> bool:
    user = ctypes.WinDLL('user32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    user.GetForegroundWindow.restype = wintypes.HWND
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowThreadProcessId.restype = wintypes.DWORD
    kernel.GetCurrentThreadId.restype = wintypes.DWORD
    for name in ('IsWindow', 'IsWindowVisible', 'IsIconic',
                 'SetForegroundWindow', 'BringWindowToTop'):
        function = getattr(user, name)
        function.argtypes = [wintypes.HWND]
        function.restype = wintypes.BOOL
    user.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
    user.ShowWindowAsync.restype = wintypes.BOOL
    user.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    user.AttachThreadInput.restype = wintypes.BOOL
    user.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                 wintypes.UINT, wintypes.UINT, wintypes.UINT]
    user.PeekMessageW.restype = wintypes.BOOL
    if not hwnd or not user.IsWindow(hwnd) or not user.IsWindowVisible(hwnd) or _window_cloaked(hwnd):
        return False
    if user.IsIconic(hwnd):
        user.ShowWindowAsync(hwnd, 9)  # Restore only minimized windows; keep maximized apps maximized.
    if user.GetForegroundWindow() == hwnd and not user.IsIconic(hwnd):
        return True
    user.BringWindowToTop(hwnd)
    user.SetForegroundWindow(hwnd)
    if user.GetForegroundWindow() == hwnd and not user.IsIconic(hwnd):
        return True
    message = wintypes.MSG()
    user.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)
    current = kernel.GetCurrentThreadId()
    threads = {user.GetWindowThreadProcessId(h, None) for h in (user.GetForegroundWindow(), hwnd) if h}
    attached = []
    try:
        for thread in threads:
            if thread and thread != current and user.AttachThreadInput(current, thread, True):
                attached.append(thread)
        user.BringWindowToTop(hwnd)
        user.SetForegroundWindow(hwnd)
        # Keep the temporary input attachment alive until asynchronous activation
        # settles, then always detach. Never use permanent topmost or fake success.
        deadline = time.monotonic() + .4
        while user.GetForegroundWindow() != hwnd and time.monotonic() < deadline:
            time.sleep(.02)
    finally:
        for thread in reversed(attached):
            user.AttachThreadInput(current, thread, False)
    return (user.GetForegroundWindow() == hwnd and bool(user.IsWindowVisible(hwnd))
            and not user.IsIconic(hwnd))


def _short_windows_path(path: Path) -> str:
    """Give older Java a Windows path it can read when folders contain Vietnamese text."""
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetShortPathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    kernel.GetShortPathNameW.restype = wintypes.DWORD
    buffer = ctypes.create_unicode_buffer(32768)
    length = kernel.GetShortPathNameW(str(path), buffer, len(buffer))
    if not length or length >= len(buffer) or not buffer.value.isascii():
        raise OSError(f'Không tạo được đường dẫn ASCII cho Java: {path}')
    return buffer.value


def open_registered_app(entry: dict, cancelled: threading.Event) -> LaunchResult:
    start = time.monotonic()
    if cancelled.is_set():
        return LaunchResult(entry['name'], False, False, 0)
    # The AppID comes from the user's config, never from model output or dictation.
    executable = Path(entry['executable_path']) if entry.get('executable_path') else None
    if executable is not None:
        if executable.suffix.lower() != '.exe' or not executable.is_file():
            return LaunchResult(entry['name'], False, False, time.monotonic() - start)
        arguments = entry.get('arguments', [])
        if not isinstance(arguments, list) or not all(isinstance(arg, str) for arg in arguments):
            raise ValueError('Tham số ứng dụng phải là danh sách chuỗi trong cấu hình.')
        path = None
    elif entry.get('shortcut_name'):
        shortcut = requested_shortcut('Mở ' + entry['shortcut_name'])
        path = Path(shortcut['shortcut_path']) if shortcut else Path('')
        if not shortcut:
            return LaunchResult(entry['name'], False, False, time.monotonic() - start)
    elif entry.get('shortcut_path'):
        path = Path(entry['shortcut_path'])
    else:
        path = None
    if executable is not None:
        launch_target = None
    elif path is not None:
        if path.suffix.lower() != '.lnk' or not path.is_file():
            return LaunchResult(entry['name'], False, False, time.monotonic() - start)
        if entry.get('shortcut_path'):
            resolved = _safe_shortcut_target(path)
            if resolved is None:
                return LaunchResult(entry['name'], False, False, time.monotonic() - start)
            process, browser_app = resolved
            entry = {**entry, 'processes': [process]}
            if browser_app:
                entry.update(browser_app=True, title_contains=entry['name'])
        launch_target = str(path)
    else:
        app_id = entry['app_id']
        if not _safe_app_id(app_id):
            raise ValueError('AppID phải là mã ứng dụng đã đăng ký, không phải lệnh shell.')
        launch_target = 'shell:AppsFolder\\' + app_id
    try:
        if executable is not None:
            # Arguments come only from config; dictation never reaches the process command line.
            command = [str(executable), *arguments]
            working_directory = Path(entry.get('working_directory', executable.parent))
            environment = None
            if entry.get('java_jar_path'):
                jar = Path(entry['java_jar_path'])
                trust_store = Path(entry.get('java_trust_store_path', ''))
                if (executable.name.lower() not in {'java.exe', 'javaw.exe'} or
                        jar.suffix.lower() != '.jar' or not jar.is_file() or
                        not trust_store.is_file()):
                    return LaunchResult(entry['name'], False, False, time.monotonic() - start)
                options = (f'-Djavax.net.ssl.trustStore={_short_windows_path(trust_store)} '
                           '-Djavax.net.ssl.trustStorePassword=changeit '
                           '-Djavax.net.ssl.trustStoreType=JKS')
                command = [str(executable), '-jar', _short_windows_path(jar)]
                inherited = os.environ.get('JAVA_TOOL_OPTIONS', '')
                environment = {**os.environ, 'JAVA_TOOL_OPTIONS':
                               f'{inherited} {options}'.strip()}
            if not working_directory.is_dir():
                return LaunchResult(entry['name'], False, False, time.monotonic() - start)
            subprocess.Popen(command, cwd=str(working_directory), env=environment,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, close_fds=True)
        else:
            os.startfile(launch_target)
    except OSError:
        return LaunchResult(entry['name'], False, False, time.monotonic() - start)
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user.SetForegroundWindow.argtypes = [wintypes.HWND]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.IsIconic.argtypes = [wintypes.HWND]
    user.GetForegroundWindow.restype = wintypes.HWND
    timeout = min(max(float(entry.get('launch_timeout_seconds', 8)), 1), 60)
    focus_deadline = None
    visible_hwnd = None
    while not cancelled.wait(.1) and time.monotonic() - start < timeout:
        for hwnd in app_windows(entry):
            foreground = focus_window(hwnd)
            if user.IsWindowVisible(hwnd) and not user.IsIconic(hwnd):
                if foreground:
                    return LaunchResult(entry['name'], True, True, time.monotonic() - start)
                visible_hwnd = hwnd
                if focus_deadline is None:
                    focus_deadline = time.monotonic() + 1.2
        if focus_deadline is not None and time.monotonic() >= focus_deadline:
            break
    if (not cancelled.is_set() and visible_hwnd and
            user.IsWindowVisible(visible_hwnd) and not user.IsIconic(visible_hwnd)):
        return LaunchResult(entry['name'], True,
                            user.GetForegroundWindow() == visible_hwnd,
                            time.monotonic() - start)
    return LaunchResult(entry['name'], False, False, time.monotonic() - start)


def open_web(url: str, name: str) -> LaunchResult:
    start = time.monotonic()
    try:
        accepted = bool(webbrowser.open(url))
        return LaunchResult(name, accepted, accepted, time.monotonic() - start, 'web')
    except Exception:
        return LaunchResult(name, False, False, time.monotonic() - start, 'web')
