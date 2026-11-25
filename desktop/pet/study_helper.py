"""Region/foreground screen capture + Groq Vision multi-key rotating solver (~1-2s, free tier)."""
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import logging
import os
import re
import ssl
import subprocess
import tempfile
import threading
from pathlib import Path
import httpx
import truststore
from PySide6.QtCore import QBuffer, QIODevice, QPoint, QRect, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QGuiApplication, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget

_GROQ_CRED_TARGET = 'Alex Groq API Keys'
_GROQ_ENDPOINT = 'https://api.groq.com/openai/v1/chat/completions'
_GROQ_MODELS = ('openai/gpt-oss-120b', 'qwen/qwen3.8-27b')
_GROQ_KEY_LOCK = threading.Lock()
_GROQ_KEY_INDEX = 0

_GEMINI_STUDY_CRED_TARGET = 'Alex Gemini Study Keys'
_GEMINI_MODELS = ('gemini-3-flash-preview', 'gemini-3.5-flash-lite', 'gemini-flash-latest')
_GEMINI_KEY_LOCK = threading.Lock()
_GEMINI_KEY_INDEX = 0
_KEY_COOLDOWN_UNTIL: dict[str, float] = {}

_OCR_PS1 = r"""param([string]$ImagePath)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[void][Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime]
[void][Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType=WindowsRuntime]
[void][Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
[void][Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
[void][Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType=WindowsRuntime]

$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]

function Await-WinRT($WinRtTask, $ResultType) {
    $netTask = $asTaskGeneric.MakeGenericMethod($ResultType).Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    return $netTask.Result
}

$file = Await-WinRT ([Windows.Storage.StorageFile]::GetFileFromPathAsync($ImagePath)) ([Windows.Storage.StorageFile])
$stream = Await-WinRT ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await-WinRT ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await-WinRT ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) {
    $lang = New-Object Windows.Globalization.Language("en-US")
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
}
$ocrResult = Await-WinRT ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Write-Output $ocrResult.Text
"""


def parse_api_keys(raw_text: str) -> list[str]:
    """Parse one or more API keys separated by newlines, commas, or spaces."""
    keys: list[str] = []
    for part in re.split(r'[\s,;]+', (raw_text or '').strip()):
        k = part.strip()
        if k and k not in keys:
            keys.append(k)
    return keys


def save_groq_keys(raw_text: str) -> list[str]:
    keys = parse_api_keys(raw_text)
    if not keys:
        raise ValueError('Chưa có Groq API key hợp lệ.')
    if os.name != 'nt':
        raise RuntimeError('Chỉ hỗ trợ lưu khóa trong Windows Credential Manager.')
    import win32cred
    blob = '\n'.join(keys)
    win32cred.CredWrite({
        'Type': win32cred.CRED_TYPE_GENERIC,
        'TargetName': _GROQ_CRED_TARGET,
        'UserName': 'Alex',
        'CredentialBlob': blob,
        'Persist': win32cred.CRED_PERSIST_LOCAL_MACHINE,
    }, 0)
    return keys


def load_groq_keys() -> list[str]:
    if os.name != 'nt':
        return []
    try:
        import win32cred
        cred = win32cred.CredRead(_GROQ_CRED_TARGET, win32cred.CRED_TYPE_GENERIC, 0)
        blob = cred.get('CredentialBlob', b'')
        raw = blob.decode('utf-16-le').rstrip('\x00') if isinstance(blob, bytes) else str(blob)
        return parse_api_keys(raw)
    except Exception:
        return []


def save_gemini_study_keys(raw_text: str) -> list[str]:
    keys = parse_api_keys(raw_text)
    if not keys:
        raise ValueError('Chưa có Gemini API key hợp lệ.')
    if os.name != 'nt':
        raise RuntimeError('Chỉ hỗ trợ lưu khóa trong Windows Credential Manager.')
    import win32cred
    win32cred.CredWrite({
        'Type': win32cred.CRED_TYPE_GENERIC,
        'TargetName': _GEMINI_STUDY_CRED_TARGET,
        'UserName': 'Alex',
        'CredentialBlob': '\n'.join(keys),
        'Persist': win32cred.CRED_PERSIST_LOCAL_MACHINE,
    }, 0)
    return keys


