"""Alex's command center, with live status and local PC metrics."""
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
QWidget#commandPage { background: #07131f; }
QWidget#commandPage QLabel { color: #e0eeef; background: transparent; }
QWidget#commandPage QLabel#subtle { color: #a1b6be; font-size: 12px; }
QWidget#commandPage QLabel#hudTitle { color: #f6fbfc; font-size: 30px; font-weight: 700; }
QWidget#commandPage QLabel#hudBrand { color: #75d3cf; font-size: 10px; font-weight: 700; }
QWidget#commandPage QLabel#hudStatus { color: #f5fafb; font-size: 21px; font-weight: 650; }
QWidget#commandPage QLabel#metricValue { color: #e8fbf7; font-size: 21px; font-weight: 650; }
QWidget#commandPage QLabel#faceBrand { color: #d1eeeb; font-size: 11px; font-weight: 700; }
QWidget#commandPage QLabel#faceBadge { color: #9ae5d5; font-size: 11px; font-weight: 650; }
QWidget#commandPage QLabel#faceNote { color: #97b2bb; font-size: 11px; }
QWidget#commandPage QLabel#hudKicker { color: #d4b885; font-size: 10px; font-weight: 700; }
QWidget#commandPage QLabel#headerState { color: #b7e9df; background: #15353a; border: 1px solid #315b5c; border-radius: 10px; padding: 7px 11px; font-size: 11px; font-weight: 600; }
QWidget#commandPage QFrame#hudPanel { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #122c3a,stop:1 #0c202d); border: 1px solid #294959; border-radius: 16px; }
QWidget#commandPage QFrame#facePanel { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #163640,stop:0.45 #0a1d29,stop:1 #091923); border: 1px solid #39646a; border-radius: 20px; }
QWidget#commandPage QFrame#hairline { background: #2d5159; border: none; max-height: 1px; }
QWidget#commandPage QPushButton { background: #1a3944; color: #e1f2ef; border: 1px solid #395d65;
    border-radius: 10px; padding: 5px 14px; min-height: 26px; font-size: 12px; font-weight: 500; text-align: left; }
QWidget#commandPage QPushButton:hover { background: #254d58; border-color: #79d8cc; }
QWidget#commandPage QPushButton:pressed { background: #315e66; }
QWidget#commandPage QPushButton:focus { border: 2px solid #94efe2; }
QWidget#commandPage QPushButton:disabled { color: #728b91; background: #142a34; border-color: #2c4550; }
QWidget#commandPage QPushButton#hudMic { background: #7de2cf; color: #082c2a; border: none; font-weight: 700; font-size: 14px; padding: 6px 14px; min-height: 28px; text-align: center; }
QWidget#commandPage QPushButton#hudMic:hover { background: #a2f1df; }
QWidget#commandPage QPushButton#hudMic:disabled { background: #284c50; color: #90aead; }
QWidget#commandPage QPushButton#hudStop { color: #ecc8bd; background: #2c3036; border: 1px solid #665454; }
QWidget#commandPage QPushButton#hudStop:disabled { color: #849399; background: #142a34; border-color: #2c4550; }
QWidget#commandPage QPushButton#quietMotion { color: #d0eee8; background: #183a42; border: 1px solid #547579; font-size: 11px; padding: 5px 12px; min-height: 22px; }
QWidget#commandPage QPushButton#quietMotion:hover { background: #2a5259; border-color: #8cdbce; }
QWidget#commandPage QLabel#shortcutHint { color: #9ab6be; background: #0d222e; border: 1px solid #234350; border-radius: 9px; padding: 7px 10px; font-size: 11px; }
'''

SIDEBAR_STYLE='''
QFrame#sidebar { background: #0a2029; border-right: 1px solid #2b4950; }
QFrame#sidebar QLabel { color: #d9efec; }
QFrame#sidebar QLabel#brand { color: #f5fffd; }
QFrame#sidebar QLabel#eyebrow, QFrame#sidebar QLabel#sideNote { color: #9cbab9; }
QFrame#sidebar QPushButton#newChat { background: #b6e9da; color: #123d36; border: none; border-radius: 10px; }
QFrame#sidebar QPushButton#nav { color: #c3dcd9; }
QFrame#sidebar QPushButton#nav:hover { background: #1d4149; }
QFrame#sidebar QPushButton#nav:checked { background: #254c51; color: #f2fffb; border-left: 3px solid #82dfce; border-radius: 10px; }
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
        p.setPen(QPen(QColor('#29434a'),1))
        for y in (7,17,28): p.drawLine(0,y,self.width(),y)
        p.setPen(QPen(QColor('#70d1bc'),1.5)); segment=[]
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

def separator():
    line=QFrame(); line.setObjectName('hairline'); line.setFixedHeight(1)
    return line

