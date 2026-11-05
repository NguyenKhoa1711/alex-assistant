"""Offline planetary maps and procedural fallback artwork.

Textures are built once. Only the selected portrait is resampled while rotating.
Bundled maps work offline; no GPU context, camera or extra dependencies.
"""
from functools import lru_cache
import math
from pathlib import Path
import numpy as np
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QImage, QPainter, QPainterPath, QColor


def _noise(h, w, sy, sx, seed):
    """Smooth longitude noise, stable across frames; wraps without a seam."""
    rng = np.random.default_rng(seed)
    grid = rng.random((sy + 1, sx + 1), dtype=np.float32)
    grid[:, -1] = grid[:, 0]
    x = np.arange(w, dtype=np.float32) * sx / w
    y = np.arange(h, dtype=np.float32) * sy / h
    ix, iy = x.astype(int), y.astype(int)
    fx, fy = x - ix, y - iy
    fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    a = grid[iy[:, None], ix] * (1 - fx) + grid[iy[:, None], ix + 1] * fx
    b = grid[iy[:, None] + 1, ix] * (1 - fx) + grid[iy[:, None] + 1, ix + 1] * fx
    return (a * (1 - fy[:, None]) + b * fy[:, None]).astype(np.float32)


def _earth_mask(h, w):
    # Illustrative coastlines. Rasterized once, then gently warped.
    shapes = [
        [(.05,.19),(.12,.12),(.23,.15),(.28,.24),(.22,.31),(.20,.40),(.16,.41),(.15,.34),(.10,.34),(.07,.28)],
        [(.18,.40),(.21,.43),(.25,.44),(.24,.49),(.20,.46)],
        [(.24,.46),(.29,.45),(.34,.51),(.33,.62),(.28,.72),(.26,.84),(.23,.75),(.21,.59)],
        [(.30,.10),(.37,.08),(.38,.20),(.33,.27),(.30,.19)],
        [(.43,.24),(.48,.21),(.49,.14),(.54,.13),(.54,.23),(.59,.19),(.64,.14),(.75,.15),(.88,.18),(.93,.28),(.86,.35),(.78,.33),(.75,.45),(.71,.47),(.68,.39),(.62,.45),(.60,.35),(.56,.33),(.54,.28),(.49,.31)],
        [(.44,.34),(.52,.32),(.59,.40),(.58,.50),(.53,.54),(.52,.67),(.48,.70),(.44,.60),(.40,.46)],
        [(.59,.60),(.61,.58),(.61,.69),(.58,.71)],
        [(.72,.51),(.78,.53),(.80,.56),(.76,.58)],
        [(.80,.63),(.87,.58),(.91,.64),(.91,.72),(.86,.77),(.78,.73),(.77,.67)],
        [(.95,.77),(.97,.72),(.98,.75),(.96,.82)],
        [(0,.94),(.18,.92),(.30,.95),(.45,.90),(.66,.94),(.80,.91),(1,.94),(1,1),(0,1)],
    ]
    image = QImage(w, h, QImage.Format.Format_RGBA8888); image.fill(QColor('black'))
    p = QPainter(image); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor('white'))
    for points in shapes:
        path = QPainterPath(QPointF(points[0][0]*w, points[0][1]*h))
        for x,y in points[1:]: path.lineTo(x*w,y*h)
        path.closeSubpath(); p.drawPath(path)
    p.end()
    return np.frombuffer(image.constBits(), np.uint8).reshape(h,w,4)[:,:,0].astype(np.float32)/255


def _blue_marble(high=True):
    """Load the bundled NASA map offline; fall back if it is missing or invalid."""
    path=Path(__file__).resolve().parent.parent/'assets/space/earth-blue-marble-2048.png'
    image=QImage(str(path))
    if image.isNull() or image.width()!=2048 or image.height()!=1024:return None
    if not high:
        image=image.scaled(1024,512,Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.SmoothTransformation)
    image=image.convertToFormat(QImage.Format.Format_RGB888)
    rows=np.frombuffer(image.constBits(),np.uint8).reshape(image.height(),image.bytesPerLine())
    rgb=rows[:,:image.width()*3].reshape(image.height(),image.width(),3).copy()
    # The static surface is NASA data; the light cloud layer is illustrative.
    cloud=.65*_noise(256,512,19,39,51)+.35*_noise(256,512,40,80,204)
    opacity=np.clip((cloud-.58)*2.2,0,.48)
    scale=image.width()//512
    opacity=np.repeat(np.repeat(opacity,scale,axis=0),scale,axis=1)[:,:,None]
    return np.ascontiguousarray((rgb*(1-opacity)+np.array([230,239,246],dtype=np.float32)*opacity).astype(np.uint8))


