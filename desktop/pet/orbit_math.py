"""Illustrative heliocentric orbits, not an ephemeris or a distance-scale model."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Planet:
    name: str
    color: str
    days: float
    distance: float  # million km, NASA Planetary Fact Sheet
    radius: float    # presentation units; compressed distance
    size: float      # presentation pixels, deliberately enlarged
    eccentricity: float
    inclination: float
    phase: float
    note: str


PLANETS = (
    Planet('Sao Thủy', '#b9aaa2', 88, 57.9, 1.25, 4, .206, 7, .5, 'Hành tinh gần Mặt Trời nhất.'),
    Planet('Sao Kim', '#edcb87', 224.7, 108.2, 1.85, 6, .007, 3.4, 2, 'Khí quyển dày giữ nhiệt rất mạnh.'),
    Planet('Trái Đất', '#65bcff', 365.2, 149.6, 2.5, 7, .017, 0, 4.5, 'Ngôi nhà của chúng ta trong hệ Mặt Trời.'),
    Planet('Sao Hỏa', '#ee886b', 687, 228, 3.15, 5, .094, 1.8, 5.6, 'Màu đỏ đến từ khoáng vật sắt trên bề mặt.'),
    Planet('Sao Mộc', '#dcb38e', 4331, 778.5, 4.15, 14, .049, 1.3, 2.8, 'Hành tinh lớn nhất trong hệ Mặt Trời.'),
    Planet('Sao Thổ', '#edce94', 10747, 1432, 5.25, 12, .052, 2.5, .3, 'Nổi bật với hệ vành đai bằng băng và đá.'),
    Planet('Sao Thiên Vương', '#94e5e8', 30589, 2867, 6.25, 9, .047, .8, 3.8, 'Một hành tinh băng khổng lồ với trục quay nghiêng mạnh.'),
    Planet('Sao Hải Vương', '#728eff', 59800, 4515, 7.25, 9, .010, 1.8, 5.2, 'Hành tinh xa Mặt Trời nhất trong tám hành tinh.'),
)


def orbital_point(planet, days=0, anomaly=None):
    """Solve Kepler's equation; display radii are intentionally compressed."""
    mean = (planet.phase + days / planet.days * math.tau) % math.tau
    eccentric = mean if anomaly is None else anomaly
    if anomaly is None:
        for _ in range(6):
            eccentric -= (eccentric - planet.eccentricity * math.sin(eccentric) - mean) / (1 - planet.eccentricity * math.cos(eccentric))
    x = planet.radius * (math.cos(eccentric) - planet.eccentricity)
    y = planet.radius * math.sqrt(1 - planet.eccentricity ** 2) * math.sin(eccentric)
    inc = math.radians(planet.inclination)
    return x, y * math.cos(inc), y * math.sin(inc)


def project(point, yaw, tilt):
    x, y, z = point
    xx = x * math.cos(yaw) - y * math.sin(yaw)
    yy = x * math.sin(yaw) + y * math.cos(yaw)
    return xx, yy * math.sin(tilt) - z * math.cos(tilt), yy * math.cos(tilt) + z * math.sin(tilt)


class DoublePinch:
    """Two short touches by the same hand; uses landmarks only, never pixels."""
    CLOSE=.45
    OPEN=.52
    def __init__(self):self.reset()

    def reset(self):
        self.state='idle';self.first_at=0.;self.release_at=0.
        self.anchor=None;self.last_pos=None;self.last_seen=None
        self.cooldown_until=0.;self.feedback=''

    @staticmethod
    def _ratio(hand):
        return math.dist(hand[4],hand[8])/max(.03,math.dist(hand[0],hand[9]))

    def update(self,hands,now):
        self.feedback=''
        if not hands:
            # Keep a short camera tracking dropout from destroying a tap.
            if self.last_seen is None or now-self.last_seen>.25:
                self.state='idle';self.anchor=None;self.last_pos=None
            return False
        if now<self.cooldown_until:return False
        ratios=[self._ratio(hand) for hand in hands]
        if self.state=='blocked':
            if all(r>self.OPEN for r in ratios):self.state='idle';self.anchor=None
            return False
        if self.state=='idle':
            closed=[i for i,r in enumerate(ratios) if r<self.CLOSE]
            # Two simultaneous pinches are reserved for separating layers.
            if len(closed)>1:self.state='blocked';return False
            if not closed:return False
            h=hands[closed[0]]
            self.anchor=tuple(h[9]);self.last_pos=self.anchor;self.last_seen=now
            self.state='down';self.first_at=now
            self.feedback='Đã chạm 1 · thả và chạm lần 2'
            return False
        # Associate by palm position, which stays stable while fingers open.
        owner=min(range(len(hands)),key=lambda i:math.dist(hands[i][9],self.last_pos))
        pos=tuple(hands[owner][9]);self.last_seen=now
        if math.dist(pos,self.last_pos)>.20 or math.dist(pos,self.anchor)>.12:
            self.state='blocked';return False
        if any(r<self.CLOSE for i,r in enumerate(ratios) if i!=owner):
            self.state='blocked';return False
        self.last_pos=pos
        ratio=ratios[owner]
        if self.state=='down':
            if now-self.first_at>.80:self.state='blocked'
            elif ratio>self.OPEN:self.state='between';self.release_at=now
            if self.state!='blocked':self.feedback='Đã chạm 1 · thả và chạm lần 2'
            return False
        if now-self.first_at>1.6:
            self.state='blocked' if ratio<self.CLOSE else 'idle'
            return False
        if ratio<self.CLOSE and now-self.release_at>=.04:
            self.state='blocked';self.cooldown_until=now+1.1
            self.feedback='Đã nhận 2 lần chạm'
            return True
        self.feedback='Đã chạm 1 · chạm lần 2'
        return False


