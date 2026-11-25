"""Scoped agent-desktop CLI client for guarded desktop actions.

The caller must enforce the current user's intent and any sensitive-action rules.
This client enforces window identity, snapshot provenance, and safe retry behavior.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


_REF = re.compile(r'@s[a-zA-Z0-9]+:e[0-9]+\Z')
_LINE = re.compile(r'\((-?\d+),(-?\d+)\)\s+([\w /-]+)\s+"([^"\r\n]*)"\s+(?:\[[^\]\r\n]+\]\s+)*\[action:')


class AgentBridgeError(RuntimeError):
    pass


class AgentTargetMissing(AgentBridgeError):
    """The scoped snapshot contains no matching target."""


def unique_ref_for_point(snapshot: dict, point, expected_line: str, operation: str) -> str:
    """Match an already-guarded Windows UIA target to exactly one agent ref."""
    match = _LINE.search(expected_line)
    if (not match or not isinstance(point, list) or len(point) != 2
            or not all(isinstance(v, int) for v in point)
            or [int(match.group(1)), int(match.group(2))] != point):
        raise AgentBridgeError('missing verified target')
    label = ' '.join(match.group(4).casefold().split())
    if not label:
        raise AgentBridgeError('unnamed target')
    role = re.sub(r'[^a-z0-9]', '', match.group(3).casefold())
    aliases = {'edit': {'edit', 'textfield', 'textarea', 'searchfield'},
               'textbox': {'edit', 'textfield', 'textarea', 'searchfield'},
               'combobox': {'combobox'}, 'button': {'button'},
               'link': {'link', 'hyperlink'}, 'hyperlink': {'link', 'hyperlink'},
               'text': {'text', 'statictext'}}
    roles = aliases.get(role, {role})
    hits, stack = [], [snapshot.get('tree')]
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        children = node.get('children', [])
        if isinstance(children, list):
            stack.extend(children)
        bounds = node.get('bounds')
        actions = node.get('available_actions', [])
        ref = node.get('ref_id')
        if (not isinstance(bounds, dict) or not isinstance(ref, str) or not _REF.fullmatch(ref)
                or node.get('identity_unproven')):
            continue
        try:
            inside = (bounds['x'] <= point[0] < bounds['x'] + bounds['width'] and
                      bounds['y'] <= point[1] < bounds['y'] + bounds['height'])
        except (KeyError, TypeError):
            continue
        same = ' '.join(str(node.get('name', '')).casefold().split()) == label
        same_role = re.sub(r'[^a-z0-9]', '', str(node.get('role', '')).casefold()) in roles
        node_role = str(node.get('role', '')).casefold()
        actionable = ('Click' in actions if operation == 'click' else
                      ((node_role in ('edit', 'textfield', 'textarea', 'searchfield', 'combobox', 'textbox')
                        and any(x in actions for x in ('SetValue', 'SetFocus')))
                       or (node_role == 'group' and {'SetValue', 'SetFocus'}.issubset(actions))))
        if inside and same and same_role and actionable:
            hits.append(ref)
    if not hits:
        raise AgentTargetMissing('target is missing')
    if len(hits) != 1:
        raise AgentBridgeError('target is ambiguous')
    return hits[0]


class AgentDesktopBridge:
    def __init__(self, binary: Path, window_id: str, identity_ok, authorize,
                 make_private, *, run=subprocess.run):
        if not re.fullmatch(r'w-[0-9]+', window_id):
            raise ValueError('invalid window id')
        self.binary = Path(binary)
        self.window_id, self.identity_ok, self.authorize = window_id, identity_ok, authorize
        self._run = run
        self.temp = tempfile.TemporaryDirectory(prefix='alex-agent-')
        try:
            make_private(self.temp.name)
            self.env = {**os.environ, 'AGENT_DESKTOP_HOME': self.temp.name}
            self.env.pop('AGENT_DESKTOP_SESSION', None)
            self.env.pop('AGENT_DESKTOP_AGENT_ID', None)
            self.session = ''
            self.refs: set[str] = set()
            self.action_uncertain = False
            start = self._call(['session', 'start', '--no-trace'])
            self.session = str(start.get('data', {}).get('session_id', ''))
            if not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', self.session):
                raise AgentBridgeError('cannot establish private session')
        except BaseException:
            self.temp.cleanup()
            raise

    def close(self):
        self.refs.clear()
        self.temp.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _call(self, args: list[str], *, text: str | None = None, action=False) -> dict:
        cmd = [str(self.binary)]
        if self.session:
            cmd += ['--session', self.session]
        cmd += args
        try:
            p = self._run(cmd, input=text, encoding='utf-8', errors='replace',
                          capture_output=True, env=self.env, timeout=20,
                          creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            reply = json.loads(p.stdout)
            if (not isinstance(reply, dict) or not isinstance(reply.get('ok'), bool)
                    or (p.returncode != 0 and reply.get('ok'))):
                raise ValueError('invalid envelope')
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            if action:
                self.action_uncertain = True
                self.refs.clear()
            raise AgentBridgeError('agent request failed; delivery may be unknown' if action
                                   else 'agent observation failed') from exc
        if action:
            # Even if the CLI reports failure, a mutation may have landed.
            self.refs.clear()
            if not reply['ok']:
                self.action_uncertain = True
        return reply

    def snapshot(self, *, max_depth: int = 10) -> dict:
        if not self.identity_ok():
            raise AgentBridgeError('target window changed')
        if max_depth not in (10, 30):
            raise AgentBridgeError('unsupported snapshot depth')
        reply = self._call(['snapshot', '--window-id', self.window_id,
                            '--compact', '--max-depth', str(max_depth), '--include-bounds', '--timeout-ms', '10000'])
        data = reply.get('data', {})
        if not reply.get('ok') or data.get('window', {}).get('id') != self.window_id:
            self.refs.clear()
            raise AgentBridgeError('snapshot target not verified')
        if data.get('complete') is not True or data.get('identity_unproven'):
            self.refs.clear()
            raise AgentBridgeError('snapshot is incomplete or identity unproven')
        refs, pending = set(), [data.get('tree')]
        while pending:
            node = pending.pop()
            if not isinstance(node, dict):
                continue
            ref = node.get('ref_id')
            if isinstance(ref, str) and _REF.fullmatch(ref):
                refs.add(ref)
            children = node.get('children', [])
            if isinstance(children, list):
                pending.extend(children)
        self.refs = refs
        return data

    def act(self, operation: str, ref: str, *, text: str = '') -> dict:
        if self.action_uncertain:
            raise AgentBridgeError('previous action has uncertain delivery')
        if operation not in ('click', 'type') or ref not in self.refs:
            raise AgentBridgeError('unsupported action or stale reference')
        if not self.identity_ok() or not self.authorize(operation, ref, text):
            raise AgentBridgeError('window or action not authorized')
        if operation == 'type':
            if (not text or len(text) > 1000 or
                    any(ord(c) < 32 or 127 <= ord(c) < 160 for c in text)):
                raise AgentBridgeError('text not eligible for this action')
            args = ['--headed', 'type', ref, '--stdin']
            return self._call(args, text=text, action=True)
        return self._call(['click', ref], action=True)

    def get_value(self, ref: str) -> dict:
        if ref not in self.refs or not self.identity_ok():
            raise AgentBridgeError('window or reference changed')
        return self._call(['get', ref, '--property', 'value'])

    def set_value_for_search(self, ref: str, text: str) -> dict:
        """Set an explicitly authorized search field once, never a message draft."""
        if (self.action_uncertain or ref not in self.refs or not self.identity_ok()
                or not self.authorize('search', ref, text)):
            raise AgentBridgeError('window or search field not authorized')
        if (not text or len(text) > 200 or
                any(ord(c) < 32 or 127 <= ord(c) < 160 for c in text)):
            raise AgentBridgeError('invalid search text')
        return self._call(['set-value', ref, '--stdin'], text=text, action=True)

    def focus_for_type(self, ref: str, text: str) -> dict:
        """Focus only the exact field authorized for this typing operation."""
        in_refs = ref in self.refs
        id_ok = self.identity_ok()
        auth_ok = self.authorize('type', ref, text)
        if self.action_uncertain or not in_refs or not id_ok or not auth_ok:
            raise AgentBridgeError(
                f'window or field not authorized (uncertain={self.action_uncertain}, '
                f'in_refs={in_refs}, id_ok={id_ok}, auth={auth_ok})'
            )
        return self._call(['--headed', 'focus', ref], action=True)

    def focus_for_observation(self, ref: str) -> dict:
        """Focus one explicitly authorized field only to inspect its state."""
        if (self.action_uncertain or ref not in self.refs or not self.identity_ok()
                or not self.authorize('focus_read', ref, '')):
            raise AgentBridgeError('window or observation field not authorized')
        return self._call(['--headed', 'focus', ref], action=True)

    def is_focused(self, ref: str) -> bool:
        """Check whether an observed reference currently holds keyboard focus."""
        if ref not in self.refs or not self.identity_ok():
            raise AgentBridgeError('window or reference changed')
        reply = self._call(['is', ref, '--property', 'focused'])
        return bool(reply.get('ok') and (reply.get('data') or {}).get('result') is True)

    def press_key(self, key: str) -> dict:
        """Send a single authorized key press (never retried on uncertain delivery)."""
        if self.action_uncertain or not self.identity_ok() or not self.authorize('key', '', key):
            raise AgentBridgeError('window or key press not authorized')
        return self._call(['--headed', 'press', key], action=True)

    def observe_deep_inputs(self, *, max_depth: int = 30, include_standard_roles: bool = False):
        """Return (snapshot_data, list[InputObservation]) without reading field values."""
        from .agent_input_observation import observe_inputs
        data = self.snapshot(max_depth=max_depth)
        return data, observe_inputs(data, include_standard_roles=include_standard_roles)
