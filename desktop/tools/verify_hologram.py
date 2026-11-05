"""Offscreen verification only; no live mic, camera or OS commands."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import sys,json,time,unittest,io
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root),str(root/'tests')]
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont,QFontDatabase,QImage,QPainter,QColor
import pet.app_window as ui
import pet.space_view as sv
from pet.hologram_face import HologramFace
from test_app_window import FakeEngine,MagicMock,QIcon
app=QApplication.instance() or QApplication([])
if len(sys.argv)>1: ui.ROOT=sv.ROOT=Path(sys.argv[1])
for f in ('segoeui.ttf','segoeuib.ttf','seguisb.ttf'):
    QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR'])/'Fonts'/f))
app.setFont(QFont('Segoe UI',10))
suite=unittest.TestSuite()
for name in ('test_app_window','test_space_view','test_camera_session','test_hologram_center'):
    suite.addTests(unittest.defaultTestLoader.loadTestsFromName(name))
out=io.StringIO()
with patch('os.startfile',side_effect=AssertionError('No live OS commands allowed')):
    result=unittest.TextTestRunner(stream=out,verbosity=2).run(suite)
pet=MagicMock(); pet.windowIcon.return_value=QIcon(); pet.isVisible.return_value=False
engine=FakeEngine(); window=ui.AlexAppWindow(engine,pet)
window.resize(1280,860); window.show(); window._show_page('center'); app.processEvents()
page=window.center_page
page.reactor.timer.stop(); page.reactor.phase=.4
engine.paused.clear(); engine.state.emit('listening','')
for _ in range(30): page.reactor._advance(1/30)
app.processEvents()
window.grab().save(str(root/'hologram-listening.png'))
engine.paused.set(); engine.state.emit('paused','')
for _ in range(30): page.reactor._advance(1/30)
app.processEvents()
window.grab().save(str(root/'hologram-paused.png'))
window.resize(800,650); app.processEvents()
window.grab().save(str(root/'hologram-compact.png'))
face=HologramFace(); face.resize(520,520); face.set_mode('speaking')
for _ in range(30): face._advance(1/30)
sheet=QImage(1500,340,QImage.Format.Format_ARGB32); sheet.fill(QColor('#10232c'))
canvas=QPainter(sheet); canvas.setFont(QFont('Segoe UI',11)); canvas.setPen(QColor('#c7eee7'))
portrait=HologramFace(); portrait.resize(300,300)
for i,(mode,label) in enumerate((('paused','Mic tắt'),('listening','Đang nghe'),('thinking','Đang xử lý'),('speaking','Đang nói'),('error','Cần kiểm tra'))):
    portrait.set_mode(mode)
    for _ in range(45): portrait._advance(1/30)
    portrait.phase=.75
    canvas.drawPixmap(i*300,0,portrait.grab()); canvas.drawText(i*300+100,325,label)
canvas.end(); sheet.save(str(root/'face-refresh-expressions.png')); portrait.deleteLater()
times=[]
for i in range(60):
    face._advance(1/30); start=time.perf_counter(); face.grab()
    times.append((time.perf_counter()-start)*1000)
moving=[]
for i in range(60):
    face.target_yaw=.24 if i<30 else -.24; face.target_pitch=.06 if i<30 else -.06
    face._advance(1/30); start=time.perf_counter(); face.grab()
    moving.append((time.perf_counter()-start)*1000)
face.hide(); window.hide(); window.avatar.robot.close()
report={'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
        'passed':result.wasSuccessful(),'hologram_render_mean_ms':round(sum(times)/len(times),2),
        'hologram_render_p95_ms':round(sorted(times)[56],2),'animation_max_fps':30,
        'moving_render_mean_ms':round(sum(moving)/len(moving),2),
        'moving_render_p95_ms':round(sorted(moving)[56],2),
        'live_mic_tested':False,'camera_opened':False,'fixtures':'QApplication offscreen; fake controller'}
(root/'hologram-tests.txt').write_text(out.getvalue(),encoding='utf-8')
(root/'hologram-tests.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report))
if not result.wasSuccessful(): print(out.getvalue())
sys.exit(not result.wasSuccessful())
