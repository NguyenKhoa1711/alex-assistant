"""Native holographic command center with actual worker state and PC metrics."""
from __future__ import annotations
import ctypes
import os
import time
from collections import deque
from PySide6.QtCore import Qt, QTimer, QPointF, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFrame
from .hologram_face import HologramFace
from .space_view import text, action

HUD_STYLE='''
QWidget#commandPage { background: #08151d; }
QWidget#commandPage QLabel { color: #d3e5e9; background: transparent; }
QWidget#commandPage QLabel#subtle { color: #93adb7; font-size: 11px; }
QWidget#commandPage QLabel#hudTitle { color: #eef8f7; font-size: 27px; font-weight: 600; }
QWidget#commandPage QLabel#hudBrand { color: #87cfc9; font-size: 11px; font-weight: 600; }
QWidget#commandPage QLabel#hudStatus { color: #e1f5f2; font-size: 22px; font-weight: 600; }
QWidget#commandPage QLabel#metricValue { color: #d5f0ed; font-size: 20px; font-weight: 600; }
QWidget#commandPage QFrame#hudPanel { background: #10232c; border: 1px solid #24414b; border-radius: 16px; }
QWidget#commandPage QFrame#facePanel { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #102b36,stop:0.55 #0c202e,stop:1 #0b1725); border: 1px solid #2a4c58; border-radius: 20px; }
QWidget#commandPage QPushButton { background: #172e38; color: #cde4e7; border: 1px solid #2b4a54;
    border-radius: 10px; padding: 10px 13px; font-size: 12px; text-align: left; }
QWidget#commandPage QPushButton:hover { background: #21414a; border-color: #70bdb8; }
QWidget#commandPage QPushButton:pressed { background: #2b545b; }
QWidget#commandPage QPushButton:disabled { color: #647e88; background: #11252e; border-color: #243c46; }
QWidget#commandPage QPushButton#hudMic { background: #a4e4d6; color: #113e40; border: none; font-weight: 600; font-size: 14px; padding: 13px; text-align: center; }
QWidget#commandPage QPushButton#hudMic:hover { background: #c3f3e5; }
QWidget#commandPage QPushButton#hudMic:disabled { background: #26474e; color: #91b0b2; }
QWidget#commandPage QPushButton#hudStop { color: #c6d9dd; background: transparent; }
QWidget#commandPage QPushButton#quietMotion { background: transparent; border: 1px solid #2f535d; font-size: 11px; padding: 7px 10px; }
QWidget#commandPage QPushButton:checked { color: #c2efe4; background: #294f53; border-color: #72b9ad; }
'''

SIDEBAR_STYLE='''
QFrame#sidebar { background: #0b1c23; border-right: 1px solid #223941; }
QFrame#sidebar QLabel { color: #c7dddf; }
QFrame#sidebar QLabel#brand { color: #e0f8f3; }
QFrame#sidebar QLabel#eyebrow, QFrame#sidebar QLabel#sideNote { color: #87a8b0; }
QFrame#sidebar QPushButton#newChat { background: #1a383f; color: #caeee5; border: 1px solid #36565d; border-radius: 12px; }
QFrame#sidebar QPushButton#nav { color: #aec6ce; }
QFrame#sidebar QPushButton#nav:hover { background: #163039; }
QFrame#sidebar QPushButton#nav:checked { background: #23434a; color: #cdf6eb; border-left: 3px solid #9edbc9; border-radius: 10px; }
'''

class MachineMetrics:
    def __init__(self): self.previous=None

    def sample(self):
        if os.name != 'nt': return '—','—'
        from ctypes import wintypes
        class Memory(ctypes.Structure):
            _fields_=[('length',wintypes.DWORD),('load',wintypes.DWORD)]+[
                (n,ctypes.c_ulonglong) for n in ('total','free','totalPage','freePage','totalVirtual','freeVirtual','extended')]
        state=Memory(); state.length=ctypes.sizeof(state); memory='—'
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state)):
            memory=f'{(state.total-state.free)/2**30:.1f} / {state.total/2**30:.1f} GB'
        idle,kernel,user=(wintypes.FILETIME() for _ in range(3)); cpu='Đang đo…'
        if ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle),ctypes.byref(kernel),ctypes.byref(user)):
            values=[v.dwHighDateTime*2**32+v.dwLowDateTime for v in (idle,kernel,user)]
            if self.previous:
                delta=[a-b for a,b in zip(values,self.previous)]; total=delta[1]+delta[2]
                if total > 0: cpu=f'{max(0,min(100,(1-delta[0]/total)*100)):.0f}%'
            self.previous=values
        return cpu,memory

