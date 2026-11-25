"""Verified Zalo and Messenger UI drivers backed by agent-desktop and UIA."""
from __future__ import annotations

import ctypes
import logging
import re
import threading
import time
import unicodedata
from typing import Callable
from urllib.parse import urlsplit

from .agent_bridge import AgentBridgeError, AgentDesktopBridge
from .agent_input_observation import InputObservation, observe_inputs, rematch
from .app_actions import folded
from .apps import focus_window, open_web
from .apps import app_windows, requested_app
from .config import load_config
from .desktop_guard import Window, current_window
from .message_flow import MessageResult, send_requested_once
from .message_identity import Candidate, normalized_name
from .message_intent import SendIntent
from .messenger_messages import parse_outgoing_messages
from .screen_context import _binary, _private_directory
from .screen_tools import window_point_is_usable
from .verified_adapter import Conversation, OutgoingMessage, VerifiedMessageAdapter


def _walk_nodes(tree):
    pending = [tree]
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            yield node
            children = node.get('children')
            if isinstance(children, list):
                pending.extend(reversed(children))


def _bind_messenger_composer_identity(snapshot: dict, hwnd: int) -> dict:
    """Add a native UIA identity only for a unique, independently matched composer.

    Agent Desktop does not expose an automation ID for this Chromium edit.
    Bind its observed point to the exact foreground window, process, name and
    a native UIA RuntimeId. Never derive identity from a draft's contents.
    """
    if (not isinstance(snapshot, dict) or snapshot.get('complete') is not True
            or snapshot.get('identity_unproven') or not hwnd):
        return snapshot
    candidates = []
    for node in _walk_nodes(snapshot.get('tree')):
        role = str(node.get('role') or '').casefold()
        label = folded(str(node.get('name') or ''))
        if (role in ('textfield', 'edit', 'textarea', 'textbox')
                and not node.get('identity_unproven') and node.get('ref_id')
                and 'SetFocus' in (node.get('available_actions') or [])
                and any(k in label for k in ('viet cho', 'tin nhan', 'message', 'nhan tin'))
                and not any(k in label for k in ('tim kiem', 'search'))):
            candidates.append(node)
    if len(candidates) != 1 or candidates[0].get('native_id'):
        return snapshot
    node = candidates[0]
    try:
        rect = node.get('bounds') or {}
        x, y, width, height = (rect[k] for k in ('x', 'y', 'width', 'height'))
        if width <= 0 or height <= 0:
            return snapshot
        point = [int(x + width / 2), int(y + height / 2)]
        current = current_window()
        if current.hwnd != hwnd or not window_point_is_usable(hwnd, point):
            return snapshot
        import uiautomation as auto
        native = auto.ControlFromPoint(*point)
        runtime_id = native.GetRuntimeId() or ()
        if (native.ControlTypeName != 'EditControl' or native.ProcessId != current.pid
                or folded(native.Name or '') != folded(str(node.get('name') or ''))
                or not runtime_id or len(runtime_id) > 20
                or any(type(value) is not int for value in runtime_id)):
            return snapshot
        value = '.'.join(str(item) for item in runtime_id)
        if len(value) > 100 or not re.fullmatch(r'[A-Za-z0-9_.:-]+', value):
            return snapshot
        node['native_id'] = {'kind': 'uia_runtime', 'value': value}
    except Exception:
        # Observation is optional; failure never permits typing or sending.
        return snapshot
    return snapshot


def _zalo_search_node(snapshot: dict) -> dict | None:
    hits = []
    for node in _walk_nodes(snapshot.get('tree')):
        native = node.get('native_id') or {}
        if (isinstance(native, dict) and native.get('value') == 'contact-search-input'
                and node.get('ref_id') and 'SetValue' in (node.get('available_actions') or [])):
            hits.append(node)
    return hits[0] if len(hits) == 1 else None


def _browser_toolbar_nodes(tree):
    """Yield browser-chrome toolbar descendants, excluding webpage documents."""
    pending = [(tree, False, False)]
    while pending:
        node, in_toolbar, in_document = pending.pop()
        if not isinstance(node, dict):
            continue
        role = str(node.get('role') or '').casefold()
        in_document = in_document or role in ('document', 'webarea', 'webview')
        in_toolbar = in_toolbar or role == 'toolbar'
        if in_toolbar and not in_document:
            yield node
        children = node.get('children')
        if isinstance(children, list):
            pending.extend((child, in_toolbar, in_document) for child in children)


_MESSENGER_THREAD_RE = re.compile(r'^/(?:messages/)?(?:e2ee/)?t/([A-Za-z0-9._-]{1,120})(?:/|$)')


def _extract_messenger_thread_id(url: str) -> str | None:
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        parsed = urlsplit(url.strip())
    except (TypeError, ValueError):
        return None
    match = _MESSENGER_THREAD_RE.match(parsed.path or '')
    return match.group(1) if match else None


def _node_messenger_thread_id(node: dict) -> str | None:
    for key in ('url', 'href'):
        tid = _extract_messenger_thread_id(node.get(key) or '')
        if tid:
            return tid
    for child in _walk_nodes(node):
        if child is node:
            continue
        if str(child.get('role') or '').casefold() == 'link':
            for key in ('url', 'href'):
                tid = _extract_messenger_thread_id(child.get(key) or '')
                if tid:
                    return tid
    return None


