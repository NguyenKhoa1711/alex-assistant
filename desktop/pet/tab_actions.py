"""Close one observed tab while keeping its browser window open."""
from __future__ import annotations
from pathlib import Path
import time
from .app_actions import ActionResult, folded

BROWSERS = {'chrome.exe':'chrome', 'msedge.exe':'edge', 'firefox.exe':'firefox', 'browser.exe':'coc coc'}


def window_identity(window):
    return (window.hwnd, window.pid, window.executable.casefold())


def prepare_tab_close(requested: str):
    from .desktop_guard import current_window
    window = current_window()
    executable = Path(window.executable).name.casefold()
    app = BROWSERS.get(executable)
    # Cốc Cốc shares browser.exe with other programs; require its install path.
    if app == 'coc coc' and 'coccoc' not in window.executable.casefold():
        app = None
    if requested and requested != app:
        # Typed requests leave Bionic in front. Resolve an explicitly named
        # browser without sending shortcuts to the chat or guessing a window.
        from .apps import app_windows
        from .window_actions import Windows
        processes=[exe for exe,name in BROWSERS.items() if name==requested]
        api=Windows()
        candidates=[]
        for hwnd in app_windows({'processes':processes}):
            identity=api.identity(hwnd)
            if not identity or identity[3]=='#32770':continue
            if requested=='coc coc' and 'coccoc' not in identity[2]:continue
            candidates.append(identity)
        if len(candidates)!=1:
            return ActionResult('Trình duyệt có nhiều cửa sổ hoặc chưa mở. Bạn đưa cửa sổ cần đóng tab lên trước rồi nói “Đóng tab” qua mic Alex nhé.')
        hwnd,pid,executable,_=candidates[0]
        return {'app':requested,'hwnd':hwnd,'pid':pid,'executable':executable,'require_foreground':False}
    if not app:
        return ActionResult('Bạn đưa tab cần đóng lên trước trong Chrome, Edge, Firefox hoặc Cốc Cốc rồi nói lại nhé.')
    return {'app':app, 'hwnd':window.hwnd, 'pid':window.pid, 'executable':window.executable}


def chrome_tabs(root):
    """Only native tab strips, not tab widgets inside websites or side panels."""
    stack=[(root,0)]; strips=[]; seen=0; started=time.monotonic()
    while stack and seen<1500 and time.monotonic()-started<3:
        control,depth=stack.pop(); seen+=1
        typ=control.ControlTypeName
        if typ=='DocumentControl' or control.IsOffscreen:
            continue
        if typ=='TabControl':
            tabs=[c for c in control.GetChildren() if c.ControlTypeName=='TabItemControl']
            if tabs: strips.append(tabs)
            continue
        if depth<16:
            stack.extend((c,depth+1) for c in control.GetChildren())
    # More than one native strip can be an app panel; do not guess.
    if len(strips)!=1:
        raise RuntimeError('Chưa xác định được duy nhất một thanh tab; mình chưa đóng gì.')
    return strips[0]


def runtime_id(control):
    return tuple(control.GetRuntimeId())


def selected_tab(tabs):
    selected=[c for c in tabs if c.GetSelectionItemPattern().IsSelected]
    if len(selected)!=1:
        raise RuntimeError('Chưa xác định được tab đang chọn; mình chưa đóng gì.')
    return selected[0]


def close_browser_tab(auto, target: dict | None) -> dict:
    from .desktop_guard import current_window
    if not target or target.get('app') not in set(BROWSERS.values()):
        raise ValueError('Thiếu cửa sổ trình duyệt cần đóng tab.')
    expected=(target['hwnd'],target['pid'],target['executable'].casefold())
    def check_window():
        if target.get('require_foreground',True):
            identity=window_identity(current_window())
        else:
            from .window_actions import Windows
            api=Windows();value=api.identity(target['hwnd'])
            identity=value[:3] if value and api.visible(target['hwnd']) and api.enabled(target['hwnd']) else None
        if identity != expected:
            raise RuntimeError('Cửa sổ đang dùng đã đổi; mình chưa đóng thêm tab nào.')
    check_window()
    root=auto.ControlFromHandle(target['hwnd'])
    before=chrome_tabs(root)
    # Closing the last tab also closes the browser. Only an explicit window
    # command may do that; keep this guard before any accessibility action.
    if len(before) <= 1:
        return {'message':'Đây là tab cuối, mình giữ lại để trình duyệt không tắt. Bạn nói “Đóng phần mềm hiện tại” nếu muốn đóng cả cửa sổ.', 'verified':False}
    selected=selected_tab(before); identity=runtime_id(selected)
    before_ids={runtime_id(c) for c in before}
    buttons=[c for c in selected.GetChildren() if c.ControlTypeName=='ButtonControl'
             and folded(c.Name) in {'close','close tab','dong','dong tab','dong the'}
             and c.IsEnabled and not c.IsOffscreen]
    if len(buttons)!=1:
        return {'message':'Chưa tìm thấy đúng nút đóng của tab đang chọn; mình chưa đóng gì.', 'verified':False}
    check_window()
    fresh=chrome_tabs(root)
    if {runtime_id(c) for c in fresh}!=before_ids or runtime_id(selected_tab(fresh))!=identity:
        return {'message':'Tab vừa thay đổi; bạn chọn lại tab rồi nói nhé.', 'verified':False}
    check_window()
    # Resolve a supported accessibility pattern before invoking, not after an
    # ambiguous exception (which could otherwise close a second tab).
    button=buttons[0]
    try:
        pattern=button.GetInvokePattern()
    except (AttributeError,LookupError):
        pattern=None
    if pattern is not None:
        invoke=pattern.Invoke
    else:
        legacy=button.GetLegacyIAccessiblePattern()
        if not legacy or not legacy.DefaultAction:
            return {'message':'Trình duyệt chưa cung cấp thao tác đóng tab này.', 'verified':False}
        invoke=legacy.DoDefaultAction
    # Invoke once. Even an accessibility event error may mean the click succeeded.
    try:
        invoke()
    except Exception:
        pass
    for _ in range(12):
        time.sleep(.15)
        try:
            after_ids={runtime_id(c) for c in chrome_tabs(root)}
            if after_ids==before_ids-{identity}:
                return {'message':'Mình đã đóng tab hiện tại.', 'verified':True}
        except Exception:
            continue
    return {'message':'Mình đã thử đóng một tab nhưng chưa xác nhận được kết quả. Nếu có hộp hỏi lưu dữ liệu, bạn xử lý trên màn hình nhé.', 'verified':False}



