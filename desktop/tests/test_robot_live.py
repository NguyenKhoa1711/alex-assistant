"""Exercise the actual Qt canvas with a dummy controller, never the microphone."""
from __future__ import annotations
import json
import os
from pathlib import Path
import sys
import threading
import time
import types

from PySide6.QtCore import QObject, Signal, QPoint, Qt
from PySide6.QtGui import QCursor, QFontDatabase, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

ROOT = Path(__file__).resolve().parent.parent
LIVE = Path(sys.argv[1])
package = types.ModuleType('pet'); package.__path__ = [str(ROOT/'pet'),str(LIVE/'pet')]
sys.modules['pet'] = package
for name, value in [('controller','Controller'),('mobile','MobileBridge')]:
    stub = types.ModuleType('pet.'+name); setattr(stub,value,object); sys.modules[stub.__name__]=stub
from pet import window as module
from pet.robot_live import local_document_allowed
from PySide6.QtCore import QUrl

class Engine(QObject):
    state=Signal(str,str); transcript=Signal(str); reply=Signal(str)
    timing=Signal(str); confirmation=Signal(str,object); finished=Signal()
    def __init__(self):
        super().__init__(); self.paused=threading.Event(); self.paused.set()
        self.mic=None; self.learning=None; self.toggles=0
    def toggle(self): self.toggles+=1
    def interrupt(self): pass
    def stop(self): pass
    def isRunning(self): return False
class Hotkey:
    registered=True
    def __init__(self,*args): pass
    def close(self): pass
class Tray(QObject):
    activated=Signal(object); MessageIcon=QSystemTrayIcon.MessageIcon
    ActivationReason=QSystemTrayIcon.ActivationReason
    def __init__(self,*args): super().__init__()
    def setToolTip(self,*args): pass
    def setContextMenu(self,*args): pass
    def showMessage(self,*args): pass
    def show(self): pass

def wait_for(check, seconds=10):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        app.processEvents()
        if check(): return
        QTest.qWait(20)
    raise AssertionError('Timed out waiting for canvas')

def js(code):
    result=[]
    view.page().runJavaScript(code, lambda value:result.append(value))
    wait_for(lambda:bool(result))
    return result[0]

def debug(): return json.loads(js('JSON.stringify(window.alexRobot.debug())'))

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
app=QApplication([]); app.setQuitOnLastWindowClosed(False)
QFontDatabase.addApplicationFont('C:/Windows/Fonts/segoeui.ttf')
module.ROOT=ROOT; module.GlobalHotkey=Hotkey; module.QSystemTrayIcon=Tray
cfg={'name':'Alex', 'pet':{'shape':'robot-heads','size':110,'x':700,'y':260,'fps':30,'start_hidden':True}}
win=module.PetWindow(cfg,Engine()); win.setWindowTitle('Alex robot test — NO MICROPHONE')
win.save_position=lambda:None
win.show()
original_cursor=QCursor.pos()
report={}
try:
    view=win.live_robot
    assert view is not None
    wait_for(lambda:view.ready or view.failed,20)
    assert view.ready and not view.failed, 'Renderer failed to load'
    win.set_state('listening','Thử biểu cảm đang nghe · mic thử luôn tắt')
    center=view.mapToGlobal(QPoint(view.width()//2,round(view.height()*.56)))
    pictures=[]
    for name, offset in [('left',QPoint(-350,0)),('right',QPoint(350,0)),
                         ('up',QPoint(0,-220)),('down',QPoint(0,220))]:
        QCursor.setPos(center+offset)
        QTest.qWait(1000)
        report[name]=debug()
        pictures.append(win.grab())
    assert report['left']['pose']['yaw'] < -.3
    assert report['right']['pose']['yaw'] > .3
    assert report['left']['eyes']['x'] < 0 < report['right']['eyes']['x']
    assert report['up']['pose']['pitch'] > .15 > report['down']['pose']['pitch']
    assert report['up']['eyes']['y'] < 0 < report['down']['eyes']['y']
    assert win.engine.paused.is_set(), 'Gaze must not enable the microphone'
    report['renderer_pid']=view.page().renderProcessPid()
    report['off_the_record']=view.profile.isOffTheRecord()
    assert report['off_the_record']
    for url in ['https://example.com/','http://127.0.0.1:8768/','file:///C:/Windows/win.ini','ftp://example.com']:
        assert not local_document_allowed(QUrl(url))
    js("window._networkBlocked=''; document.addEventListener('securitypolicyviolation', e => window._networkBlocked=e.violatedDirective); fetch('https://example.com/').catch(()=>{});")
    wait_for(lambda:js('window._networkBlocked')=='connect-src')
    point=win.mapToGlobal(QPoint(110,170))
    target=app.widgetAt(point)
    assert target is win, f'Canvas intercepted input: {target}'
    QTest.mouseClick(win,Qt.MouseButton.LeftButton,pos=QPoint(110,170))
    assert win.engine.toggles==1
    old=win.pos()
    QTest.mousePress(win,Qt.MouseButton.LeftButton,pos=QPoint(110,170))
    QTest.mouseMove(win,QPoint(145,190),40)
    QTest.mouseRelease(win,Qt.MouseButton.LeftButton,pos=QPoint(145,190))
    assert win.pos()!=old and win.engine.toggles==1
    for mode in ['listening','thinking','speaking','error','paused']:
        win.engine.state.emit(mode,mode); QTest.qWait(150)
        assert debug()['state']==('sleeping' if mode=='paused' else mode)
    win.toggle_follow_cursor(False); QTest.qWait(150)
    assert debug()['pointer'] is None and debug()['state']=='sleeping'
    win.toggle_follow_cursor(True); QTest.qWait(150)
    win.hide(); QTest.qWait(150); frozen=debug()['draws']
    QTest.qWait(300)
    assert debug()['draws']==frozen and not debug()['active']
    win.show(); QTest.qWait(150); assert debug()['draws']>frozen
    win.change_shape('mascot'); QTest.qWait(150); assert not view.isVisible()
    win.change_shape('robot-heads'); QTest.qWait(150); assert view.isVisible()
    QTest.qWait(1000)
    before=debug(); started=time.perf_counter(); QTest.qWait(5000); after=debug()
    delta=after['draws']-before['draws']
    report['steady']={'fps':delta/(time.perf_counter()-started),
                     'draw_ms':(after['meanDrawMs']*after['draws']-before['meanDrawMs']*before['draws'])/max(1,delta)}
    report['host_pid']=os.getpid()
    board=QImage(win.width()*4,win.height(),QImage.Format.Format_ARGB32)
    board.fill(Qt.GlobalColor.white); p=QPainter(board)
    for i,pix in enumerate(pictures): p.drawPixmap(i*win.width(),0,pix)
    p.end(); board.save(str(ROOT/'cursor-preview.png'))
    report['final']=debug()
    (ROOT/'live-test-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('PASS: four directions, mic stays paused, states, click/drag, toggle, hidden freeze, legacy shape, offline isolation.')
    print(json.dumps({'steady':report['steady'],'host_pid':os.getpid(),'renderer_pid':report['renderer_pid']}),flush=True)
    if '--hold-preview' in sys.argv:
        QTest.qWait(30000)
finally:
    QCursor.setPos(original_cursor)
    win.hide()
    if win.live_robot is not None:
        win.live_robot.shutdown()
        win.live_robot.page().deleteLater()
    win.robot_head.close()
    app.processEvents()