def _document_thread_id(snap: dict) -> str | None:
    ids: set[str] = set()
    for node in _walk_nodes(snap.get('tree')):
        if str(node.get('role') or '').casefold() in ('document', 'webarea', 'webview'):
            tid = _extract_messenger_thread_id(node.get('url') or '')
            if tid:
                ids.add(tid)
    return next(iter(ids)) if len(ids) == 1 else None


def _find_zalo_hwnd() -> int | None:
    """Resolve Zalo from its registered process, never by an arbitrary title."""
    try:
        cfg = load_config()
        entry = requested_app('Mở Zalo', cfg.get('apps', {}).get('entries', []))
        windows = app_windows(entry) if entry else []
        # Multiple matches require the caller to disambiguate; selecting the
        # first matching window can bind a message to the wrong account.
        return int(windows[0]) if len(windows) == 1 and windows[0] else None
    except (OSError, TypeError, ValueError, KeyError):
        return None


_MESSENGER_PROCESSES = (
    'chrome.exe',
    'msedge.exe',
    'firefox.exe',
    'brave.exe',
    'opera.exe',
    'coccoc.exe',
    'messenger.exe',
)


def _find_messenger_hwnd() -> int | None:
    """Resolve Messenger from a registered app entry or known browser/app processes."""
    try:
        cfg = load_config()
        entry = requested_app('Mở Messenger', cfg.get('apps', {}).get('entries', []))
        if not entry:
            entry = {
                'title_contains': 'messenger',
                'browser_app': True,
                'processes': list(_MESSENGER_PROCESSES),
            }
        windows = app_windows(entry)
        # Require a single unambiguous window; never bind to an arbitrary non-browser title.
        return int(windows[0]) if len(windows) == 1 and windows[0] else None
    except (OSError, TypeError, ValueError, KeyError):
        return None


