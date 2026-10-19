"""Bounded local diagnostics; transcript text is controlled by privacy config."""
from __future__ import annotations
import json
import logging


def trace(stage: str, turn: str, save_text: bool, text: str = '', **fields: object) -> None:
    record = {'stage': stage, 'turn': turn, **fields}
    if save_text:
        record['text'] = text[:1200]
    else:
        record['characters'] = len(text)
    logging.info('VOICE_TRACE %s', json.dumps(record, ensure_ascii=False))
