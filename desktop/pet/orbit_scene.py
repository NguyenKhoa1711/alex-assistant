"""Lightweight illustrated solar scene: cached scenery, sprites and orbit geometry."""
from __future__ import annotations
import math
import random
import time
from PySide6.QtCore import Qt, QTimer, QRectF, QPointF, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient, QFont
from PySide6.QtWidgets import QWidget
from .orbit_math import PLANETS, orbital_point, project, GestureMotion
from .planet_art import PlanetArt


class PlanetPortrait(QWidget):
    def __init__(self, art, parent=None):
        super().__init__(parent)
        self.art, self.index = art, 2
        self.seconds = 0.
        self.setMinimumHeight(150)
        self.setMaximumHeight(245)
        self.setAccessibleName('Minh họa cận cảnh hành tinh đang chọn')

    def set_time(self, seconds):
        # No independent timer: follows the scene's pause/hide/minimize lifecycle.
        if int(seconds*20) != int(self.seconds*20):
            self.seconds = seconds
            self.update()

    def paintEvent(self, event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        center=QPointF(self.width()/2,self.height()/2)
        radius=min(self.width()*(.24 if self.index==5 else .38),self.height()*.38)
        p.setPen(QPen(QColor('#233b4a'),.6)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(center,radius*1.45,radius*1.45)
        p.setPen(QPen(QColor('#4e7a83'),1))
        p.drawArc(QRectF(center.x()-radius*1.45,center.y()-radius*1.45,radius*2.9,radius*2.9),int(20+self.seconds*3)*16,35*16)
        self.art.draw(p,self.index,center,radius,seconds=self.seconds)
        p.end()


class OrbitCanvas(QWidget):
    selected = Signal(int)
    advanced = Signal(float)
    zoomChanged = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(260,250)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setAccessibleName('Hệ Mặt Trời. Kéo xoay, cuộn thu phóng; bấm hành tinh để khám phá.')
        self.yaw, self.tilt, self.zoom = -.25, .72, 1.
        self.pan = QPointF()
        self.days, self.rate = 0., 35.
        self.playing, self.active, self.labels, self.orbits = True, False, True, True
        self.trails = True
        self.effects = True
        self.seconds = 0.
        self._twinkles = []
        self._view_target = None
        self.selection = 2
        self.drag = self.origin = None
        self.hit_points = []
        self.stars = None
        self._background_key = None
        self._geometry_key = None
        self._paths, self._dust = [], []
        self.art = PlanetArt()
        self.hands = []
        self.motion = GestureMotion()
        self.last_tick = time.monotonic()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._tick)

    def set_active(self, active):
        self.active = active
        self.last_tick = time.monotonic()
        self.timer.start() if active and self.playing else self.timer.stop()

    def set_playing(self, playing):
        self.playing = playing
        self.set_active(self.active)

    def _tick(self):
        now = time.monotonic()
        dt=max(0.,min(.1,now-self.last_tick))
        self.last_tick = now
        if not self.active or not self.playing: return
        self.days = (self.days + dt*self.rate) % (59800*100)
        if self.effects:
            self.seconds += dt
            self.advanced.emit(self.seconds)
        if self._view_target is not None:
            yaw,tilt,zoom=self._view_target
            amount=1-math.exp(-dt*7)
            delta=(yaw-self.yaw+math.pi)%math.tau-math.pi
            self.yaw+=delta*amount
            self.tilt+=(tilt-self.tilt)*amount
            self.zoom+=(zoom-self.zoom)*amount
            if abs(delta)+abs(tilt-self.tilt)+abs(zoom-self.zoom)<.001:
                self.yaw,self.tilt,self.zoom=self._view_target; self._view_target=None
        self.update()

    def rotate_zoom(self, dx, dy, zoom):
        self._view_target=None
        self.yaw = (self.yaw + dx) % math.tau
        # Allow passing above and below the orbital plane, not just 7–86°.
        self.tilt = (self.tilt + dy + math.pi) % math.tau - math.pi
        old=self.zoom
        self.zoom = max(.45,min(6.,self.zoom*zoom))
        if self.zoom!=old: self.zoomChanged.emit(self.zoom)
        self.update()

    def zoom_at(self, factor, anchor=None):
        """Keep the location under the pointer stationary while zooming."""
        old=self.zoom
        new=max(.45,min(6.,old*factor))
        if old == new: return
        if anchor is None: anchor=QPointF(self.width()*.5,self.height()*.52)
        center=QPointF(self.width()*.5,self.height()*.52)
        self.pan=anchor-center-(anchor-center-self.pan)*(new/old)
        self.zoom=new; self._view_target=None; self.update(); self.zoomChanged.emit(new)

    def reset_view(self):
        self._view_target=None
        self.yaw,self.tilt,self.zoom = -.25,.72,1.
        self.pan=QPointF()
        self.motion.reset(); self.update(); self.zoomChanged.emit(self.zoom)

    def view_from_above(self):
        self.pan=QPointF()
        if self.active and self.playing:
            self._view_target=(-.25,1.5,1.)
        else:
            self.yaw,self.tilt,self.zoom = -.25,1.5,1.
            self.zoomChanged.emit(self.zoom)
        self.motion.reset(); self.update()

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            self.drag=self.origin=event.position()
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self,event):
        if self.drag is not None:
            delta=event.position()-self.drag
            self.rotate_zoom(delta.x()*.006,delta.y()*.006,1.)
            self.drag=event.position()

    def mouseReleaseEvent(self,event):
        if event.button()!=Qt.MouseButton.LeftButton: return
        if self.origin is not None and (event.position()-self.origin).manhattanLength()<6:
            for index,point,radius in reversed(self.hit_points):
                if math.hypot(event.position().x()-point.x(),event.position().y()-point.y())<radius+8:
                    self.selected.emit(index); break
        self.drag=self.origin=None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def wheelEvent(self,event):
        self.zoom_at(math.exp(event.angleDelta().y()*.001),event.position()); event.accept()

    def keyPressEvent(self,event):
        controls={Qt.Key.Key_Left:(-.1,0,1),Qt.Key.Key_Right:(.1,0,1),
                  Qt.Key.Key_Up:(0,-.1,1),Qt.Key.Key_Down:(0,.1,1),
                  Qt.Key.Key_Plus:(0,0,1.1),Qt.Key.Key_Minus:(0,0,.9)}
        if event.key() in controls: self.rotate_zoom(*controls[event.key()])
        else: super().keyPressEvent(event)

    def _background(self):
        dpr=self.devicePixelRatioF()
        key=(self.width(),self.height(),dpr)
        if self._background_key==key: return
        self._background_key=key
        self.stars=QPixmap(round(self.width()*dpr),round(self.height()*dpr))
        self.stars.setDevicePixelRatio(dpr); self.stars.fill(QColor('#050b15'))
        p=QPainter(self.stars); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        # Broad, restrained nebula clouds are cached with the star field.
        for x,y,r,color in ((.14,.18,.65,'#101e36'),(.85,.8,.6,'#0a232f'),
                            (.72,.12,.4,'#1e1936'),(.42,.65,.34,'#102836'),
                            (.90,.32,.23,'#29203c')):
            g=QRadialGradient(self.width()*x,self.height()*y,self.width()*r)
            c=QColor(color); g.setColorAt(0,c); c.setAlpha(0); g.setColorAt(1,c)
            p.fillRect(self.rect(),g)
        rng=random.Random(417)
        self._twinkles=[]
        count=min(1600,max(520,round(self.width()*self.height()/850)))
        for j in range(count):
            pos=QPointF(rng.random()*self.width(),rng.random()*self.height())
            size=rng.choice((.28,.38,.48,.62,.82))
            c=QColor('#d4e7f5' if j%5 else '#e8cca5'); c.setAlpha(rng.randint(40,190))
            p.setBrush(c); p.drawEllipse(pos,size,size)
            if j%65==0:
                self._twinkles.append((pos,rng.random()*math.tau))
                halo=QRadialGradient(pos,5)
                halo.setColorAt(0,QColor(188,225,255,85)); halo.setColorAt(1,QColor(188,225,255,0))
                p.setBrush(halo); p.setPen(Qt.PenStyle.NoPen); p.drawEllipse(pos,5,5)
                p.setPen(QPen(QColor(180,222,244,65),.6))
                p.drawLine(pos-QPointF(3,0),pos+QPointF(3,0))
                p.drawLine(pos-QPointF(0,3),pos+QPointF(0,3)); p.setPen(Qt.PenStyle.NoPen)
        p.end()

    def _screen(self,point):
        scale=min(self.width()/17,self.height()/10.5)*self.zoom
        x,y,z=project(point,self.yaw,self.tilt)
        return QPointF(self.width()*.5+x*scale,self.height()*.52+y*scale)+self.pan,z

    def _geometry(self):
        key=(self.width(),self.height(),self.yaw,self.tilt,self.zoom,self.pan.x(),self.pan.y())
        if self._geometry_key==key: return
        self._geometry_key=key
        self._paths=[]
        for body in PLANETS:
            back,front=QPainterPath(),QPainterPath()
            prev=None
            for j in range(257):
                point,z=self._screen(orbital_point(body,anomaly=j/256*math.tau))
                if prev is not None:
                    path=front if z>=0 else back
                    path.moveTo(prev); path.lineTo(point)
                prev=point
            self._paths.append((back,front))
        rng=random.Random(32); self._dust=[]
        for _ in range(260):
            a=rng.random()*math.tau; r=rng.uniform(3.48,3.73)
            point,z=self._screen((r*math.cos(a),r*math.sin(a),rng.uniform(-.045,.045)))
            self._dust.append((point,rng.randint(35,85)))

    def _draw_labels(self,p,bodies):
        boxes=[]; p.setFont(QFont('Segoe UI',9))
        # Selected label gets first claim on space, then nearer bodies.
        ordered=sorted(bodies,key=lambda b:(b[1]!=self.selection,-b[0]))
        for _,i,pos,radius in ordered:
            if not self.rect().adjusted(4,36,-4,-30).contains(pos.toPoint()): continue
            name='Mặt Trời' if i==-1 else PLANETS[i].name
            width=p.fontMetrics().horizontalAdvance(name)+14
            box=QRectF(min(self.width()-width-8,max(8,pos.x()+radius+7)),
                       min(self.height()-52,max(38,pos.y()-11)),width,22)
            found=False
            for offset in (0,24,-24,48,-48,72,-72):
                candidate=box.translated(0,offset)
                if candidate.top()<36 or candidate.bottom()>self.height()-29: continue
                if not any(candidate.intersects(other.adjusted(-3,-2,3,2)) for other in boxes):
                    box=candidate; found=True; break
            if not found: continue
            boxes.append(box)
            p.setPen(QPen(QColor('#567c8a'),.7))
            p.drawLine(pos+QPointF(radius,0),QPointF(box.left(),box.center().y()))
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(8,17,28,185)); p.drawRoundedRect(box,5,5)
            p.setPen(QColor('#f2d399' if i==-1 else '#c4e7e2' if i==self.selection else '#a2bbcd'))
            p.drawText(box,Qt.AlignmentFlag.AlignCenter,name)

    def paintEvent(self,event):
        self._background(); self._geometry()
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds=QPainterPath(); bounds.addRoundedRect(QRectF(self.rect()).adjusted(.5,.5,-.5,-.5),18,18)
        p.setClipPath(bounds); p.drawPixmap(0,0,self.stars)
        if self.effects:
            for pos,phase in self._twinkles:
                alpha=round(35+28*(1+math.sin(self.seconds*.8+phase)))
                p.setPen(QPen(QColor(192,224,255,alpha),.7))
                p.drawLine(pos-QPointF(2.8,0),pos+QPointF(2.8,0))
                p.drawLine(pos-QPointF(0,2.8),pos+QPointF(0,2.8))
        p.setBrush(Qt.BrushStyle.NoBrush)
        if self.orbits:
            for i,(back,front) in enumerate(self._paths):
                color=QColor(PLANETS[i].color if i==self.selection else '#7595ac')
                for path,alpha in ((back,42),(front,95)):
                    color.setAlpha(alpha+45 if i==self.selection else alpha)
                    if i==self.selection:
                        glow=QColor(color); glow.setAlpha(20)
                        p.setPen(QPen(glow,5)); p.drawPath(path)
                    p.setPen(QPen(color,1.15 if i==self.selection else .65)); p.drawPath(path)
            for point,alpha in self._dust:
                p.setPen(QColor(163,161,153,alpha)); p.drawPoint(point)
        bodies=[]
        for i,body in enumerate(PLANETS):
            pos,z=self._screen(orbital_point(body,self.days))
            radius=(body.size*1.18+1.5)*math.sqrt(self.zoom)
            bodies.append((z,i,pos,radius))
            if self.trails:
                for k in range(18):
                    a,_=self._screen(orbital_point(body,self.days-body.days*(18-k)*.0025))
                    b,_=self._screen(orbital_point(body,self.days-body.days*(17-k)*.0025))
                    color=QColor(body.color); color.setAlpha(round(8+k*5))
                    p.setPen(QPen(color,2 if i==self.selection else 1.3)); p.drawLine(a,b)
        center,_=self._screen((0,0,0))
        if self.effects:
            glow_radius=(75+math.sin(self.seconds*.65)*4)*math.sqrt(self.zoom)
            glow=QRadialGradient(center,glow_radius)
            glow.setColorAt(0,QColor(255,183,69,45)); glow.setColorAt(.4,QColor(255,135,28,20))
            glow.setColorAt(1,QColor(255,105,22,0))
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(glow)
            p.drawEllipse(center,glow_radius,glow_radius)
        bodies.append((0,-1,center,24*math.sqrt(self.zoom)))
        self.hit_points=[]
        for _,i,pos,radius in sorted(bodies):
            if i==self.selection and self.effects and self.playing and self.active:
                self.art.draw_scene(p,i,pos,radius,self.seconds)
            else:
                self.art.draw(p,i,pos,radius)
            if i==self.selection:
                p.setPen(QPen(QColor('#a3e3da'),1)); p.setBrush(Qt.BrushStyle.NoBrush)
                ring=QRectF(pos.x()-radius-7,pos.y()-radius-7,(radius+7)*2,(radius+7)*2)
                phase=self.seconds*12 if self.effects else 0
                for angle in (20,140,260): p.drawArc(ring,round((angle+phase)*16),50*16)
                if i==2:
                    a=self.days/27.3*math.tau
                    moon=pos+QPointF(math.cos(a)*(radius+13),math.sin(a)*(radius+13)*.5)
                    p.setBrush(QColor('#c7d4df')); p.setPen(Qt.PenStyle.NoPen); p.drawEllipse(moon,2.3,2.3)
            if i>=0: self.hit_points.append((i,pos,radius))
        if self.labels: self._draw_labels(p,bodies)
        p.setFont(QFont('Segoe UI',9)); p.setPen(QColor('#8eafb9'))
        heading=p.fontMetrics().elidedText('HỆ MẶT TRỜI  /  08 HÀNH TINH',Qt.TextElideMode.ElideRight,self.width()-36)
        p.drawText(18,27,heading)
        p.setPen(QColor('#7593a5'))
        p.drawText(18,self.height()-17,f'Ngày {int(self.days):,}   ·   Kéo xoay / cuộn thu phóng')
        if self.hands: self._draw_hands(p)
        p.setClipping(False); p.setBrush(Qt.BrushStyle.NoBrush); p.setPen(QPen(QColor('#2c4254'),1))
        p.drawPath(bounds); p.end()

    def _draw_hands(self,p):
        box=QRectF(self.width()-142,40,126,94)
        p.setPen(QPen(QColor('#42786f'),1)); p.setBrush(QColor('#0d202d')); p.drawRoundedRect(box,8,8)
        edges=((0,1,2,3,4),(0,5,6,7,8),(5,9,10,11,12),(9,13,14,15,16),(13,17,18,19,20),(0,17))
        for hand in self.hands:
            pts=[QPointF(box.x()+v[0]*box.width(),box.y()+v[1]*box.height()) for v in hand]
            p.setPen(QPen(QColor('#8ee7c8'),2))
            for edge in edges:
                for a,b in zip(edge,edge[1:]): p.drawLine(pts[a],pts[b])