class FullscreenV:
    """Opt-in camera landmark gesture: hold an index/middle V to toggle."""
    HOLD_SECONDS=1.1
    def __init__(self):self.reset()

    def reset(self):
        self.started=None;self.last_valid=None;self.frames=0
        self.latched=False;self.release_at=None;self.cooldown_until=0.
        self.holding=False;self.feedback=''

    @staticmethod
    def is_v(hand):
        wrist=hand[0]
        palm=max(.03,math.dist(wrist,hand[9]))
        def extended(tip,pip):
            return math.dist(wrist,hand[tip])>math.dist(wrist,hand[pip])+.05*palm
        def folded(tip,pip):
            return math.dist(wrist,hand[tip])<math.dist(wrist,hand[pip])+.08*palm
        return (extended(8,6) and extended(12,10) and folded(16,14) and folded(20,18)
                and math.dist(hand[8],hand[12])>.20*palm
                and math.dist(hand[4],hand[8])>.55*palm)

    def update(self,hands,now):
        self.feedback='';self.holding=False
        candidates=[i for i,h in enumerate(hands) if self.is_v(h)]
        # Two V signs or another pinched hand would conflict with two-hand
        # navigation. A relaxed second hand is allowed.
        valid=len(candidates)==1
        if valid:
            owner=candidates[0]
            valid=not any(i!=owner and DoublePinch._ratio(h)<.55 for i,h in enumerate(hands))
        if self.latched:
            if valid:
                self.holding=True;self.release_at=None
            else:
                if self.release_at is None:self.release_at=now
                if now-self.release_at>=.25:
                    self.latched=False;self.release_at=None
                    self.started=None;self.last_valid=None;self.frames=0
            return False
        if now<self.cooldown_until:return False
        if not valid:
            # One missed tracking frame should not restart an intentional hold.
            if self.last_valid is None or now-self.last_valid>.20:
                self.started=None;self.frames=0
            return False
        self.holding=True
        if self.started is None:self.started=now;self.frames=0
        self.last_valid=now;self.frames+=1
        elapsed=max(0.,now-self.started)
        if elapsed>=self.HOLD_SECONDS and self.frames>=5:
            self.latched=True;self.cooldown_until=now+1.1
            self.feedback='Đã nhận chữ V'
            return True
        self.feedback=f'Giữ chữ V · {min(1.,elapsed/self.HOLD_SECONDS):.0%}'
        return False


class PlanetSwipe:
    """One open palm swiped horizontally; release before the next selection."""
    DISTANCE = .16
    WINDOW = 1.2
    COOLDOWN = .9

    def __init__(self):
        self.reset()

    def reset(self):
        self.start = self.last = None
        self.start_time = self.last_time = 0.
        self.frames = 0
        self.latched = False
        self.released_at = None
        self.cooldown_until = 0.

    @staticmethod
    def is_open(hand):
        if len(hand) != 21:
            return False
        wrist = hand[0]
        palm = max(.03, math.dist(wrist, hand[9]))
        fingers = ((8, 6), (12, 10), (16, 14), (20, 18))
        extended = all(math.dist(wrist, hand[tip]) > math.dist(wrist, hand[pip]) + .10*palm
                       for tip, pip in fingers)
        return extended and math.dist(hand[4], hand[8]) > .65*palm

    def update(self, hands, now):
        valid = len(hands) == 1 and self.is_open(hands[0])
        if not valid:
            self.start = self.last = None
            self.frames = 0
            if self.latched:
                if self.released_at is None:
                    self.released_at = now
                elif now-self.released_at >= .25:
                    self.latched = False
            return 0
        self.released_at = None
        if self.latched or now < self.cooldown_until:
            return 0
        p = hands[0][9]
        point = (float(p[0]), float(p[1]))
        if not (.04 < point[0] < .96 and .04 < point[1] < .96):
            self.start = self.last = None
            self.frames = 0
            return 0
        if (self.start is None or now-self.start_time > self.WINDOW or
                now-self.last_time > .3 or (self.last is not None and math.dist(point, self.last) > .14)):
            self.start, self.start_time, self.frames = point, now, 1
        else:
            self.frames += 1
        self.last, self.last_time = point, now
        dx, dy = point[0]-self.start[0], point[1]-self.start[1]
        if self.frames >= 3 and abs(dx) >= self.DISTANCE and abs(dy) <= .12:
            self.latched = True
            self.cooldown_until = now+self.COOLDOWN
            self.start = self.last = None
            return 1 if dx > 0 else -1
        return 0


