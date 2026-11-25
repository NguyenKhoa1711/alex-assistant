"""Select a single, exact contact or group without guessing between names."""
from __future__ import annotations

from dataclasses import dataclass
import unicodedata


@dataclass(frozen=True)
class Candidate:
    id: str
    name: str
    kind: str
    can_send: bool = True


def normalized_name(value: str) -> str:
    # Preserve accents: An and Ân must remain distinct people.
    return ' '.join(unicodedata.normalize('NFC', value).casefold().split())


def exact_candidate(name: str, candidates: list[Candidate]) -> Candidate | None:
    wanted = normalized_name(name)
    if not wanted or not isinstance(candidates, list):
        return None
    matches = [x for x in candidates if x.id and x.kind in ('person', 'group')
               and normalized_name(x.name) == wanted]
    if len(matches) != 1 or not matches[0].can_send:
        return None
    return matches[0]
