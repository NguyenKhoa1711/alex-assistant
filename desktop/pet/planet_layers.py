"""Offline, illustrative exploded-view of the selected planet's interior."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import math
import random
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QWidget

from .orbit_math import PLANETS


@dataclass(frozen=True)
class Layer:
    name: str
    color: str
    description: str


# Schematic, not measured scales. NASA sources in ALEX-DESKTOP.md. Gas and ice
# giant interiors are model-dependent, with no invented solid surface.
EARTH = (
    Layer('Vỏ Trái Đất', '#ac917c', 'Lớp đá mỏng bên ngoài.'),
    Layer('Lớp phủ', '#bd7055', 'Đá nóng, phần lớn rắn, chuyển động rất chậm.'),
    Layer('Lõi ngoài', '#c98b59', 'Sắt và niken ở trạng thái lỏng.'),
    Layer('Lõi trong', '#f5d8a8', 'Chủ yếu là sắt và niken rắn.'),
)
ROCKY = {
    0: (Layer('Lớp vỏ', '#b6b1a6', 'Bề mặt đá nhiều hố va chạm.'),
        Layer('Lớp phủ', '#c98264', 'Lớp đá bao quanh phần lõi.'),
        Layer('Lõi kim loại', '#f2c078', 'Lõi lớn, giàu sắt; một phần nóng chảy.')),
    1: (Layer('Mây và khí quyển', '#eddfbc', 'Mây dày che bề mặt đá của Sao Kim.'),
        Layer('Lớp vỏ', '#e6c08f', 'Bề mặt đá nằm dưới khí quyển dày.'),
        Layer('Lớp phủ', '#d78663', 'Lớp đá nóng bên trong.'),
        Layer('Lõi', '#f1be7d', 'Lõi kim loại; trạng thái chưa chắc chắn.')),
    2: EARTH,
    3: (Layer('Lớp vỏ', '#d99779', 'Bề mặt đá giàu khoáng vật sắt.'),
        Layer('Lớp phủ', '#ca7355', 'Lớp đá bên dưới lớp vỏ.'),
        Layer('Lõi', '#efb067', 'Lõi lỏng giàu sắt và các nguyên tố nhẹ.')),
}
GIANTS = {
    4: (Layer('Mây và khí quyển', '#e9cba3', 'Các dải mây bao quanh Sao Mộc.'),
        Layer('Hydro phân tử', '#dba882', 'Hydro và heli bị nén dần theo độ sâu.'),
        Layer('Hydro kim loại', '#c87655', 'Chất lưu dẫn điện dưới áp suất lớn.'),
        Layer('Vùng lõi', '#f3ca8c', 'Có thể là lõi phân tán; còn nghiên cứu.')),
    5: (Layer('Mây và khí quyển', '#ead8b3', 'Mây bao quanh Sao Thổ; vành nằm bên ngoài.'),
        Layer('Hydro phân tử', '#d9bd91', 'Hydro và heli bị nén dần theo độ sâu.'),
        Layer('Hydro kim loại', '#bc906a', 'Hydro dẫn điện dưới áp suất lớn.'),
        Layer('Vùng lõi', '#dec18b', 'Vùng giàu nguyên tố nặng; còn nghiên cứu.')),
    6: (Layer('Khí quyển', '#9ddbe3', 'Metan góp phần tạo màu xanh Sao Thiên Vương.'),
        Layer('Chất lưu đậm đặc', '#61a6c6', 'Nước, amoniac, metan nóng và bị nén.'),
        Layer('Vùng lõi', '#d5b593', 'Có thể giàu đá; cấu trúc còn nghiên cứu.')),
    7: (Layer('Khí quyển', '#83b7ec', 'Sao Hải Vương có mây và gió mạnh.'),
        Layer('Chất lưu đậm đặc', '#4d7cc5', 'Nước, amoniac, metan nóng và bị nén.'),
        Layer('Vùng lõi', '#c5a68f', 'Có thể giàu đá; cấu trúc còn nghiên cứu.')),
}

# Approximate relative boundaries for an educational cutaway, not measured
# visualizations. The very thin crust/clouds are enlarged to remain visible;
# giant-planet interiors and their boundaries remain under investigation.
LAYER_RADII = {
    0: (1., .97, .85),
    1: (1., .98, .95, .52),
    2: (1., .975, .546, .192),
    3: (1., .975, .53),
    4: (1., .91, .70, .27),
    5: (1., .90, .62, .24),
    6: (1., .86, .25),
    7: (1., .86, .25),
}
# First layer representing a core, used for material rendering only. The final
# (innermost) region remains intact; preceding layers may break artistically.
CORE_START = (2, 3, 2, 2, 3, 3, 2, 2)


def layers_for(index):
    if not 0 <= index < len(PLANETS):
        raise ValueError('Unknown planet')
    return ROCKY[index] if index in ROCKY else GIANTS[index]


class PlanetLayersCanvas(QWidget):
    changed = Signal()
    layer_selected = Signal(int)

    def __init__(self, art, parent=None):
        super().__init__(parent)
        self.art=art
        self.index=2
        self.amount=0.
        self.zoom=1.
        self.pan=QPointF()
        self.angle=0.
        self.seconds=0.
        self._last_tick=time.monotonic()
        self.selected_layer=0
        self.glass_effect=True
        self.drag=None
        self.origin=None
        self.hit_boxes=[]
        self._unit_sphere=self._sphere_path(QPointF(),1.)
        self._shards=self._make_shards()
        self._completed_cache=OrderedDict()
        self._material_cache=OrderedDict()
        self.setMinimumSize(260,250)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setAccessibleName('Hình cắt lớp hành tinh. Cuộn để phóng to, kéo để dịch, bấm tên lớp để xem.')
        self.timer=QTimer(self); self.timer.setInterval(50)
        self.timer.timeout.connect(self._tick)

    def set_active(self,active):
        self._last_tick=time.monotonic()
        if not active:
            self._completed_cache.clear(); self._material_cache.clear()
        self.timer.start() if active else self.timer.stop()

    def _tick(self):
        now=time.monotonic()
        self.seconds+=max(0.,min(.1,now-self._last_tick))
        self._last_tick=now
        self.update()

    def set_planet(self,index):
        layers_for(index)
        self.index=index
        self.selected_layer=self.stage_for(self.amount,len(layers_for(index)))[0]
        self._completed_cache.clear(); self._material_cache.clear(); self.update()

    def set_amount(self,value):
        count=len(layers_for(self.index))
        previous=self.stage_for(self.amount,count)[0]
        self.amount=max(0.,min(1.,float(value)))
        stage=self.stage_for(self.amount,count)[0]
        if stage!=previous:self.selected_layer=stage
        self.update()

    def set_glass_effect(self,enabled):
        self.glass_effect=bool(enabled)
        self._completed_cache.clear()
        self.update()

    def reset_view(self):
        self.zoom=1.; self.pan=QPointF(); self.angle=0.; self.update(); self.changed.emit()

    def zoom_at(self,factor,anchor=None):
        old=self.zoom; new=max(.65,min(3.,old*factor))
        if old==new: return
        center=QPointF(self.width()/2,self.height()/2)
        if anchor is None: anchor=center
        self.pan=anchor-center-(anchor-center-self.pan)*(new/old)
        self.zoom=new; self.update(); self.changed.emit()

    def rotate_zoom(self,dx,dy,zoom):
        self.angle=(self.angle+dx) % math.tau
        self.pan+=QPointF(0,dy*28)
        self.zoom_at(zoom)
        self.update()

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            self.drag=self.origin=event.position()
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self,event):
        if self.drag is not None:
            self.pan+=event.position()-self.drag; self.drag=event.position(); self.update()

    def mouseReleaseEvent(self,event):
        if event.button()!=Qt.MouseButton.LeftButton: return
        if self.origin is not None and (event.position()-self.origin).manhattanLength()<6:
            for i,box in self.hit_boxes:
                if box.contains(event.position()):
                    self.selected_layer=i; self.layer_selected.emit(i); self.update(); break
        self.drag=self.origin=None; self.setCursor(Qt.CursorShape.OpenHandCursor)

    def wheelEvent(self,event):
        self.zoom_at(math.exp(event.angleDelta().y()*.001),event.position()); event.accept()

    def keyPressEvent(self,event):
        if event.key() in (Qt.Key.Key_Plus,Qt.Key.Key_Equal): self.zoom_at(1.2)
        elif event.key()==Qt.Key.Key_Minus: self.zoom_at(1/1.2)
        elif event.key()==Qt.Key.Key_0: self.reset_view()
        else: return super().keyPressEvent(event)
        event.accept()

    @staticmethod
    def _sphere_path(center,radius):
        path=QPainterPath(); path.addEllipse(center,radius,radius)
        return path

    @staticmethod
    def _scene_layout(width,height):
        center=QPointF(width*.5,(38+height-118)*.5)
        radius=max(18.,min(width*.20,max(18.,(height-168)*.34),145.))
        return center,radius

    @staticmethod
    def stage_for(amount,count):
        """Four ordered intervals for Earth; other planets use their own layer count."""
        progress=max(0.,min(1.,float(amount)))*count
        stage=min(int(progress),count-1)
        return stage,min(1.,progress-stage)

    @staticmethod
    def _make_shards(count=24):
        """Partition a disc into deterministic irregular glass-like polygons."""
        seeds=[]; rng=random.Random(5479)
        for i in range(count):
            radius=min(.97,.95*math.sqrt((i+.5)/count)*rng.uniform(.80,1.12))
            angle=i*2.399963229728653+rng.uniform(-.4,.4)
            seeds.append(QPointF(radius*math.cos(angle),radius*math.sin(angle)))
        pieces=[]
        for seed in seeds:
            vertices=[(-1.,-1.),(1.,-1.),(1.,1.),(-1.,1.)]
            for other in seeds:
                if other==seed:continue
                nx=other.x()-seed.x(); ny=other.y()-seed.y()
                bound=(other.x()**2+other.y()**2-seed.x()**2-seed.y()**2)/2
                if not vertices:break
                clipped=[]; previous=vertices[-1]
                previous_value=previous[0]*nx+previous[1]*ny-bound
                for current in vertices:
                    value=current[0]*nx+current[1]*ny-bound
                    if (value<=0)!=(previous_value<=0):
                        ratio=previous_value/(previous_value-value)
                        clipped.append((previous[0]+ratio*(current[0]-previous[0]),
                                        previous[1]+ratio*(current[1]-previous[1])))
                    if value<=0:clipped.append(current)
                    previous,previous_value=current,value
                vertices=clipped
            if not vertices:continue
            shape=QPainterPath(); shape.moveTo(*vertices[0])
            for point in vertices[1:]:shape.lineTo(*point)
            shape.closeSubpath()
            if not shape.isEmpty():pieces.append((shape,seed))
        return pieces

    def _draw_full_layer(self,p,center,radius,index,entries):
        if index==0:
            self.art.draw_detail(p,self.index,center,radius,round(self.angle/.08)*.08)
        else:
            self._draw_material(p,center,radius,index,entries)

    def _draw_material(self,p,center,radius,index,entries):
        """Bounded offline illustrations of rock, dense fluid, and core."""
        transform=p.worldTransform()
        scale=math.sqrt(abs(transform.m11()*transform.m22()-transform.m12()*transform.m21()))
        physical=radius*scale*p.device().devicePixelRatioF()
        side=256 if physical<100 else 384 if physical<190 else 512
        key=(self.index,index,side)
        image=self._material_cache.get(key)
        if image is None:
            image=QPixmap(side,side);image.fill(Qt.GlobalColor.transparent)
            q=QPainter(image);q.setRenderHint(QPainter.RenderHint.Antialiasing)
            r=side/2.;c=QPointF(r,r);color=QColor(entries[index].color)
            gradient=QRadialGradient(c-QPointF(r*.32,r*.38),r*1.65)
            gradient.setColorAt(0,color.lighter(150));gradient.setColorAt(.48,color)
            gradient.setColorAt(1,color.darker(190))
            q.setPen(Qt.PenStyle.NoPen);q.setBrush(gradient);q.drawEllipse(c,r,r)
            disc=QPainterPath();disc.addEllipse(c,r,r);q.setClipPath(disc)
            rng=random.Random(4709+self.index*37+index*101)
            is_core=index>=CORE_START[self.index]
            is_fluid=((self.index>=4 and not is_core) or
                      (self.index==1 and index==0) or (self.index==2 and index==2))
            if is_fluid:
                # Broad wispy variations suggest a fluid; they are not maps of
                # the unobserved planetary interior or hard layer boundaries.
                for _ in range(45):
                    y=rng.uniform(0,side); path=QPainterPath(QPointF(-side*.1,y))
                    path.cubicTo(side*.20,y+rng.uniform(-.13,.13)*side,
                                 side*.65,y+rng.uniform(-.13,.13)*side,
                                 side*1.1,y+rng.uniform(-.04,.04)*side)
                    ink=color.lighter(rng.randint(120,165)) if rng.random()<.5 else color.darker(rng.randint(120,155))
                    ink.setAlpha(rng.randint(10,30));q.setPen(QPen(ink,rng.uniform(.004,.022)*side))
                    q.setBrush(Qt.BrushStyle.NoBrush);q.drawPath(path)
            elif not is_core:
                # Subtle mottling suggests solid rock, not a pool of lava.
                for _ in range(210):
                    x=rng.uniform(0,side);y=rng.uniform(0,side)
                    ink=color.lighter(rng.randint(115,160)) if rng.random()<.5 else color.darker(rng.randint(120,170))
                    ink.setAlpha(rng.randint(12,36));q.setPen(Qt.PenStyle.NoPen);q.setBrush(ink)
                    w=rng.uniform(.004,.035)*side
                    q.drawEllipse(QPointF(x,y),w,w*rng.uniform(.28,.8))
                for _ in range(16):
                    y=rng.uniform(0,side); path=QPainterPath(QPointF(-side*.05,y))
                    path.cubicTo(side*.22,y+rng.uniform(-.1,.1)*side,
                                 side*.68,y+rng.uniform(-.1,.1)*side,
                                 side*1.05,y+rng.uniform(-.06,.06)*side)
                    ink=color.darker(160);ink.setAlpha(28);q.setPen(QPen(ink,side*.002))
                    q.setBrush(Qt.BrushStyle.NoBrush);q.drawPath(path)
            else:
                # Smooth shading for the innermost core and metallic regions.
                highlight=QRadialGradient(c-QPointF(r*.35,r*.38),r*.65)
                highlight.setColorAt(0,QColor(255,245,204,42));highlight.setColorAt(1,QColor(255,215,160,0))
                q.setPen(Qt.PenStyle.NoPen);q.setBrush(highlight);q.drawEllipse(c,r,r)
            if self.index>=4 and index>0:
                # Gas giant boundaries are uncertain and gradual, not hard shells.
                fade=QRadialGradient(c,r)
                fade.setColorAt(0,QColor(255,255,255,255))
                fade.setColorAt(.87,QColor(255,255,255,255))
                fade.setColorAt(1,QColor(255,255,255,0))
                q.setClipping(False);q.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
                q.setPen(Qt.PenStyle.NoPen);q.setBrush(fade);q.drawRect(QRectF(0,0,side,side))
            q.end();self._material_cache[key]=image
            while len(self._material_cache)>8:self._material_cache.popitem(last=False)
        else:self._material_cache.move_to_end(key)
        p.save();p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawPixmap(QRectF(center.x()-radius,center.y()-radius,2*radius,2*radius),image,QRectF(image.rect()))
        p.restore()

    def _draw_shards(self,p,center,radius,index,entries,phase,opacity=1.):
        if phase<=.0001:
            p.save(); p.setOpacity(opacity)
            self._draw_full_layer(p,center,radius,index,entries); p.restore(); return
        # First show the cracks; fragments only move once they have formed.
        movement=max(0.,min(1.,(phase-.35)/.65))
        movement=movement*movement*(3.-2.*movement)
        color=QColor(entries[index].color)
        for i,(path,seed) in enumerate(self._shards):
            angle=math.atan2(seed.y(),seed.x()) if not seed.isNull() else i*2.4
            drift=radius*(.58+.15*((i*7)%5)/4)*movement
            p.save(); p.setOpacity(opacity)
            p.translate(center.x()+math.cos(angle)*drift,center.y()+math.sin(angle)*drift)
            p.rotate(movement*(1 if i%2 else -1)*(5+i%4*2)); p.scale(radius,radius)
            p.save(); p.setClipPath(path,Qt.ClipOperation.IntersectClip)
            p.setClipPath(self._unit_sphere,Qt.ClipOperation.IntersectClip)
            self._draw_full_layer(p,QPointF(),1.,index,entries)
            # A short glint follows the fragment; seams form the glass cracks.
            glint=QColor('#ffffff'); glint.setAlpha(round(60*min(1.,phase*3)))
            p.setPen(QPen(glint,.009)); p.drawLine(seed+QPointF(-.10,-.05),seed+QPointF(.04,-.14))
            p.restore()
            edge=QColor('#e1fbff') if index==0 else color.lighter(185)
            edge.setAlpha(round(210*min(1.,phase*5)))
            p.setPen(QPen(edge,.012)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.save(); p.setClipPath(self._unit_sphere,Qt.ClipOperation.IntersectClip); p.drawPath(path); p.restore()
            p.save(); p.setClipPath(path,Qt.ClipOperation.IntersectClip); p.drawPath(self._unit_sphere); p.restore()
            p.restore()

    def _draw_completed(self,p,center,radius,index,entries):
        """Cache fragments in a bounded, zoom-aware crop around the planet."""
        dpr=self.devicePixelRatioF()
        tier=1. if self.zoom<1.35 else 1.5 if self.zoom<1.85 else 2.
        extent=radius*2.05
        pixel_scale=min(dpr*tier,1536/(extent*2))
        key=(self.index,index,round(radius,3),round(pixel_scale,3),round(self.angle/.08))
        cached=self._completed_cache.get(key)
        if cached is None:
            side=max(1,math.ceil(extent*2*pixel_scale))
            cached=QPixmap(side,side)
            cached.setDevicePixelRatio(pixel_scale); cached.fill(Qt.GlobalColor.transparent)
            offscreen=QPainter(cached); offscreen.setRenderHint(QPainter.RenderHint.Antialiasing)
            offscreen.translate(-center.x()+extent,-center.y()+extent)
            self._draw_shards(offscreen,center,radius,index,entries,1.,.40)
            offscreen.end(); self._completed_cache[key]=cached
            while len(self._completed_cache)>3:self._completed_cache.popitem(last=False)
        else:self._completed_cache.move_to_end(key)
        p.drawPixmap(QPointF(center.x()-extent,center.y()-extent),cached)

    def _draw_cutaway(self,p,center,radius,entries):
        """Open a partial cutaway and reveal deeper regions progressively."""
        self.art.draw_detail(p,self.index,center,radius,round(self.angle/.08)*.08)
        amount=max(0.,min(1.,self.amount))
        if amount<.001:return
        progress=amount*amount*(3.-2.*amount)
        extent=88.*progress
        bounds=QRectF(center.x()-radius,center.y()-radius,2*radius,2*radius)
        wedge=QPainterPath(center)
        wedge.arcTo(bounds,18.,-extent)
        wedge.closeSubpath()
        p.save();p.setClipPath(wedge,Qt.ClipOperation.IntersectClip)
        # A shaded radial face preserves the spherical outline. Each following
        # layer is revealed only as the user advances through its stage.
        radii=LAYER_RADII[self.index]
        for i,entry in enumerate(entries):
            opacity=1. if i==0 else max(0.,min(1.,amount*len(entries)-(i-1)))
            if opacity<=0.:continue
            r=radius*radii[i]
            p.save();p.setOpacity(opacity);self._draw_material(p,center,r,i,entries);p.restore()
        # Interior boundaries are schematic, especially for the gas giants.
        for i in range(1,len(entries)) if self.index<4 else ():
            visible=max(0.,min(1.,amount*len(entries)-(i-1)))
            if visible<=0.:continue
            r=radius*radii[i]
            edge=QColor('#ffeacb' if self.index<4 else '#d6eef0');edge.setAlpha(round(120*visible))
            p.setPen(QPen(edge,max(.5,radius*.009)));p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(center,r,r)
        p.restore()
        edge=QColor('#e3f3ed');edge.setAlpha(170)
        p.setPen(QPen(edge,max(.5,radius*.008)));p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(wedge)

    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds=QPainterPath(); bounds.addRoundedRect(QRectF(self.rect()).adjusted(.5,.5,-.5,-.5),18,18)
        p.setClipPath(bounds)
        back=QLinearGradient(0,0,self.width(),self.height())
        back.setColorAt(0,QColor('#081522')); back.setColorAt(.55,QColor('#0b1b2b')); back.setColorAt(1,QColor('#10172b'))
        p.fillRect(self.rect(),back)
        rng=random.Random(432)
        for _ in range(95):
            c=QColor('#b5d7e6'); c.setAlpha(rng.randrange(25,100)); p.setPen(c)
            p.drawPoint(QPointF(rng.random()*self.width(),rng.random()*self.height()))
        p.setFont(QFont('Segoe UI',9)); p.setPen(QColor('#8dcac5'))
        p.drawText(18,27,'KHÁM PHÁ BÊN TRONG  /  '+PLANETS[self.index].name.upper())
        p.setPen(QColor('#7f9cac'))
        note=('Hiệu ứng vỡ minh họa · lớp chất lỏng không vỡ như kính' if self.glass_effect
              else 'Mô hình minh họa · lớp mỏng phóng đại, lõi còn nghiên cứu')
        p.drawText(18,self.height()-17,note)
        center=QPointF(self.width()/2,self.height()/2)
        p.save(); p.translate(center+self.pan); p.scale(self.zoom,self.zoom); p.translate(-center)
        w,h=float(self.width()),float(self.height())
        entries=layers_for(self.index)
        center,radius=self._scene_layout(w,h)
        stage,phase=self.stage_for(self.amount,len(entries))
        glow=QRadialGradient(center,radius*2.4)
        glow.setColorAt(0,QColor(65,154,171,48)); glow.setColorAt(1,QColor(65,154,171,0))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(glow); p.drawEllipse(center,radius*2.4,radius*2.4)
        if self.glass_effect:
            # Use each planet's own approximate radii rather than equally spaced
            # spheres. Only the innermost region is never shattered.
            radii=LAYER_RADII[self.index]
            for i in range(stage):
                self._draw_completed(p,center,radius*radii[i],i,entries)
            if stage==len(entries)-1:
                self._draw_full_layer(p,center,radius*radii[stage],stage,entries)
            else:
                self._draw_full_layer(p,center,radius*radii[stage+1],stage+1,entries)
                self._draw_shards(p,center,radius*radii[stage],stage,entries,phase)
        else:
            self._draw_cutaway(p,center,radius,entries)
        # Labels remain fixed and clickable while the artwork is zoomed/panned.
        p.restore()
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(7,18,30,180))
        p.drawRoundedRect(QRectF(12,34,w-24,26),7,7)
        p.setFont(QFont('Segoe UI',9,QFont.Weight.DemiBold)); p.setPen(QColor('#caeee7'))
        p.drawText(QRectF(18,37,w-36,22),Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,
                   f'ĐIỂM {stage+1}/{len(entries)} · {entries[stage].name} · {round(phase*100)}%')

        # A two-column legend stays readable and clickable on small laptop windows.
        self.hit_boxes=[]
        if self.amount>.30:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(7,18,30,195))
            p.drawRoundedRect(QRectF(10,h-124,w-20,96),9,9)
            p.save(); p.setOpacity(min(1.,(self.amount-.30)/.10))
            p.setFont(QFont('Segoe UI',8)); p.setPen(QColor('#8dcac5'))
            p.drawText(QPointF(18,h-109),'CÁC LỚP BÊN TRONG')
            for i,entry in enumerate(entries):
                x=18+(i%2)*(w-36)/2; y=h-100+(i//2)*22
                label=QRectF(x,y,(w-44)/2,20)
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(entry.color)); p.drawEllipse(QPointF(x+5,y+10),3.4,3.4)
                p.setFont(QFont('Segoe UI',9,QFont.Weight.DemiBold if i==self.selected_layer else QFont.Weight.Normal))
                p.setPen(QColor('#eaf8f4' if i==self.selected_layer else '#b2ccd2'))
                shown=p.fontMetrics().elidedText(f'{i+1} · {entry.name}',Qt.TextElideMode.ElideRight,int(label.width()-17))
                p.drawText(label.adjusted(14,0,0,0),Qt.AlignmentFlag.AlignVCenter,shown)
                self.hit_boxes.append((i,label))
            p.restore()
        selected=entries[self.selected_layer]
        p.setFont(QFont('Segoe UI',9)); p.setPen(QColor('#b6d6d7'))
        desc=QRectF(18,h-53,w-36,27)
        description=f'{selected.name}: {selected.description}'
        p.drawText(desc,Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter|Qt.TextFlag.TextWordWrap,
                   p.fontMetrics().elidedText(description,Qt.TextElideMode.ElideRight,int(desc.width()*1.6)))
        p.setClipping(False); p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor('#2c4858'),1)); p.drawPath(bounds); p.end()
