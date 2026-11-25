"""Bound the local model's screen tools and compact snapshots, never the guard."""
from __future__ import annotations
import json
import re
from .app_actions import folded


def snapshot_excerpt(raw: str, limit: int = 2400) -> tuple[str, str]:
    try:
        outer=json.loads(raw)
        if outer.get('is_error'):
            return '', 'Chưa đọc được giao diện để thao tác.'
        value=outer.get('result','')
        try:
            inner=json.loads(value)
            if isinstance(inner,list) and len(inner)==1 and isinstance(inner[0],str):
                value=inner[0]
        except (ValueError,TypeError):
            pass
        if not isinstance(value,str):return '', 'Dữ liệu giao diện không hợp lệ.'
        lines=value.splitlines()
        idx=next((i for i,line in enumerate(lines) if 'UI Tree:' in line),None)
        if idx is None:return '', 'Giao diện chưa cung cấp cây điều khiển.'
        selected=[];used=0;window_indent=None;inside_window=False
        for line in lines[idx:]:
            root_window=re.match(r'^(\s*)(?:├──|└──)\s+window\s+"',line)
            if root_window and not inside_window:
                window_indent=len(root_window.group(1));inside_window=True
            elif inside_window and re.match(r'^\s{0,'+str(window_indent)+r'}(?:├──|└──)\s+',line):
                break  # Do not expose taskbar or other top-level windows as targets.
            if used+len(line)+1>limit:break
            selected.append(line);used+=len(line)+1
        if not any('[action:' in line for line in selected):
            return '', 'Chưa thấy nút hoặc mục có thể thao tác trên cửa sổ.'
        return '\n'.join(selected), ''
    except (ValueError,TypeError,AttributeError):
        return '', 'Dữ liệu giao diện không hợp lệ.'


def screen_tools(all_tools: list[dict], question: str) -> list[dict]:
    """Describe only approved UI tools; server still validates the full request."""
    available={item.get('function',{}).get('name') for item in all_tools if isinstance(item,dict)}
    position={'type':'array','items':{'type':'integer'},'minItems':2,'maxItems':2}
    key=folded(question)
    button='right' if re.search(r'\b(?:chuot phai|bam phai|click phai)\b',key) else 'left'
    clicks=2 if re.search(r'\b(?:nhap dup|bam dup|click dup|double click)\b',key) else 1
    definitions=[
        ('Snapshot','Read the current UI tree. Call after clicking before Finish.',{},[]),
        ('Click','Click the exact loc [x,y] of the intended element from the newest UI tree.',
         {'loc':position,'button':{'type':'string','enum':[button]},
          'clicks':{'type':'integer','enum':[clicks]}},['loc']),
        ('Finish','After Snapshot, evidence is a SHORT exact label from the latest UI tree (at most 80 characters), never the entire tree or the Click result.',
         {'evidence':{'type':'string','maxLength':80}},['evidence']),
        ('Cancel','Stop if the target or outcome is unclear.',{},[]),
    ]
    raw_question=question.casefold()
    if (re.search(r'\b(?:nhập|điền|gõ)\b',raw_question)
            or re.search(r'\b(?:nhap|dien|go)\s+(?:chu|noi dung|van ban|text)\b',folded(question))):
        definitions.append(('Type','Type only the exact text requested at a loc from the newest UI tree.',
            {'text':{'type':'string'},'loc':position,'clear':{'type':'boolean'},
             'press_enter':{'type':'boolean'}},['text','loc']))
    tools=[]
    for name,description,properties,required in definitions:
        if name not in available:continue
        parameters={'type':'object','properties':properties,'additionalProperties':False}
        if required:parameters['required']=required
        tools.append({'type':'function','function':{'name':name,'description':description,
                                                     'parameters':parameters}})
    return tools


