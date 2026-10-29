# HoopAI

Automatically find the scoring moments in a basketball video and cut out highlight clips.

The pipeline is built on a custom-trained YOLOv8 two-class detection model (`basketball` / `hoop`). Scoring detection does not depend on a fixed camera position: it uses the detected hoop location directly and checks whether the ball center enters the hoop region while moving downward, so it also works when the camera angle changes.

## Pipeline

```
video file
   │
   ├─▶ ingest.frame_extractor.extract_frames        frame sampling + timestamps
   │
   ├─▶ detect.basket_detector.BasketDetector        detect ball and hoop per frame
   │
   ├─▶ events.scoring_event.ScoringEventDetector    ball in hoop + downward → scoring event
   │
   └─▶ clips.clip_exporter.export_clips             FFmpeg cuts clips at event times
                                                         │
                                                         ▼
                                                   highlight mp4 clips
```

> **Current status: there is no unified entry point.** The repository contains only the four modules
> above — no `main.py`, no CLI, no tests. To run the whole pipeline you have to wire the four steps
> together yourself as shown in [Usage](#usage) below, or write a new entry script.

## Environment setup

Prerequisites:

| Dependency | Version | Notes |
|------------|---------|-------|
| Python | 3.11+ | Verified locally on 3.12.13; the leftover `__pycache__` in the repo was compiled by 3.11 and can safely be deleted |
| FFmpeg | any recent version | `clips.clip_exporter` invokes the `ffmpeg` command line directly; if it is missing it raises `OSError` |

Install:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Install FFmpeg on macOS
brew install ffmpeg
```

<!-- AUTO-GENERATED: generated from requirements.txt — do not edit by hand -->
### Python dependencies

| Package | Version constraint | Purpose |
|---------|--------------------|---------|
| `ultralytics` | `>=8.0.0` | YOLOv8 model loading and inference (`detect/`) |
| `opencv-python` | `>=4.8.0` | Video decoding and frame extraction (`ingest/`) |
| `numpy` | `>=1.24.0` | Frame array types |
| `tqdm` | `>=4.65.0` | Progress bars (not actually referenced by the current code) |
<!-- END AUTO-GENERATED -->

The model weights live at `data/models/basketball.pt` (excluded by `.gitignore`, so they are not in the
repository — supply them locally or retrain, see [docs/RUNBOOK.md](docs/RUNBOOK.md)).

> Loading a `.pt` executes code embedded in the file (pickle-based `torch.load`), so only place weights
> from a source you trust. When the source is not fully under your control, verify first with
> `BasketDetector(expected_sha256=...)` — see
> [RUNBOOK · Trust boundary for weight files](docs/RUNBOOK.md#trust-boundary-for-weight-files).

## Usage

For now the four modules have to be wired together by hand:

```python
from ingest.frame_extractor import extract_frames
from detect.basket_detector import BasketDetector
from events.scoring_event import ScoringEventDetector
from clips.clip_exporter import export_clips

video = "data/samples/IMG_2362 2.MOV"

detector = BasketDetector(model_path="data/models/basketball.pt", confidence=0.35)
scorer = ScoringEventDetector(cooldown_seconds=3.0, min_downward_frames=3)

for frame_idx, timestamp, frame in extract_frames(video, sample_every_n=1):
    detection = detector.detect(frame)
    event = scorer.update(frame_idx, timestamp, detection)
    if event:
        print(f"Basket @ {event.timestamp_seconds:.1f}s (conf={event.confidence:.2f})")

paths = export_clips(
    video,
    scorer.events,
    output_dir="output/clips",
    pre_roll=4.0,
    post_roll=2.0,
)
print(f"Exported {len(paths)} clips")
```

### Tuning parameters

| Parameter | Default | Effect |
|-----------|---------|--------|
| `extract_frames(sample_every_n=)` | `1` | Frame sampling stride. Raising it speeds things up but thins out the downward trajectory — `ScoringEventDetector`'s `min_downward_frames` counts **sampled frames**, so when you raise `sample_every_n` you must lower `min_downward_frames` accordingly or baskets will be missed |
| `BasketDetector(confidence=)` | `0.35` | Detection confidence threshold. Boxes below it are discarded; only the single highest-confidence ball and hoop are kept per frame |
| `ScoringEventDetector(cooldown_seconds=)` | `3.0` | Minimum interval between two scoring events, used to suppress counting the same basket twice |
| `ScoringEventDetector(min_downward_frames=)` | `3` | Number of consecutive descending frames required to decide the ball "is falling" |
| `_box_overlap(margin=)` | `1.4` | Scale factor applied to the hoop decision region (hardcoded, not a constructor parameter). Raising it is more permissive but will count rim-outs as baskets |
| `export_clips(pre_roll=, post_roll=)` | `4.0` / `2.0` | Seconds cut before and after the event timestamp. When a basket happens within the first `pre_roll` seconds the start clamps to 0 and the clip is correspondingly shorter, while still keeping `post_roll` seconds after the event |
| `export_clips(timeout=)` | `120.0` | Wall-clock budget in seconds for a single ffmpeg call. A timeout counts as a failure: the clip is skipped, the half-written file is deleted, and the next clip is cut. Raise it for very large pre/post rolls or slow storage |
| `BasketDetector(expected_sha256=)` | `None` | Optional. When a sha256 of the weights file is given it is verified before loading; a mismatch raises `ValueError`. Only `None` means "skip verification" — an empty or whitespace-only string also raises `ValueError` (it usually means a config lookup came back empty, and silently proceeding is more dangerous than erroring). The default behavior is unchanged |

<!-- AUTO-GENERATED: generated from the modules' exported symbols — do not edit by hand -->
## Module reference

### `ingest/frame_extractor.py`

| Symbol | Signature | Notes |
|--------|-----------|-------|
| `extract_frames` | `(video_path: str, sample_every_n: int = 1) -> Iterator[Tuple[int, float, np.ndarray]]` | Returns an iterator yielding `(frame_index, timestamp_seconds, frame)` per frame. **Validation runs at call time** (the function itself is not a generator; a separate inner generator carries the iteration), so the exceptions below are raised by the call itself and not deferred to the first iteration: `FileNotFoundError` if the file does not exist; `RuntimeError` if it cannot be decoded or the container reports fps ≤ 0 (timestamps would be uncomputable); `ValueError` if `sample_every_n < 1` |
| `get_video_info` | `(video_path: str) -> dict` | Returns `fps` / `frame_count` / `width` / `height` / `duration_seconds` |

### `detect/basket_detector.py`

| Symbol | Signature | Notes |
|--------|-----------|-------|
| `ModelClass` | `IntEnum(BALL=0, HOOP=1)` | Class indices of the custom-trained model, in the order of `names` in `data.yaml` |
| `BALL_CLASS` | `= ModelClass.BALL` | Class ID of `basketball` (an `IntEnum` member, directly comparable with `int`) |
| `HOOP_CLASS` | `= ModelClass.HOOP` | Class ID of `hoop` |
| `BasketDetector.__init__` | `(model_path: str = "data/models/basketball.pt", confidence: float = 0.35, expected_sha256: Optional[str] = None)` | Loads the YOLO weights. When `expected_sha256` is not `None` the file is verified before loading; a mismatch or a blank string raises `ValueError` |
| `BasketDetector.detect` | `(frame: np.ndarray) -> dict` | Returns `{"ball": det \| None, "hoop": det \| None, "frame_shape": (h, w)}`, where `det` is `{"box": [x1,y1,x2,y2], "confidence": float, "center": (cx, cy)}` |

### `events/scoring_event.py`

| Symbol | Signature | Notes |
|--------|-----------|-------|
| `Point` | `= Tuple[int, int]` | Pixel coordinates `(cx, cy)`, matching the `center` produced by `BasketDetector.detect` |
| `HistoryEntry` | `= Tuple[int, float, Optional[Point], float]` | One entry of the rolling history: `(frame_index, timestamp_seconds, ball_center, confidence)`; `ball_center` is `None` on frames where no ball was detected |
| `ScoringEvent` | `dataclass(frame_index, timestamp_seconds, confidence, ball_center)` | A single scoring event |
| `ScoringEventDetector.__init__` | `(cooldown_seconds: float = 3.0, min_downward_frames: int = 3)` | Maintains a 30-frame rolling history |
| `ScoringEventDetector.update` | `(frame_index: int, timestamp: float, detection: dict) -> ScoringEvent \| None` | Feed in one frame's detection; on a hit it returns the event and appends it to `.events` |
| `ScoringEventDetector.events` | `List[ScoringEvent]` | All scoring events accumulated so far |

### `clips/clip_exporter.py`

| Symbol | Signature | Notes |
|--------|-----------|-------|
| `export_clips` | `(video_path: str, events: List[ScoringEvent], output_dir: str, pre_roll: float = 4.0, post_roll: float = 2.0, timeout: float = 120.0) -> List[str]` | Cuts one `libx264 / crf 23 / aac` mp4 per event. A single failed clip (non-zero exit or exceeding `timeout`) only prints a warning, deletes **the partial file this invocation wrote** and skips ahead without aborting the batch (if ffmpeg fails before it ever opens the output, a previously exported clip of the same name is not deleted by mistake) — **so the returned list may be shorter than `events`**, and the timestamps of the failed events are summarized in a final printed line |

Output filename format: `{video_name}_basket_{index:03d}_t{timestamp:.1f}s.mp4`
<!-- END AUTO-GENERATED -->

## Documentation

| File | Contents |
|------|----------|
| [docs/STUDENT_GUIDE.md](docs/STUDENT_GUIDE.md) | **Start here if you just want to use HoopAI.** Accounts, uploading, getting clips back, and what the limits mean. Part 2 covers deploying, for maintainers with an SSH key. |
| [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) | Development environment, code style, testing, PR checklist |
| [docs/RUNBOOK.md](docs/RUNBOOK.md) | Model training and retraining, troubleshooting, dataset configuration |

The guide above is about the **hosted** instance at
https://hoopai.ithacateens.com. The rest of this README is about running the
pipeline on your own machine; the two are independent and you do not need the
local setup to use the hosted one.

## Datasets

The training data comes from Roboflow. Both versions live under `data/` (images and labels are excluded
by `.gitignore`; only the YAML files and the Roboflow metadata are kept):

| Dataset | Class names | Source |
|---------|-------------|--------|
| `data/basketball_dataset/` | `['basketball', 'hoop']` | [Roboflow Universe · basketball-qus2n/basketball-detection](https://universe.roboflow.com/basketball-qus2n/basketball-detection/dataset/1) (CC BY 4.0); `hoopai.yaml` is the config actually used for training |
| `data/hoopal_dataset/` | `['Basketball', 'Hoop']` | [Roboflow Universe · yimings-workspace-vykdp/hoopai](https://universe.roboflow.com/yimings-workspace-vykdp/hoopai/dataset/dataset) (CC BY 4.0) |

The class order is the same in both datasets, so `BALL_CLASS=0` / `HOOP_CLASS=1` holds for either.
