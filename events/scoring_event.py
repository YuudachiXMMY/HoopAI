"""
events/scoring_event.py
Detects made baskets by checking if the ball enters the detected hoop region.
Works on any camera angle since it uses the actual hoop location.
"""

from collections import deque
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class ScoringEvent:
    frame_index: int
    timestamp_seconds: float
    confidence: float
    ball_center: tuple


def _box_overlap(ball_center, hoop_box, margin: float = 1.4) -> bool:
    """Check if ball center is inside hoop box (with margin for near-misses)."""
    cx, cy = ball_center
    x1, y1, x2, y2 = hoop_box
    w = (x2 - x1) * margin
    h = (y2 - y1) * margin
    mx = (x1 + x2) / 2
    my = (y1 + y2) / 2
    return abs(cx - mx) < w / 2 and abs(cy - my) < h / 2


class ScoringEventDetector:
    def __init__(
        self,
        cooldown_seconds: float = 3.0,
        min_downward_frames: int = 3,
    ):
        self.cooldown_seconds = cooldown_seconds
        self.min_downward_frames = min_downward_frames
        self._history: deque = deque(maxlen=30)
        self._last_event_ts: float = -999.0
        self.events: List[ScoringEvent] = []

    def _is_moving_down(self) -> bool:
        centers = [e[2] for e in self._history if e[2] is not None]
        if len(centers) < self.min_downward_frames + 1:
            return False
        recent = centers[-(self.min_downward_frames + 1):]
        downward = sum(1 for i in range(1, len(recent)) if recent[i][1] > recent[i-1][1])
        return downward >= self.min_downward_frames

    def update(
        self,
        frame_index: int,
        timestamp: float,
        detection: dict,
    ) -> Optional[ScoringEvent]:
        ball = detection.get("ball")
        hoop = detection.get("hoop")
        center = ball["center"] if ball else None
        conf = ball["confidence"] if ball else 0.0

        self._history.append((frame_index, timestamp, center, conf))

        if timestamp - self._last_event_ts < self.cooldown_seconds:
            return None

        # Need both ball and hoop visible
        if ball is None or hoop is None:
            return None

        # Ball must be inside the hoop region and moving downward
        if _box_overlap(ball["center"], hoop["box"]) and self._is_moving_down():
            event = ScoringEvent(
                frame_index=frame_index,
                timestamp_seconds=timestamp,
                confidence=conf,
                ball_center=center,
            )
            self.events.append(event)
            self._last_event_ts = timestamp
            return event

        return None