class CommandCenter(QWidget):
    chat_requested=Signal()
    space_requested=Signal()
    mic_requested=Signal()
    stop_requested=Signal()
    command_requested=Signal(str)
    fullscreen_requested=Signal()

    def __init__(self,parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,True)
        self.setObjectName('commandPage'); self.setStyleSheet(HUD_STYLE)
        self.active=False; self.metrics=MachineMetrics(); self.compact=None; self.immersive=False
        layout=QVBoxLayout(self); self._main_layout=layout; layout.setContentsMargins(28,24,28,24); layout.setSpacing(16)
        self.header_widget=QWidget(); header=QHBoxLayout(self.header_widget); header.setContentsMargins(0,0,0,0)
        title=QVBoxLayout(); title.setSpacing(4)
        title.addWidget(text('ALEX  /  KHÔNG GIAN CỦA BẠN','hudKicker'))
        title.addWidget(text('Trạm chỉ huy','hudTitle'))
        title.addWidget(text('Một không gian dành riêng cho bạn và Alex.','subtle'))
        header.addLayout(title,1)
        self.header_state=text('●  MIC ĐANG TẮT','headerState')
        self.header_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self.header_state,0,Qt.AlignmentFlag.AlignVCenter)
        header.addSpacing(12)
        self.clock=text('','subtle'); self.clock.setAlignment(Qt.AlignmentFlag.AlignRight)
        header.addWidget(self.clock); layout.addWidget(self.header_widget)
        self.body=QGridLayout(); self.body.setSpacing(14); layout.addLayout(self.body,1)

        self.face_panel,face_box=panel('facePanel'); self._face_box=face_box
        face_box.setContentsMargins(18,16,18,15); face_box.setSpacing(9)
        identity=QHBoxLayout(); self.face_brand=text('ALEX  /  TRỢ LÝ CỦA BẠN','faceBrand')
        identity.addWidget(self.face_brand,1)
        self.badge=text('●  MIC ĐANG TẮT','faceBadge'); self.badge.setMinimumWidth(126)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignRight); identity.addWidget(self.badge)
        face_box.addLayout(identity)
        self.face_rule=separator(); face_box.addWidget(self.face_rule)
        self.reactor=HologramFace(); face_box.addWidget(self.reactor,1)
        face_footer=QHBoxLayout()
        self.follow_note=text('LÕI TƯƠNG TÁC 3D  /  ALEX','faceNote'); face_footer.addWidget(self.follow_note,1)
        self.fullscreen_button=action('Phóng to toàn màn hình',self.fullscreen_requested.emit)
        self.fullscreen_button.setObjectName('quietMotion')
        self.fullscreen_button.setAccessibleName('Phóng to toàn màn hình Trạm chỉ huy')
        self.fullscreen_button.setToolTip('Nhấn phím ` để bật hoặc thoát toàn màn hình')
        self.motion=self.fullscreen_button
        face_footer.addWidget(self.fullscreen_button)
        face_box.addLayout(face_footer)

        self.controls,controls=panel(); controls.setContentsMargins(18,14,18,14); controls.setSpacing(7)
        controls.addWidget(text('01  /  ĐIỀU KHIỂN','hudKicker'))
        self.mode=text('Đang khởi động','hudStatus',True); self.mode.setMinimumHeight(30); controls.addWidget(self.mode)
        self.caption=text('Đang kết nối bộ xử lý Alex.','subtle',True); self.caption.setMinimumHeight(20); self.caption.setMaximumHeight(44); controls.addWidget(self.caption)
        controls.addSpacing(2); controls.addWidget(separator()); controls.addSpacing(2)
        self.mic=action('Bật mic',self.mic_requested.emit); self.mic.setObjectName('hudMic'); self.mic.setMinimumHeight(38); controls.addWidget(self.mic)
        self.chat_button=action('Nhắn tin cho Alex  →',self.chat_requested.emit); self.chat_button.setMinimumHeight(36); controls.addWidget(self.chat_button)
        self.stop=action('Dừng tác vụ',self.stop_requested.emit); self.stop.setObjectName('hudStop'); self.stop.setMinimumHeight(36); controls.addWidget(self.stop)
        controls.addStretch(1)
        self.controls_tip=text('PHÍM TẮT\n` · Toàn màn hình   |   Esc · Thu nhỏ\nCtrl + Space · Hiện / ẩn pet','shortcutHint',True)
        self.controls_tip.setMinimumHeight(62)
        controls.addWidget(self.controls_tip)

        self.latest_panel,latest_box=panel(); latest_box.setContentsMargins(18,12,18,12); latest_box.setSpacing(5)
        latest_box.addWidget(text('02  /  PHẢN HỒI GẦN NHẤT','hudKicker'))
        self.latest=text('Bật mic hoặc nhắn tin để bắt đầu trò chuyện.','',True)
        self.latest.setMaximumHeight(64); latest_box.addWidget(self.latest)

        self.telemetry,stats=panel(); stats.setContentsMargins(18,12,18,12); stats.setSpacing(6)
        stats.addWidget(text('03  /  HOẠT ĐỘNG LAPTOP','hudKicker'))
        self.values={}; self.traces={}; readings=QHBoxLayout(); readings.setSpacing(14)
        for name,label in (('cpu','CPU'),('ram','BỘ NHỚ')):
            column=QVBoxLayout(); column.setSpacing(3); column.addWidget(text(label,'subtle'))
            value=text('—','metricValue'); self.values[name]=value; column.addWidget(value)
            trace=MetricTrace(); self.traces[name]=trace; column.addWidget(trace); readings.addLayout(column,1)
        self.values['ram'].setStyleSheet('font-size:12px;font-weight:600;')
        stats.addLayout(readings)
        self.values['privacy']=text('Hội thoại lưu tạm trong phiên','subtle',True); stats.addWidget(self.values['privacy'])
        stats.addWidget(text('Cập nhật mỗi 2 giây','subtle'))

        self.timer=QTimer(self); self.timer.setInterval(2000); self.timer.timeout.connect(self._sample)
        self._layout_panels(False)

    def _layout_panels(self,compact,force=False):
        if compact == self.compact and not force: return
        self.compact=compact
        self.face_brand.setText('ALEX' if compact else 'ALEX  /  TRỢ LÝ CỦA BẠN')
        for widget in (self.telemetry,self.face_panel,self.controls,self.latest_panel): self.body.removeWidget(widget)
        self.header_widget.setVisible(not self.immersive)
        self.controls.setVisible(not self.immersive)
        self.latest_panel.setVisible(not self.immersive)
        self.telemetry.setVisible(not compact and not self.immersive)
        self.face_brand.setVisible(not self.immersive)
        self.badge.setVisible(not self.immersive)
        self.face_rule.setVisible(not self.immersive)
        self.header_state.setVisible(not compact and not self.immersive)
        self.controls_tip.setVisible(not compact and not self.immersive)
        self.follow_note.setVisible(not compact and not self.immersive)
        self.fullscreen_button.setVisible(not self.immersive)
        if self.immersive:
            self._main_layout.setContentsMargins(0,0,0,0)
            self._main_layout.setSpacing(0)
            self._face_box.setContentsMargins(0,0,0,0)
            self._face_box.setSpacing(0)
            self.face_panel.setStyleSheet('QFrame#facePanel { background: #020812; border: none; border-radius: 0px; }')
            self.body.setSpacing(0)
            self.body.addWidget(self.face_panel,0,0)
            self.body.setColumnStretch(0,1); self.body.setColumnStretch(1,0)
            self.body.setRowStretch(0,1)
            return
        self._main_layout.setContentsMargins(28,24,28,24)
        self._main_layout.setSpacing(16)
        self._face_box.setContentsMargins(18,16,18,15)
        self._face_box.setSpacing(9)
        self.face_panel.setStyleSheet('')
        self.body.setSpacing(14)
        rail_width=190 if compact else 270
        for widget in (self.controls,self.telemetry,self.latest_panel): widget.setFixedWidth(rail_width)
        self.body.addWidget(self.face_panel,0,0,3,1)
        self.body.addWidget(self.controls,0,1)
        self.body.addWidget(self.latest_panel,1,1)
        if not compact: self.body.addWidget(self.telemetry,2,1)
        self.body.setColumnStretch(0,1); self.body.setColumnStretch(1,0)
        self.body.setRowStretch(0,1); self.body.setRowStretch(1,0)
        self.body.setRowStretch(2,0)

    def set_immersive(self,immersive):
        self.immersive=bool(immersive)
        self.fullscreen_button.setText('Thoát toàn màn hình  (Esc)' if self.immersive else 'Phóng to toàn màn hình')
        self._layout_panels(self.width()<760 or self.height()<710,force=True)

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
        if ready and not busy and mode not in ('error', 'speaking'): mode='listening' if mic_on else 'paused'
        if not ready: mode='thinking'
        names={'thinking':'Đang xử lý','speaking':'Đang nói','listening':'Đang nghe',
               'paused':'Mic đang tắt','idle':'Sẵn sàng','error':'Cần kiểm tra'}
        self.mode.setText(names.get(mode,'Sẵn sàng') if ready else 'Đang khởi động')
        self.caption.setText(caption if mode=='error' else 'Alex đang xử lý yêu cầu của bạn.' if busy else
                             'Mic đang bật. Bạn có thể nói với mình.' if mic_on else 'Bật mic để nói hoặc chọn Nhập tin nhắn.')
        self.badge.setText('●  ĐANG NÓI' if mode=='speaking' else '●  ĐANG XỬ LÝ' if busy or not ready else
                           '●  ĐANG NGHE' if mic_on else '●  MIC ĐANG TẮT')
        self.header_state.setText(self.badge.text())
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
