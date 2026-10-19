"""Bionic 1.1.7 UI bridge. Send through its composer; read its DB read-only.

Never writes chat rows, calls a separate LLM, or bypasses Bionic tool approvals.
"""
from __future__ import annotations
from collections.abc import Callable, Iterator
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import threading
import time
from urllib.parse import urlparse
import httpx
import websocket


EDITOR = '[data-bionic-rich-text-input="true"][aria-label="Bionic chat input"]'
def active_elements(selector: str) -> str:
    """Find controls in the selected Bionic tab, excluding mounted hidden tabs."""
    return (f'[...document.querySelectorAll({json.dumps(selector)})]'
            ".filter(e=>e.getClientRects().length&&!e.closest('[aria-hidden=\"true\"],[inert]'))")


ACTIVE_EDITORS = active_elements(EDITOR)
ACTIVE_SEND = active_elements('button[aria-label="Send"]')
ACTIVE_STOP = active_elements('button[aria-label="Stop"],button[aria-label="Interrupt"]')
LOGIN_CHECK = """(()=>{
  const buttons=ACTIVE_SEND_PLACEHOLDER;
  for(const b of buttons)for(const e of b.querySelectorAll('*')){
    if(!/^(Log in|Sign in)$/i.test(e.textContent.trim())||!e.getClientRects().length)continue;
    let visible=true;
    for(let p=e;p&&p!==b.parentElement;p=p.parentElement){
      const s=getComputedStyle(p);
      if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)<0.1){visible=false;break;}
    }
    if(visible)return true;
  }
  return false;
})()"""
LOGIN_CHECK = LOGIN_CHECK.replace('ACTIVE_SEND_PLACEHOLDER', ACTIVE_SEND)
LOGIN_ERROR = 'Bionic yêu cầu đăng nhập lại. Bấm Log in trong Bionic rồi thử lại.'


class BionicUnavailable(RuntimeError):
    pass


class Renderer:
    def __init__(self, port: int) -> None:
        with httpx.Client(trust_env=False, timeout=3) as client:
            pages = client.get(f'http://127.0.0.1:{port}/json/list').raise_for_status().json()
        pages = [p for p in pages if p.get('type') == 'page' and
                 '/Bionic/resources/app/.webpack-bionic/renderer/index.html' in p.get('url', '')]
        if not pages:
            raise BionicUnavailable('Bionic chưa có cửa sổ chat.')
        if len(pages) != 1:
            raise RuntimeError('Hãy mở đúng một cửa sổ Bionic để nối pet.')
        address = pages[0]['webSocketDebuggerUrl']
        parsed = urlparse(address)
        if parsed.hostname != '127.0.0.1' or parsed.port != port:
            raise RuntimeError('Cầu nối Bionic không phải localhost.')
        self.ws = websocket.create_connection(address, suppress_origin=True, timeout=5,
                                              http_proxy_host=None, http_no_proxy=['127.0.0.1'])
        self.sequence = 0

    def call(self, method: str, params: dict) -> dict:
        self.sequence += 1
        self.ws.send(json.dumps({'id': self.sequence, 'method': method, 'params': params}))
        while True:
            result = json.loads(self.ws.recv())
            if result.get('id') == self.sequence:
                if result.get('error'):
                    raise RuntimeError('Không thực hiện được thao tác giao diện Bionic.')
                return result.get('result', {})

    def evaluate(self, expression: str):
        result = self.call('Runtime.evaluate', {'expression': expression, 'returnByValue': True})
        if result.get('exceptionDetails'):
            raise RuntimeError('Giao diện Bionic đã thay đổi; chưa gửi câu hỏi.')
        return result.get('result', {}).get('value')

    def close(self) -> None:
        self.ws.close()


def active_session(state_dir: Path) -> tuple[str, str]:
    # Bionic can truncate/rewrite its state while switching tabs. Retry only
    # this read, never a submitted message or a computer action.
    for attempt in range(4):
        try:
            files = list(state_dir.glob('window-*.json'))
            if not files:
                raise RuntimeError('Mở một cuộc chat Bionic trước khi nói với pet.')
            data = json.loads(max(files, key=lambda p: p.stat().st_mtime).read_text(encoding='utf-8'))
            break
        except (OSError, json.JSONDecodeError) as exc:
            if attempt == 3:
                raise RuntimeError('Chưa đọc được trạng thái chat Bionic; bạn thử lại sau một chút nhé.') from exc
            time.sleep(.05)
    pane = data.get('tabLayouts', {}).get('bionic.sessions', {})
    if pane.get('type') != 'pane':
        raise RuntimeError('Pet cần một khung chat Bionic; hãy đóng chế độ chia đôi.')
    tabs, index = pane.get('tabs', []), pane.get('active')
    if not isinstance(index, int) or not 0 <= index < len(tabs):
        raise RuntimeError('Hãy chọn một cuộc chat Bionic.')
    parts = tabs[index].split(':')
    if (len(parts) != 5 or parts[0] not in {'bionicSession', 'bionicTemporarySession'}
            or parts[1] != 'v2'):
        raise RuntimeError('Hãy mở một cuộc chat đã tạo trong Bionic.')
    import uuid
    project, session = str(uuid.UUID(parts[2])), str(uuid.UUID(parts[4]))
    return project, session


