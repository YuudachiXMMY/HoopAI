import argparse
import sys
from pathlib import Path

from ingest.frame_extractor import extract_frames, get_video_info
from detect.basket_detector import BasketDetector
from events.scoring_event import ScoringEventDetector
from clips.clip_exporter import export_clips


def main():
    parser = argparse.ArgumentParser(description="HoopAI — Basketball Highlight Generator")
    parser.add_argument("--input", required=True, help="Path to input video file")
    parser.add_argument("--output", default="highlights", help="Output directory for clips (default: highlights)")
    parser.add_argument("--pre", type=float, default=4.0, help="Seconds before basket to include (default: 4.0)")
    parser.add_argument("--post", type=float, default=2.0, help="Seconds after basket to include (default: 2.0)")
    parser.add_argument("--sample", type=int, default=1, help="Sample every N frames (default: 1)")
    parser.add_argument("--confidence", type=float, default=0.35, help="Detection confidence threshold (default: 0.35)")
    parser.add_argument("--model", default="data/models/basketball.pt", help="Path to YOLO model weights")
    args = parser.parse_args()

    video_path = Path(args.input)
    if not video_path.exists():
        print(f"Error: video file not found: {video_path}")
        sys.exit(1)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n=== HoopAI ===")
    print(f"Input:      {video_path}")
    print(f"Output:     {output_dir}")
    print(f"Model:      {args.model}")
    print(f"Confidence: {args.confidence}")
    print(f"Pre/Post:   {args.pre}s / {args.post}s")
    print(f"Sample:     every {args.sample} frame(s)\n")

    info = get_video_info(str(video_path))
    # `duration_seconds`, not `duration`. get_video_info has never returned the
    # latter, so this line raised KeyError on every single run — before any
    # frame was read, which is why it was invisible: the crash happens in the
    # banner, so there is no partial output to suggest the pipeline started.
    print(
        f"Video info: {info['frame_count']} frames, "
        f"{info['fps']:.1f} fps, {info['duration_seconds']:.1f}s\n"
    )

    detector = BasketDetector(model_path=args.model, confidence=args.confidence)
    event_detector = ScoringEventDetector()

    basket_count = 0
    events = []
    total_frames = info["frame_count"] // args.sample

    print("Scanning for baskets...")
    for i, (frame_idx, timestamp, frame) in enumerate(extract_frames(str(video_path), sample_every_n=args.sample)):
        if i % 100 == 0:
            pct = (i / max(total_frames, 1)) * 100
            print(f"  {pct:.0f}% — frame {frame_idx} ({timestamp:.1f}s)", end="\r")

        detection = detector.detect(frame)
        event = event_detector.update(frame_idx, timestamp, detection)

        if event:
            basket_count += 1
            events.append(event)
            mins = int(timestamp // 60)
            secs = timestamp % 60
            print(f"\n  Basket #{basket_count} at {mins}m{secs:.1f}s")

    print(f"\n\nDone scanning. {basket_count} basket(s) detected.")

    if events:
        print(f"\nExporting {basket_count} highlight clip(s) to {output_dir}...")
        export_clips(
            video_path=str(video_path),
            events=events,
            output_dir=str(output_dir),
            pre_roll=args.pre,
            post_roll=args.post,
        )
        print(f"\nAll clips saved to: {output_dir}")
    else:
        print("No baskets detected — no clips exported.")
        print("Tips: try lowering --confidence or increasing --sample rate.")

    print("\n=== HoopAI complete ===\n")


if __name__ == "__main__":
    main()
