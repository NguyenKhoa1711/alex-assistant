import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import numpy as np
from PySide6.QtWidgets import QApplication
from pet import voice_motion
from pet.hologram_face import HologramFace
from pet.tts import Speaker
from pet.tts_turbo import TurboSpeaker
from pet.polyglot_tts import HybridSpeaker


class FacialMotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def tearDown(self):
        voice_motion.clear()

    def test_audio_meter_is_transient_and_uses_only_volume(self):
        with patch('pet.voice_motion.time.monotonic', return_value=10.):
            voice_motion.feed_pcm(np.full(512, 4000, dtype=np.int16))
        self.assertGreater(voice_motion.level(10.1),0.)
        self.assertEqual(voice_motion.level(10.3),0.)
        voice_motion.clear(); self.assertEqual(voice_motion.level(10.1),0.)

    def test_eye_blink_and_speech_change_face_and_silence_closes_mouth(self):
        face=HologramFace(); face.resize(520,440); face.show(); self.app.processEvents(); face.timer.stop()
        try:
            self.assertFalse(face.portrait.isNull())
            self.assertEqual(face.blink_frame.size(),face.portrait.size())
            self.assertEqual(face.talk_frame.size(),face.portrait.size())
            face.phase=2.; face._invalidate(); eyes_open=face.grab().toImage()
            face.phase=3.7; face._invalidate(); eyes_closed=face.grab().toImage()
            self.assertNotEqual(eyes_open,eyes_closed)
            face.phase=2.; face.set_mode('speaking')
            with patch('pet.human_portrait.voice_motion.level',return_value=.9):
                for _ in range(10): face._advance(1/30)
            self.assertGreater(face.lip_open,.5)
            talking=face.grab().toImage()
            with patch('pet.human_portrait.voice_motion.level',return_value=0.):
                for _ in range(30): face._advance(1/30)
            self.assertLess(face.lip_open,.01)
            self.assertNotEqual(talking,face.grab().toImage())
            face.set_reduced_motion(True)
            self.assertFalse(face.timer.isActive())
        finally:
            face.hide(); face.deleteLater(); self.app.processEvents()

    def test_piper_playback_feeds_levels_without_opening_a_device(self):
        samples=np.full(1024,1000,dtype=np.int16)
        speaker=Speaker.__new__(Speaker); speaker.speed=1.; speaker.device=None
        speaker.voice=SimpleNamespace(synthesize=lambda *a,**k: [SimpleNamespace(
            audio_int16_bytes=samples.tobytes(),sample_rate=48000)])
        fake_stream=MagicMock()
        fake_stream.__enter__.return_value=fake_stream
        with patch('pet.tts.sd.OutputStream',return_value=fake_stream), \
             patch('pet.tts.voice_motion.feed_pcm', wraps=voice_motion.feed_pcm) as meter:
            speaker.speak('test',threading.Event(),lambda _t: None)
        self.assertEqual(meter.call_count,2)
        self.assertEqual(fake_stream.write.call_count,2)
        self.assertEqual(voice_motion.level(),0.)

    def test_turbo_and_native_voice_feed_level_without_extra_audio_stream(self):
        pcm=np.full(4096,1000,dtype=np.int16).tobytes()
        stream=MagicMock(); calls=[]
        turbo=TurboSpeaker.__new__(TurboSpeaker); turbo.device=None
        turbo._get_cached=MagicMock(return_value=(48000,pcm))
        with patch('pet.tts_turbo.sd.OutputStream',return_value=stream) as output, \
             patch('pet.tts_turbo.voice_motion.feed_pcm', wraps=voice_motion.feed_pcm) as meter:
            turbo.speak_sequence(['mẫu'],threading.Event(),calls.append)
        self.assertEqual(output.call_count,1)
        self.assertEqual(len(calls),1)
        self.assertEqual(meter.call_count,2)
        self.assertEqual(stream.write.call_count,2)
        self.assertEqual(voice_motion.level(),0.)
        native=HybridSpeaker(MagicMock(),None)
        native.render_pcm=MagicMock(return_value=(48000,pcm))
        stream=MagicMock(); stream.__enter__.return_value=stream
        with patch('pet.polyglot_tts.sd.OutputStream',return_value=stream) as output, \
             patch('pet.polyglot_tts.voice_motion.feed_pcm', wraps=voice_motion.feed_pcm) as meter:
            native.speak('\ue100en\ue101hello\ue102',threading.Event(),lambda _t:None)
        self.assertEqual(output.call_count,1)
        self.assertEqual(meter.call_count,2)
        self.assertEqual(voice_motion.level(),0.)