class ZaloUiDriver:
    """Verified UI driver for Zalo desktop using UIA + agent-desktop deep bridge."""

    def __init__(self, cancelled: threading.Event | None = None) -> None:
        self.cancelled = cancelled or threading.Event()
        self.hwnd: int | None = None
        self.window: Window | None = None
        self.bridge: AgentDesktopBridge | None = None
        self._chosen_row_aid: str = ''
        self._chosen_name: str = ''
        self._input_obs: InputObservation | None = None
        self._input_placeholder_name: str = ''
        self._authorized_text: str = ''
        self._authorized_focus_ref: str = ''
        self._authorized_search: tuple[str, str] | None = None
        self._allow_send_key: bool = False
        self._verified_address_value: str = ''
        self._verified_address_url: str = ''

    def close(self) -> None:
        if self.bridge is not None:
            try:
                self.bridge.close()
            except Exception:
                pass
            self.bridge = None

    def _ensure_bridge(self) -> AgentDesktopBridge:
        if self.bridge is not None:
            if self.cancelled.is_set() or current_window() != self.window:
                raise RuntimeError('Cửa sổ Zalo đã thay đổi; dừng thao tác.')
            return self.bridge
        if self.hwnd is None:
            self.hwnd = _find_zalo_hwnd()
        if not self.hwnd:
            raise RuntimeError('Chưa thấy cửa sổ Zalo đang mở.')
        if not focus_window(self.hwnd):
            raise RuntimeError('Không đưa được cửa sổ Zalo lên trước.')
        win = current_window()
        if win.hwnd != self.hwnd:
            raise RuntimeError('Cửa sổ Zalo không ở tiền cảnh.')
        self.window = win
        if self.bridge is None:
            binary = _binary()
            if binary is None:
                raise RuntimeError('Công cụ agent-desktop chưa sẵn sàng.')
            expected_hwnd = self.hwnd
            expected_window = win

            def _same() -> bool:
                return current_window() == expected_window and not self.cancelled.is_set()

            def _authorize(op: str, _ref: str, value: str) -> bool:
                if op == 'type':
                    return bool(self._authorized_text and value == self._authorized_text)
                if op == 'focus_read':
                    return bool(self._authorized_focus_ref and _ref == self._authorized_focus_ref and value == '')
                if op == 'search':
                    return self._authorized_search == (_ref, value)
                if op == 'key':
                    return self._allow_send_key and value == 'Return'
                return op == 'click'

            self.bridge = AgentDesktopBridge(binary, f'w-{expected_hwnd}', _same, _authorize, _private_directory)
        return self.bridge

    def search_contacts(self, name: str) -> tuple[list[Candidate], bool]:
        from app_action_worker import Ui, zalo_contact_name, zalo_find
        bridge = self._ensure_bridge()
        ui = Ui('Zalo', existing_hwnd=self.hwnd)
        search = _zalo_search_node(bridge.snapshot(max_depth=30))
        if search is None:
            return [], False
        identity = (search.get('native_id'), search.get('bounds'))
        self._authorized_search = (search['ref_id'], name)
        try:
            result = bridge.set_value_for_search(search['ref_id'], name)
        finally:
            self._authorized_search = None
        if not result.get('ok'):
            return [], False
        current = _zalo_search_node(bridge.snapshot(max_depth=30))
        if current is None or (current.get('native_id'), current.get('bounds')) != identity:
            return [], False
        observed = bridge.get_value(current['ref_id'])
        value = (observed.get('data') or {}).get('value')
        if (not observed.get('ok') or not isinstance(value, str) or
                unicodedata.normalize('NFC', value) != unicodedata.normalize('NFC', name)):
            return [], False
        candidates: list[Candidate] = []
        previous_sig = None
        complete = False
        for _ in range(12):
            if self.cancelled.is_set():
                return [], False
            time.sleep(0.2)
            area = zalo_find(ui.root, 'searchResultList')
            if area is None:
                continue
            found: list[Candidate] = []
            seen: set[str] = set()
            pending = [(area, 0)]
            visited = 0
            truncated = False
            while pending and visited < 1200:
                row, level = pending.pop()
                visited += 1
                if row.IsOffscreen:
                    continue
                aid = row.AutomationId or ''
                if aid.startswith(('friend-item-', 'group-item-')):
                    if aid not in seen:
                        seen.add(aid)
                        cname = zalo_contact_name(row)
                        if cname:
                            kind = 'group' if aid.startswith('group-item-') else 'person'
                            found.append(Candidate(id=aid, name=cname, kind=kind, can_send=True))
                    continue
                if seen and row.ControlTypeName == 'TextControl' and re.fullmatch(
                        r'(?:tin nhan|messages)(?: ?\(.*\))?', folded(row.Name or '')):
                    pending.clear()
                    break
                children = row.GetChildren()
                if children and level >= 24:
                    truncated = True
                    break
                pending.extend((child, level + 1) for child in reversed(children))
            if truncated or pending:
                previous_sig = None
                continue
            sig = tuple((c.id, c.name) for c in found)
            candidates = found
            if sig == previous_sig:
                complete = True
                break
            previous_sig = sig
        current = _zalo_search_node(bridge.snapshot(max_depth=30))
        if current is None or (current.get('native_id'), current.get('bounds')) != identity:
            return [], False
        observed = bridge.get_value(current['ref_id'])
        value = (observed.get('data') or {}).get('value')
        if (not observed.get('ok') or not isinstance(value, str) or
                unicodedata.normalize('NFC', value) != unicodedata.normalize('NFC', name)):
            return [], False
        return candidates, complete

    def open_contact(self, contact_id: str) -> None:
        from app_action_worker import Ui, zalo_contact_name, zalo_find
        self._ensure_bridge()
        ui = Ui('Zalo', existing_hwnd=self.hwnd)
        row = zalo_find(ui.root, contact_id)
        if row is None:
            raise RuntimeError('Không tìm thấy mục liên hệ để mở.')
        self._chosen_row_aid = contact_id
        self._chosen_name = zalo_contact_name(row)
        row.SetFocus()
        time.sleep(0.05)
        try:
            row.GetInvokePattern().Invoke()
        except Exception:
            row.Click(simulateMove=False)
        time.sleep(0.3)

    def current_conversation(self) -> Conversation | None:
        from app_action_worker import Ui, texts, zalo_find
        if not self.hwnd or current_window().hwnd != self.hwnd:
            return None
        ui = Ui('Zalo', existing_hwnd=self.hwnd)
        header = zalo_find(ui.root, 'chatViewContainer')
        if header is None:
            return None
        title = ''
        for t in texts(header, 6):
            if any(ch.isalnum() for ch in t):
                title = t
                break
        if not title:
            return None
        return Conversation(service='Zalo', id=self._chosen_row_aid, name=title, foreground=True)

    def _locate_rich_input(self, bridge: AgentDesktopBridge) -> InputObservation | None:
        data = bridge.snapshot(max_depth=30)
        def rich_nodes(snapshot):
            return [n for n in _walk_nodes(snapshot.get('tree'))
                    if n.get('role') == 'group' and isinstance(n.get('native_id'), dict)
                    and n['native_id'].get('value') == 'richInput' and n.get('ref_id')]
        nodes = rich_nodes(data)
        if len(nodes) != 1:
            return None
        node = nodes[0]
        def observed(snapshot, field):
            hits = [o for o in observe_inputs(snapshot) if o.ref == field.get('ref_id')]
            return hits[0] if len(hits) == 1 else None
        result = observed(data, node)
        if result is not None:
            return result
        bounds = node.get('bounds') or {}
        try:
            x = int(bounds['x'] + bounds['width'] / 2)
            y = int(bounds['y'] + bounds['height'] / 2)
            if bounds['width'] <= 0 or bounds['height'] <= 0 or not window_point_is_usable(self.hwnd, [x, y]):
                return None
        except (KeyError, TypeError, ValueError, OverflowError):
            return None
        if 'SetFocus' not in (node.get('available_actions') or []):
            return None
        identity = (node['native_id'].get('kind'), node['native_id'].get('value'), dict(bounds))
        ref = node['ref_id']
        self._authorized_focus_ref = ref
        try:
            focused = bridge.focus_for_observation(ref)
        finally:
            self._authorized_focus_ref = ''
        disposition = (focused.get('data') or {}).get('disposition') or {}
        if not focused.get('ok') or disposition.get('delivery') not in ('delivered_verified', 'delivered_unverified'):
            return None
        fresh = bridge.snapshot(max_depth=30)
        newer = rich_nodes(fresh)
        if len(newer) != 1:
            return None
        new_node = newer[0]
        if (new_node['native_id'].get('kind'), new_node['native_id'].get('value'), new_node.get('bounds')) != identity:
            return None
        if not window_point_is_usable(self.hwnd, [x, y]):
            return None
        # Some providers report an unverified focus delivery even when the
        # focus landed. Independently check the newly observed exact ref;
        # never replay the focus action when its result is uncertain.
        if not bridge.is_focused(new_node['ref_id']):
            return None
        return observed(fresh, new_node)

    def read_draft(self) -> str | None:
        bridge = self._ensure_bridge()
        obs = self._locate_rich_input(bridge)
        if obs is None:
            return None
        self._input_obs = obs
        reply = bridge.get_value(obs.ref)
        if not reply.get('ok'):
            return None
        val = (reply.get('data') or {}).get('value')
        if not isinstance(val, str):
            return None
        return val

    def type_literal(self, value: str) -> None:
        bridge = self._ensure_bridge()
        if self._input_obs is None:
            obs = self._locate_rich_input(bridge)
            if obs is None:
                raise AgentBridgeError('Không xác định được ô nhập Zalo.')
            self._input_obs = obs
        self._authorized_text = value
        focused = bridge.focus_for_type(self._input_obs.ref, value)
        disp = (focused.get('data') or {}).get('disposition') or {}
        if not focused.get('ok') or disp.get('delivery') != 'delivered_verified':
            raise AgentBridgeError('Không chọn được ô nhập Zalo.')
        fresh = bridge.snapshot(max_depth=30)
        matched = rematch(self._input_obs, fresh)
        if matched is None:
            raise AgentBridgeError('Ô nhập Zalo đã thay đổi vị trí hoặc định danh.')
        self._input_obs = matched
        res = bridge.act('type', matched.ref, text=value)
        if not res.get('ok'):
            raise AgentBridgeError('Không nhập được nội dung vào Zalo.')

    def outgoing_messages(self) -> list[OutgoingMessage] | None:
        # A UI label or ephemeral agent ref is not evidence that the current
        # account sent a new message. Stop before typing/submitting until the
        # provider exposes verified stable IDs, author, and delivery status.
        return None

    def submit_once(self, expected: Conversation, expected_text: str) -> None:
        bridge = self._ensure_bridge()
        if self.current_conversation() != expected:
            raise AgentBridgeError('Cuộc trò chuyện Zalo đã thay đổi trước khi gửi.')
        if self.read_draft() != expected_text:
            raise AgentBridgeError('Nội dung bản nháp không khớp trước khi gửi.')
        if self._input_obs is None or not bridge.is_focused(self._input_obs.ref):
            raise AgentBridgeError('Ô nhập Zalo không còn focus trước khi gửi.')
        self._allow_send_key = True
        try:
            res = bridge.press_key('Return')
            if not res.get('ok'):
                raise AgentBridgeError('Không xác nhận được thao tác bấm gửi.')
        finally:
            self._allow_send_key = False
        time.sleep(0.4)


