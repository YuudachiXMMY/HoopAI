"""
clips/clip_exporter.py
Uses FFmpeg to cut highlight clips around each scoring event.
Each clip = [event_time - pre_roll] to [event_time + post_roll].
"""

import subprocess
import shutil
from pathlib import Path
from typing import List
from events.scoring_event import ScoringEvent


def _check_ffmpeg():
    if not shutil.which("ffmpeg"):
        raise EnvironmentError(
            "ffmpeg not found. Install it with:  brew install ffmpeg"
        )


def export_clips(
    video_path: str,
    events: List[ScoringEvent],
    output_dir: str,
    pre_roll: float = 4.0,   # seconds before the basket
    post_roll: float = 2.0,  # seconds after the basket
) -> List[str]:
    """
    Export one highlight clip per scoring event.

    Returns list of output file paths.
    """
    _check_ffmpeg()

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    video_name = Path(video_path).stem
    output_paths = []

    for i, event in enumerate(events, start=1):
        start = max(0.0, event.timestamp_seconds - pre_roll)
        duration = pre_roll + post_roll

        out_file = out_dir / f"{video_name}_basket_{i:03d}_t{event.timestamp_seconds:.1f}s.mp4"

        cmd = [
            "ffmpeg",
            "-y",                        # overwrite without asking
            "-ss", str(start),
            "-i", video_path,
            "-t", str(duration),
            "-c:v", "libx264",
            "-crf", "23",
            "-preset", "fast",
            "-c:a", "aac",
            str(out_file),
        ]

        print(f"  Exporting clip {i}/{len(events)}: {out_file.name}")
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            print(f"  ⚠️  FFmpeg error on clip {i}:\n{result.stderr}")
        else:
            output_paths.append(str(out_file))

    return output_paths
