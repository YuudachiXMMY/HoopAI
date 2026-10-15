# CLAUDE.md

Basketball scoring detection and highlight-clip pipeline. Pure Python, offline batch processing, not a service.

## The single most important thing

**There is no entry script.** The repository contains only four library modules — no `main.py`, no CLI,
no `if __name__ == "__main__"`. Do not look for one and do not assume it exists. Running the pipeline
requires hand-written wiring code — a usable snippet is in [README · Usage](README.md#usage).

## Code search

`.codegraph/` is already indexed → use `codegraph_explore` before grep when locating or understanding code.

## Architecture

Four pipeline stages, one-way data flow:

```
ingest.frame_extractor.extract_frames(video, sample_every_n)
    → yield (frame_index, timestamp_seconds, frame)
detect.basket_detector.BasketDetector.detect(frame)
    → {"ball": det|None, "hoop": det|None, "frame_shape": (h, w)}
events.scoring_event.ScoringEventDetector.update(frame_index, timestamp, detection)
    → ScoringEvent | None   (on a hit it is also appended to .events)
clips.clip_exporter.export_clips(video, events, output_dir, pre_roll, post_roll, timeout)
    → List[str] (mp4 paths, possibly shorter than events — failed clips are skipped)
```

The contract between stages is a bare dict with no schema validation. The shape of `det` is fixed as
`{"box": [x1,y1,x2,y2], "confidence": float, "center": (cx, cy)}` — changing either end requires
changing the other.

Model: custom-trained YOLOv8, two classes `['basketball', 'hoop']`, weights at
`data/models/basketball.pt` (gitignored, not in the repository).

## Commands

No `Makefile` / `pyproject.toml` / `package.json`, and no wrapper scripts.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
brew install ffmpeg                    # clips/ invokes ffmpeg on the command line

# Resume training. You must pass data= explicitly: the checkpoint stores the training machine's
# absolute path, which does not exist locally and gets discarded.
yolo detect train resume=True \
  model=runs/detect/data/models/basketball/weights/last.pt \
  data="$PWD/data/basketball_dataset/hoopai.yaml"

# Detection only, with annotated visual output and no scoring logic
yolo detect predict model=data/models/basketball.pt source=<video> conf=0.35
```

## Pitfalls

1. **Hardcoded class indices** — `ModelClass` in `detect/basket_detector.py` (`BALL = 0` / `HOOP = 1`,
   with `BALL_CLASS` / `HOOP_CLASS` as aliases). The model's actual class names are **not** verified
   after loading, so if you swap in a model with a different class order, ball and hoop are silently
   swapped and the pipeline outputs zero events without erroring.

2. **`sample_every_n` is coupled to `min_downward_frames`** — the downward check counts **sampled
   frames**, not video frames. When you raise `sample_every_n` for speed you must lower
   `min_downward_frames` accordingly, otherwise the required run of descending frames is never reached
   and everything is missed.

3. **`_box_overlap`'s `margin=1.4` is not configurable** — it is hardcoded as a function default
   parameter in `events/scoring_event.py`, not a constructor parameter of `ScoringEventDetector`.
   Tuning the false-positive rate requires a source change.

4. **Scoring requires ball and hoop visible in the same frame** — `ScoringEventDetector.update` returns
   immediately if either is `None`. No events are produced for any stretch where the hoop is occluded or
   out of frame.

5. **`data=` must be an absolute path when training** — all four YAML files write `train: train/images`
   and set no `path:`, so the dataset root is taken from the parent directory of the `data=` argument.
   And since `check_file` returns the string you passed verbatim, a relative `data=` makes the root
   relative too, which ultralytics ≤ 8.3.133 then rewrites **unconditionally** under its own
   `datasets_dir` setting (the `path.exists()` guard was only added in ≥ 8.3.134).
   `requirements.txt` allows `>=8.0.0`, so only `data="$PWD/..."` holds across the entire range — this
   was measured on 8.4.177 and 8.3.133 against real data; the result table and source references are in
   the [RUNBOOK](docs/RUNBOOK.md#dataset-yaml-paths). **Do not commit machine-local absolute paths into
   the YAML files.** (Note: omitting `path:` and writing a relative `path:` go through the same line of
   code, with no asymmetry — an earlier claim to the contrary in this file has been corrected.)

6. **The model is undertrained** — only 2 of 20 epochs completed, mAP50 ≈ 0.76. When investigating
   missed baskets, suspect this before the scoring logic.

7. **Sample video filenames contain spaces** — e.g. `data/samples/IMG_2362 2.MOV`, which must be quoted
   in the shell.

8. **Loading `.pt` weights executes code** — `YOLO(path)` goes through pickle-based `torch.load`. The
   weights are not in the repository and carry no signature, so treat any file you place in
   `data/models/` the same as a script you are willing to run directly. When the source is not under
   your control, pass a checksum to `BasketDetector(expected_sha256=...)` (a TOCTOU window between
   verification and loading remains and cannot be eliminated).

9. **`project=` must be absolute too** — a relative `project` resolves differently by version: 8.3.133
   resolves it against cwd to `data/models/<name>`, while 8.4.177 nests it under `runs_dir/<task>/` as
   `runs/detect/data/models/<name>` (both measured). An absolute path is consistent across versions.
   Also, `runs/detect/data/models/basketball/weights/` holds leftovers from that historical 2-epoch
   training run, so `cp`-ing from it silently deploys old weights — see
   [RUNBOOK](docs/RUNBOOK.md#weight-output-path-use-an-absolute-project).

## Code style

No linter / formatter / pre-commit hook. The existing conventions:

- First line of a module docstring is the module path, the next line its responsibility
- Public functions carry type annotations; those returning a `dict` describe its structure in the docstring
- Private helpers use a single leading underscore (`_box_overlap`, `_check_ffmpeg`)
- Paths use `pathlib.Path`
- Status output uses `print`, indented by two spaces (`  Video : ...`) — no `logging`
- Structured data uses `@dataclass`

## Testing

**There are no tests at all**, and `pytest` is not in `requirements.txt` either. There is no regression
protection when changing the scoring logic — adding tests before touching `events/scoring_event.py` is
recommended; it is pure standard library and can be driven directly with handcrafted dicts, making it
the easiest thing to test.

## Documentation sync

README / CONTRIBUTING / RUNBOOK contain 4 `<!-- AUTO-GENERATED -->` blocks, each with its own source of truth:

| Block location | Source of truth |
|----------------|-----------------|
| README "Python dependencies" | `requirements.txt` |
| README "Module reference" | the modules' exported symbols and signatures |
| CONTRIBUTING "Command reference" | `requirements.txt` + `runs/detect/data/models/basketball/args.yaml` |
| RUNBOOK "Current model status" | `runs/.../args.yaml` + `runs/.../results.csv` |

When changing a source of truth, regenerate the corresponding block; do not hand-edit the block contents.

## Git

- Commit messages use Conventional Commits (`feat:` / `fix:` / `docs:` / `refactor:` / `test:` / `chore:`)
- Never commit: model weights (`*.pt`), videos (`*.mp4` / `*.MOV`), dataset images, `runs/`, machine-local absolute paths
