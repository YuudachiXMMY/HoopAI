"""
ingest/frame_extractor.py
Reads a video file and yields frames with their timestamps for downstream processing.
"""

import cv2
from pathlib import Path


def extract_frames(video_path: str, sample_every_n: int = 1):
    """
    Generator — yields (frame_index, timestamp_seconds, frame) for each sampled frame.

    Args:
        video_path:      Path to the input video file.
        sample_every_n:  Process every Nth frame (1 = every frame, 2 = every other, etc.)
                         Use higher values on long videos to speed up detection.
    """
    path = Path(video_path)
    if not path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps if fps > 0 else 0

    print(f"  Video : {path.name}")
    print(f"  FPS   : {fps:.1f}")
    print(f"  Frames: {total_frames}")
    print(f"  Length: {duration:.1f}s")

    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % sample_every_n == 0:
            timestamp = frame_idx / fps
            yield frame_idx, timestamp, frame

        frame_idx += 1

    cap.release()


def get_video_info(video_path: str) -> dict:
    """Return basic metadata about a video file."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    info = {
        "fps": cap.get(cv2.CAP_PROP_FPS),
        "frame_count": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
    }
    info["duration_seconds"] = info["frame_count"] / info["fps"] if info["fps"] > 0 else 0
    cap.release()
    return info
