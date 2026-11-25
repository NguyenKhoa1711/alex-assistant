"""Dispatch a pre-approved UI step through agent-desktop, preserving DesktopGuard."""
from __future__ import annotations
import logging
import re
from .agent_bridge import AgentBridgeError, AgentDesktopBridge, AgentTargetMissing, unique_ref_for_point
from .app_actions import folded
from .desktop_guard import current_window
from .screen_context import _binary, _private_directory


def is_eligible(name, args, enabled, target_line='', executable=''):
    # These remain on the existing guarded backend until there is a dedicated
    # verified workflow for clearing an existing field or submitting a form.
    if not enabled or name not in ('Click', 'Type'):
        return False
    if name == 'Type' and (args.get('clear') or args.get('press_enter')):
        return False
    if name == 'Type' and re.search(r'\)\s+(?:document|combobox)\s+"',target_line,re.I):
        # agent-desktop's ref matcher/UIA SetFocus does not reliably focus
        # RichEdit Document or Chromium combobox controls. Select the existing
        # guarded input backend BEFORE attempting anything; never fall back.
        return False
    if name == 'Type' and executable.casefold() in ('chrome', 'msedge', 'brave', 'opera', 'browser', 'coccoc'):
        # Chromium web inputs require a real click+type rather than UIA SetFocus;
        # select the existing guarded input backend BEFORE attempting anything.
        return False
    # agent-desktop click is one semantic left-click; preserve the existing
    # backend for right-clicks, double-clicks and other click options.
    if name == 'Click' and (args.get('button', 'left') != 'left' or args.get('clicks', 1) != 1):
        return False
    if name == 'Click' and re.search(
            r'\b(?:send|gui|submit|publish|dang|buy|mua|pay|thanh toan|delete|remove|xoa|'
            r'run|execute|chay|install|cai dat|uninstall|go cai dat|dong y|cho phep|'
            r'accept|allow|yes|ok|confirm|xac nhan)\b', folded(target_line)):
        return False
    return True


def is_simple_type_request(question):
    key = folded(question).strip(' .!?…')
    # Opening an app first does not authorize clearing a draft. Recognize the
    # same explicit typing clause, then require the real field to be EMPTY in
    # run_agent_step before converting clear=True into a non-clearing insert.
    for separator in re.finditer(r'\s+(?:roi|sau do|xong roi)\s+', key):
        head, tail = key[:separator.start()], key[separator.end():]
        if (len(head) <= 120 and not re.search(r'\b(?:khong|dung|roi|va|gui|xoa|nhap|go|dien)\b', head)
                and re.fullmatch(r'(?:(?:may|ban|alex|hay|vui long|lam on)\s+)*'
                                 r'(?:mo|bat|chay)\s+[^,;\r\n"“”]+', head)):
            key = tail
            break
    return bool(re.fullmatch(
        r'(?:(?:may|ban|alex|hay|vui long|lam on)\s+)*'
        r'(?:nhap|go|dien)\s+(?:(?:chu|noi dung|van ban)\s+)?'
        r'.+?\s+(?:vao|trong)\s+(?:o|khung)\s+(?:van ban|nhap lieu|soan thao)'
        r'(?:\s+(?:tren|o)\s+man hinh)?(?:\s+(?:cho|giup)\s+(?:tao|toi|minh|tui))?'
        r'(?:\s+(?:di|nhe|nha|voi))?', key))


def should_require_empty(name, args, enabled, goal):
    return bool(enabled and name == 'Type' and args.get('clear') in (True, 'true')
                and not args.get('press_enter') and is_simple_type_request(goal))


def dispatched_step_key(name, window, args, target_line):
    """Private, in-memory identity used to prevent replay within one plan."""
    point = args.get('loc')
    if not isinstance(point, list) or len(point) != 2 or not all(isinstance(x, int) for x in point):
        raise AgentBridgeError('Vị trí thao tác không hợp lệ.')
    text = args.get('text', '') if name == 'Type' else ''
    match = re.search(r'\)\s+([\w /-]+)\s+"([^"\n]*)"', target_line)
    if not match:
        raise AgentBridgeError('Chưa xác định được nhãn đích thao tác.')
    stable_target = (match.group(1).casefold(), match.group(2).casefold())
    return (name, window.hwnd, tuple(point), hash(stable_target), hash(text))


