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

    Raises:
        FileNotFoundError:  video_path does not exist.
        RuntimeError:       the file could not be opened, or reports an unusable
                            frame rate (see below).
    """
    path = Path(video_path)
    if not path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        # OpenCV reports 0 for some MOV / variable-frame-rate containers and for
        # damaged metadata, even when isOpened() is True. Every timestamp below
        # derives from fps, so continuing would either divide by zero or hand
        # downstream stages wrong times and cut clips at the wrong offsets.
        # Released here explicitly: this raise is outside the try/finally below.
        cap.release()
        raise RuntimeError(
            f"Video reports unusable fps ({fps}), cannot compute timestamps: {video_path}"
        )

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps

    print(f"  Video : {path.name}")
    print(f"  FPS   : {fps:.1f}")
    print(f"  Frames: {total_frames}")
    print(f"  Length: {duration:.1f}s")

    # try/finally rather than a trailing release(): a consumer that breaks out of
    # the for-loop leaves this generator suspended at the yield, so the capture
    # must still be released when it is closed or garbage-collected.
    try:
        frame_idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % sample_every_n == 0:
                timestamp = frame_idx / fps
                yield frame_idx, timestamp, frame

            frame_idx += 1
    finally:
        cap.release()


def get_video_info(video_path: str) -> dict:
    """Return basic metadata about a video file."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    try:
        info = {
            "fps": cap.get(cv2.CAP_PROP_FPS),
            "frame_count": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
            "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        }
        # Unlike extract_frames this tolerates fps == 0: it is a diagnostic helper,
        # so reporting the bad metadata is more useful than refusing to return it.
        info["duration_seconds"] = info["frame_count"] / info["fps"] if info["fps"] > 0 else 0
    finally:
        cap.release()
    return info
