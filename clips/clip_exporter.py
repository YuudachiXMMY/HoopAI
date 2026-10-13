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
        raise OSError(
            "ffmpeg not found. Install it with:  brew install ffmpeg"
        )


def _remove_partial(out_file: Path) -> None:
    """Drop the truncated file a killed or failed ffmpeg leaves behind.

    Failed clips are absent from the returned list, so without this the output
    directory still holds an unplayable mp4 that looks like a real highlight.
    """
    try:
        out_file.unlink(missing_ok=True)
    except OSError:
        # Cleanup is best-effort; losing it must not abort the remaining clips.
        pass


def export_clips(
    video_path: str,
    events: List[ScoringEvent],
    output_dir: str,
    pre_roll: float = 4.0,   # seconds before the basket
    post_roll: float = 2.0,  # seconds after the basket
    timeout: float = 120.0,  # per-clip wall-clock budget for one ffmpeg call
) -> List[str]:
    """
    Export one highlight clip per scoring event.

    Returns the list of successfully written file paths.

    A single FFmpeg failure is reported and skipped rather than aborting the
    batch, so the returned list may be SHORTER than `events`. Callers that need
    to know compare `len(result)` against `len(events)`; every skipped event is
    named in the printed summary. A clip that exceeds `timeout` counts as such a
    failure: raise it for unusually long pre/post rolls or very slow storage.
    """
    _check_ffmpeg()

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    video_name = Path(video_path).stem
    output_paths = []
    failed = []

    for i, event in enumerate(events, start=1):
        start = max(0.0, event.timestamp_seconds - pre_roll)
        # Derived from the clamped start, not from pre_roll + post_roll: for a
        # basket inside the first `pre_roll` seconds the start clamps to 0, and a
        # constant duration would push the cut that much further past the basket
        # than the documented window above.
        duration = event.timestamp_seconds + post_roll - start

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
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout
            )
        except subprocess.TimeoutExpired:
            # Unbounded, a wedged ffmpeg (odd container, stalled network mount,
            # hung decoder) blocks this sequential loop forever and prints
            # nothing further, so the whole batch hangs with no diagnosis.
            failed.append(event)
            _remove_partial(out_file)
            print(
                f"  ⚠️  FFmpeg timed out after {timeout:.0f}s on clip "
                f"{i}/{len(events)} (event @ {event.timestamp_seconds:.1f}s, "
                f"frame {event.frame_index})"
            )
            continue

        if result.returncode != 0:
            # Name the event, not just the loop index: the index alone does not
            # say which basket was lost once the caller only has the returned list.
            failed.append(event)
            _remove_partial(out_file)
            print(
                f"  ⚠️  FFmpeg failed on clip {i}/{len(events)} "
                f"(event @ {event.timestamp_seconds:.1f}s, frame {event.frame_index}, "
                f"exit {result.returncode}):\n{result.stderr}"
            )
        else:
            output_paths.append(str(out_file))

    if failed:
        # Without this the caller sees a short list and cannot tell a failed
        # export apart from "fewer events were detected".
        missed = ", ".join(f"{e.timestamp_seconds:.1f}s" for e in failed)
        print(
            f"  {len(output_paths)}/{len(events)} clips exported, "
            f"{len(failed)} failed at: {missed}"
        )

    return output_paths
