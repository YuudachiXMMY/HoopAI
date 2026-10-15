# Contributing

## Development environment

### Prerequisites

| Tool | Version | Required | Purpose |
|------|---------|----------|---------|
| Python | 3.11+ | Yes | Runtime |
| FFmpeg | recent version | Yes | `clips/` cuts clips by invoking it on the command line |
| Git | — | Yes | Version control |

### Installation

```bash
git clone https://github.com/YuudachiXMMY/HoopAI.git
cd HoopAI

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

brew install ffmpeg        # macOS
# sudo apt install ffmpeg  # Debian / Ubuntu
```

### Files needed locally but not in the repo

The following are excluded by `.gitignore`, so they do not exist after a clone and must be supplied yourself:

| Path | Contents | How to obtain |
|------|----------|---------------|
| `data/models/basketball.pt` | YOLOv8 weights | Ask a maintainer, or retrain per the [RUNBOOK](RUNBOOK.md) |
| `data/*_dataset/{train,valid,test}/` | Images and YOLO labels | Re-download from Roboflow (links are in the README) |
| `data/samples/*.MOV` | Test videos | Record your own or ask a maintainer |

> **Weights are executable content.** `YOLO(path)` loads `.pt` files via pickle-based `torch.load`,
> which executes code embedded in the file as it loads. Only place weights from a source you trust;
> when the source is not fully under your control, pass a checksum to
> `BasketDetector(expected_sha256=...)` — details in
> [RUNBOOK · Trust boundary for weight files](RUNBOOK.md#trust-boundary-for-weight-files).

## Command reference

<!-- AUTO-GENERATED: generated from requirements.txt and runs/detect/data/models/basketball/args.yaml — do not edit by hand -->

This project has **no** `Makefile`, `pyproject.toml` or `package.json`, so there are no wrapped scripts.
These are the commands that actually exist:

| Command | Notes |
|---------|-------|
| `pip install -r requirements.txt` | Install the runtime dependencies |
| `yolo detect train data="$PWD/data/basketball_dataset/hoopai.yaml" model=yolov8n.pt epochs=20 imgsz=416 batch=4 device=cpu workers=0 patience=5 project="$PWD/data/models" name=basketball exist_ok=True` | Reproduce the model training (hyperparameters taken from the previous run's `args.yaml`). Run it from the repository root; both `data=` and `project=` must be absolute paths, otherwise the resolved locations vary by ultralytics version — rationale and measurements in the [RUNBOOK](RUNBOOK.md#dataset-yaml-paths). Output lands in `data/models/basketball/weights/` |
| `yolo detect predict model=data/models/basketball.pt source=<video path> conf=0.35` | Run detection only, with annotated visual output and no scoring logic |
| `ffmpeg -version` | Verify FFmpeg is available |

<!-- END AUTO-GENERATED -->

## Environment variables

The code reads **no environment variables at all** (no `os.environ` / `os.getenv` / `dotenv` calls), so
there is no `.env.example`. Everything configurable is passed through function and constructor
parameters — the full list is in [README · Tuning parameters](../README.md#tuning-parameters).

If environment variables are introduced later, add a `.env.example` alongside them (`.gitignore` already
whitelists it) and document them here.

## Code style

The repository currently has **no linter, formatter or pre-commit hook configured**. The conventions the
existing code follows:

- Every module starts with a triple-quoted docstring whose first line is the module path, followed by a line describing its responsibility
- Public functions carry type annotations; functions returning a `dict` describe its structure in the docstring
- Private helpers are prefixed with a single underscore (e.g. `_box_overlap`, `_check_ffmpeg`)
- Use `pathlib.Path` instead of string path concatenation
- Progress and status go through `print`, indented by two spaces (e.g. `  Video : ...`)
- Prefer `@dataclass` for structured data (see `ScoringEvent`)

If you do introduce tooling, `ruff` (lint + format) is the suggested choice — `.gitignore` already
reserves `.ruff_cache/`.

## Testing

**There are currently no tests at all.** `.gitignore` already reserves the cache paths for `pytest` and
coverage, but `pytest` is not in `requirements.txt`.

Suggestions for when you add tests:

```bash
pip install pytest
pytest                      # everything
pytest tests/test_events.py # a single file
pytest --cov=. --cov-report=term-missing
```

The best places to start (pure logic, no model or video needed, easiest to write):

| Target | Why it is worth testing |
|--------|-------------------------|
| `events.scoring_event._box_overlap` | Pure geometry with well-defined inputs and outputs; the `margin` boundary behavior is the main source of false positives |
| `events.scoring_event.ScoringEventDetector` | Can be driven directly with handcrafted `detection` dicts, no real model required; covers the cooldown, downward-frame-count and missing-ball-or-hoop branches |
| `ingest.frame_extractor.extract_frames` | The three error paths — missing file, undecodable file, fps ≤ 0 — can be asserted directly by exception type (the latter two need `cv2.VideoCapture` mocked) |

Tests touching `BasketDetector` and `export_clips` need mocks (`YOLO` and `subprocess.run`
respectively), otherwise they depend on the weights file and FFmpeg.

## Commit conventions

The existing history uses Conventional Commits:

```
feat: track basketball scoring pipeline and add .gitignore
```

Common prefixes: `feat` / `fix` / `docs` / `refactor` / `test` / `chore`.

## PR checklist

Before opening a PR, check yourself:

- [ ] Syntax check passes (no dependencies needed): `python -m compileall -q ingest detect events clips` prints nothing
- [ ] All four modules import inside a virtualenv with the dependencies installed:
      `python -c "import ingest.frame_extractor, detect.basket_detector, events.scoring_event, clips.clip_exporter"`
      — it must reach the **submodules**. All four `__init__.py` files are 0 bytes, so
      `import ingest, detect, events, clips` returns 0 even in an environment with nothing installed and
      catches no import errors at all
- [ ] Nothing excluded by `.gitignore` was committed — especially model weights (`*.pt`), videos
      (`*.mp4` / `*.MOV`), dataset images, `runs/`
      (exception: `data/models/CHECKSUMS.txt` is whitelisted and **should** be committed)
- [ ] No machine-local absolute paths were committed into the `train:` / `val:` / `test:` / `path:` keys
      of a dataset YAML. Relative subpaths with no `path:` key is the current convention, but remember it
      requires passing an absolute `data=` when training (see
      [RUNBOOK · Dataset YAML paths](RUNBOOK.md#dataset-yaml-paths))
- [ ] Changed a module's public interface → update the `AUTO-GENERATED` "Module reference" table in the README
- [ ] Changed `requirements.txt` → update the `AUTO-GENERATED` dependency/command tables in the README and in this file
- [ ] Changed a default parameter value → update the README's "Tuning parameters" table
- [ ] Commit messages follow Conventional Commits
