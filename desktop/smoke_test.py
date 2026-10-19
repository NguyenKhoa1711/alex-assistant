"""Local integration check. Synthetic speech is not a microphone accuracy test."""
from __future__ import annotations
import os
os.environ.update(HF_HUB_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1')
import json
import threading
import time
import numpy as np
from pet.config import load_config
from pet.stt import SpeechToText
from pet.tts import Speaker
from pet.llm import LocalChat
from pet.wake import extract_wake, speech_text

cfg = load_config()
speaker = Speaker(cfg['tts'], cfg['audio']['output_device'])
stt = SpeechToText(cfg['stt'], print)
phrase = 'A lếch, hai cộng ba bằng mấy?'
chunks = list(speaker.voice.synthesize(phrase))
audio = np.concatenate([np.frombuffer(c.audio_int16_bytes, dtype=np.int16) for c in chunks]).astype(np.float32) / 32768
rate = chunks[0].sample_rate
audio = np.interp(np.arange(0, len(audio), rate / 16000), np.arange(len(audio)), audio).astype(np.float32)
text, elapsed = stt.transcribe(audio)
print(json.dumps({'synthetic_phrase': phrase, 'recognized': text, 'stt_seconds': elapsed,
                  'wake': extract_wake(text, cfg['wake']['aliases'])}, ensure_ascii=False), flush=True)
chat = LocalChat(cfg['llm'], cfg['name'])
cancel = threading.Event()
answer = ''.join(chat.stream('Hai cộng ba bằng mấy? Trả lời một câu ngắn.', cancel))
print(json.dumps({'answer': answer, 'first_token_seconds': chat.first_token_seconds}, ensure_ascii=False), flush=True)
first = speaker.speak(speech_text(answer, cfg['name'], cfg['spoken_name']), cancel, lambda value: print(f'Piper first PCM: {value:.3f}s', flush=True))
print('LOCAL INTEGRATION OK', flush=True)
