"""Bounded UI + gesture process checks; no live mic/camera/PC actions."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root),str(root/'tests')]
import contextlib
import io
import json
import time
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from pet.space_view import OrbitCanvas, SpacePage
import pet.app_window as ui
import pet.space_view as sv

if len(sys.argv)>1: ui.ROOT=sv.ROOT=Path(sys.argv[1])

suite=unittest.TestSuite()
for name in ('test_app_window','test_space_view','test_camera_session'):
    suite.addTests(unittest.defaultTestLoader.loadTestsFromName(name))
output=io.StringIO()
with patch('os.startfile',side_effect=AssertionError('No desktop actions in this test')):
    result=unittest.TextTestRunner(stream=output,verbosity=2).run(suite)
app=QApplication.instance() or QApplication([])
canvas=OrbitCanvas(); canvas.resize(1000,500); canvas.show(); app.processEvents()
timings=[]
for i in range(80):
    canvas.days=i*3
    started=time.perf_counter(); canvas.grab()
    timings.append((time.perf_counter()-started)*1000)
canvas.hide(); canvas.deleteLater(); app.processEvents()
page=SpacePage(); page.resize(1050,780); page.show(); app.processEvents()
page.canvas.timer.stop()
detail_times=[]
for i in range(60):
    page.canvas.days=i*2; page.canvas.seconds=i/20
    page.portrait.set_time(i/20)
    start=time.perf_counter(); page.grab()
    detail_times.append((time.perf_counter()-start)*1000)
page.hide(); page.camera.shutdown(); page.deleteLater(); app.processEvents()
report={'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
        'passed':result.wasSuccessful(),'offscreen_render_ms_mean':round(sum(timings)/len(timings),2),
        'offscreen_render_ms_p95':round(sorted(timings)[int(.95*len(timings))],2),
        'whole_page_animated_mean_ms':round(sum(detail_times)/len(detail_times),2),
        'whole_page_animated_p95_ms':round(sorted(detail_times)[int(.95*len(detail_times))],2),
        'camera_opened':False,'live_mic_tested':False,
        'notes':'Qt offscreen fixture; camera protocol uses a synthetic child, no hardware.'}
(root/'orbit-tests.txt').write_text(output.getvalue(),encoding='utf-8')
(root/'orbit-tests.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report))
if not result.wasSuccessful(): print(output.getvalue())
sys.exit(not result.wasSuccessful())