def run_agent_step(guard, window, name, args, *, require_empty=False, bridge_type=AgentDesktopBridge):
    guard._agent_phase = 'preflight'
    if name not in ('Click', 'Type') or current_window() != window:
        raise AgentBridgeError('Cửa sổ hoặc thao tác không còn hợp lệ.')
    if name == 'Type' and (args.get('press_enter') or args.get('clear')):
        # Enter may send a message, and clear could overwrite a draft. Neither
        # is implicitly authorized by a request to type text.
        raise AgentBridgeError('Chưa hỗ trợ xóa nội dung cũ hoặc gửi Enter qua bước này.')
    binary = _binary()
    if binary is None:
        raise AgentBridgeError('Công cụ agent-desktop chưa sẵn sàng.')
    point = args.get('loc')
    line = guard._target_line(point)
    operation = name.casefold()
    text = args.get('text', '') if name == 'Type' else ''
    if not isinstance(text, str):
        raise AgentBridgeError('Nội dung nhập không hợp lệ.')
    # The existing DesktopGuard has already approved this exact step. Do not
    # expose this helper to a model or fall back to an unguarded input method.
    guard._agent_phase = 'session'
    with bridge_type(binary, f'w-{window.hwnd}', lambda: current_window() == window,
                     lambda op, ref, value: op == operation and value == text,
                     _private_directory) as bridge:
        depth = 10
        guard._agent_phase = 'snapshot'
        snapshot = bridge.snapshot()
        guard._agent_phase = 'target'
        try:
            ref = unique_ref_for_point(snapshot, point, line, operation)
        except AgentTargetMissing:
            # Some Chromium applications nest controls beyond the normal
            # snapshot depth. Retry only the read, never an action; preserve
            # exact window, role, name and bounds checks.
            depth = 30
            snapshot = bridge.snapshot(max_depth=depth)
            ref = unique_ref_for_point(snapshot, point, line, operation)
        if name == 'Type':
            guard._agent_phase = 'focus'
            already_focused = bool(hasattr(bridge, 'is_focused') and bridge.is_focused(ref))
            if not already_focused:
                focused = bridge.focus_for_type(ref, text)
                disposition = (focused.get('data') or {}).get('disposition') or {}
                verified = bool(focused.get('ok') and disposition.get('delivery') == 'delivered_verified')
                if not verified and hasattr(bridge, 'is_focused'):
                    verified = bool(bridge.is_focused(ref))
                if not verified:
                    err_code = (focused.get('error') or {}).get('code') if isinstance(focused.get('error'), dict) else ''
                    logging.warning('AGENT_FOCUS_FAIL ok=%s delivery=%s err=%s',
                                    focused.get('ok'), disposition.get('delivery'), err_code)
                    raise AgentBridgeError('Chưa xác định được ô nhập có được chọn; không nhập.')
                # Focus can change the accessibility tree and invalidate references.
                # Re-resolve the same guarded field before reading or typing.
                snapshot = bridge.snapshot(max_depth=depth) if depth != 10 else bridge.snapshot()
                ref = unique_ref_for_point(snapshot, point, line, operation)
        if require_empty:
            guard._agent_phase = 'empty_check'
            readback = bridge.get_value(ref)
            if not readback.get('ok') or (readback.get('data') or {}).get('value') != '':
                raise AgentBridgeError('Ô nhập chưa trống hoặc không đọc được; không ghi đè.')
        guard._agent_phase = 'input'
        result = bridge.act(operation, ref, text=text)
        delivery = (result.get('data') or {}).get('disposition', {}).get('delivery')
        if not result.get('ok') or delivery not in ('delivered_verified', 'delivered_unverified'):
            raise AgentBridgeError('Chưa xác định được kết quả thao tác; không tự lặp lại.')
        scope = (result.get('data') or {}).get('details', {}).get('verification_scope')
        return {'delivery': delivery,
                'element_value_verified': name == 'Type' and delivery == 'delivered_verified' and scope == 'element_value',
                'instruction': 'Tool status only, not text shown on screen. Observe the UI before reporting the outcome.'}