_MAPS = {
    0:'2k_mercury.jpg', 1:'2k_venus_atmosphere.jpg', 3:'2k_mars.jpg',
    4:'2k_jupiter.jpg', 5:'2k_saturn.jpg', 6:'2k_uranus.jpg', 7:'2k_neptune.jpg',
}


def _mapped_planet(index, high=False):
    """Load a local equirectangular map; reject broken/mismatched files."""
    if index==2:
        return _blue_marble(high)
    filename=_MAPS.get(index)
    if filename is None:return None
    path=Path(__file__).resolve().parent.parent/'assets/space'/filename
    image=QImage(str(path))
    if image.isNull() or image.width()!=2048 or image.height()!=1024:return None
    if not high:
        image=image.scaled(1024,512,Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.SmoothTransformation)
    image=image.convertToFormat(QImage.Format.Format_RGB888)
    rows=np.frombuffer(image.constBits(),np.uint8).reshape(image.height(),image.bytesPerLine())
    rgb=rows[:,:image.width()*3].reshape(image.height(),image.width(),3).copy()
    if index==7:
        # Historic Neptune imagery was often enhanced to a very deep blue.
        # Gently soften the illustrative map toward the more natural blue-cyan.
        r=rgb[:,:,0].astype(np.float32);g=rgb[:,:,1].astype(np.float32)
        b=rgb[:,:,2].astype(np.float32)
        rgb[:,:,0]=np.clip(.7*r+.3*g+14,0,255).astype(np.uint8)
        rgb[:,:,1]=np.clip(.8*g+.2*b+10,0,255).astype(np.uint8)
    return rgb


@lru_cache(maxsize=10)
def _texture(index, high=False):
    mapped=_mapped_planet(index,high)
    if mapped is not None:return mapped
    h,w = (512,1024) if index==2 else (256,512)
    v,u = np.mgrid[0:h,0:w].astype(np.float32)
    u /= w; v /= h
    coarse = _noise(h,w,8,16,102+index)
    fine = _noise(h,w,40,80,202+index)
    grain = _noise(h,w,100,200,302+index)
    detail = .55*coarse + .3*fine + .15*grain
    if index == 2:
        mask = _earth_mask(h,w)
        ix = ((u*w+(fine-.5)*9).astype(int))%w
        iy = np.clip((v*h+(coarse-.5)*7).astype(int),0,h-1)
        land = mask[iy,ix]
        arid = np.exp(-((v-.35)/.075)**2)*(.55+.45*coarse)
        ocean = np.stack((8+detail*10,36+detail*25,73+detail*39),axis=-1)
        green = np.stack((40+coarse*38+arid*90,64+fine*38+arid*61,39+coarse*21+arid*33),axis=-1)
        rgb = ocean*(1-land[:,:,None])+green*land[:,:,None]
        ice = np.clip((np.abs(v-.5)-.39)*20+coarse*.3,0,1)
        rgb = rgb*(1-ice[:,:,None])+np.array([205,227,233])*ice[:,:,None]
        clouds = .65*_noise(h,w,19,39,51)+.35*fine
        cloud = np.clip((clouds-.54)*3.4,0,.86)
        filaments=_noise(h,w,64,128,619)
        cloud *= .55+.25*filaments+.2*np.sin(u*math.tau*5+v*19+coarse*5)**2
        rgb = rgb*(1-cloud[:,:,None])+np.array([232,240,245])*cloud[:,:,None]
    elif index in (1,4,5,6,7):
        palettes={1:([128,83,38],[240,213,159]),4:([115,67,45],[230,217,189]),
                  5:([153,123,77],[231,215,176]),6:([66,139,156],[164,218,220]),
                  7:([19,46,121],[75,131,207])}
        low,high = (np.array(c,dtype=np.float32) for c in palettes[index])
        turbulence = (coarse-.5)*2.7 + (fine-.5)*.38
        bands = (.5+.5*np.sin(v*(95 if index==4 else 72)+turbulence))
        stripes = .5+.5*np.sin(v*263+coarse*3)
        blend = np.clip(.30+.42*bands+.14*stripes+.19*detail,0,1)
        if index in (6,7): blend=.45+.15*bands+.25*detail
        rgb = low[None,None,:]*(1-blend[:,:,None])+high[None,None,:]*blend[:,:,None]
        if index==4:
            dx=((u-.62+.5)%1-.5)/.053; dy=(v-.61)/.029
            spot=np.clip(1-(dx*dx+dy*dy)/1.5,0,1)
            swirl=.7+.3*np.sin((dx*dx+dy*dy)*14+fine*2)
            rgb=rgb*(1-spot[:,:,None]*.8)+np.array([164,81,49])*spot[:,:,None]*.8*swirl[:,:,None]
    else:
        low,high = (([245,72,7],[255,229,107]) if index==-1 else
                    ([92,42,23],[198,115,66]) if index==3 else ([66,62,57],[175,165,149]))
        t = np.clip(detail*1.3-.15,0,1)
        rgb=np.array(low)[None,None,:]*(1-t[:,:,None])+np.array(high)[None,None,:]*t[:,:,None]
        if index>=0:
            rng=np.random.default_rng(800+index)
            for _ in range(65):
                cx,cy=rng.uniform(0,1),rng.uniform(.13,.88)
                radius=rng.uniform(.004,.028)
                d=np.sqrt((((u-cx+.5)%1-.5)*np.cos((cy-.5)*math.pi))**2+(v-cy)**2)
                pit=np.exp(-(d/(radius*.65))**4)
                rim=np.exp(-((d-radius)/(radius*.17))**2)
                rgb *= (1-.26*pit+.18*rim)[:,:,None]
            if index==3:
                ice=np.clip((np.abs(v-.5)-.45)*25,0,1)
                rgb=rgb*(1-ice[:,:,None])+np.array([213,208,189])*ice[:,:,None]
    return np.ascontiguousarray(np.clip(rgb,0,255).astype(np.uint8))


