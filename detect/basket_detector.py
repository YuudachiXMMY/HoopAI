"""
detect/basket_detector.py
Uses the custom-trained YOLOv8 model to detect both the basketball and hoop.
"""

import hashlib
from enum import IntEnum
from pathlib import Path
from typing import Optional

from ultralytics import YOLO
import numpy as np


class ModelClass(IntEnum):
    """Class indices of the custom-trained model, in `names` order from data.yaml.

    Mirrors an external artifact: if a replacement model orders or numbers its
    classes differently these values must change with it, or ball and hoop are
    silently swapped and the pipeline emits zero events without erroring.
    """

    BALL = 0   # 'basketball'
    HOOP = 1   # 'hoop'


# Part of the documented module surface — kept as plain names so existing
# callers and the README module reference stay valid.
BALL_CLASS = ModelClass.BALL
HOOP_CLASS = ModelClass.HOOP


def _verify_sha256(model_path: str, expected: str) -> None:
    """Abort before the checkpoint is unpickled if it is not the expected file.

    Read in chunks rather than all at once: checkpoints can be arbitrarily large
    and this runs before anything else in __init__.
    """
    digest = hashlib.sha256()
    with Path(model_path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)

    actual = digest.hexdigest()
    if actual != expected.lower():
        raise ValueError(
            f"Model checksum mismatch for {model_path}: "
            f"expected {expected.lower()}, got {actual}"
        )


class BasketDetector:
    def __init__(
        self,
        model_path: str = "data/models/basketball.pt",
        confidence: float = 0.35,
        expected_sha256: Optional[str] = None,
    ):
        # YOLO() loads .pt checkpoints via pickle-based torch.load, which executes
        # code embedded in the file. The weights are not in the repo (see RUNBOOK)
        # and carry no signature, so pass expected_sha256 whenever they came from
        # anywhere you would not run an arbitrary script from.
        if expected_sha256:
            _verify_sha256(model_path, expected_sha256)

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

            if cls == ModelClass.BALL and conf > best_ball_conf:
                best_ball_conf = conf
                ball = det
            elif cls == ModelClass.HOOP and conf > best_hoop_conf:
                best_hoop_conf = conf
                hoop = det

        height, width = frame.shape[:2]

        return {
            "ball": ball,
            "hoop": hoop,
            # Native ints, not numpy integers: matches the explicit int() casts
            # in `det` above so the whole contract is plain Python.
            "frame_shape": (int(height), int(width)),
        }
