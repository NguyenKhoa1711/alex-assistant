"""Exercise the real local model and Windows MCP using a harmless test task."""
import json
import sys
import threading
from pet.computer import Computer
from pet.config import load_config, ROOT
from pet.llm import LocalChat

cfg = load_config()
cancel = threading.Event()
def reject(description, decision):
    print('NEEDS REVIEW: ' + description, flush=True)
    decision.allowed = False
    decision.done.set()
computer = Computer(cfg['computer'], lambda text: print(text, flush=True), reject)
try:
    schemas = computer.tools(cancel)
    (ROOT / 'tool-schemas.json').write_text(json.dumps(schemas, ensure_ascii=False, indent=2), encoding='utf-8')
    print('TOOLS: ' + ', '.join(s['function']['name'] for s in schemas), flush=True)
    chat = LocalChat(cfg['llm'], cfg['name'])
    chat.computer = computer
    chat.computer_enabled = True
    question = sys.argv[1] if len(sys.argv) > 1 else 'Mở ứng dụng Máy tính Calculator giúp tôi.'
    print('REQUEST: ' + question, flush=True)
    for text in chat.stream(question, cancel):
        print('ANSWER: ' + text, flush=True)
    print('TTFT: ' + str(chat.first_token_seconds), flush=True)
finally:
    computer.close()