def validate_screen_tool(name: str, args: dict, question: str) -> str:
    if not isinstance(args,dict):return 'Tham số thao tác không hợp lệ.'
    allowed={item['function']['name'] for item in screen_tools(
        [{'function':{'name':n}} for n in ('Snapshot','Click','Type','Finish','Cancel')], question)}
    if name not in allowed:return 'Công cụ không thuộc yêu cầu trên màn hình.'
    if name=='Type':
        text=args.get('text')
        if not isinstance(text,str) or not text or text.casefold() not in question.casefold():
            return 'Chỉ nhập nguyên văn nội dung người dùng đã yêu cầu.'
    if name=='Click':
        schema=next(tool['function']['parameters']['properties'] for tool in screen_tools(
            [{'function':{'name':'Click'}}],question))
        if args.get('button','left') not in schema['button']['enum']:
            return 'Kiểu nút chuột không khớp yêu cầu.'
        if args.get('clicks',1) not in schema['clicks']['enum']:
            return 'Số lần bấm không khớp yêu cầu.'
    return ''


def search_focus_hint(question: str, excerpt: str) -> str:
    """Guide a single search-box focus when the user did not request a query."""
    if not is_search_focus_request(question): return ""
    matches=[]
    for line in excerpt.splitlines():
        if not re.search(r'\b(?:combo box|edit|text field|search box) "(?:Tìm kiếm|Search)"',line,re.I):
            continue
        if '[value:' in line and not re.search(r'\[value:""\]',line):
            continue
        if re.search(r'\(-?\d+,-?\d+\)',line): matches.append(line.strip())
    # An edit nested in an identically named combo box is the input itself.
    edits=[line for line in matches if re.search(r'\b(?:edit|text field|search box) "',line,re.I)]
    if len(edits)==1: matches=edits
    if len(matches)!=1:return ""
    return ("Yêu cầu chỉ mở ô tìm kiếm trống, không nhập hay gửi tìm kiếm. "
            "Bấm MỘT lần đúng ô này, rồi Snapshot và Finish; không bấm thêm nút khác: " + matches[0])


def search_focus_target(hint: str):
    match = re.search(r'\((-?\d+),(-?\d+)\).*?"(Tìm kiếm|Search)"', hint, re.I)
    if not match:return None
    return [int(match.group(1)),int(match.group(2))],match.group(3)


def focused_search_is_verified(pid: int, label: str) -> bool:
    """Read only focus metadata, never the field value."""
    try:
        import uiautomation as automation
        with automation.UIAutomationInitializerInThread():
            control=automation.GetFocusedControl()
            return (bool(control.HasKeyboardFocus) and control.ProcessId == pid
                    and control.ControlTypeName in ('EditControl','ComboBoxControl')
                    and control.Name.casefold() == label.casefold())
    except Exception:
        return False


def is_search_focus_request(question: str) -> bool:
    key=folded(question)
    return bool(re.search(r"\b(?:bam|nhan|nhap|click|mo)\b", key)
        and re.search(r"\b(?:nut|o|thanh)\s+(?:nhap\s+)?tim kiem\b",key)
        and not re.search(r"\b(?:giong noi|bang giong|bang tieng|tu khoa|noi dung|tim kiem ve)\b",key)
        and not re.search(r"\btim kiem cho\s+(?!toi\b|tao\b|minh\b|tui\b|em\b|anh\b|ban\b|may\b)",key))


def target_is_in_excerpt(loc, excerpt: str) -> bool:
    if not isinstance(loc,list) or len(loc)!=2 or any(type(n) is not int for n in loc):return False
    point=f'({loc[0]},{loc[1]})'
    return any(point in line and '[action:' in line for line in excerpt.splitlines())


def excerpt_matches_window(excerpt: str, screen_text: str) -> bool:
    first=screen_text.splitlines()[0] if screen_text else ''
    if not first.startswith('Cửa sổ: '):return False
    title=first[len('Cửa sổ: '):]
    return bool(title and any(re.match(r'^\s*(?:├──|└──)\s+window\s+',line)
                              and ('"'+title+'"') in line for line in excerpt.splitlines()))