@lru_cache(maxsize=3)
def _geometry(size):
    axis=(np.arange(size,dtype=np.float32)+.5)*2/size-1
    x,y=np.meshgrid(axis,axis)
    r=np.sqrt(x*x+y*y); z=np.sqrt(np.maximum(0,1-r*r))
    lon=np.arctan2(x,z)/math.tau + .5
    lat=np.arcsin(np.clip(y,-1,1))/math.pi + .5
    diffuse=np.maximum(0,-.48*x-.28*y+.83*z)
    light=.065+.935*diffuse**.78
    alpha=np.clip((1-r)*size/2+.5,0,1)
    return lon,lat,light,alpha,z


def sphere(index, size, phase=0.):
    """Owned antialiased RGBA image; bilinear sampling avoids stepping on rotation."""
    size=max(24,min(768,int(size)))
    lon,lat,light,alpha,z = _geometry(size)
    tex=_texture(index,size>256); h,w=tex.shape[:2]
    sx=((lon+(phase%math.tau)/math.tau)%1)*w
    sy=np.clip(lat*(h-1),0,h-1)
    ix=sx.astype(np.int32); iy=sy.astype(np.int32)
    fx=(sx-ix).astype(np.float32)[:,:,None]; fy=(sy-iy).astype(np.float32)[:,:,None]
    ix %= w
    nx=(ix+1)%w; ny=np.minimum(iy+1,h-1)
    rgb=(tex[iy,ix]*(1-fx)+tex[iy,nx]*fx)*(1-fy)+(tex[ny,ix]*(1-fx)+tex[ny,nx]*fx)*fy
    if index!=-1:
        rgb *= light[:,:,None]
        if index in (2,6,7):
            rim=(1-z)**4*light*.34
            rgb=rgb*(1-rim[:,:,None])+np.array([67,155,235])*rim[:,:,None]
    rgba=np.empty((size,size,4),np.uint8)
    rgba[:,:,:3]=np.clip(rgb,0,255).astype(np.uint8)
    rgba[:,:,3]=(alpha*255).astype(np.uint8)
    return QImage(rgba.data,size,size,rgba.strides[0],QImage.Format.Format_RGBA8888).copy()