def read_entries(path: Path, session: str, stop_id: str | None = None) -> tuple[str | None, list[dict]]:
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2)) as conn:
        row = conn.execute('SELECT committed_head_entry_id FROM sessions WHERE session_id=?', (session,)).fetchone()
        if row is None:
            raise RuntimeError('Không tìm thấy cuộc chat Bionic đang chọn.')
        head = current = row[0]
        entries: list[dict] = []
        for _ in range(180):
            if not current or current == stop_id:
                break
            row = conn.execute('SELECT previous_id,entry_json FROM chat_entries WHERE id=?', (current,)).fetchone()
            if row is None:
                break
            current, raw = row
            entries.append(json.loads(raw))
        return head, list(reversed(entries))


def context_tokens(path: Path, session: str) -> int:
    """Read Bionic's own estimate; do not infer it from message text."""
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2)) as conn:
        row = conn.execute('SELECT session_json FROM sessions WHERE session_id=?', (session,)).fetchone()
    if not row:
        return 0
    estimate = json.loads(row[0]).get('contextEstimation') or {}
    return int(estimate.get('total') or 0)


def _is_compaction_note(entry: dict) -> bool:
    """Bionic's hidden handoff marker is not a new user request."""
    message = entry.get('message') or {}
    source = entry.get('source') or {}
    return (entry.get('hidden') is True and source.get('type') == 'ngModule'
            and source.get('ngModule') == 'lmstudio/context-compaction-v1'
            and isinstance(message, dict) and message.get('role') == 'user'
            and message.get('noReplayPostCompaction') is True)


def finished_answer(entries: list[dict], question: str) -> tuple[bool, str]:
    matched, answer = False, ''
    for entry in entries:
        if _is_compaction_note(entry):
            continue
        message = entry.get('message', {})
        if not isinstance(message, dict):
            continue
        parts = message.get('parts', [])
        text = '\n'.join(p['text'] for p in parts if p.get('type') == 'text')
        if message.get('role') == 'user':
            if matched:
                # Do not read a later user's response as this pet's response.
                return False, ''
            matched = ' '.join(text.split()) == ' '.join(question.split())
        elif matched and message.get('role') == 'assistant' and text and not any(p.get('type') == 'toolCallRequest' for p in parts):
            answer = text
        elif matched and entry.get('type') == 'turnSummary':
            return True, answer
    return False, ''


def turn_error(entries: list[dict], question: str) -> str | None:
    """Return a safe user-facing error only for the turn we just submitted."""
    matched = False
    for entry in entries:
        if _is_compaction_note(entry):
            continue
        message = entry.get('message')
        if entry.get('type') == 'message' and isinstance(message, dict) and message.get('role') == 'user':
            text = ' '.join(part.get('text', '') for part in message.get('parts', []) if part.get('type') == 'text')
            if matched:
                return None
            matched = ' '.join(text.split()) == ' '.join(question.split())
        elif matched and entry.get('type') == 'error':
            if entry.get('errorCode') == 'local_model_context_length_insufficient':
                return ('Chat Bionic hiện quá dài cho model local. '
                        'Mở chat mới trong Bionic để pet trả lời nhanh và ổn định hơn.')
            if (entry.get('source') or {}).get('ngModule') == 'lmstudio/context-compaction-v1' and \
                    'Indexed model not found' in entry.get('message', ''):
                return ('Bionic lỗi khi thu gọn chat dài dù model vẫn còn trên máy. '
                        'Alex sẽ dùng chat mới cho lượt tiếp theo.')
            return 'Bionic báo lỗi khi trả lời. Xem chi tiết trong chat Bionic.'
    return None


def model_permitted(spec: dict, project_id: str, cfg: dict) -> bool:
    """Keep ordinary voice chats local; allow cloud only in named project IDs."""
    if not cfg.get('require_local_model', True):
        return True
    if spec.get('type') == 'cloudInference':
        return project_id in cfg.get('cloud_project_ids', []) and bool(spec.get('model'))
    prefixes = cfg.get('local_model_prefixes', ['qwen/qwen3.5-4b@'])
    identifier = spec.get('indexedModelIdentifier', '')
    return spec.get('type') == 'indexed' and any(
        identifier == prefix.rstrip('@') or identifier.startswith(prefix)
        for prefix in prefixes)


