"""Read-only, privacy-minimized observation of agent-desktop input controls.

This module does not authorize or perform any action. Callers must bind an
observation to the same foreground window and re-observe before acting.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import re

_REF = re.compile(r'@s[a-zA-Z0-9]+:e[0-9]+\Z')
_ID = re.compile(r'[A-Za-z0-9_.:-]{1,100}\Z')
_STANDARD_INPUT_ROLES = ('edit', 'textfield', 'textarea', 'searchfield', 'combobox', 'textbox')


@dataclass(frozen=True)
class InputObservation:
    identity: str
    point: tuple[int, int]
    # Only for an immediate action in this same agent session; never persist it.
    ref: str
    role: str = 'group'


def observe_inputs(snapshot: dict, *, include_standard_roles: bool = False) -> list[InputObservation]:
    """Find unambiguous named UIA input identities without reading their values.

    Generic group controls qualify only when the accessibility provider exposes
    both SetValue and SetFocus. Standard input roles (edit/textfield/...) also
    qualify when ``include_standard_roles=True`` and they expose SetFocus.
    A deep traversal is not proof that the entire app's tree is present:
    ambiguity or an unproven node is rejected locally.
    """
    if not isinstance(snapshot, dict) or snapshot.get('complete') is not True or snapshot.get('identity_unproven'):
        return []
    found = []
    stack = [snapshot.get('tree')]
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        children = node.get('children')
        if isinstance(children, list):
            stack.extend(children)
        role = str(node.get('role') or '').casefold()
        if node.get('identity_unproven'):
            continue
        if role == 'group':
            required_actions = {'SetValue', 'SetFocus'}
        elif include_standard_roles and role in _STANDARD_INPUT_ROLES:
            required_actions = {'SetFocus'}
        else:
            continue
        actions = node.get('available_actions')
        native = node.get('native_id')
        ref = node.get('ref_id')
        if (not isinstance(actions, list) or not required_actions.issubset(actions)
                or not isinstance(native, dict) or not isinstance(native.get('kind'), str)
                or not isinstance(native.get('value'), str) or not _ID.fullmatch(native['value'])
                or not isinstance(ref, str) or not _REF.fullmatch(ref)):
            continue
        bounds = node.get('bounds')
        try:
            values = [bounds[k] for k in ('x', 'y', 'width', 'height')]
            if (any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values)
                    or values[2] <= 0 or values[3] <= 0):
                continue
            x, y, width, height = values
            point = (int(x + width / 2), int(y + height / 2))
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        # Never derive this identifier from a field's value, label, or content.
        payload = (native['kind'] + '\0' + native['value']).encode('utf-8')
        identity = hashlib.sha256(payload).hexdigest()[:16]
        found.append(InputObservation(identity, point, ref, role=role))
    # Duplicate automation identities or coincident centers cannot be safely
    # distinguished by a coordinate-based caller.
    return [item for item in found
            if sum(x.identity == item.identity for x in found) == 1
            and sum(x.point == item.point for x in found) == 1]


def rematch(observation: InputObservation, fresh_snapshot: dict,
            *, include_standard_roles: bool = False) -> InputObservation | None:
    """Reject changed/missing geometry or identity; return the fresh session ref."""
    matches = [item for item in observe_inputs(fresh_snapshot, include_standard_roles=include_standard_roles)
               if item.identity == observation.identity and item.point == observation.point]
    return matches[0] if len(matches) == 1 else None
