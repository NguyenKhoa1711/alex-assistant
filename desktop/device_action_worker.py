"""One local device request per process; no resident service or shell commands."""
import json
import sys
from pet.app_actions import Action
from pet.device_actions import execute_device_action

if __name__ == '__main__':
    try:
        action = Action(**json.load(sys.stdin))
        result = execute_device_action(action)
    except Exception as exc:
        result = {'message': str(exc)[:240] if isinstance(exc, (RuntimeError, ValueError)) else
                  'Windows chưa cho điều chỉnh âm lượng hoặc độ sáng. Mình chưa xác nhận thay đổi.',
                  'verified': False, 'error_type': type(exc).__name__}
    print(json.dumps(result, ensure_ascii=False), flush=True)
