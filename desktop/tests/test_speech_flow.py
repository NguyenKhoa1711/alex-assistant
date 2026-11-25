import base64
import json
from queue import Queue
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import patch
import numpy as np
from pet.speech_pcm import SpeechEdges, trim_speech_edges
from pet.tts_turbo import TurboSpeaker
from pet.polyglot_tts import HybridSpeaker


def quiet(ms): return bytes(48*ms*2)
def tone(ms,value=1000): return np.full(48*ms,value,dtype='<i2').tobytes()


class EdgeTests(unittest.TestCase):
    def test_caps_only_outer_quiet_and_preserves_speech(self):
        audio=quiet(500)+tone(250)+quiet(600)
        self.assertEqual(trim_speech_edges(audio),quiet(40)+tone(250)+quiet(100))

    def test_internal_pause_across_stream_chunks_is_not_shortened(self):
        trim=SpeechEdges()
        out=trim.feed(quiet(500))+trim.feed(tone(200)+quiet(250))
        out+=trim.feed(quiet(100))+trim.feed(tone(200)+quiet(600))+trim.finish()
        self.assertEqual(out,quiet(40)+tone(200)+quiet(350)+tone(200)+quiet(100))

    def test_all_quiet_produces_no_sound_and_negative_peak_stays(self):
        self.assertEqual(trim_speech_edges(quiet(500)),b'')
        self.assertEqual(trim_speech_edges(tone(20,-32768)),tone(20,-32768))
        with self.assertRaises(ValueError): trim_speech_edges(b'\x00')


class SequenceTests(unittest.TestCase):
    def speaker(self):
        speaker=object.__new__(TurboSpeaker)
        speaker.voice='Thái Sơn'; speaker.device=None; speaker.sequence=0
        speaker.render_lock=threading.Lock(); speaker.write_lock=threading.Lock()
        speaker._get_cached=lambda text:None
        speaker.cached={}
        speaker._put_cached=lambda text,sr,pcm:speaker.cached.update({text:pcm})
        speaker.pending=Queue(); speaker.messages=[]
        class Input:
            def write(self,raw):
                message=json.loads(raw)
                speaker.messages.append(message)
                for audio in (quiet(300)+tone(200),quiet(100)+tone(200)+quiet(600)):
                    speaker.pending.put({'id':message['id'],'chunk':base64.b64encode(audio).decode()})
                speaker.pending.put({'id':message['id'],'done':True})
            def flush(self): pass
        speaker.proc=SimpleNamespace(poll=lambda:None,stdin=Input())
        speaker._await=lambda request_id,event,timeout:speaker.pending.get(timeout=1)
        return speaker

    def test_all_sentences_stream_into_one_output_and_cache_trimmed_audio(self):
        speaker=self.speaker(); streams=[]; played=[]
        class Output:
            def __init__(self,**kw): self.audio=[]; streams.append(self)
            def start(self): pass
            def write(self,pcm): self.audio.append(pcm.tobytes())
            def stop(self): pass
            def close(self): pass
            def abort(self): pass
        with patch('pet.tts_turbo.sd.OutputStream',Output),patch('pet.tts_turbo.voice_motion.feed_pcm'),patch('pet.tts_turbo.voice_motion.clear'):
            speaker.speak_sequence(['Câu một.','Câu hai.','Câu ba.'],threading.Event(),played.append)
        self.assertEqual([m['stream'] for m in speaker.messages],[True,True,True])
        self.assertEqual(len(streams),1)
        self.assertEqual(len(played),1)
        expected=quiet(40)+tone(200)+quiet(100)+tone(200)+quiet(100)
        self.assertEqual(b''.join(streams[0].audio),expected*3)
        self.assertTrue(all(pcm==expected for pcm in speaker.cached.values()))

    def test_cancelled_sequence_never_starts_output(self):
        speaker=self.speaker(); event=threading.Event(); event.set()
        with patch('pet.tts_turbo.sd.OutputStream') as output:
            self.assertIsNone(speaker.speak_sequence(['Không phát.'],event,lambda _:None))
        output.assert_not_called()
        self.assertFalse(speaker.messages)


class MixedLanguagePauseTests(unittest.TestCase):
    def test_native_spans_keep_their_voice_and_have_short_boundaries(self):
        speaker=object.__new__(HybridSpeaker)
        speaker.vietnamese=SimpleNamespace(render_pcm=lambda text,event:(48000,quiet(300)+tone(100,1000)+quiet(500)))
        calls=[]
        def native(language,text,event):
            calls.append((language,text))
            return quiet(300)+tone(100,2000)+quiet(500)
        speaker._render_native=native
        marker='\ue100en\ue101Hello\ue102'
        rate,pcm=speaker.render_pcm('Chào. '+marker,threading.Event())
        self.assertEqual(calls,[('en','Hello')])
        self.assertEqual(rate,48000)
        self.assertEqual(pcm,quiet(40)+tone(100)+quiet(100)+quiet(40)+quiet(40)+tone(100,2000)+quiet(100))

if __name__=='__main__': unittest.main()