class MessengerUiDriver:
    """Verified UI driver for Messenger web in browser via agent-desktop."""

    def __init__(self, cancelled: threading.Event | None = None) -> None:
        self.cancelled = cancelled or threading.Event()
        self.hwnd: int | None = None
        self.bridge: AgentDesktopBridge | None = None
        self._chosen_id: str = ''
        self._chosen_name: str = ''
        self._ref_by_candidate_id: dict[str, str] = {}
        self._input_obs: InputObservation | None = None
        self._authorized_text: str = ''
        self._allow_send_key: bool = False
        self._allow_escape_key: bool = False
        self._verified_address_value: str = ''
        self._verified_address_url: str = ''

    def close(self) -> None:
        if self.bridge is not None:
            try:
                self.bridge.close()
            except Exception:
                pass
            self.bridge = None

    def _ensure_bridge(self) -> AgentDesktopBridge:
        if self.hwnd is None:
            self.hwnd = _find_messenger_hwnd()
            if self.hwnd is None:
                open_web('https://www.messenger.com', 'Messenger')
                for _ in range(15):
                    if self.cancelled.is_set():
                        break
                    time.sleep(0.4)
                    self.hwnd = _find_messenger_hwnd()
                    if self.hwnd:
                        break
        if not self.hwnd:
            raise RuntimeError('Chưa thấy cửa sổ Messenger đang mở.')
        if not focus_window(self.hwnd):
            raise RuntimeError('Không đưa được cửa sổ Messenger lên trước.')
        win = current_window()
        if win.hwnd != self.hwnd:
            raise RuntimeError('Cửa sổ Messenger không ở tiền cảnh.')
        if self.bridge is None:
            binary = _binary()
            if binary is None:
                raise RuntimeError('Công cụ agent-desktop chưa sẵn sàng.')
            expected_hwnd = self.hwnd

            def _same() -> bool:
                return current_window().hwnd == expected_hwnd and not self.cancelled.is_set()

            def _authorize(op: str, _ref: str, value: str) -> bool:
                if op == 'type':
                    return bool(self._authorized_text and value == self._authorized_text)
                if op == 'key':
                    return (self._allow_send_key and value == 'Return') or (
                        self._allow_escape_key and value in ('Escape', 'F6')
                    )
                return op == 'click'

            self.bridge = AgentDesktopBridge(binary, f'w-{expected_hwnd}', _same, _authorize, _private_directory)
        return self.bridge

    def search_contacts(self, name: str) -> tuple[list[Candidate], bool]:
        bridge = self._ensure_bridge()
        data = bridge.snapshot(max_depth=30)
        if data.get('complete') is not True:
            return [], False
        addr_ref = self._find_address_bar_ref(data)
        if addr_ref and self._address_focused_state(addr_ref) is True:
            self._allow_escape_key = True
            try:
                bridge.press_key('Escape')
                bridge.press_key('F6')
            finally:
                self._allow_escape_key = False
            time.sleep(0.15)
            data = bridge.snapshot(max_depth=30)
            if data.get('complete') is not True:
                return [], False
        data = self._verify_messenger_surface(data)
        search_ref = ''
        for node in _walk_nodes(data.get('tree')):
            role = str(node.get('role') or '').casefold()
            label = folded(str(node.get('name') or ''))
            if role in ('searchfield', 'edit', 'textfield', 'combobox') and (
                    'messenger' in label or 'tim kiem' in label or 'search' in label):
                ref = node.get('ref_id')
                if isinstance(ref, str) and ref:
                    search_ref = ref
                    break
        if not search_ref:
            return [], False
        self._authorized_text = name
        bridge.focus_for_type(search_ref, name)
        fresh = bridge.snapshot(max_depth=30)
        fresh = self._verify_messenger_surface(fresh)
        # Re-find search ref after focus
        search_ref = ''
        for node in _walk_nodes(fresh.get('tree')):
            role = str(node.get('role') or '').casefold()
            label = folded(str(node.get('name') or ''))
            if role in ('searchfield', 'edit', 'textfield', 'combobox') and (
                    'messenger' in label or 'tim kiem' in label or 'search' in label):
                search_ref = node.get('ref_id') or ''
                break
        if not search_ref:
            return [], False
        bridge.act('type', search_ref, text=name)
        time.sleep(0.8)
        results_snap = bridge.snapshot(max_depth=30)
        if results_snap.get('complete') is not True:
            return [], False
        results_snap = self._verify_messenger_surface(results_snap)
        candidates: list[Candidate] = []
        seen_ids: set[str] = set()
        self._ref_by_candidate_id = {}
        for node in _walk_nodes(results_snap.get('tree')):
            role = str(node.get('role') or '').casefold()
            label = str(node.get('name') or '').strip()
            ref = node.get('ref_id') or ''
            if not label or not ref or role not in ('link', 'listitem', 'option', 'button', 'row'):
                continue
            if normalized_name(label) != normalized_name(name):
                continue
            thread_id = _node_messenger_thread_id(node)
            if thread_id:
                candidate_id = f'messenger:thread:{thread_id}'
            else:
                native = node.get('native_id')
                if isinstance(native, dict) and native.get('kind') and native.get('value'):
                    candidate_id = f"messenger:node:{native['kind']}:{native['value']}"
                else:
                    continue
            if candidate_id not in seen_ids:
                seen_ids.add(candidate_id)
                self._ref_by_candidate_id[candidate_id] = ref
                candidates.append(Candidate(id=candidate_id, name=label, kind='person', can_send=True))
        return candidates, True

    @staticmethod
    def _is_trusted_messenger_url(url: str) -> bool:
        try:
            if not isinstance(url, str) or any(ord(c) < 32 or c == '\\' for c in url):
                return False
            parsed = urlsplit(url.strip())
            host = (parsed.hostname or '').casefold()
            if (parsed.scheme.casefold() != 'https' or parsed.username is not None
                    or parsed.password is not None or parsed.port not in (None, 443)):
                return False
            if host in ('messenger.com', 'www.messenger.com'):
                return True
            return (host in ('facebook.com', 'www.facebook.com') and
                    (parsed.path == '/messages' or parsed.path.startswith('/messages/')))
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _find_address_bar_ref(snap: dict) -> str:
        hits = []
        for node in _browser_toolbar_nodes(snap.get('tree')):
            role = str(node.get('role') or '').casefold()
            name = str(node.get('name') or '').casefold()
            y = (node.get('bounds') or {}).get('y', 99999)
            if (role in ('edit', 'combobox', 'textbox', 'textfield') and y < 200 and node.get('ref_id')
                    and name in ('address and search bar', 'address bar', 'thanh địa chỉ và tìm kiếm', 'thanh địa chỉ')):
                hits.append(node['ref_id'])
        return hits[0] if len(hits) == 1 else ''

    @staticmethod
    def _find_site_info_ref(snap: dict) -> str:
        hits = []
        for node in _browser_toolbar_nodes(snap.get('tree')):
            role = str(node.get('role') or '').casefold()
            name = str(node.get('name') or '').casefold()
            y = (node.get('bounds') or {}).get('y', 99999)
            if (role == 'button' and y < 200 and node.get('ref_id')
                    and any(k in name for k in ('site information', 'site info', 'thông tin trang', 'thong tin trang'))):
                hits.append(node['ref_id'])
        return hits[0] if len(hits) == 1 else ''

    def _address_focused_state(self, ref: str) -> bool | None:
        """An editable address is not proof of the page currently loaded."""
        if not self.bridge or ref not in self.bridge.refs or not self.bridge.identity_ok():
            return None
        reply = self.bridge._call(['is', ref, '--property', 'focused'])
        data = reply.get('data') or {}
        if not reply.get('ok') or data.get('applicable') is not True or type(data.get('result')) is not bool:
            return None
        return data['result']

    @staticmethod
    def _owned_popup(hwnd: int, owner: int) -> bool:
        from ctypes import wintypes
        api = ctypes.WinDLL('user32')
        api.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        api.GetWindow.restype = wintypes.HWND
        return bool(hwnd and owner and int(api.GetWindow(hwnd, 4) or 0) == owner)

    @staticmethod
    def _read_security_popup_is_https(browser_hwnd: int, browser_pid: int) -> bool:
        import uiautomation as auto
        from ctypes import wintypes

        popup_win = current_window()
        if not popup_win.hwnd or popup_win.hwnd == browser_hwnd or popup_win.pid != browser_pid:
            return False
        api = ctypes.WinDLL('user32')
        api.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        api.GetWindow.restype = wintypes.HWND
        owner = int(api.GetWindow(popup_win.hwnd, 4) or 0)  # GW_OWNER
        if owner != browser_hwnd:
            return False
        popup = auto.ControlFromHandle(popup_win.hwnd)
        secure_count = 0
        not_secure_count = 0
        pending = [(popup, 0)]
        visited = 0
        while pending and visited < 500:
            node, depth = pending.pop()
            visited += 1
            label = str(node.Name or '').casefold()
            if any(x in label for x in ('not secure', 'connection is not secure', 'không an toàn')):
                not_secure_count += 1
            elif any(x in label for x in ('connection is secure', 'kết nối an toàn', 'kết nối của bạn là an toàn')):
                secure_count += 1
            if depth < 10:
                pending.extend((child, depth + 1) for child in node.GetChildren())
        return secure_count == 1 and not_secure_count == 0

    def _verify_browser_address_and_security(self, snap: dict) -> dict:
        if self.bridge is None or not self.hwnd:
            raise RuntimeError('Chưa xác minh được địa chỉ của tab Messenger.')
        addr_ref = self._find_address_bar_ref(snap)
        if not addr_ref:
            raise RuntimeError('Chưa xác minh được địa chỉ của tab Messenger.')
        addr_focused = self._address_focused_state(addr_ref)
        if addr_focused is not False:
            raise RuntimeError(f'Thanh địa chỉ đang được nhập hoặc chưa xác định được trạng thái (focused={addr_focused}).')
        res = self.bridge.get_value(addr_ref)
        val = (res.get('data') or {}).get('value') if res.get('ok') else None
        if not isinstance(val, str) or not val.strip():
            raise RuntimeError('Chưa xác minh được địa chỉ của tab Messenger.')
        val = val.strip()
        if '://' in val:
            if not self._is_trusted_messenger_url(val):
                raise RuntimeError('Tab hiện tại không phải trang Messenger đã được xác minh.')
            self._verified_address_value = val
            self._verified_address_url = val
            return snap
        candidate_url = f'https://{val}'
        if not self._is_trusted_messenger_url(candidate_url):
            raise RuntimeError('Tab hiện tại không phải trang Messenger đã được xác minh.')
        site_btn = self._find_site_info_ref(snap)
        if not site_btn:
            raise RuntimeError('Chưa xác minh được kết nối HTTPS của tab Messenger.')
        original = current_window()
        if not original.hwnd or original.hwnd != self.hwnd:
            raise RuntimeError('Cửa sổ Messenger không ở tiền cảnh.')
        popup_hwnd = 0
        try:
            clicked = self.bridge.act('click', site_btn)
            if not clicked.get('ok'):
                raise RuntimeError('Chưa mở được thông tin bảo mật của tab Messenger.')
            popup_hwnd = current_window().hwnd
            for _ in range(10):
                if popup_hwnd and popup_hwnd != self.hwnd:
                    break
                time.sleep(0.05)
                popup_hwnd = current_window().hwnd
            if not self._read_security_popup_is_https(self.hwnd, original.pid):
                raise RuntimeError('Chưa xác minh được kết nối HTTPS an toàn của tab Messenger.')
        finally:
            now = current_window()
            if (popup_hwnd and now.hwnd == popup_hwnd and now.pid == original.pid
                    and self._owned_popup(popup_hwnd, self.hwnd)):
                focus_window(self.hwnd)
        if current_window().hwnd != self.hwnd:
            raise RuntimeError('Cửa sổ Messenger không ở tiền cảnh sau khi kiểm tra bảo mật.')
        after_snap = self.bridge.snapshot(max_depth=30)
        after_ref = self._find_address_bar_ref(after_snap)
        if not after_ref:
            raise RuntimeError('Chưa xác minh được lại thanh địa chỉ Messenger.')
        if self._address_focused_state(after_ref) is not False:
            raise RuntimeError('Thanh địa chỉ đã thay đổi trạng thái khi kiểm tra.')
        after_res = self.bridge.get_value(after_ref)
        after_val = (after_res.get('data') or {}).get('value') if after_res.get('ok') else None
        if not isinstance(after_val, str) or after_val.strip() != val:
            raise RuntimeError('Địa chỉ tab Messenger đã thay đổi trong lúc kiểm tra.')
        self._verified_address_value = val
        self._verified_address_url = candidate_url
        return after_snap

    def _verify_messenger_surface(self, snap: dict) -> dict:
        """Require an authoritative document URL or verified Chrome address bar + HTTPS popup."""
        urls = [n.get('url').strip() for n in _walk_nodes(snap.get('tree'))
                if str(n.get('role') or '').casefold() in ('document', 'webarea', 'webview')
                and isinstance(n.get('url'), str) and n.get('url').strip()]
        if not urls:
            return self._verify_browser_address_and_security(snap)
        for url in urls:
            if not self._is_trusted_messenger_url(url):
                raise RuntimeError('Tab hiện tại không phải trang Messenger đã được xác minh.')
        self._verified_address_url = urls[0]
        return snap

    def open_contact(self, contact_id: str) -> None:
        bridge = self._ensure_bridge()
        snap = bridge.snapshot(max_depth=30)
        snap = self._verify_messenger_surface(snap)
        target_ref = self._ref_by_candidate_id.get(contact_id, '')
        chosen_name = ''
        found_ref = ''
        for node in _walk_nodes(snap.get('tree')):
            node_ref = node.get('ref_id') or ''
            node_tid = _node_messenger_thread_id(node)
            native = node.get('native_id')
            node_nid = (
                f"messenger:node:{native['kind']}:{native['value']}"
                if isinstance(native, dict) and native.get('kind') and native.get('value')
                else ''
            )
            matches_id = (
                (contact_id == f'messenger:thread:{node_tid}' if node_tid else False)
                or (contact_id == node_nid if node_nid else False)
                or (bool(target_ref) and node_ref == target_ref)
            )
            if matches_id and node_ref:
                chosen_name = str(node.get('name') or '').strip()
                found_ref = node_ref
                break
        if not found_ref or not chosen_name:
            raise AgentBridgeError('Không xác nhận được đúng liên hệ Messenger để mở.')
        self._chosen_id = contact_id
        self._chosen_name = chosen_name
        bridge.act('click', found_ref)
        time.sleep(0.5)

    def current_conversation(self) -> Conversation | None:
        if not self.hwnd or current_window().hwnd != self.hwnd or not self._chosen_name:
            return None
        bridge = self._ensure_bridge()
        data = bridge.snapshot(max_depth=30)
        data = self._verify_messenger_surface(data)
        doc_thread = _document_thread_id(data) or _extract_messenger_thread_id(self._verified_address_url)
        main_nodes = [n for n in _walk_nodes(data.get('tree')) if str(n.get('role') or '').casefold() == 'main']
        scope_roots = main_nodes if main_nodes else [data.get('tree')]
        matches = []
        for root in scope_roots:
            for node in _walk_nodes(root):
                role = str(node.get('role') or '').casefold()
                label = str(node.get('name') or '').strip()
                if role == 'heading' and normalized_name(label) == normalized_name(self._chosen_name):
                    if doc_thread:
                        stable_id = f'messenger:thread:{doc_thread}'
                    else:
                        native = node.get('native_id') or {}
                        stable_id = (
                            f"messenger:heading:{native.get('kind')}:{native.get('value')}"
                            if isinstance(native, dict) and native.get('value')
                            else ''
                        )
                    if stable_id:
                        matches.append(Conversation(service='Messenger', id=stable_id, name=label, foreground=True))
        return matches[0] if len(matches) == 1 else None

    def _locate_compose_input(self, bridge: AgentDesktopBridge) -> InputObservation | None:
        data = bridge.snapshot(max_depth=30)
        data = self._verify_messenger_surface(data)
        data = _bind_messenger_composer_identity(data, self.hwnd)
        obs_list = observe_inputs(data, include_standard_roles=True)
        main_nodes = [n for n in _walk_nodes(data.get('tree')) if str(n.get('role') or '').casefold() == 'main']
        scope_roots = main_nodes if main_nodes else [data.get('tree')]
        compose_hits = []
        seen_refs: set[str] = set()
        for root in scope_roots:
            for node in _walk_nodes(root):
                role = str(node.get('role') or '').casefold()
                if role == 'searchfield':
                    continue
                label = folded(str(node.get('name') or ''))
                if any(bad in label for bad in ('tim kiem', 'search')):
                    continue
                if any(k in label for k in ('viet cho', 'tin nhan', 'message', 'nhan tin')):
                    ref = node.get('ref_id')
                    if ref and ref not in seen_refs:
                        for obs in obs_list:
                            if obs.ref == ref:
                                seen_refs.add(ref)
                                compose_hits.append(obs)
        if len(compose_hits) == 1:
            return compose_hits[0]
        return None

    def read_draft(self) -> str | None:
        bridge = self._ensure_bridge()
        obs = self._locate_compose_input(bridge)
        if obs is None:
            return None
        self._input_obs = obs
        reply = bridge.get_value(obs.ref)
        if not reply.get('ok'):
            return None
        val = (reply.get('data') or {}).get('value')
        return val if isinstance(val, str) else None

    def type_literal(self, value: str) -> None:
        bridge = self._ensure_bridge()
        if self._input_obs is None:
            obs = self._locate_compose_input(bridge)
            if obs is None:
                raise AgentBridgeError('Không xác định được ô nhập Messenger.')
            self._input_obs = obs
        self._authorized_text = value
        focused = bridge.focus_for_type(self._input_obs.ref, value)
        disp = (focused.get('data') or {}).get('disposition') or {}
        if not focused.get('ok') or disp.get('delivery') != 'delivered_verified':
            raise AgentBridgeError('Không chọn được ô nhập Messenger.')
        fresh = bridge.snapshot(max_depth=30)
        fresh = _bind_messenger_composer_identity(fresh, self.hwnd)
        matched = rematch(self._input_obs, fresh, include_standard_roles=True)
        if matched is None:
            raise AgentBridgeError('Ô nhập Messenger đã thay đổi vị trí hoặc định danh.')
        self._input_obs = matched
        res = bridge.act('type', matched.ref, text=value)
        if not res.get('ok'):
            raise AgentBridgeError('Không nhập được nội dung vào Messenger.')

    def outgoing_messages(self) -> list[OutgoingMessage] | None:
        bridge = self._ensure_bridge()
        data = bridge.snapshot(max_depth=30)
        if data.get('complete') is not True:
            return None
        try:
            data = self._verify_messenger_surface(data)
        except RuntimeError:
            # An unverified browser origin cannot establish a baseline.  Let
            # the adapter stop before touching the draft rather than report a
            # generic error or treating messages from another tab as evidence.
            return None
        return parse_outgoing_messages(data.get('tree'))

    def submit_once(self, expected: Conversation, expected_text: str) -> None:
        bridge = self._ensure_bridge()
        if self.current_conversation() != expected:
            raise AgentBridgeError('Cuộc trò chuyện Messenger đã thay đổi trước khi gửi.')
        if self.read_draft() != expected_text:
            raise AgentBridgeError('Nội dung bản nháp Messenger không khớp trước khi gửi.')
        if self._input_obs is None or not bridge.is_focused(self._input_obs.ref):
            raise AgentBridgeError('Ô nhập Messenger không còn focus trước khi gửi.')
        self._allow_send_key = True
        try:
            res = bridge.press_key('Return')
            if not res.get('ok'):
                raise AgentBridgeError('Không xác nhận được thao tác bấm gửi.')
        finally:
            self._allow_send_key = False
        time.sleep(0.4)


