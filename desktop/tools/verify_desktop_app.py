"""Focused regression with live settings in memory and external actions denied.

Some legacy preview scripts replace sys.modules and require positional paths;
they are not compatible with blanket unittest discovery. Run only true suites.
"""
from pathlib import Path
from copy import deepcopy
import contextlib
import io
import json
import os
import platform
import socket
import subprocess
import sys
import unittest
from unittest.mock import patch

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout.reconfigure(encoding='utf-8')
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
platform.uname()
import sounddevice
import yaml
cfg = yaml.safe_load((Path(sys.argv[1])/'config.yaml').read_text('utf-8'))

def config():
    value = deepcopy(cfg)
    value.setdefault('learning', {})['enabled'] = False
    value.setdefault('privacy', {})['save_transcripts'] = False
    return value

def denied(*args, **kwargs):
    raise AssertionError('Unmocked external action during regression')

connect = socket.socket.connect
def local_only(sock, address):
    if isinstance(address, tuple) and address[0] not in {'127.0.0.1', 'localhost', '::1'}:
        raise AssertionError('External network not allowed during regression')
    return connect(sock, address)

names = ['core', 'apps', 'incomplete_open', 'phonetic_real_mic', 'dialogue',
         'learning', 'power', 'background_launcher', 'window_state',
         'close_actions', 'device_actions', 'files', 'mobile', 'voice_diagnostics',
         'controller', 'desktop_requests', 'app_window']
with contextlib.ExitStack() as stack:
    stack.enter_context(patch('pet.config.load_config', side_effect=config))
    stack.enter_context(patch('subprocess.Popen', side_effect=denied))
    stack.enter_context(patch('subprocess.run', side_effect=denied))
    stack.enter_context(patch('os.startfile', side_effect=denied))
    stack.enter_context(patch.object(socket.socket, 'connect', local_only))
    suite = unittest.TestSuite()
    for name in names:
        suite.addTests(unittest.defaultTestLoader.discover(str(root/'tests'), pattern='test_'+name+'.py'))
    output = io.StringIO()
    result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
    (root/'focused-tests.txt').write_text(output.getvalue(), encoding='utf-8')
    summary = {'tests':result.testsRun, 'failures':len(result.failures), 'errors':len(result.errors),
               'passed':result.wasSuccessful(), 'names':names,
               'failed_tests':[str(t) for t,_ in result.failures+result.errors]}
    (root/'focused-tests.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))
sys.exit(not result.wasSuccessful())
