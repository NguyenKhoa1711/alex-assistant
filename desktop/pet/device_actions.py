"""Explicit Vietnamese laptop volume/brightness commands, handled locally."""
from __future__ import annotations
import re
import time
from .app_actions import Action, folded

_DIGITS = {'khong': 0, 'mot': 1, 'hai': 2, 'ba': 3, 'bon': 4, 'tu': 4,
           'nam': 5, 'lam': 5, 'sau': 6, 'bay': 7, 'tam': 8, 'chin': 9}
_TARGET = (r'(?P<target>am luong|am thanh|tieng loa|loa|volume|'
           r'do sang(?: man hinh)?|anh sang(?: man hinh)?|brightness)'
           r'(?: (?:laptop|may tinh|cua may|cua laptop))?')
_NUMBER = r'(?P<number>-?\d+(?:[.,]\d+)?|(?:khong|mot|hai|ba|bon|tu|nam|lam|sau|bay|tam|chin|muoi|tram|linh|le)(?: (?:khong|mot|hai|ba|bon|tu|nam|lam|sau|bay|tam|chin|muoi|tram|linh|le))*)'
_PERCENT = r'(?:\s*(?:%|phan tram))?'


def percentage(text: str) -> int | None:
    """Read exact integer percentages; do not guess ambiguous or decimal numbers."""
    if re.fullmatch(r'-?\d+', text):
        return int(text)
    if text in _DIGITS:
        return _DIGITS[text]
    if text in ('mot tram', 'tram'):
        return 100
    words = text.split()
    if words and words[0] == 'muoi':
        if len(words) == 1:
            return 10
        if len(words) == 2 and words[1] in _DIGITS:
            return 10 + _DIGITS[words[1]]
    if len(words) in (2, 3) and words[0] in _DIGITS and words[1] == 'muoi':
        tens = _DIGITS[words[0]]
        if 2 <= tens <= 9 and (len(words) == 2 or words[2] in _DIGITS):
            return 10*tens + (_DIGITS[words[2]] if len(words) == 3 else 0)
    return None


def parse_device_action(question: str) -> Action | None:
    text = folded(question.strip(' .!?'))
    prefix = r'(?:(?:alex oi|ban|hay) )?(?:(?:hay|lam on|vui long) )?'
    suffix = r'(?: (?:cho|giup) (?:toi|minh))?(?: (?:di|nhe|voi|mot chut|mot xiu|len|xuong))?'
    def match(pattern): return re.fullmatch(prefix + pattern + suffix, text)
    def app(m):
        return 'Brightness' if any(s in m['target'] for s in ('sang', 'brightness')) else 'Volume'
    def valued(m, operation):
        number = percentage(m['number'])
        if number is None or not 0 <= number <= 100:
            return Action(app(m), 'invalid')
        return Action(app(m), operation, str(number))

    if match(r'(?:tat tieng|tat am|tat loa|tat am thanh|tat am luong|mute)(?: (?:laptop|may tinh))?'):
        return Action('Volume', 'mute')
    if match(r'(?:bat tieng|bat lai tieng|bat am|bat loa|bat am thanh|bo tat tieng|unmute)(?: (?:laptop|may tinh))?'):
        return Action('Volume', 'unmute')
    read = match(_TARGET + r'(?: hien tai)? (?:la )?bao nhieu(?: phan tram)?')
    if read: return Action(app(read), 'read')
    change = match(r'(?P<verb>tang|giam|ha|nang) ' + _TARGET +
                   r'(?: (?P<direction>len|xuong|con|them|bot))?(?: ' + _NUMBER + _PERCENT + r')?')
    if change is None:
        change = match(r'(?P<verb>tang|giam|ha|nang) (?:(?P<direction>len|xuong|con|them|bot) )?' +
                       _NUMBER + _PERCENT + r' (?:cua )?' + _TARGET)
    if change:
        operation = 'up' if change['verb'] in ('tang', 'nang') else 'down'
        if change['number'] is None:
            return Action(app(change), operation, '10')
        if change['direction'] in ('len', 'xuong', 'con'):
            operation = 'set'
        return valued(change, operation)
    absolute = match(r'(?:(?:dat|chinh|dieu chinh|de) )?' + _TARGET +
                     r'(?: (?:o muc|muc|ve|con|la|bang|len|xuong))? ' + _NUMBER + _PERCENT)
    if absolute: return valued(absolute, 'set')
    return None


def execute_device_action(action: Action, backend=None) -> dict:
    """Apply at most one level change, then read back the actual hardware value."""
    label = 'Âm lượng' if action.app == 'Volume' else 'Độ sáng màn hình'
    if action.app not in ('Volume', 'Brightness'):
        raise ValueError('Không phải điều khiển âm lượng hoặc độ sáng.')
    if action.operation == 'invalid':
        return {'message': 'Bạn nói mức nguyên từ 0 đến 100 phần trăm giúp mình nhé.', 'verified': False}
    allowed = {'up', 'down', 'set', 'read'} | ({'mute', 'unmute'} if action.app == 'Volume' else set())
    if action.operation not in allowed:
        raise ValueError('Lệnh điều chỉnh chưa được hỗ trợ.')
    number = None
    if action.operation in ('up', 'down', 'set'):
        if not re.fullmatch(r'\d{1,3}', action.query) or not 0 <= int(action.query) <= 100:
            raise ValueError('Mức điều chỉnh phải từ 0 đến 100 phần trăm.')
        number = int(action.query)
    if backend is None:
        from .windows_controls import WindowsVolume, WindowsBrightness
        backend = WindowsVolume() if action.app == 'Volume' else WindowsBrightness()
    before = backend.current()
    if action.operation == 'read':
        extra = ' và đang tắt tiếng' if before.get('muted') else ''
        return {'message': f'{label} hiện tại là {before["level"]} phần trăm{extra}.', 'verified': True}
    expected_mute = before.get('muted', False)
    target = before['level']
    if action.operation in ('mute', 'unmute'):
        expected_mute = action.operation == 'mute'
        if expected_mute != before.get('muted'):
            backend.set_muted(expected_mute)
    else:
        if action.operation == 'set': target = number
        elif action.operation == 'up': target += number
        else: target -= number
        target = backend.supported_level(max(0, min(100, target)))
        if target != before['level']:
            backend.set_level(target)
        if action.app == 'Volume' and target > 0 and action.operation in ('up', 'set'):
            expected_mute = False
            if before.get('muted'): backend.set_muted(False)
    # Some display drivers commit brightness asynchronously. Never reapply the action.
    for _ in range(8):
        after = backend.current()
        if abs(after['level']-target) <= 1 and after.get('muted', False) == expected_mute:
            if action.operation == 'mute': message = 'Mình đã tắt tiếng loa laptop.'
            elif action.operation == 'unmute': message = f'Mình đã bật tiếng. Âm lượng đang ở {after["level"]} phần trăm.'
            else:
                extra = ' (loa vẫn đang tắt tiếng)' if after.get('muted') else ''
                message = f'{label} đang ở {after["level"]} phần trăm{extra}.'
            return {'message': message, 'verified': True}
        time.sleep(.1)
    return {'message': f'Mình chưa xác nhận được thay đổi {label.lower()}. Bạn kiểm tra cài đặt Windows nhé.', 'verified': False}
