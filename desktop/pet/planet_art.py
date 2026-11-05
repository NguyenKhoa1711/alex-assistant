"""DPI-aware planet artwork: nine scene sprites and one moving portrait only."""
from __future__ import annotations
import math
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QRadialGradient
from .planet_surface import sphere


class PlanetArt:
    def __init__(self):
        self.cache = {}
        self._portrait_key = None
        self._portrait = None
        self._detail_key = None
        self._detail = None
        self._scene_key = None
        self._scene = None

    def sprite(self,index):
        if index not in self.cache:
            self.cache[index]=self._render(index,384,0.)
        return self.cache[index]

    def draw(self,painter,index,center,radius,opacity=1.,seconds=None):
        painter.save(); painter.setOpacity(opacity)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if seconds is None:
            pixmap=self.sprite(index)
        else:
            dpr=painter.device().devicePixelRatioF()
            side=max(256,min(1024,math.ceil(radius*4.5*dpr/32)*32))
            frame=int(seconds*20)
            key=(index,side,frame)
            if key!=self._portrait_key:
                self._portrait_key=key
                self._portrait=self._render(index,side,frame/20*.13)
            pixmap=self._portrait
        painter.drawPixmap(QRectF(center.x()-radius*2.25,center.y()-radius*2.25,
                                  radius*4.5,radius*4.5),pixmap,QRectF(pixmap.rect()))
        painter.restore()

    def draw_detail(self,painter,index,center,radius,angle=0.):
        """Match zoom and DPI, with one bounded high-detail cached image."""
        dpr=painter.device().devicePixelRatioF()
        transform=painter.worldTransform()
        scale=math.sqrt(abs(transform.m11()*transform.m22()-transform.m12()*transform.m21()))
        physical_radius=radius*scale*dpr
        side=max(384,min(1536,math.ceil((physical_radius*4.5-1e-5)/64)*64))
        key=(index,side,round(angle,3))
        if key != self._detail_key:
            self._detail_key=key
            self._detail=self._render(index,side,angle)
        painter.save(); painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(QRectF(center.x()-radius*2.25,center.y()-radius*2.25,
                                  radius*4.5,radius*4.5),self._detail,QRectF(self._detail.rect()))
        painter.restore()

    def draw_scene(self,painter,index,center,radius,seconds):
        """Animate only the selected scene planet, with a single bounded cache."""
        self.sprite(index)
        dpr=painter.device().devicePixelRatioF()
        side=max(192,min(512,math.ceil(radius*4.5*dpr/32)*32))
        frame=int(seconds*10)
        key=(index,side,frame)
        if key != self._scene_key:
            self._scene_key=key
            self._scene=self._render(index,side,frame/10*.13)
        painter.save(); painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(QRectF(center.x()-radius*2.25,center.y()-radius*2.25,
                                  radius*4.5,radius*4.5),self._scene,QRectF(self._scene.rect()))
        painter.restore()

    def _render(self,index,side,phase):
        pixmap=QPixmap(side,side); pixmap.fill(Qt.GlobalColor.transparent)
        p=QPainter(pixmap); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.translate(side/2,side/2); p.scale(side/4.5,side/4.5)
        p.setPen(Qt.PenStyle.NoPen)
        if index==-1:
            halo=QRadialGradient(0,0,2.23)
            for stop,rgba in ((0,(255,221,121,255)),(.40,(255,175,50,140)),
                              (.57,(255,117,24,48)),(1,(255,91,16,0))):
                halo.setColorAt(stop,QColor(*rgba))
            p.setBrush(halo); p.drawEllipse(QPointF(),2.23,2.23)

        def rings(front):
            p.save(); p.rotate(-23)
            p.setClipRect(QRectF(-2.2,0 if front else -1,4.4,1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            for j in range(64):
                r=1.24+j*.012
                if 1.65<r<1.70: continue
                brightness=.83+.17*math.sin(j*2.38)
                c=QColor(round(209*brightness),round(185*brightness),round(143*brightness),180 if front else 115)
                p.setPen(QPen(c,.013))
                p.drawEllipse(QRectF(-r,-r*.32,r*2,r*.64))
            p.restore()

        if index==5: rings(False)
        p.drawImage(QRectF(-1,-1,2,2),sphere(index,round(side/2.25),phase))
        if index in (1,2,6,7):
            atmosphere=QRadialGradient(0,0,1.085)
            c=QColor('#539cef' if index==2 else '#93d3de' if index in (6,7) else '#f2c477')
            c.setAlpha(0); atmosphere.setColorAt(0,c); atmosphere.setColorAt(.90,c)
            c.setAlpha(80); atmosphere.setColorAt(.93,c)
            c.setAlpha(0); atmosphere.setColorAt(1,c)
            p.setBrush(atmosphere); p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(),1.085,1.085)
        if index==5: rings(True)
        p.end(); return pixmap