def load_gemini_study_keys() -> list[str]:
    if os.name != 'nt':
        return []
    keys: list[str] = []
    try:
        import win32cred
        cred = win32cred.CredRead(_GEMINI_STUDY_CRED_TARGET, win32cred.CRED_TYPE_GENERIC, 0)
        blob = cred.get('CredentialBlob', b'')
        raw = blob.decode('utf-16-le').rstrip('\x00') if isinstance(blob, bytes) else str(blob)
        keys = parse_api_keys(raw)
    except Exception:
        keys = []
    if not keys:
        try:
            from .gemini import _read_api_key
            single = _read_api_key().strip()
            if single:
                keys = [single]
        except Exception:
            pass
    valid_keys = [k for k in keys if k.startswith(('AIza', 'AQ.'))]
    return valid_keys if valid_keys else keys


class RegionSnipOverlay(QWidget):
    """Full-screen translucent overlay for drag-selecting a problem region or pressing F/Enter for full screen."""

    captured = Signal(QPixmap)
    cancelled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setCursor(Qt.CursorShape.CrossCursor)
        screen = QGuiApplication.primaryScreen()
        self._screen_geo = screen.geometry() if screen else QRect(0, 0, 1920, 1080)
        self._full_pixmap = screen.grabWindow(0) if screen else QPixmap()
        self.setGeometry(self._screen_geo)
        self._origin: QPoint | None = None
        self._current: QPoint | None = None

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.cancelled.emit()
            self.close()
            return
        if key in (Qt.Key.Key_F, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            pix = self._full_pixmap.copy()
            self.captured.emit(pix)
            self.close()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self.cancelled.emit()
            self.close()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.position().toPoint()
            self._current = self._origin
            self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._origin is not None:
            self._current = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._origin is None:
            return
        end = event.position().toPoint()
        rect = QRect(self._origin, end).normalized()
        self._origin = None
        self._current = None
        if rect.width() < 12 or rect.height() < 12:
            self.cancelled.emit()
            self.close()
            return
        sx = self._full_pixmap.width() / max(1, self.width())
        sy = self._full_pixmap.height() / max(1, self.height())
        scaled_rect = QRect(
            int(round(rect.x() * sx)),
            int(round(rect.y() * sy)),
            int(round(rect.width() * sx)),
            int(round(rect.height() * sy)),
        ).intersected(self._full_pixmap.rect())
        cropped = self._full_pixmap.copy(scaled_rect)
        cropped.setDevicePixelRatio(1.0)
        self.captured.emit(cropped)
        self.close()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        if not self._full_pixmap.isNull():
            p.drawPixmap(self.rect(), self._full_pixmap)
        p.fillRect(self.rect(), QColor(8, 22, 30, 125))
        if self._origin is not None and self._current is not None:
            sel = QRect(self._origin, self._current).normalized()
            if not self._full_pixmap.isNull():
                sx = self._full_pixmap.width() / max(1, self.width())
                sy = self._full_pixmap.height() / max(1, self.height())
                src = QRect(
                    int(round(sel.x() * sx)),
                    int(round(sel.y() * sy)),
                    int(round(sel.width() * sx)),
                    int(round(sel.height() * sy)),
                ).intersected(self._full_pixmap.rect())
                p.drawPixmap(sel, self._full_pixmap, src)
            p.setPen(QPen(QColor('#20d6c2'), 2))
            p.drawRect(sel)
        hint = 'Kéo chuột khoanh vùng đề bài · Nhấn F / Enter chụp toàn màn hình · Esc để hủy'
        p.setFont(QFont('Segoe UI', 10, QFont.Weight.DemiBold))
        pill = QRect(max(20, (self.width() - 620) // 2), 18, min(620, self.width() - 40), 36)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(13, 43, 48, 230))
        p.drawRoundedRect(pill, 18, 18)
        p.setPen(QColor('#e8fff8'))
        p.drawText(pill, Qt.AlignmentFlag.AlignCenter, hint)


def capture_foreground_or_screen() -> QPixmap:
    """Capture the active foreground window accurately under Windows DPI scaling (no focus loss)."""
    screen = QGuiApplication.primaryScreen()
    if not screen:
        return QPixmap()
    full = screen.grabWindow(0)
    if full.isNull():
        return full
    full.setDevicePixelRatio(1.0)
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if hwnd:
            rect = wintypes.RECT()
            if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                # GetWindowRect already returns physical pixels on DPI-aware Qt apps!
                w = rect.right - rect.left
                h = rect.bottom - rect.top
                if w >= 400 and h >= 300:
                    dpr = screen.devicePixelRatio() or 1.0
                    s_geo = screen.geometry()
                    s_phys_x = int(round(s_geo.left() * dpr))
                    s_phys_y = int(round(s_geo.top() * dpr))
                    crop = QRect(
                        rect.left - s_phys_x,
                        rect.top - s_phys_y,
                        w,
                        h,
                    ).intersected(full.rect())
                    if crop.width() >= 400 and crop.height() >= 300:
                        return full.copy(crop)
    except Exception:
        pass
    # Never silently send a different, potentially sensitive window.
    return QPixmap()


def pixmap_to_jpeg_base64(pixmap: QPixmap, max_width: int = 1400, quality: int = 82) -> str:
    """Encode QPixmap directly to compact JPEG base64 in memory."""
    if pixmap.isNull():
        return ''
    target = pixmap
    if target.width() > max_width:
        target = target.scaledToWidth(max_width, Qt.TransformationMode.SmoothTransformation)
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    target.save(buf, 'JPEG', quality)
    raw = bytes(buf.data())
    buf.close()
    return base64.b64encode(raw).decode('ascii')


def extract_short_answer(full_reply: str) -> str:
    """Extract the concise final answer after 'ĐÁP ÁN:' (single or multi-line) for the Pet bubble."""
    text = (full_reply or '').strip()
    if '</think>' in text:
        text = text.split('</think>', 1)[-1].strip()
    m = re.search(r'(?ims)(?:\*\*)?ĐÁP\s*ÁN(?:\*\*)?\s*:\s*(.+)$', text)
    if m:
        block = m.group(1).strip()
        lines = [ln.strip().lstrip('-•*').strip().replace('**', '').replace('$', '') for ln in block.splitlines() if ln.strip()]
        ans = ' | '.join(lines).strip()
        if ans:
            return ans
    lines = [ln.strip().replace('**', '').replace('$', '') for ln in text.splitlines() if ln.strip()]
    return lines[-1] if lines else 'Không có đáp án.'


def extract_text_windows_ocr(pixmap: QPixmap) -> str:
    """Run built-in Windows OCR on a QPixmap."""
    if pixmap.isNull():
        return ''
    with tempfile.TemporaryDirectory(prefix='alex_ocr_') as tmpdir:
        tmp = Path(tmpdir)
        img_path = tmp / 'crop.png'
        ps1_path = tmp / 'ocr.ps1'
        target = pixmap
        if pixmap.width() < 700:
            target = pixmap.scaledToWidth(pixmap.width() * 2, Qt.TransformationMode.SmoothTransformation)
        target.save(str(img_path), 'PNG')
        ps1_path.write_text(_OCR_PS1, encoding='utf-8')
        try:
            proc = subprocess.run(
                [
                    'powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                    '-File', str(ps1_path), '-ImagePath', str(img_path),
                ],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=15,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
            return (proc.stdout or '').strip()
        except Exception as exc:
            logging.warning('Windows OCR failed: %s', exc)
            return ''


def solve_problem_groq_vision(
    pixmap: QPixmap,
    keys: list[str] | None = None,
    model: str = _GROQ_MODELS[0],
) -> tuple[str, str]:
    """Solve problem from screenshot via Windows OCR + Groq 120B/27B with automatic multi-key rotation."""
    global _GROQ_KEY_INDEX
    key_list = keys if keys is not None else load_groq_keys()
    if not key_list:
        msg = 'Chưa có Groq key. Chuột phải Pet → Thiết lập Groq API.'
        return msg, msg

    ocr_text = extract_text_windows_ocr(pixmap)
    if not ocr_text:
        msg = 'Không đọc được chữ từ ảnh. Hãy khoanh vùng rõ hơn và thử lại.'
        return msg, msg

    models_to_try = [model] + [m for m in _GROQ_MODELS if m != model]
    with _GROQ_KEY_LOCK:
        start_idx = _GROQ_KEY_INDEX % len(key_list)

    last_err = ''
    ssl_ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    with httpx.Client(timeout=25.0, verify=ssl_ctx) as client:
        for mdl in models_to_try:
            payload = {
                'model': mdl,
                'messages': [
                    {
                        'role': 'system',
                        'content': (
                            'Bạn là trợ lý học tập. Chỉ giải những câu và dữ kiện đọc rõ. '
                            'Kiểm tra lại phép tính, đơn vị và đáp án; nếu đề mờ, thiếu ký hiệu hoặc có nhiều cách hiểu, '
                            'nói rõ phần chưa chắc và yêu cầu ảnh rõ hơn, không tự đoán. '
                            'Giải cẩn thận rồi chốt dòng cuối theo mẫu:\n'
                            'ĐÁP ÁN: C1: <đáp án> | C2: <đáp án> | ...'
                        ),
                    },
                    {
                        'role': 'user',
                        'content': f'Đề bài:\n{ocr_text}\n\nHãy tính từng bước cẩn thận và chốt dòng cuối theo mẫu "ĐÁP ÁN: ...":',
                    },
                ],
                'temperature': 0.05,
                'max_tokens': 1800,
            }
            for offset in range(len(key_list)):
                idx = (start_idx + offset) % len(key_list)
                key = key_list[idx]
                try:
                    resp = client.post(
                        _GROQ_ENDPOINT,
                        headers={
                            'Authorization': f'Bearer {key}',
                            'Content-Type': 'application/json',
                        },
                        json=payload,
                    )
                    if resp.status_code in (401, 403, 429):
                        last_err = f'HTTP {resp.status_code}'
                        continue
                    if resp.status_code == 404:
                        last_err = f'Model {mdl} 404'
                        break
                    resp.raise_for_status()
                    data = resp.json()
                    with _GROQ_KEY_LOCK:
                        _GROQ_KEY_INDEX = idx
                    choices = data.get('choices') or []
                    if not choices:
                        last_err = 'phản hồi rỗng'
                        continue
                    full_reply = ((choices[0].get('message') or {}).get('content') or '').strip()
                    if '</think>' in full_reply:
                        full_reply = full_reply.split('</think>', 1)[-1].strip()
                    if not full_reply:
                        last_err = 'phản hồi rỗng'
                        continue
                    if str(choices[0].get('finish_reason') or '').lower() == 'length':
                        note = 'Lời giải có thể bị cắt; hãy chụp ít câu hơn.'
                        return note, full_reply + '\n\n' + note
                    short_ans = extract_short_answer(full_reply)
                    return short_ans, (full_reply or short_ans)
                except Exception:
                    last_err = 'lỗi kết nối hoặc phản hồi'
                    continue

    msg = f'Tất cả Groq key đều lỗi hoặc hết lượt ({last_err}).'
    return msg, msg


def solve_problem_gemini_vision(
    pixmap: QPixmap,
    keys: list[str] | None = None,
    model: str = _GEMINI_MODELS[0],
) -> tuple[str, str]:
    """Solve from the image, preferring the last working Gemini key with failover."""
    global _GEMINI_KEY_INDEX
    key_list = keys if keys is not None else load_gemini_study_keys()
    if not key_list:
        msg = 'Chưa có Gemini key. Chuột phải Pet → Thiết lập nhiều Gemini API key.'
        return msg, msg

    b64 = pixmap_to_jpeg_base64(pixmap, max_width=1920, quality=92)
    if not b64:
        msg = 'Không chụp được ảnh màn hình.'
        return msg, msg

    payload = {
        'contents': [
            {
                'parts': [
                    {
                        'text': (
                            'Bạn là trợ lý giải bài tập và trả lời MỌI LOẠI CÂU HỎI ở mọi lĩnh vực và mọi cấp học (từ đại học, cao học đến phổ thông: '
                            'Toán, Lý, Hóa, Sinh, Tin học/Code, Ngoại ngữ, Triết học, Kinh tế chính trị, Pháp luật, Lịch sử, Tư tưởng, Quản trị, Kỹ thuật, Y dược, IQ, trắc nghiệm hay tự luận...). '
                            'Trước tiên đọc đúng từng số, dấu, công thức, hình vẽ và các lựa chọn. '
                            'Giải các câu nhìn rõ; kiểm tra độc lập phép tính, điều kiện, đơn vị và sự phù hợp với lựa chọn trước khi kết luận. '
                            'Nếu ảnh mờ, bị cắt, thiếu dữ kiện hoặc hình không rõ, nêu rõ câu nào chưa chắc và đề nghị chụp lại; tuyệt đối không đoán. '
                            'Nếu là TRẮC NGHIỆM hoặc ĐIỀN SỐ (có thể có nhiều câu): giải tất cả các câu nhìn thấy rõ theo đúng số câu trên ảnh, '
                            'rồi ở DÒNG CUỐI CÙNG gộp trên 1 dòng đúng mẫu: ĐÁP ÁN: C1: <đáp án> | C2: <đáp án> | ... '
                            'Nếu là TỰ LUẬN / VIẾT ĐOẠN / CODE / LÝ THUYẾT: trình bày câu trả lời đầy đủ, chính xác, mạch lạc, đúng trọng tâm (dùng chữ thường dễ đọc, hạn chế LaTeX rườm rà), '
                            'rồi ở DÒNG CUỐI CÙNG tóm tắt ý chính trong 1 dòng theo mẫu: ĐÁP ÁN: <tóm tắt ngắn gọn>'
                        ),
                    },
                    {
                        'inline_data': {
                            'mime_type': 'image/jpeg',
                            'data': b64,
                        },
                    },
                ],
            }
        ],
        'generationConfig': {
            'temperature': 0.05,
            'maxOutputTokens': 8192,
        },
    }

    models_to_try = [model] + [m for m in _GEMINI_MODELS if m != model]
    now = __import__('time').time()
    with _GEMINI_KEY_LOCK:
        start_idx = _GEMINI_KEY_INDEX % len(key_list)

    last_err = ''
    ssl_ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    with httpx.Client(timeout=18.0, verify=ssl_ctx) as client:
        for mdl in models_to_try:
            url = f'https://generativelanguage.googleapis.com/v1beta/models/{mdl}:generateContent'
            req_payload = dict(payload)
            gen_cfg = dict(payload['generationConfig'])
            # Gemini 3 defaults to substantial internal reasoning, which also
            # consumes the output budget and may cut a short essay mid-sentence.
            # Apply its supported low setting only to explicit Gemini 3 models;
            # the moving "latest" alias may refer to a different generation.
            if mdl.startswith('gemini-3'):
                gen_cfg['thinkingConfig'] = {'thinkingLevel': 'LOW'}
            req_payload['generationConfig'] = gen_cfg
            for offset in range(len(key_list)):
                idx = (start_idx + offset) % len(key_list)
                key = key_list[idx]
                if _KEY_COOLDOWN_UNTIL.get(key, 0.0) > now:
                    last_err = 'tạm chờ sau khi vượt hạn mức'
                    continue
                try:
                    resp = client.post(url, params={'key': key}, json=req_payload)
                    if resp.status_code == 429:
                        _KEY_COOLDOWN_UNTIL[key] = now + 60.0
                        last_err = 'HTTP 429'
                        continue
                    if resp.status_code == 401:
                        # A rejected key is unlikely to become valid next turn;
                        # avoid repeatedly waiting on it for five minutes.
                        _KEY_COOLDOWN_UNTIL[key] = now + 300.0
                        last_err = 'HTTP 401'
                        continue
                    if resp.status_code in (400, 403, 503):
                        last_err = f'HTTP {resp.status_code}'
                        continue
                    if resp.status_code == 404:
                        last_err = f'Model {mdl} 404'
                        break
                    resp.raise_for_status()
                    data = resp.json()
                    cands = data.get('candidates') or []
                    if not cands:
                        last_err = 'empty_candidates'
                        continue
                    parts = ((cands[0].get('content') or {}).get('parts') or [])
                    visible_parts = [str(p.get('text') or '') for p in parts if p.get('text') and not p.get('thought')]
                    full_reply = '\n'.join(visible_parts).strip()
                    if not full_reply:
                        last_err = 'empty_text'
                        continue
                    with _GEMINI_KEY_LOCK:
                        # Reuse the key that actually returned text rather than
                        # cycling into keys that may have exhausted their quota.
                        _GEMINI_KEY_INDEX = idx
                    truncated = (cands[0].get('finishReason') or '').upper() == 'MAX_TOKENS'
                    if truncated:
                        full_reply += '\n\nLời giải có thể bị cắt; hãy chụp ít câu hơn để kiểm tra lại.'
                    short_ans = extract_short_answer(full_reply)
                    if truncated:
                        short_ans = 'Lời giải có thể bị cắt; hãy chụp ít câu hơn.'
                    return short_ans, full_reply
                except Exception:
                    # HTTP exceptions can contain key-bearing request URLs.
                    last_err = 'lỗi kết nối hoặc phản hồi'
                    continue

    msg = f'Tất cả Gemini key đều lỗi hoặc hết lượt ({last_err}).'
    return msg, msg


def solve_problem_smart(pixmap: QPixmap) -> tuple[str, str]:
    """Prefer Gemini Vision; use configured Groq OCR fallback if it fails."""
    gemini_keys = load_gemini_study_keys()
    if gemini_keys:
        try:
            result = solve_problem_gemini_vision(pixmap, keys=gemini_keys)
        except Exception:
            result = ('Tất cả Gemini key đều lỗi hoặc hết lượt (lỗi kết nối).',)*2
        if not (result[0] == result[1] and result[0].startswith('Tất cả Gemini key đều lỗi')):
            return result
    groq_keys = load_groq_keys()
    if groq_keys:
        short, full = solve_problem_groq_vision(pixmap, keys=groq_keys)
        if gemini_keys and short and not short.startswith(('Tất cả Groq key', 'Không đọc được chữ')):
            full = 'Đã dùng Groq và OCR dự phòng; kiểm tra kỹ công thức và hình vẽ.\n\n' + full
        return short, full
    if gemini_keys:
        return result
    msg = 'Chưa có API key. Chuột phải Pet → Thiết lập nhiều Gemini API key.'
    return msg, msg


def open_gemini_web_with_clipboard(pixmap: QPixmap) -> None:
    """Copy captured QPixmap to clipboard and open gemini.google.com in the user's browser."""
    cb = QApplication.clipboard()
    if cb is not None and not pixmap.isNull():
        cb.setPixmap(pixmap)
    QDesktopServices.openUrl(QUrl('https://gemini.google.com/app'))


class StudyAnswerPopup(QWidget):
    """Non-focus-stealing floating card for reading full essay/step-by-step solutions (Ctrl+Shift+A to toggle)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.resize(440, 320)
        self.setStyleSheet(
            'QWidget#studyCard { background: rgba(16, 36, 46, 240); border: 1px solid #3c7b88; border-radius: 14px; }'
            'QLabel { color: #d8fff5; font-weight: 600; font-size: 12px; }'
            'QTextEdit { background: transparent; color: #f2fbff; border: none; font-size: 13px; }'
            'QPushButton { background: #1e5763; color: #e8fff9; border: 1px solid #3c7b88; border-radius: 7px; padding: 4px 10px; font-size: 11px; }'
            'QPushButton:hover { background: #266c7a; }'
        )
        self.setObjectName('studyCard')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        head = QHBoxLayout()
        head.addWidget(QLabel('Alex · Lời giải đầy đủ (Ctrl+Shift+A để ẩn/hiện)', self), 1)
        copy_btn = QPushButton('Copy', self)
        copy_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        copy_btn.clicked.connect(self._copy_text)
        close_btn = QPushButton('Ẩn', self)
        close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close_btn.clicked.connect(self.hide)
        head.addWidget(copy_btn)
        head.addWidget(close_btn)
        layout.addLayout(head)

        self.viewer = QTextEdit(self)
        self.viewer.setReadOnly(True)
        self.viewer.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout.addWidget(self.viewer, 1)

    def _copy_text(self) -> None:
        cb = QApplication.clipboard()
        if cb is not None:
            cb.setText(self.viewer.toPlainText())

    def show_answer(self, text: str, anchor_pos: QPoint | None = None) -> None:
        clean = (text or '').replace('**', '').strip()
        self.viewer.setPlainText(clean)
        screen = QGuiApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        if anchor_pos is not None:
            x = max(geo.left() + 12, min(anchor_pos.x() - self.width() - 12, geo.right() - self.width() - 12))
            y = max(geo.top() + 12, min(anchor_pos.y(), geo.bottom() - self.height() - 12))
        else:
            x = geo.right() - self.width() - 24
            y = geo.bottom() - self.height() - 180
        self.move(x, y)
        self.show()
