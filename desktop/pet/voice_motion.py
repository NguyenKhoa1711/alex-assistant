"""Transient output-volume signal for the portrait; never store audio or text."""
import time
import numpy as np

_sample = (0., 0.)


def feed_pcm(pcm):
    global _sample
    values = np.asarray(pcm, dtype=np.float32)
    if values.size:
        level = min(1., float(np.sqrt(np.mean(values * values))) / 32768. * 6.)
        _sample = (time.monotonic(), level)


def level(now=None):
    stamp, value = _sample
    now = time.monotonic() if now is None else now
    return value if 0 <= now-stamp <= .25 else 0.


def clear():
    global _sample
    _sample = (0., 0.)
