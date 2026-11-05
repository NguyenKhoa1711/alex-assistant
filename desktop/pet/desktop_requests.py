"""Desktop text requests run on the pet's existing worker, never a second model."""
from __future__ import annotations

from dataclasses import dataclass, field
from queue import Empty, Full, Queue
import logging
import threading
import time


@dataclass(frozen=True)
class DesktopRequest:
    text: str
    speak: bool = False
    target: tuple | None = None
    reset: bool = False
    created: float = field(default_factory=time.monotonic)


class DesktopRequestsMixin:
    def _init_desktop_requests(self):
        self.desktop_requests = Queue(maxsize=1)
        self.desktop_ready = threading.Event()
        self._desktop_speak = True

    def submit_text(self, text: str, speak: bool = False, target=None, *, reset=False) -> str:
        text = text.strip()
        if not reset and not text:
            return 'Bạn nhập câu hỏi trước nhé.'
        if len(text) > 4000:
            return 'Mỗi lượt tối đa 4.000 ký tự. Bạn chia nhỏ nội dung nhé.'
        if self.stopping.is_set() or not self.isRunning() or not self.desktop_ready.is_set():
            return 'Alex đang khởi động. Bạn đợi trạng thái sẵn sàng rồi gửi nhé.'
        if self.busy.is_set():
            return 'Alex đang xử lý. Bạn đợi xong hoặc bấm Dừng nhé.'
        try:
            self.desktop_requests.put_nowait(DesktopRequest(text, speak, target, reset))
        except Full:
            return 'Alex đã nhận một yêu cầu, bạn đợi một chút nhé.'
        return ''

    def _discard_desktop_requests(self):
        while True:
            try:
                self.desktop_requests.get_nowait()
            except Empty:
                break
            self.desktop_finished.emit(False, 'Đã hủy yêu cầu đang chờ.')

    def _prepare_desktop_target(self, job: DesktopRequest):
        from .app_actions import parse_action
        action = parse_action(job.text)
        if action is None or action.app not in {'Window', 'Tabs'}:
            return
        # Named-window actions can resolve their own explicit target.
        if action.app == 'Window' and action.operation == 'close_current' and action.query:
            return
        from .window_actions import Windows
        from .apps import focus_window
        api = Windows()
        target = job.target
        if not target or api.identity(target[0]) != target:
            raise ValueError('Bạn chọn cửa sổ cần điều khiển, rồi trở lại Alex để gửi lệnh nhé.')
        if not api.visible(target[0]) or not api.enabled(target[0]):
            raise ValueError('Cửa sổ cần điều khiển chưa sẵn sàng. Mình chưa thao tác.')
        if not focus_window(target[0]) or api.foreground() != target[0]:
            raise ValueError('Windows chưa cho chuyển đến cửa sổ cần điều khiển. Mình chưa thao tác.')

    def _run_desktop_request(self) -> bool:
        try:
            job = self.desktop_requests.get_nowait()
        except Empty:
            return False
        from .mobile import _pc_unlocked
        if (self.stopping.is_set() or time.monotonic() - job.created > 15
                or job.created <= max(self._last_sleep_at, self._woke_at)
                or not _pc_unlocked()):
            self.desktop_finished.emit(False, 'Yêu cầu đã hết hạn hoặc Windows đang khóa. Bạn gửi lại khi sẵn sàng nhé.')
            return True
        self.busy.set()
        self.cancelled.clear()
        self._desktop_speak = job.speak
        if self.mic:
            self.mic.gate(False)
        started = time.monotonic()
        try:
            if job.reset:
                if hasattr(self.chat, 'history'):
                    self.chat.history.clear()
                for context in self.opening_contexts.values():
                    context.clear()
                self.pending_app = self.pending_song = None
                self.awaiting_contact = False
                self.previous_question, self.previous_question_at = '', 0.0
                self.desktop_finished.emit(True, 'Đã bắt đầu cuộc trò chuyện mới.')
                return True
            self._prepare_desktop_target(job)
            self.state.emit('thinking', 'Đang xử lý yêu cầu của bạn…')
            from .audio import Utterance
            import numpy as np
            # No STT invocation, no recorded audio, and no extra inference thread.
            self._answer(job.text, Utterance(np.empty(0, dtype=np.float32), started), 0.0)
            cancelled = self.cancelled.is_set()
            self.desktop_finished.emit(not cancelled,
                'Đã dừng.' if cancelled else f'Hoàn tất trong {time.monotonic() - started:.1f} giây')
        except Exception as exc:
            logging.warning('Desktop text turn failed: %s', type(exc).__name__)
            message = (str(exc) if isinstance(exc, ValueError) else
                       'Chưa xử lý được yêu cầu. Bạn kiểm tra bộ xử lý Alex trên laptop rồi thử lại nhé.')
            self.desktop_finished.emit(False, message)
        finally:
            self._desktop_speak = True
            if job.speak:
                self.stopping.wait(self.cfg['audio'].get('echo_cooldown_seconds', 0.4))
            self.busy.clear()
            if self.mic:
                self.mic.flush()
                self.mic.gate(not self.paused.is_set() and not self.stopping.is_set())
            if self.paused.is_set():
                self.state.emit('paused', 'Mic tắt · bạn vẫn có thể nhập câu hỏi')
            else:
                self._idle()
        return True
