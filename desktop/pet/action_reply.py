"""Gemma may phrase an action result, but cannot change its verified facts."""
from __future__ import annotations

import json
import logging
import re
import threading
import unicodedata
from urllib.parse import urlparse

import httpx

_FILLER = {'minh', 'toi', 'ban', 'nhe', 'nha', 'ne', 'a', 'u', 'um', 'oi',
           'oke', 'ok', 'duoc', 'the', 'vay', 'mot', 'xiu', 'rồi', 'roi'}
_OPTIONAL = {'minh', 'toi', 'ban', 'duoc', 'toi', 'nhe', 'nha', 'ne', 'a', 'u', 'um', 'oi'}
_NEGATIVE = {'chua', 'khong', 'loi', 'that', 'bai'}


def style_action_result(message: str) -> str:
    """Change only unambiguous boilerplate pronouns, never names or paths."""
    fixed = {
        'Bạn muốn mở ứng dụng nào, nói lại giúp mình nhé.':
            'Mày muốn mở ứng dụng nào, nói lại giúp tao nhé.',
        'Bạn muốn mở thư mục nào, nói lại giúp mình nhé.':
            'Mày muốn mở thư mục nào, nói lại giúp tao nhé.',
        'Bạn nói mức nguyên từ 0 đến 100 phần trăm giúp mình nhé.':
            'Mày nói mức nguyên từ 0 đến 100 phần trăm giúp tao nhé.',
        'Đã dừng theo yêu cầu của bạn.': 'Đã dừng theo yêu cầu của mày.',
        'Cửa sổ đã thay đổi; mình chưa chỉnh gì.': 'Cửa sổ đã thay đổi; tao chưa chỉnh gì.',
        'Cửa sổ đã ở trạng thái bạn yêu cầu rồi.': 'Cửa sổ đã ở trạng thái mày yêu cầu rồi.',
        'Cửa sổ đã thay đổi; mình chưa xác nhận được kết quả.':
            'Cửa sổ đã thay đổi; tao chưa xác nhận được kết quả.',
        'Đã gửi lệnh rồi dừng chờ; bạn kiểm tra cửa sổ nhé.':
            'Đã gửi lệnh rồi dừng chờ; mày kiểm tra cửa sổ nhé.',
    }
    if message in fixed:
        return fixed[message]
    message = re.sub(r'^Mình(?=\s)', 'Tao', message)
    message = re.sub(r'^Bạn(?=\s)', 'Mày', message)
    # Exact fixed endings, not substitutions inside application/file names.
    for original, replacement in (
        (' Bạn thử lại nhé.', ' Mày thử lại nhé.'),
        (' Bạn thử lại sau.', ' Mày thử lại sau.'),
        (' đang chạy; bạn có thể chọn ở thanh tác vụ.',
         ' đang chạy; mày có thể chọn ở thanh tác vụ.'),
        (' Bạn kiểm tra kết quả trước khi thử tiếp nhé.',
         ' Mày kiểm tra kết quả trước khi thử tiếp nhé.'),
    ):
        if message.endswith(original):
            message = message[:-len(original)] + replacement
            break
    return message


def _words(value: str) -> list[str]:
    value = unicodedata.normalize('NFD', value.casefold().replace('đ', 'd'))
    value = ''.join(c for c in value if unicodedata.category(c) != 'Mn')
    return re.findall(r'\w+', value, flags=re.UNICODE)


def safe_action_reply(evidence: str, candidate: str) -> bool:
    """Reject replies that introduce claims or drop meaningful result details."""
    if not isinstance(candidate, str) or not candidate.strip() or len(candidate) > 240:
        return False
    if any(c in candidate for c in '\r\n<>`') or re.search(r'https?://', candidate, re.I):
        return False
    # A second sentence or a new clause can add an unsupported outcome.
    if re.search(r'[.!?]\s+[^\W\d_]', candidate, re.UNICODE):
        return False
    if any(p in candidate and p not in evidence for p in ',;:'):
        return False
    source = _words(evidence)
    proposed = _words(candidate)
    if not source or not proposed:
        return False
    source_set, proposed_set = set(source), set(proposed)
    if (source_set - _OPTIONAL) - proposed_set:
        return False
    if proposed_set - source_set - _FILLER:
        return False
    if [w for w in source if w.isdigit()] != [w for w in proposed if w.isdigit()]:
        return False
    if bool('?' in evidence) != bool('?' in candidate):
        return False
    negative = source_set & _NEGATIVE
    if negative != (proposed_set & _NEGATIVE):
        return False
    if any(proposed.count(word) != source.count(word) for word in negative):
        return False
    if negative and ('roi' in proposed_set and 'roi' not in source_set):
        return False
    if negative:
        # Keep the original order of all meaningful words in uncertain/failure
        # results; merely retaining the word "chưa" is not enough.
        required = [word for word in source if word not in _OPTIONAL]
        cursor = iter(proposed)
        if not all(any(word == item for item in cursor) for word in required):
            return False
    # A failed/unknown result must not start with a positive "đã" claim.
    if negative and 'da' in proposed_set:
        first_negative = min(proposed.index(w) for w in negative)
        if proposed.index('da') < first_negative:
            return False
    return True


def phrase_action_result(config: dict, question: str, evidence: str,
                         cancelled: threading.Event) -> str:
    """Use local Gemma without tools; return the original result on any uncertainty."""
    if cancelled.is_set() or not evidence or len(evidence) > 500:
        return evidence
    try:
        parsed = urlparse(str(config.get('base_url', '')))
        valid = parsed.scheme == 'http' and parsed.hostname == '127.0.0.1' and parsed.port
    except ValueError:
        return evidence
    if not valid:
        return evidence
    system = ('Bạn là Alex. Diễn đạt lại kết quả thực tế thành một câu tiếng Việt tự nhiên, '
              'ngắn và thân thiện; xưng tao, gọi người dùng là mày. '
              'Giữ nguyên tên, con số và trạng thái của kết quả. '
              'Không thêm việc đã làm, không tự gọi công cụ. Nếu chưa xác nhận thì nói chưa xác nhận; '
              'nếu chỉ gửi địa chỉ đến trình duyệt thì không nói trang đã mở xong. '
              'Trả lời duy nhất câu đó.')
    payload = {'model': config.get('model', 'alex-gemma'), 'stream': False,
               'temperature': .35, 'max_tokens': 96,
               'chat_template_kwargs': {'enable_thinking': False},
               'messages': [{'role': 'system', 'content': system},
                            {'role': 'user', 'content': json.dumps(
                                {'yeu_cau': question[:300], 'ket_qua': evidence}, ensure_ascii=False)}]}
    try:
        timeout = httpx.Timeout(2.8, connect=.5, read=2.8, write=1, pool=.5)
        with httpx.Client(timeout=timeout, trust_env=False, follow_redirects=False) as client:
            response = client.post(config['base_url'].rstrip('/') + '/v1/chat/completions', json=payload)
            response.raise_for_status()
            choice = response.json()['choices'][0]
            if choice.get('finish_reason') != 'stop':
                return evidence
            candidate = choice['message']['content'].strip()
        if not cancelled.is_set() and safe_action_reply(evidence, candidate):
            return candidate
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, AttributeError):
        logging.info('Gemma action phrasing unavailable; using checked result')
    return evidence
