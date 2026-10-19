"""Integration test: sends a visible test question to the native Bionic chat."""
import threading
from pet.bionic import BionicChat
from pet.config import load_config
from pet.tts import Speaker
from pet.wake import speech_text

cfg = load_config()
chat = BionicChat(cfg['bionic'])
speaker = Speaker(cfg['tts'], cfg['audio']['output_device'])
cancelled = threading.Event()
for reply in chat.stream('Câu thử giọng pet: hai cộng hai bằng mấy? Chỉ trả lời một câu ngắn.', cancelled):
    print('BIONIC:', reply, flush=True)
    print(f'Bionic native reply: {chat.response_seconds:.2f}s', flush=True)
    speaker.speak(speech_text(reply, cfg['name'], cfg['spoken_name']), cancelled,
                  lambda value: print(f'Piper first output: {value:.3f}s', flush=True))
print('NATIVE VOICE OK', flush=True)
