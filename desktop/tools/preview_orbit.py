"""Offscreen fixtures only. Does not open camera/mic or control live windows."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import sys
import json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root),str(root/'tests')]
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont,QFontDatabase
from PySide6.QtTest import QTest
from test_app_window import FakeEngine,MagicMock,QIcon
import pet.app_window as ui
import pet.command_center as cc
import pet.space_view as sv

app=QApplication([])
for font in ('segoeui.ttf','segoeuib.ttf','seguisb.ttf'):
    QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR'])/'Fonts'/font))
app.setFont(QFont('Segoe UI',10))
ui.ROOT=sv.ROOT=Path(sys.argv[1])
pet=MagicMock(); pet.windowIcon.return_value=QIcon(); pet.isVisible.return_value=True
window=ui.AlexAppWindow(FakeEngine(),pet)
window.resize(1280,860); window.show()
sizes={}
for name in ('center','space','chat'):
    window._show_page(name); window._state('paused',''); QTest.qWait(350); app.processEvents()
    window.grab().save(str(root/f'preview-{name}.png'))
    sizes[name]=[window.width(),window.height()]
window.resize(960,720); window._show_page('space'); app.processEvents()
window.grab().save(str(root/'preview-space-small.png'))
sizes['small']=[window.width(),window.height()]
window.resize(800,580)
for _ in range(3): app.processEvents()
window.grab().save(str(root/'preview-space-compact.png'))
sizes['compact']=[window.width(),window.height()]
window.resize(1280,860); window.space_page.pick.setCurrentIndex(5)
app.processEvents(); window.grab().save(str(root/'preview-space-saturn.png'))
print(json.dumps(sizes))
window.hide(); window.space_page.camera.shutdown()
window.avatar.robot.close(); window.center_page.set_active(False)
