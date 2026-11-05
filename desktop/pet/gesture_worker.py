"""Opt-in camera worker. Frames live only in RAM; stdout carries landmarks only."""
import argparse
import json
import os
from pathlib import Path
import threading
import time
import sys
import tempfile


def emit(value):
    print(json.dumps(value, separators=(',', ':')), flush=True)


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', required=True)
    parser.add_argument('--camera', type=int, default=0)
    parser.add_argument('--probe', action='store_true', help='Synthetic frame only; never open camera')
    args = parser.parse_args()
    # Native MediaPipe path handling is not Unicode-safe on Windows. Load the
    # model through Python first; no personal images are written to this folder.
    model_bytes = Path(args.model).resolve().read_bytes()
    os.chdir(tempfile.gettempdir())
    os.environ['GLOG_minloglevel'] = '2'
    os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
    import cv2
    import numpy as np
    import mediapipe as mp
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision
    options = vision.HandLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_buffer=model_bytes),
        running_mode=vision.RunningMode.VIDEO, num_hands=2,
        min_hand_detection_confidence=.6, min_hand_presence_confidence=.6,
        min_tracking_confidence=.6)
    stop = threading.Event()

    def commands():
        # EOF also closes the camera if the parent disappears.
        for line in sys.stdin:
            if line.strip() == 'stop':
                break
        stop.set()

    cap = None
    with vision.HandLandmarker.create_from_options(options) as detector:
        if args.probe:
            result = detector.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB,
                data=np.zeros((360, 480, 3), dtype=np.uint8)), 1)
            emit({'probe': 'ok', 'hands': len(result.hand_landmarks)})
            return
        threading.Thread(target=commands, daemon=True).start()
        try:
            cap = cv2.VideoCapture(args.camera, cv2.CAP_DSHOW if os.name == 'nt' else cv2.CAP_ANY)
            if not cap.isOpened():
                emit({'error': 'camera_unavailable'})
                return
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            cap.set(cv2.CAP_PROP_FPS, 15)
            emit({'ready': True})
            last = 0
            while not stop.is_set():
                started = time.monotonic()
                ok, frame = cap.read()
                if not ok:
                    emit({'error': 'camera_read'})
                    break
                frame = cv2.resize(cv2.flip(frame, 1), (480, 360))
                stamp = max(last+1, int(started*1000))
                last = stamp
                result = detector.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB,
                    data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)), stamp)
                emit({'hands': [[[round(p.x, 4), round(p.y, 4)] for p in hand]
                                for hand in result.hand_landmarks]})
                stop.wait(max(0, 1/15 - (time.monotonic()-started)))
        finally:
            if cap is not None:
                cap.release()


if __name__ == '__main__':
    try:
        run()
    except Exception:
        # Never include camera pixels, personal paths or raw exception text in logs.
        emit({'error': 'worker_failed'})
        sys.exit(1)