def named_click_locations(target: str, excerpt: str) -> list[list[int]]:
    """Return unique coordinates only for visible clickable labels containing the requested name."""
    name=folded(target).strip()
    if not name:return []
    found=[]
    for line in excerpt.splitlines():
        match=re.search(r'\((-?\d+),(-?\d+)\)\s+(?:button|link|menu item|tab item)\s+"([^"]+)".*\[action:\s*click\]',line,re.I)
        if not match:continue
        label=folded(match.group(3))
        if not re.search(r'(?<!\w)'+re.escape(name)+r'(?!\w)',label):continue
        loc=[int(match.group(1)),int(match.group(2))]
        if loc not in found:found.append(loc)
    return found


def named_click_label(target: str, excerpt: str) -> str:
    locations = named_click_locations(target, excerpt)
    if len(locations) != 1:
        return ''
    point = f'({locations[0][0]},{locations[0][1]})'
    for line in excerpt.splitlines():
        if point not in line:
            continue
        match = re.search(r'\((-?\d+),(-?\d+)\)\s+(?:button|link|menu item|tab item)\s+"([^"]+)".*\[action:\s*click\]', line, re.I)
        if match and re.search(r'(?<!\w)' + re.escape(folded(target)) + r'(?!\w)', folded(match.group(3))):
            return match.group(3)
    return ''


def window_point_is_usable(hwnd: int, loc) -> bool:
    """Reject targets outside or covered by a different top-level window."""
    if not isinstance(loc,list) or len(loc)!=2 or any(type(n) is not int for n in loc):return False
    try:
        import ctypes
        from ctypes import wintypes
        user=ctypes.WinDLL('user32',use_last_error=True)
        # The MCP returns physical pixels; use the same DPI coordinates in this thread.
        set_dpi=user.SetThreadDpiAwarenessContext
        set_dpi.argtypes=[ctypes.c_void_p];set_dpi.restype=ctypes.c_void_p
        previous=set_dpi(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
        if not previous:return False
        try:
            user.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
            user.GetWindowRect.restype=wintypes.BOOL
            user.WindowFromPoint.argtypes=[wintypes.POINT]
            user.WindowFromPoint.restype=wintypes.HWND
            user.GetAncestor.argtypes=[wintypes.HWND,wintypes.UINT]
            user.GetAncestor.restype=wintypes.HWND
            rect=wintypes.RECT()
            if not user.GetWindowRect(hwnd,ctypes.byref(rect)):return False
            x,y=loc
            if not (rect.left<=x<rect.right and rect.top<=y<rect.bottom):return False
            hit=user.WindowFromPoint(wintypes.POINT(x,y))
            return bool(hit and int(user.GetAncestor(hit,2) or 0)==int(hwnd))
        finally:
            set_dpi(previous)
    except (OSError,TypeError,ValueError,AttributeError):
        return False


def prioritize_named_excerpt(target: str, compact: str, extended: str) -> str:
    """Retain a requested control beyond the short model context, without other page text."""
    locations=named_click_locations(target, extended)
    if len(locations)!=1 or named_click_locations(target,compact):return compact
    point=f'({locations[0][0]},{locations[0][1]})'
    line=next((line for line in extended.splitlines() if point in line and '[action:' in line), '')
    return compact+'\n'+line if line else compact


def window_caption(hwnd: int) -> str:
    try:
        import ctypes
        from ctypes import wintypes
        user=ctypes.WinDLL('user32',use_last_error=True)
        user.GetWindowTextW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
        user.GetWindowTextW.restype=ctypes.c_int
        text=ctypes.create_unicode_buffer(512)
        user.GetWindowTextW(hwnd,text,len(text))
        return text.value
    except (OSError,TypeError,ValueError,AttributeError):
        return ''
