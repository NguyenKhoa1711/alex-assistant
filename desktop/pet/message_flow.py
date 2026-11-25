"""Bound a single outgoing message to an independently checked UI adapter."""
from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Callable, Protocol

from .message_intent import SendIntent


class MessageAdapter(Protocol):
    def find_exact_recipients(self, recipient: str) -> list[str]: ...
    def open_and_verify_recipient(self, recipient_id: str, recipient: str) -> bool: ...
    def set_and_verify_draft(self, content: str) -> bool: ...
    def still_matches(self, recipient_id: str, recipient: str, content: str) -> bool: ...
    def sent_message_baseline(self, recipient_id: str, content: str) -> object: ...
    def send_once(self) -> None: ...
    def message_visible_after_send(self, recipient_id: str, content: str, baseline: object) -> bool: ...


@dataclass(frozen=True)
class MessageResult:
    status: str
    sent: bool = False


def send_requested_once(intent: SendIntent, adapter: MessageAdapter,
                        cancelled: Callable[[], bool] = lambda: False) -> MessageResult:
    """Never retry after attempting send; an uncertain result must stay uncertain."""
    attempted = False
    draft_created = False
    try:
        if cancelled():
            return MessageResult('cancelled')
        matches = adapter.find_exact_recipients(intent.recipient)
        if len(matches) != 1:
            return MessageResult('recipient_not_unique')
        recipient_id = matches[0]
        if cancelled():
            return MessageResult('cancelled')
        if not adapter.open_and_verify_recipient(recipient_id, intent.recipient):
            return MessageResult('recipient_unverified')
        if cancelled():
            return MessageResult('cancelled')
        # Establish a reliable baseline before touching the user's draft. If
        # the platform cannot prove sender, delivery and a stable message ID,
        # stop without typing or attempting to send.
        try:
            baseline = adapter.sent_message_baseline(recipient_id, intent.content)
        except ValueError:
            return MessageResult('verification_unavailable')
        if cancelled():
            return MessageResult('cancelled')
        # The operation can fail after typing; callers must warn that a draft
        # may remain even when the adapter throws or cannot verify the result.
        draft_created = True
        if not adapter.set_and_verify_draft(intent.content):
            return MessageResult('draft_unverified')
        if not adapter.still_matches(recipient_id, intent.recipient, intent.content):
            return MessageResult('changed_before_send')
        if cancelled():
            return MessageResult('cancelled_draft')
        attempted = True
        adapter.send_once()
        if not adapter.message_visible_after_send(recipient_id, intent.content, baseline):
            return MessageResult('send_unverified')
        return MessageResult('sent', True)
    except Exception as exc:
        stage = 'attempted' if attempted else 'draft' if draft_created else 'preflight'
        # UI and tool exception text can contain message drafts, contact names,
        # or conversation data. Log only technical diagnostics, not the text.
        logging.warning('MESSAGING_ABORT service=%s stage=%s type=%s',
                        intent.service, stage, type(exc).__name__)
        return MessageResult('send_unverified' if attempted else
                             'not_sent_draft_may_remain' if draft_created else 'not_sent')
