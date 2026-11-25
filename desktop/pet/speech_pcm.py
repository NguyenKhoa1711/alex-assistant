"""Remove excessive quiet at utterance edges, preserving internal pauses."""
import numpy as np


class SpeechEdges:
    def __init__(self, sample_rate=48000, lead_ms=40, tail_ms=100, threshold=32):
        self.lead=int(sample_rate*lead_ms/1000)*2
        self.tail=int(sample_rate*tail_ms/1000)*2
        self.threshold=threshold
        self.quiet=b''
        self.started=False

    def feed(self, pcm: bytes) -> bytes:
        if len(pcm)%2: raise ValueError('Invalid int16 PCM')
        if not pcm: return b''
        samples=np.frombuffer(pcm,dtype='<i2')
        active=np.flatnonzero(np.abs(samples.astype(np.int32))>self.threshold)
        if not len(active):
            self.quiet+=pcm
            if not self.started: self.quiet=self.quiet[-self.lead:] if self.lead else b''
            return b''
        end=(int(active[-1])+1)*2
        if not self.started:
            start=int(active[0])*2
            prefix=(self.quiet+pcm[:start])[-self.lead:] if self.lead else b''
            output=prefix+pcm[start:end]
            self.started=True
        else:
            output=self.quiet+pcm[:end]
        self.quiet=pcm[end:]
        return output

    def finish(self) -> bytes:
        output=self.quiet[:self.tail] if self.started else b''
        self.quiet=b''
        return output


def trim_speech_edges(pcm: bytes, sample_rate=48000) -> bytes:
    trim=SpeechEdges(sample_rate)
    return trim.feed(pcm)+trim.finish()
