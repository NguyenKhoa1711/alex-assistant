"""Platform-independent message adapter; drivers must provide stable UI identities.

Never expose message contents in logs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .message_identity import Candidate, exact_candidate, normalized_name


@dataclass(frozen=True)
class Conversation:
    service: str
    id: str
    name: str
    foreground: bool


@dataclass(frozen=True)
class OutgoingMessage:
    id: str
    text: str
    status: str
    sender_is_user: bool


class UiDriver(Protocol):
    def search_contacts(self, name: str) -> tuple[list[Candidate], bool]: ...
    def open_contact(self, contact_id: str) -> None: ...
    def current_conversation(self) -> Conversation | None: ...
    def read_draft(self) -> str | None: ...
    def type_literal(self, value: str) -> None: ...
    def outgoing_messages(self) -> list[OutgoingMessage] | None: ...
    def submit_once(self, expected: Conversation, expected_text: str) -> None:
        """Recheck conversation, focus and exact draft immediately before submitting."""
        ...


class VerifiedMessageAdapter:
    def __init__(self, service: str, driver: UiDriver):
        if service not in ('Zalo', 'Messenger'):
            raise ValueError('unsupported service')
        self.service = service
        self.driver = driver
        self.chosen = None
        self.draft = None

    def find_exact_recipients(self, recipient: str) -> list[str]:
        candidates, complete = self.driver.search_contacts(recipient)
        match = exact_candidate(recipient, candidates) if complete else None
        self.chosen = match
        return [match.id] if match else []

    def _same_conversation(self, recipient_id: str, recipient: str) -> bool:
        current = self.driver.current_conversation()
        return bool(current and current.foreground and current.service == self.service
                    and current.id == recipient_id and self.chosen and self.chosen.id == recipient_id
                    and normalized_name(current.name) == normalized_name(recipient))

    def open_and_verify_recipient(self, recipient_id: str, recipient: str) -> bool:
        self.driver.open_contact(recipient_id)
        return self._same_conversation(recipient_id, recipient)

    def set_and_verify_draft(self, content: str) -> bool:
        # Never replace a pre-existing draft. A failed read is not an empty draft.
        if not self.chosen or not self._same_conversation(self.chosen.id, self.chosen.name):
            return False
        if self.driver.read_draft() != '' or not content or any(c in content for c in '\r\n'):
            return False
        self.driver.type_literal(content)
        valid = self.driver.read_draft() == content
        self.draft = content if valid else None
        return valid

    def still_matches(self, recipient_id: str, recipient: str, content: str) -> bool:
        return self._same_conversation(recipient_id, recipient) and self.driver.read_draft() == content

    def sent_message_baseline(self, recipient_id: str, content: str) -> object:
        messages = self.driver.outgoing_messages()
        if messages is None or any(not item.id for item in messages):
            raise ValueError('cannot establish outgoing baseline')
        return frozenset(item.id for item in messages)

    def send_once(self) -> None:
        if not self.chosen or self.draft is None:
            raise ValueError('missing verified recipient or draft')
        expected = Conversation(self.service, self.chosen.id, self.chosen.name, True)
        self.driver.submit_once(expected, self.draft)

    def message_visible_after_send(self, recipient_id: str, content: str, baseline: object) -> bool:
        if not self.chosen or not self._same_conversation(recipient_id, self.chosen.name):
            return False
        messages = self.driver.outgoing_messages()
        if messages is None or not isinstance(baseline, frozenset):
            return False
        return any(m.id and m.id not in baseline and m.sender_is_user and m.text == content
                   and m.status in ('sent', 'delivered', 'seen') for m in messages)