class BionicChat:
    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self.first_token_seconds = None  # Native UI does not expose first-token timing.
        self.response_seconds: float | None = None
        self.target: tuple[str, str] | None = None
        self.submitted = False
        self.on_submitted: Callable[[], None] | None = None
        self.state_dir = Path.home() / '.lmstudio/.internal/ui-state/bionic'
        self.base = Path.home() / '.lmstudio/apps/bionic'

    def check_ready(self) -> tuple[str, str]:
        try:
            renderer = Renderer(self.cfg['bridge_port'])
        except (BionicUnavailable, OSError, httpx.HTTPError, websocket.WebSocketException):
            from .launcher import open_bionic
            open_bionic(self.cfg['bridge_port'], show=False)
            for attempt in range(40):
                try:
                    renderer = Renderer(self.cfg['bridge_port'])
                    break
                except (BionicUnavailable, OSError, httpx.HTTPError):
                    if attempt == 39:
                        raise RuntimeError('Bionic chưa sẵn sàng. Mở Mo-tro-ly.bat rồi thử lại.')
                    time.sleep(.25)
        try:
            if renderer.evaluate(LOGIN_CHECK):
                raise RuntimeError(LOGIN_ERROR)
            target = active_session(self.state_dir)
            if self.cfg.get('require_local_model', True):
                db = self.base / 'projects' / target[0] / '.internal/ng-sessions.sqlite'
                with closing(sqlite3.connect(db.as_uri() + '?mode=ro', uri=True)) as conn:
                    row = conn.execute('SELECT session_json FROM sessions WHERE session_id=?', (target[1],)).fetchone()
                spec = json.loads(row[0]).get('modelSpecifier', {}) if row else {}
                if not model_permitted(spec, target[0], self.cfg):
                    raise RuntimeError('Chọn Qwen3.5 4B local cho chat thường, hoặc mở Project Làm Project (Cloud) để dùng cloud.')
            # A restored Bionic window can appear before React mounts its composer.
            for _ in range(32):
                count = renderer.evaluate(f'{ACTIVE_EDITORS}.length')
                if count:
                    break
                time.sleep(.25)
            status = renderer.evaluate(f"(()=>{{const e={ACTIVE_EDITORS};if(e.length!==1)return 'editor';if({ACTIVE_STOP}.length)return 'busy';return e[0].innerText.trim()?'draft':'ready'}})()")
            if status != 'ready':
                raise RuntimeError({'editor': 'Hãy đóng hộp tạo chat mới và chọn một cuộc chat Bionic.',
                                    'busy': 'Bionic đang xử lý câu trước; hãy đợi xong.',
                                    'draft': 'Ô chat Bionic còn bản nháp; hãy gửi hoặc xóa bản nháp trước.'}.get(status, 'Bionic chưa sẵn sàng.'))
            return target
        finally:
            renderer.close()

    def cancel(self) -> None:
        target = self.target
        if target is None or not self.submitted:
            return
        try:
            if active_session(self.state_dir) != target:
                return
            renderer = Renderer(self.cfg['bridge_port'])
            try:
                if self.target != target or not self.submitted:
                    return
                # Only cancel the chat targeted by this active voice turn.
                renderer.evaluate(f"(()=>{{const b={ACTIVE_STOP}[0];if(b){{b.click();return true}}return false}})()")
            finally:
                renderer.close()
        except Exception:
            pass

    def _start_fresh_chat(self, previous: tuple[str, str]) -> None:
        renderer = Renderer(self.cfg['bridge_port'])
        try:
            clicked = renderer.evaluate("(()=>{const b=[...document.querySelectorAll('button[aria-label=\"New Chat\"]')].find(e=>e.getClientRects().length);if(!b)return false;b.click();return true})()")
            if not clicked:
                raise RuntimeError('Không thấy nút chat mới của Bionic.')
        finally:
            renderer.close()
        for _ in range(30):
            try:
                current = active_session(self.state_dir)
            except RuntimeError:
                # A blank new chat has no session ID until its first message is sent.
                return
            if current != previous:
                if current[0] != previous[0]:
                    raise RuntimeError('Tab Bionic đã đổi Project; câu hỏi chưa được gửi.')
                # Recent Bionic versions assign a temporary ID before the first send.
                return
            time.sleep(.1)
        raise RuntimeError('Bionic chưa chuyển sang chat mới; câu hỏi chưa được gửi.')

    def stream(self, question: str, cancelled: threading.Event) -> Iterator[str]:
        started = time.monotonic()
        self.response_seconds = None
        self.submitted = False
        self.target = self.check_ready()
        project, session = self.target
        database = self.base / 'projects' / project / '.internal/ng-sessions.sqlite'
        limit = int(self.cfg.get('auto_rotate_after_tokens') or 0)
        rotate = (limit > 0 and project in self.cfg.get('auto_rotate_project_ids', []) and
                  context_tokens(database, session) >= limit)
        if rotate:
            self._start_fresh_chat(self.target)
            head = None
        else:
            head, _ = read_entries(database, session)
        try:
            try:
                renderer = Renderer(self.cfg['bridge_port'])
            except (OSError, httpx.HTTPError, websocket.WebSocketException) as exc:
                raise RuntimeError('Mở Bionic bằng Mo-Bionic-va-Alex.bat để kết nối pet.') from exc
            try:
                if renderer.evaluate(LOGIN_CHECK):
                    raise RuntimeError(LOGIN_ERROR)
                status = renderer.evaluate(f"(()=>{{const e={ACTIVE_EDITORS};if(e.length!==1)return 'no-editor';if({ACTIVE_STOP}.length)return 'busy';if(e[0].innerText.trim())return 'draft';e[0].focus();return 'ready'}})()")
                errors = {'draft': 'Ô chat Bionic còn bản nháp; hãy gửi hoặc xóa bản nháp trước.',
                          'busy': 'Bionic đang xử lý câu trước; hãy đợi xong.',
                          'no-editor': 'Chưa thấy ô chat Bionic. Mở một cuộc chat rồi thử lại.'}
                if status != 'ready':
                    raise RuntimeError(errors.get(status, 'Bionic chưa sẵn sàng.'))
                if cancelled.is_set():
                    return
                if not rotate and active_session(self.state_dir) != self.target:
                    raise RuntimeError('Tab Bionic vừa đổi; chưa gửi câu hỏi.')
                renderer.call('Input.insertText', {'text': question})
                # React updates the send button after the input event.
                for _ in range(20):
                    if cancelled.wait(.05):
                        return
                    if renderer.evaluate(LOGIN_CHECK):
                        raise RuntimeError(LOGIN_ERROR + ' Câu hỏi còn ở ô nhập.')
                    ready = renderer.evaluate(f"(()=>{{const b={ACTIVE_SEND}[0];return !!b&&!b.disabled&&b.getAttribute('aria-disabled')!=='true'}})()")
                    if ready:
                        break
                else:
                    raise RuntimeError('Bionic chưa cho gửi. Câu hỏi được giữ trong ô nhập.')
                if not rotate and active_session(self.state_dir) != self.target:
                    raise RuntimeError('Tab Bionic vừa đổi. Kiểm tra bản nháp trước khi gửi.')
                sent = renderer.evaluate(f"(()=>{{const e={ACTIVE_EDITORS}[0];const b={ACTIVE_SEND}[0];if(!e||e.innerText.trim().replace(/\\s+/g,' ')!=={json.dumps(' '.join(question.split()))}||!b||b.disabled||b.getAttribute('aria-disabled')==='true')return false;b.click();return true}})()")
                if not sent:
                    raise RuntimeError('Ô nhập vừa thay đổi; pet chưa gửi.')
                self.submitted = True
            finally:
                renderer.close()
            if rotate:
                previous = (project, session)
                for _ in range(100):
                    if cancelled.wait(.1):
                        return
                    try:
                        current = active_session(self.state_dir)
                    except RuntimeError:
                        continue
                    if current != previous:
                        if current[0] != project:
                            raise RuntimeError('Bionic đã chuyển sang Project khác; kiểm tra chat vừa tạo.')
                        self.target = current
                        session = current[1]
                        break
                else:
                    raise RuntimeError('Bionic chưa tạo chat mới sau khi gửi; pet không gửi lại câu hỏi.')
            reported_submission = False
            while not cancelled.wait(.2):
                _, entries = read_entries(database, session, head)
                error = turn_error(entries, question)
                if error:
                    raise RuntimeError(error)
                if not reported_submission:
                    for entry in entries:
                        msg = entry.get('message')
                        if isinstance(msg, dict) and msg.get('role') == 'user':
                            value = ' '.join(part.get('text', '') for part in msg.get('parts', []) if part.get('type') == 'text')
                            if ' '.join(value.split()) == ' '.join(question.split()):
                                reported_submission = True
                                if self.on_submitted:
                                    self.on_submitted()
                                break
                done, answer = finished_answer(entries, question)
                if done:
                    if not answer.strip():
                        raise RuntimeError('Bionic đã dừng nhưng chưa có câu trả lời. Xem lỗi trong chat.')
                    self.response_seconds = time.monotonic() - started
                    yield answer
                    return
                if time.monotonic() - started > self.cfg.get('timeout_seconds', 300):
                    # Never resubmit automatically: that could repeat a computer action.
                    raise RuntimeError('Bionic chưa trả lời xong. Kiểm tra chat; pet không gửi lại câu hỏi.')
        finally:
            self.submitted = False
            self.target = None
