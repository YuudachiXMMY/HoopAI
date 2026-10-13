"""
detect/basket_detector.py
Uses the custom-trained YOLOv8 model to detect both the basketball and hoop.
"""

from ultralytics import YOLO
import numpy as np
from pathlib import Path

BALL_CLASS = 0   # 'basketball' in our custom model
HOOP_CLASS = 1   # 'hoop' in our custom model


class BasketDetector:
    def __init__(self, model_path: str = "data/models/basketball.pt", confidence: float = 0.35):
        print(f"  Loading custom basketball model ({model_path}) ...")
        self.model = YOLO(model_path)
        self.confidence = confidence

    def detect(self, frame: np.ndarray) -> dict:
        results = self.model(frame, verbose=False)[0]

        ball = None
        hoop = None
        best_ball_conf = 0.0
        best_hoop_conf = 0.0

        for box in results.boxes:
            cls = int(box.cls[0])
            conf = float(box.conf[0])
            if conf < self.confidence:
                continue

            x1, y1, x2, y2 = box.xyxy[0].tolist()
            det = {
                "box": [int(x1), int(y1), int(x2), int(y2)],
                "confidence": conf,
                "center": (int((x1 + x2) / 2), int((y1 + y2) / 2)),
            }

            if cls == BALL_CLASS and conf > best_ball_conf:
                best_ball_conf = conf
                ball = det
            elif cls == HOOP_CLASS and conf > best_hoop_conf:
                best_hoop_conf = conf
                hoop = det

        return {
            "ball": ball,
            "hoop": hoop,
            "frame_shape": frame.shape[:2],
        }