def format_message_result(intent: SendIntent, result: MessageResult) -> str:
    """Format an honest Vietnamese status message without inventing unverified claims."""
    messages = {
        'sent': f'Tao đã gửi tin nhắn cho {intent.recipient} trên {intent.service}.',
        'send_unverified': (
            f'Tao đã bấm gửi cho {intent.recipient} trên {intent.service}, '
            f'nhưng chưa đọc lại được để xác nhận tin đã đi. Mày kiểm tra lại trên {intent.service}, đừng gửi lại kẻo trùng.'
        ),
        'recipient_not_unique': (
            f'Tao chưa tìm thấy duy nhất một người tên {intent.recipient} trên {intent.service} '
            '(có thể không thấy hoặc bị trùng tên). Mày nói rõ tên hơn nhé.'
        ),
        'recipient_unverified': (
            f'Tao chưa xác nhận đã mở đúng cuộc trò chuyện với {intent.recipient} trên {intent.service}, nên chưa nhập tin.'
        ),
        'verification_unavailable': (
            f'Tao chưa kiểm chứng được tin gửi trên {intent.service}, nên chưa soạn hoặc gửi. '
            'Phần này đang được hoàn thiện.'
        ),
        'draft_unverified': (
            f'Tao chưa gửi được vì không kiểm chứng được ô soạn hoặc nội dung trên {intent.service}. '
            'Có thể vẫn còn chữ nháp; mày kiểm tra ô soạn nhé.'
        ),
        'changed_before_send': (
            f'Cửa sổ hoặc nội dung trên {intent.service} vừa thay đổi trước lúc gửi, nên tao đã dừng lại.'
        ),
        'cancelled': 'Tao đã dừng gửi tin theo yêu cầu.',
        'cancelled_draft': (
            f'Tao đã dừng trước khi bấm gửi trên {intent.service}, nhưng chữ nháp có thể vẫn còn trong ô soạn.'
        ),
        'not_sent_draft_may_remain': (
            f'Tao chưa gửi tin trên {intent.service}, nhưng có thể vẫn còn chữ nháp trong ô soạn. Mày kiểm tra lại nhé.'
        ),
        'not_sent': (
            f'Tao chưa gửi được tin nhắn trên {intent.service}. Mày kiểm tra ứng dụng đã mở và đăng nhập chưa nhé.'
        ),
    }
    return messages.get(result.status, f'Chưa xác nhận được trạng thái gửi tin trên {intent.service}.')


def execute_send_message(
    intent: SendIntent,
    cancelled: threading.Event,
    *,
    driver_factory: Callable[[str, threading.Event], object] | None = None,
) -> tuple[MessageResult, str]:
    """Run the verified single-shot messaging flow and return (MessageResult, Vietnamese reply)."""
    if driver_factory is not None:
        driver = driver_factory(intent.service, cancelled)
    elif intent.service == 'Zalo':
        driver = ZaloUiDriver(cancelled)
    else:
        driver = MessengerUiDriver(cancelled)
    try:
        adapter = VerifiedMessageAdapter(intent.service, driver)
        result = send_requested_once(intent, adapter, cancelled.is_set)
        logging.info('MESSAGING service=%s status=%s sent=%s', intent.service, result.status, result.sent)
        return result, format_message_result(intent, result)
    finally:
        close_fn = getattr(driver, 'close', None)
        if callable(close_fn):
            try:
                close_fn()
            except Exception:
                pass