class MetricTrace(QWidget):
    """Up to one minute of real local measurements; no generated data."""
    def __init__(self):
        super().__init__(); self.samples=deque(maxlen=30); self.setFixedHeight(29)

    def add(self,value):
        self.samples.append(None if value is None else max(0,min(100,float(value)))); self.update()

    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor('#24414a'),1))
        for y in (7,17,28): p.drawLine(0,y,self.width(),y)
        p.setPen(QPen(QColor('#89d8ce'),1.3)); segment=[]
        for i,value in enumerate(self.samples):
            if value is None:
                if len(segment)>1: p.drawPolyline(QPolygonF(segment))
                segment=[]; continue
            segment.append(QPointF(self.width()*(30-len(self.samples)+i)/29,27-value*.24))
        if len(segment)>1: p.drawPolyline(QPolygonF(segment))
        p.end()

def panel(name='hudPanel'):
    frame=QFrame(); frame.setObjectName(name)
    box=QVBoxLayout(frame); box.setContentsMargins(15,15,15,15); box.setSpacing(10)
    return frame,box

class CommandCenter(QWidget):
    chat_requested=Signal()
    space_requested=Signal()
    mic_requested=Signal()
    stop_requested=Signal()
    command_requested=Signal(str)

    def __init__(self,parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,True)
        self.setObjectName('commandPage'); self.setStyleSheet(HUD_STYLE)
        self.active=False; self.metrics=MachineMetrics(); self.compact=None
        layout=QVBoxLayout(self); layout.setContentsMargins(24,22,24,20); layout.setSpacing(14)
        header=QHBoxLayout(); title=QVBoxLayout(); title.setSpacing(4)
        title.addWidget(text('KHÔNG GIAN CỦA BẠN','hudBrand'))
        title.addWidget(text('Trạm chỉ huy','hudTitle')); header.addLayout(title,1)
        self.clock=text('','subtle'); self.clock.setAlignment(Qt.AlignmentFlag.AlignRight)
        header.addWidget(self.clock); layout.addLayout(header)
        self.body=QGridLayout(); self.body.setSpacing(14); layout.addLayout(self.body,1)

        self.face_panel,face_box=panel('facePanel'); face_box.setContentsMargins(16,14,16,13); face_box.setSpacing(6)
        identity=QHBoxLayout(); identity.addWidget(text('A L E X','hudBrand'),1)
        self.badge=text('●  MIC ĐANG TẮT','subtle'); self.badge.setMinimumWidth(126)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignRight); identity.addWidget(self.badge)
        face_box.addLayout(identity)
        self.reactor=HologramFace(); face_box.addWidget(self.reactor,1)
        face_footer=QHBoxLayout()
        self.follow_note=text('Di chuột để Alex nhìn theo','subtle'); face_footer.addWidget(self.follow_note,1)
        self.motion=action('Giảm chuyển động',lambda:None); self.motion.setObjectName('quietMotion'); self.motion.setCheckable(True)
        self.motion.toggled.connect(self.reactor.set_reduced_motion)
        self.motion.setAccessibleName('Giảm chuyển động khuôn mặt hologram'); face_footer.addWidget(self.motion)
        face_box.addLayout(face_footer)

        self.controls,controls=panel(); controls.setContentsMargins(17,17,17,17); controls.setSpacing(10)
        controls.addWidget(text('TRÒ CHUYỆN CÙNG ALEX','hudBrand'))
        self.mode=text('Đang khởi động','hudStatus',True); controls.addWidget(self.mode)
        self.caption=text('Đang kết nối bộ xử lý Alex.','subtle',True); self.caption.setMaximumHeight(54); controls.addWidget(self.caption)
        controls.addStretch(1)
        self.mic=action('Bật mic',self.mic_requested.emit); self.mic.setObjectName('hudMic'); controls.addWidget(self.mic)
        controls.addWidget(action('Nhập tin nhắn  →',self.chat_requested.emit))
        self.stop=action('Dừng tác vụ',self.stop_requested.emit); self.stop.setObjectName('hudStop'); controls.addWidget(self.stop)

        self.telemetry,stats=panel(); stats.setContentsMargins(17,14,17,14); stats.setSpacing(8)
        stats.addWidget(text('LAPTOP CỦA BẠN','hudBrand'))
        self.values={}; self.traces={}; readings=QHBoxLayout(); readings.setSpacing(14)
        for name,label in (('cpu','CPU'),('ram','BỘ NHỚ')):
            column=QVBoxLayout(); column.setSpacing(3); column.addWidget(text(label,'subtle'))
            value=text('—','metricValue'); self.values[name]=value; column.addWidget(value)
            trace=MetricTrace(); self.traces[name]=trace; column.addWidget(trace); readings.addLayout(column,1)
        self.values['ram'].setStyleSheet('font-size:12px;font-weight:600;')
        stats.addLayout(readings)
        self.values['privacy']=text('Hội thoại chỉ giữ trong phiên','subtle',True); stats.addWidget(self.values['privacy'])
        stats.addWidget(text('Số đo thực · cập nhật mỗi 2 giây','subtle'))

        actions=QHBoxLayout(); actions.setSpacing(10)
        actions.addWidget(action('HỌC TẬP  ↗',lambda:self.command_requested.emit('Mở thư mục HỌC TẬP cho tôi')),1)
        actions.addWidget(action('YouTube  ↗',lambda:self.command_requested.emit('Mở YouTube cho tôi')),1)
        actions.addWidget(action('Vũ trụ Alex  ↗',self.space_requested.emit),1)
        layout.addLayout(actions)
        last,box=panel(); box.setContentsMargins(17,12,17,12); box.setSpacing(5)
        box.addWidget(text('LỜI NHẮN TỪ ALEX','hudBrand'))
        self.latest=text('Mình ở đây. Bật mic hoặc nhập tin nhắn để bắt đầu.','',True)
        self.latest.setMaximumHeight(44); box.addWidget(self.latest); layout.addWidget(last)
        self.timer=QTimer(self); self.timer.setInterval(2000); self.timer.timeout.connect(self._sample)
        self._layout_panels(False)

    def _layout_panels(self,compact):
        if compact == self.compact: return
        self.compact=compact
        for widget in (self.telemetry,self.face_panel,self.controls): self.body.removeWidget(widget)
        self.telemetry.setVisible(not compact); self.follow_note.setVisible(not compact)
        rail_width=182 if compact else 226
        self.controls.setFixedWidth(rail_width); self.telemetry.setFixedWidth(rail_width)
        self.body.addWidget(self.face_panel,0,0,2,1)
        if compact:
            self.body.addWidget(self.controls,0,1,2,1)
        else:
            self.body.addWidget(self.controls,0,1); self.body.addWidget(self.telemetry,1,1)
        self.body.setColumnStretch(0,1); self.body.setColumnStretch(1,0)
        self.body.setRowStretch(0,1); self.body.setRowStretch(1,0)

    def resizeEvent(self,event):
        self._layout_panels(self.width()<760 or self.height()<710); super().resizeEvent(event)

    def _sample(self):
        self.clock.setText(time.strftime('%H:%M\n%d / %m / %Y'))
        try: cpu,ram=self.metrics.sample()
        except (OSError,AttributeError): cpu,ram='—','—'
        self.values['cpu'].setText(cpu); self.values['ram'].setText(ram)
        try: cpu_percent=float(cpu.rstrip('%'))
        except ValueError: cpu_percent=None
        try:
            used,total=ram.replace(' GB','').split(' / '); ram_percent=float(used)/float(total)*100
        except (ValueError,ZeroDivisionError): ram_percent=None
        self.traces['cpu'].add(cpu_percent); self.traces['ram'].add(ram_percent)

    def sync(self,ready,busy,mic_on,mode,caption):
        if ready and not busy and mode != 'error': mode='listening' if mic_on else 'paused'
        if not ready: mode='thinking'
        names={'thinking':'Đang xử lý','speaking':'Đang nói','listening':'Đang nghe',
               'paused':'Mic đang tắt','idle':'Sẵn sàng','error':'Cần kiểm tra'}
        self.mode.setText(names.get(mode,'Sẵn sàng') if ready else 'Đang khởi động')
        self.caption.setText(caption if mode=='error' else 'Alex đang xử lý yêu cầu của bạn.' if busy else
                             'Mic đang bật. Bạn có thể nói với mình.' if mic_on else 'Bật mic để nói hoặc chọn Nhập tin nhắn.')
        self.badge.setText('●  ĐANG NÓI' if mode=='speaking' else '●  ĐANG XỬ LÝ' if busy or not ready else
                           '●  ĐANG NGHE' if mic_on else '●  MIC ĐANG TẮT')
        self.reactor.set_mode(mode)
        self.mic.setText('Tắt mic' if mic_on else 'Bật mic'); self.mic.setEnabled(ready and not busy)
        self.stop.setEnabled(busy)

    def set_active(self,active):
        self.active=bool(active); self.reactor.set_active(active)
        if active: self._sample(); self.timer.start()
        else: self.timer.stop()

    def showEvent(self,event):
        super().showEvent(event); self.set_active(not self.window().isMinimized())

    def hideEvent(self,event):
        self.set_active(False); super().hideEvent(event)