class GestureMotion:
    """Only controls the visualization. No clicks, OS keys or assistant commands."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.previous = None
        self.mode = ''
        self.last_time = 0
        self.separation_delta = 0.
        self._separation_anchor = None

    @staticmethod
    def _pinched(hand, continuing=False):
        palm = max(.03, math.dist(hand[0], hand[9]))
        return math.dist(hand[4], hand[8]) < palm * (.55 if continuing else .42)

    def update(self, hands, now):
        self.separation_delta = 0.
        if not hands or now - self.last_time > .5:
            self.previous = None
            self._separation_anchor = None
        self.last_time = now
        if not hands:
            self.mode = ''
            return 0., 0., 1., 'Đưa bàn tay vào khung hình'
        hands = sorted(hands[:2], key=lambda h: h[0][0])
        if len(hands) == 2:
            pinches=[self._pinched(h,self.mode=='separate') for h in hands]
            if all(pinches):
                a,b=hands[0][9],hands[1][9]
                current=(math.hypot(a[0]-b[0],a[1]-b[1]),)
                mode='separate'
                tip='Chụm hai tay • kéo ra / khép lại để tách / ghép lớp'
            elif any(pinches):
                # A pinched hand is the rotation clutch, even while the other
                # hand is still visible. Never resize while changing to rotate.
                h=hands[pinches.index(True)]
                current=((h[4][0]+h[8][0])/2,(h[4][1]+h[8][1])/2)
                mode='rotate';tip='Đang xoay • giữ chụm một tay để khóa zoom'
            else:
                a,b=hands[0][9],hands[1][9]
                if any(not (.06<=p[0]<=.94 and .06<=p[1]<=.94) for p in (a,b)):
                    self.previous=None;self.mode='edge'
                    return 0.,0.,1.,'Giữ hai bàn tay trong khung hình để zoom'
                current=(math.hypot(a[0]-b[0],a[1]-b[1]),)
                mode='zoom';tip='Hai tay mở • đưa ra / khép vào để thu phóng'
        else:
            h = hands[0]
            if not self._pinched(h, self.mode == 'rotate'):
                self.reset()
                return 0., 0., 1., 'Chụm ngón cái và trỏ, rồi di chuyển để xoay'
            current = ((h[4][0]+h[8][0])/2, (h[4][1]+h[8][1])/2)
            mode, tip = 'rotate', 'Đang xoay • thả ngón tay để dừng'
        result = (0., 0., 1., tip)
        if self.previous is not None and self.mode == mode:
            if mode == 'rotate':
                # Ignore discontinuities instead of jumping when tracking swaps hands.
                dx, dy = current[0]-self.previous[0], current[1]-self.previous[1]
                if abs(dx) < .15 and abs(dy) < .15:
                    result = (dx * 3.4, dy * 2.6, 1., tip)
            elif mode == 'separate':
                # Keep sub-threshold movement instead of discarding it each
                # frame: slow intentional drags should still advance layers.
                anchor = self._separation_anchor
                if anchor is None:
                    anchor = self.previous[0]
                delta = current[0] - anchor
                if .002 <= abs(delta) < .15:
                    self.separation_delta = delta
                    self._separation_anchor = current[0]
                elif abs(delta) >= .15:
                    # Rebase a tracking discontinuity; never apply the jump.
                    self._separation_anchor = current[0]
            elif self.previous[0] > .06:
                ratio = current[0] / self.previous[0]
                # Suppress small camera jitter and limit each zoom step.
                if abs(ratio-1.)>.006:
                    result = (0., 0., max(.96, min(1.04, ratio**.75)), tip)
        if mode == 'separate' and self.mode != mode:
            self._separation_anchor = current[0]
        elif mode != 'separate':
            self._separation_anchor = None
        self.mode, self.previous = mode, current
        return result
