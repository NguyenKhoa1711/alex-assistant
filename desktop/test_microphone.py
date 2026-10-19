"""Compare local recognizers on the same microphone take, kept only in RAM."""
from __future__ import annotations
import gc
import json
import os
import sys
import threading
import time

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')

os.environ.update(HF_HUB_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1', DO_NOT_TRACK='1')
import numpy as np
import sounddevice as sd
from PySide6.QtCore import QObject, Signal, QTimer, QLockFile
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QLabel, QPushButton,
                              QComboBox, QPlainTextEdit, QProgressBar, QMessageBox)
from pet.config import ROOT, load_config
from pet.stt import SpeechToText
from pet.audio import Segmenter, FRAME_MS


class Results(QObject):
    message = Signal(str)
    done = Signal()


class MicTest(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle('Alex — Thử mic tiếng Việt')
        self.resize(780, 620)
        self.cfg = load_config()
        self.events = Results()
        self.events.message.connect(self.show_result)
        self.events.done.connect(self.ready)
        self.stream: sd.RawInputStream | None = None
        self.frames: list[bytes] = []
        self.statuses: set[str] = set()
        self.level = 0.0
        self.started_at = 0.0
        self.working = False
        layout = QVBoxLayout(self)
        instruction = QLabel('Bấm Bắt đầu thu → nói một câu → bấm Dừng.\n'
            'Thử: “Mở Spotify giúp mình”, “Ba cộng bốn bằng mấy?”,\n'
            'rồi một câu trò chuyện theo cách bạn thường nói.\n'
            'Cùng một bản thu sẽ được nhận bằng ba model; không gửi chat, không mở ứng dụng.')
        instruction.setWordWrap(True)
        layout.addWidget(instruction)
        self.devices = QComboBox()
        default = sd.query_devices(kind='input')
        selected = 0
        for device in sd.query_devices():
            host = sd.query_hostapis(device['hostapi'])['name']
            if device['max_input_channels'] and host in ('MME', 'Windows WASAPI'):
                label = f"{device['name']}, {host}"
                self.devices.addItem(label, label)
                if device['index'] == default['index']:
                    selected = self.devices.count() - 1
        configured = self.devices.findText(str(os.environ.get(
            'ALEX_TEST_INPUT_DEVICE', self.cfg['audio'].get('input_device', ''))))
        self.devices.setCurrentIndex(configured if configured >= 0 else selected)
        layout.addWidget(QLabel('Mic đang thử (có thể chọn lại):'))
        layout.addWidget(self.devices)
        self.meter = QProgressBar(); self.meter.setRange(0, 100)
        self.meter.setFormat('Mức mic: %p%')
        layout.addWidget(self.meter)
        self.button = QPushButton('Bắt đầu thu')
        self.button.clicked.connect(self.toggle_recording)
        layout.addWidget(self.button)
        self.status = QLabel('Chỉ bật mic khi bạn bấm Bắt đầu thu. Bản ghi âm không lưu ra tệp.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.output = QPlainTextEdit(); self.output.setReadOnly(True)
        layout.addWidget(self.output)
        self.timer = QTimer(self); self.timer.timeout.connect(self.tick); self.timer.start(100)

    def show_result(self, text: str) -> None:
        self.output.appendPlainText(text)

    def callback(self, data: bytes, frames: int, timing: object, status: object) -> None:
        self.frames.append(bytes(data))
        pcm = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768
        self.level = float(np.sqrt(np.mean(pcm ** 2))) if len(pcm) else 0.0
        if status:
            self.statuses.add(str(status))

    def toggle_recording(self) -> None:
        if self.stream:
            self.stop_recording()
            return
        self.frames = []; self.statuses = set(); self.level = 0
        device = self.devices.currentData()
        extra = sd.WasapiSettings(auto_convert=True) if 'Windows WASAPI' in device else None
        try:
            self.stream = sd.RawInputStream(samplerate=16000, channels=1, dtype='int16',
                blocksize=480, device=device, extra_settings=extra, callback=self.callback)
            self.stream.start()
        except Exception as exc:
            if self.stream:
                self.stream.close(); self.stream = None
            self.status.setText(f'Không mở được mic: {exc}')
            return
        self.started_at = time.monotonic()
        self.button.setText('ĐANG THU — Bấm để dừng')
        self.status.setText('ĐANG THU — bạn nói tự nhiên. Tự dừng sau 20 giây.')
        self.devices.setEnabled(False)

    def tick(self) -> None:
        self.meter.setValue(min(100, round(self.level * 500)))
        if self.stream and time.monotonic() - self.started_at >= 20:
            self.stop_recording()

    def stop_recording(self) -> None:
        self.stream.stop(); self.stream.close(); self.stream = None
        samples = np.frombuffer(b''.join(self.frames), dtype=np.int16).astype(np.float32) / 32768
        self.frames = []; self.level = 0
        self.button.setEnabled(False); self.button.setText('Đang so sánh các model…')
        self.status.setText('Mic đã tắt. Đang nhận chữ từ cùng bản thu, không kết nối Internet.')
        self.working = True
        threading.Thread(target=self.compare, args=(samples, self.devices.currentData(), list(self.statuses)),
                         daemon=True).start()

    def compare(self, samples: np.ndarray, device: str, statuses: list[str]) -> None:
        try:
            if len(samples) < 1600:
                raise ValueError('Bản thu quá ngắn; hãy thử lại.')
            rms = float(np.sqrt(np.mean(samples ** 2)))
            peak = float(np.max(np.abs(samples)))
            clipping = float(np.mean(np.abs(samples) >= .995))
            self.events.message.emit(f'\nMic: {device}\nThu {len(samples)/16000:.1f}s | RMS {rms:.4f}'
                                     f' | đỉnh {peak:.3f} | quá tải {clipping:.1%}')
            if statuses:
                self.events.message.emit('Cảnh báo thiết bị: ' + '; '.join(statuses))
            if peak < .02:
                self.events.message.emit('Tiếng thu rất nhỏ: kiểm tra mic đang chọn, hướng mic và mức âm lượng.')
            elif clipping > .01:
                self.events.message.emit('Âm thanh bị vỡ: giảm mức mic hoặc nói xa mic hơn một chút.')
            # Replay the same PCM through the pet's actual VAD to detect clipped speech.
            segmenter = Segmenter(self.cfg['audio'])
            pcm = np.clip(samples * 32768, -32768, 32767).astype('<i2').tobytes()
            stride = self.cfg['audio']['sample_rate'] * FRAME_MS // 1000 * 2
            utterances = []
            for offset in range(0, len(pcm) - stride + 1, stride):
                utterance = segmenter.feed(pcm[offset:offset + stride], offset / 32000)
                if utterance is not None:
                    utterances.append(utterance)
            for extra in range(self.cfg['audio']['silence_ms'] // FRAME_MS + 2):
                utterance = segmenter.feed(bytes(stride), len(samples) / 16000 + extra * FRAME_MS / 1000)
                if utterance is not None:
                    utterances.append(utterance)
            self.events.message.emit('Pet sẽ cắt bản thu thành ' + str(len(utterances)) +
                ' đoạn: ' + ', '.join(f'{len(u.samples)/16000:.1f}s' for u in utterances))
            print(json.dumps({'test': 'pet_segmentation', 'microphone': device,
                'segments': [round(len(u.samples)/16000, 2) for u in utterances],
                'recording_seconds': round(len(samples)/16000, 2)}, ensure_ascii=False), flush=True)
            for name, path, beam, prompt in (
                ('Whisper medium đang dùng', 'models/whisper-medium', 5, self.cfg['stt'].get('initial_prompt', '')),
                ('PhoWhisper tiếng Việt', 'models/phowhisper-small', 5, ''),
                ('Whisper cũ', 'models/whisper-small', 3, self.cfg['stt'].get('initial_prompt', '')),
            ):
                self.events.message.emit(f'Đang nạp {name}…')
                stt = SpeechToText(dict(self.cfg['stt'], model_path=path, beam_size=beam,
                                       initial_prompt=prompt), self.events.message.emit)
                try:
                    text, elapsed = stt.transcribe(samples)
                    self.events.message.emit(f'{name} ({stt.device}, {elapsed:.2f}s):\n{text or "[Không nhận được tiếng nói]"}')
                    if name == 'Whisper medium đang dùng' and utterances:
                        cuts = [stt.transcribe(item.samples)[0] for item in utterances]
                        self.events.message.emit('Khi pet tự cắt câu:\n' +
                                                 ' | '.join(cuts or ['[Không nhận được tiếng nói]']))
                        print(json.dumps({'test': 'pet_segment_transcripts',
                            'microphone': device, 'recognized': cuts}, ensure_ascii=False), flush=True)
                    print(json.dumps({'test': 'live_microphone', 'model': name, 'device': stt.device,
                        'microphone': device, 'recognized': text, 'stt_seconds': round(elapsed, 3),
                        'rms': round(rms, 4), 'peak': round(peak, 3)}, ensure_ascii=False), flush=True)
                finally:
                    stt.model.model.unload_model(); del stt; gc.collect()
        except Exception as exc:
            self.events.message.emit(f'Lỗi: {exc}')
            print(f'MIC_TEST_ERROR {exc}', flush=True)
        finally:
            self.events.done.emit()

    def ready(self) -> None:
        self.working = False
        self.button.setEnabled(True); self.button.setText('Bắt đầu thu')
        self.devices.setEnabled(True)
        self.status.setText('Đã xong. Bạn xem chữ của các model bên dưới và thử câu tiếp theo.')

    def closeEvent(self, event) -> None:
        if self.working:
            self.status.setText('Đợi nhận chữ xong rồi đóng cửa sổ để tránh ngắt model giữa chừng.')
            event.ignore(); return
        if self.stream:
            self.stream.stop(); self.stream.close(); self.stream = None
        self.frames = []
        event.accept()


if __name__ == '__main__':
    app = QApplication(sys.argv); app.setFont(QFont('Segoe UI', 10))
    lock = QLockFile(str(ROOT / 'pet.lock')); lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, 'Alex', 'Thoát pet ở khay hệ thống trước khi thử mic để tránh ghi âm hai lần.')
        raise SystemExit(1)
    window = MicTest(); window.show(); window.raise_(); window.activateWindow()
    try:
        raise SystemExit(app.exec())
    finally:
        lock.unlock()
