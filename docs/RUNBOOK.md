# Runbook

HoopAI is an **offline batch tool**, not a service: there is no deployment process, no long-running
process, no health check endpoint and no monitoring or alerting. This runbook covers the operational
scenarios that actually exist — running the pipeline, training/retraining the model, troubleshooting,
and rolling back weights.

## 1. Running the pipeline

### Preflight checks

```bash
source .venv/bin/activate
python -c "import cv2, ultralytics, numpy; print('deps ok')"
ffmpeg -version | head -1
ls -lh data/models/basketball.pt
```

Continue only when all four pass. For missing weights see [§2](#2-training-and-retraining-the-model);
for missing FFmpeg see [§4](#4-troubleshooting).

### Running it

The repository has no entry script, so the four modules have to be wired together by hand — the full
snippet is in [README · Usage](../README.md#usage).

Validate with a short video (< 30 seconds) first, then run the full recording: CPU inference is slow and
a long video can take tens of minutes to several hours.

### Verifying the output

```bash
ls -lh output/clips/
```

Each basket produces one `{video_name}_basket_{index}_t{timestamp}s.mp4`, 6 seconds long by default
(4 seconds before the event + 2 after). Spot-check two or three clips: the scoring action should land
roughly 2 seconds from the end. If a clip contains no basket at all, see
[§4 false positives](#too-many-false-positives-scoring-judgment-is-off).

## 2. Training and retraining the model

### Current model status

<!-- AUTO-GENERATED: generated from runs/detect/data/models/basketball/{args.yaml,results.csv} — do not edit by hand -->

| Item | Value |
|------|-------|
| Training data | `data/basketball_dataset/hoopai.yaml` (1218 train / 114 valid / 57 test) |
| Classes | `['basketball', 'hoop']` (`nc=2`) |
| Planned epochs | 20 (`patience=5`) |
| **Epochs actually completed** | **2** — `results.csv` has only 2 rows; training was interrupted |
| Input size | `imgsz=416`, `batch=4` |
| Device | `device=cpu`, `workers=0` |
| Time per epoch | epoch 1: 1013 s, epoch 2: 11629 s (about 3.2 hours) |
| Weight output | `runs/detect/data/models/basketball/weights/{best,last}.pt` |

Validation metrics of the last epochs:

| Metric | epoch 1 | epoch 2 |
|--------|---------|---------|
| precision(B) | 0.692 | 0.793 |
| recall(B) | 0.728 | 0.636 |
| mAP50(B) | 0.763 | 0.756 |
| mAP50-95(B) | 0.446 | 0.450 |

<!-- END AUTO-GENERATED -->

> **The model is undertrained.** Only 2 of 20 epochs ran, mAP50 is about 0.76, and recall dropped from
> 0.73 to 0.64 in epoch 2. Missed baskets most likely stem from this rather than from the scoring logic.
> Continuing training is the most direct improvement available.

### Weight output path: use an absolute `project=`

Same lesson as `data=`: **a relative `project=` resolves differently depending on the ultralytics
version.** Measured against `get_save_dir`:

| ultralytics | `project=data/models` (relative) | `project="$PWD/data/models"` (absolute) |
|-------------|----------------------------------|------------------------------------------|
| 8.3.133 | `data/models/<name>` — relative to cwd | `<repo root>/data/models/<name>` |
| 8.4.177 | `runs/detect/data/models/<name>` — nested under `runs_dir/<task>/` | `<repo root>/data/models/<name>` |

`get_save_dir` in 8.4.x has one extra step: `if not Path(project).is_absolute(): project = Path(SETTINGS["runs_dir"]) / task / project`.
An absolute path skips it, and both versions agree.

That is why every training command below writes `project="$PWD/data/models"`, so the output reliably
lands in `data/models/<name>/weights/`. (Note: the historical `args.yaml` records the relative
`project: data/models`; deviating from it here is deliberate, in exchange for a predictable location.)

**About that old directory that still exists:** `runs/detect/data/models/basketball/weights/` holds the
**2-epoch checkpoints** from the historical interrupted run (`best.pt` / `last.pt`, 89 MB each,
2026-06-12), consistent with 8.4.x's relative-`project` behavior. Retraining with the absolute
`project=` above **will not overwrite it**, so do not `cp` from there — it will succeed and deploy the
old weights without any error. Resuming training *from* it is correct, though: that is the actual
interruption point.

### Resume training (from the interruption point)

```bash
yolo detect train \
  resume=True \
  model=runs/detect/data/models/basketball/weights/last.pt \
  data="$PWD/data/basketball_dataset/hoopai.yaml"
```

You must pass `data=` explicitly: the checkpoint stores the training machine's absolute path
`/Users/user/HoopAI (Execute Plan)/data/basketball_dataset/hoopai.yaml`, which does not exist locally, so
ultralytics discards it. Apart from `data`, the remaining hyperparameters are taken from the checkpoint.

### Retraining from scratch

First confirm the dataset image directories are in place ([§4](#dataset-yaml-paths)), then run from the
**repository root**:

```bash
yolo detect train \
  data="$PWD/data/basketball_dataset/hoopai.yaml" \
  model=yolov8n.pt \
  epochs=20 imgsz=416 batch=4 \
  device=cpu workers=0 patience=5 \
  project="$PWD/data/models" name=basketball exist_ok=True
```

The reasons both `data=` and `project=` use absolute paths are in [§4](#dataset-yaml-paths) and
[above](#weight-output-path-use-an-absolute-project). The output reliably lands in
`data/models/basketball/weights/`. ultralytics also prints the actual `save_dir` at startup; copying from
whatever it prints is the safest approach.

At the measured CPU speed, 20 epochs takes tens of hours. With a GPU, switch to `device=0 workers=8` and
you can also raise `batch` and `imgsz`.

### Deploying new weights

```bash
# Back up the existing weights (timestamped, so a rollback is possible)
cp data/models/basketball.pt "data/models/basketball.pt.bak.$(date +%Y%m%d-%H%M%S)"

# Replace with the best.pt just produced by the training command above. The path should match the
# save_dir printed when training started; check the mtime to confirm it is from this run, and do not
# pick up the 2-epoch weights in the old runs/detect/... directory.
ls -l data/models/basketball/weights/best.pt
cp data/models/basketball/weights/best.pt data/models/basketball.pt

# Record the checksum, for verification via BasketDetector(expected_sha256=...)
shasum -a 256 data/models/basketball.pt | tee -a data/models/CHECKSUMS.txt
```

`CHECKSUMS.txt` is whitelisted in `.gitignore` (`!data/models/CHECKSUMS.txt`) and **needs to be
committed** so whoever receives the weights can verify them — otherwise it is only a local record, and
you have to communicate the checksum out of band when distributing weights.

After replacing the weights you must re-validate against a video with known baskets and confirm the
detection count has not dropped.

`ModelClass.BALL = 0` / `ModelClass.HOOP = 1` in `detect/basket_detector.py` are hardcoded.
**If a new model's class order or class count differs from `['basketball', 'hoop']`, this enum must be
changed with it**, otherwise ball and hoop are swapped and the pipeline silently outputs zero results.

### Trust boundary for weight files

`YOLO(model_path)` loads `.pt` files via pickle-based `torch.load`, which **executes code embedded in the
file as it loads**. The weights are not in the repository and carry no signature; per CONTRIBUTING they
are "obtained from a maintainer or retrained yourself" — which means any file you place in
`data/models/` must be treated the same as a script you are willing to run directly.

When the source is not fully under your control, pass the checksum to the constructor so a mismatch
raises `ValueError` before loading:

```python
detector = BasketDetector(
    model_path="data/models/basketball.pt",
    expected_sha256="<the value recorded in CHECKSUMS.txt above>",
)
```

The default `expected_sha256=None` performs no verification, exactly as before.

## 3. Rollback

Weights and code roll back separately.

### Rolling back the model weights

```bash
ls -lt data/models/basketball.pt.bak.*
cp data/models/basketball.pt.bak.<timestamp> data/models/basketball.pt
```

The weights are not in git (`*.pt` is excluded by `.gitignore`), so **only the `.bak` backups created
manually above can be rolled back to**. Always back up before replacing.

### Rolling back the code

```bash
git log --oneline
git revert <commit>     # use revert for commits that were already pushed
```

## 4. Troubleshooting

### Dataset YAML paths

**Symptom:** `yolo detect train` reports that the dataset cannot be found, or an image count of 0.

**Key takeaway: pass `data=` as an absolute path.**

```bash
yolo detect train data="$PWD/data/basketball_dataset/hoopai.yaml" ...
```

#### How ultralytics actually resolves them

Each point below was checked against upstream `check_det_dataset` (`ultralytics/data/utils.py`, read at
v8.2.0 / v8.3.133 / v8.3.134 / main) and `check_file` (`ultralytics/utils/checks.py`):

```python
path = Path(extract_dir or data.get("path") or Path(data.get("yaml_file", "")).parent)
if not path.is_absolute():                      # <= 8.3.133
    path = (DATASETS_DIR / path).resolve()
# >= 8.3.134 changed this to: if not path.exists() and not path.is_absolute():
```

1. **The dataset root** = `path:` (if the YAML has one), otherwise = the **parent directory string** of the `data=` argument.
2. `check_file()` **returns the string you passed verbatim** when the file already exists; it does not make it absolute. So a relative `data=` yields a relative root.
3. When the root is relative: **≤ 8.3.133 unconditionally** relocates it under ultralytics' own `datasets_dir` setting; **≥ 8.3.134** relocates it only when that relative path does not exist relative to the current working directory.
4. When the root is absolute, both versions use it as-is.

`requirements.txt` only says `ultralytics>=8.0.0`, which includes ≤ 8.3.133, so **an absolute `data=` is
the only form that holds across the entire allowed range**. A relative `data=` requires both "≥ 8.3.134"
and "run from the repository root".

#### Measured results

Not just read from the source — `check_det_dataset` was run once per version against the real
1218 / 114 / 57 images:

| ultralytics | absolute `data=` | relative `data=` (cwd = repo root) | relative `data=` (cwd elsewhere) |
|-------------|------------------|------------------------------------|----------------------------------|
| 8.4.177 | ✅ resolves correctly | ✅ resolves correctly (the `path.exists()` guard kicks in) | ❌ cannot even find the YAML file |
| 8.3.133 | ✅ resolves correctly | ❌ `missing path '<datasets_dir>/data/basketball_dataset/valid/images'` | ❌ cannot even find the YAML file |

The error text in the 8.3.133 cell is literally the result of the `DATASETS_DIR / path` join, matching
the source above. **An absolute `data=` is the only fully green column of the three.**

One more easy trap: the default value of `datasets_dir` is **not** fixed — locally, 8.4.177 read
`~/Desktop/datasets`, while a side-installed 8.3.133 read `<cwd>/datasets` after its settings were reset.
Do not count on it pointing anywhere in particular.

> **Correction:** earlier documentation in this repository claimed that "omitting `path:` falls back to
> the YAML's own parent directory (an absolute path), and only a relative `path:` is resolved against
> `datasets_dir`". **That is wrong** — both go through the same line of code (the `or` on line 1 above),
> with no asymmetry whatsoever; and the parent directory obtained by the fallback is just as relative as
> the `data=` argument, not absolute. Consequently the "do not add a relative `path:`" prohibition in
> `docs/CONTRIBUTING.md` and `CLAUDE.md` has been relaxed too: what actually needs avoiding is
> **committing machine-local absolute paths** and **relying on a relative `data=`**.

#### Current YAML contents

None of the four YAML files set `path:`; the values are subpaths relative to the dataset root:

```yaml
train: train/images
val: valid/images
test: test/images
```

`data/basketball_dataset/{train,valid,test}/images/` do exist locally (1218 / 114 / 57 images), and the
table above was measured against exactly that data.

**The earlier problem** (visible in `git log`): `hoopai.yaml` and `data_fixed.yaml` contained another
machine's absolute path `/Users/user/HoopAI (Execute Plan)/...`, which was a genuine failure. As for the
`../train/images` originally in the two `data.yaml` files — that was **not** broken:
`check_det_dataset` strips the `../` and retries when the first joined path does not exist (all versions
listed above have this fallback), so it already resolved correctly. Those two edits merely removed a
redundant hop; they were not bug fixes.

**Do not** commit machine-local absolute paths into the YAML files — the PR checklist in
`docs/CONTRIBUTING.md` has an item for exactly that.

### `hoopal_dataset` has no validation split

`data/hoopal_dataset/` has only 42 training images, and `valid/` and `test/` are empty, so training on it
alone cannot be validated. It is the annotation of 42 frames from a single video (`IMG_2362 2.MOV`),
suitable as supplementary data merged into `basketball_dataset` but not for standalone training. Note
that its class names are capitalized (`['Basketball', 'Hoop']`), but the order matches the main dataset,
so the class ID mapping is unaffected.

### `ffmpeg not found`

```
OSError: ffmpeg not found. Install it with:  brew install ffmpeg
```

`clips/clip_exporter.py` checks with `shutil.which("ffmpeg")` before exporting. After installing, reopen
your terminal and confirm `ffmpeg` is on `PATH`.

### `⚠️  FFmpeg timed out after 120s on clip N/M`

A single clip's ffmpeg call exceeded `export_clips(timeout=)` (120 seconds by default). That clip is
skipped, the partial file is deleted, and the batch continues — so **the returned list will be shorter
than `events`**, and the summary line at the end lists the dropped timestamps.

Common causes and fixes:

| Cause | Fix |
|-------|-----|
| `pre_roll` / `post_roll` set very high, so the clip is long by itself | Raise `timeout` |
| The source video is on a network or external drive and reads slowly | Copy the video locally first, or raise `timeout` |
| The source file is corrupt and ffmpeg is stuck decoding | Transcode per "`RuntimeError: Could not open video`" below and retry |

Before the timeout existed the whole batch would simply hang without erroring, which is exactly why it
was added; if you genuinely need to wait indefinitely, pass a very large value rather than removing it.

### `FileNotFoundError: Video not found`

Wrong path. Note that the filenames under `data/samples/` contain spaces (`IMG_2362 2.MOV`), so they must
be quoted in the shell.

### `RuntimeError: Could not open video`

OpenCV cannot decode that container/codec. Confirm the file is intact, then transcode to H.264 mp4:

```bash
ffmpeg -i "input.MOV" -c:v libx264 -crf 20 -c:a aac output.mp4
```

### `RuntimeError: Video reports unusable fps (0.0)`

The file opens, but the frame rate OpenCV reads is 0 — common with variable-frame-rate (VFR) phone
recordings and `.MOV` files, or with corrupt container metadata. Every timestamp is derived from fps, so
without it the scoring moment cannot be located; the code raises here instead of inventing a fake value
(otherwise clips would be cut at the wrong positions, silently).

First see what OpenCV actually reads:

```bash
python3 -c "import cv2; c=cv2.VideoCapture('input.MOV'); print(c.get(cv2.CAP_PROP_FPS))"
```

If it prints `0.0`, transcode to a constant frame rate before running (`-r` forces CFR):

```bash
ffmpeg -i "input.MOV" -r 30 -c:v libx264 -crf 20 -c:a aac output.mp4
```

### Missed baskets (a basket is never detected)

Check in descending order of likelihood:

1. **The model is undertrained** — the most likely cause, see [§2](#current-model-status). Continue training first.
2. **`sample_every_n` is too large** — the downward check counts sampled frames. When you raise `sample_every_n` you must lower `min_downward_frames` accordingly, otherwise the required run of descending frames is never reached.
3. **The confidence threshold is too high** — try lowering `BasketDetector(confidence=)` from `0.35` to `0.25`.
4. **The hoop is not detected** — `ScoringEventDetector.update` requires ball and hoop to be **visible in the same frame**. When the hoop is occluded, out of frame, or backlit, no events are produced for that entire stretch. Temporarily printing `detection["hoop"]` per frame confirms the hoop's detection rate.
5. **The cooldown swallowed the event** — when consecutive fast-break baskets are closer together than `cooldown_seconds` (3 seconds by default), the second one is suppressed.

### Too many false positives (scoring judgment is off)

1. **`margin` is too wide** — `_box_overlap(margin=1.4)` in `events/scoring_event.py` enlarges the hoop region by 1.4×, so a rim-out can be counted as a basket. The value is hardcoded and requires a source change; lowering it also lowers recall.
2. **The downward-frame requirement is too low** — raise `min_downward_frames` (default 3) to require a longer descending trajectory.
3. **Only the ball center is considered** — the check only tests whether the ball's center point falls inside the enlarged box, ignoring the ball's diameter, so a small ball far from the camera is easier to misjudge.

### Inference is too slow

- Raise `extract_frames(sample_every_n=)` (remember to lower `min_downward_frames` accordingly)
- Run on a GPU: `BasketDetector` passes through to `ultralytics`, so set `CUDA_VISIBLE_DEVICES` or specify the device at the `YOLO` call site
- Validate parameters on a short clip before running a full-length video

## 5. Known issues

| Issue | Impact | Location |
|-------|--------|----------|
| No pipeline entry script | Every use requires hand-written wiring code | Repository root |
| The model trained for only 2 of 20 epochs | Elevated miss rate | `data/models/basketball.pt` |
| Dataset paths depend on how you invoke training: `data=` must be absolute | With a relative `data=` and ultralytics < 8.3.134, training fails outright | `data/*_dataset/*.yaml`, [§4](#dataset-yaml-paths) |
| A relative `project=` resolves to different locations per ultralytics version; the old directory still holds the 2-epoch checkpoints | `cp`-ing from the old path silently deploys the old weights | `runs/detect/data/models/` and `data/models/`, [§2](#weight-output-path-use-an-absolute-project) |
| Class indices are hardcoded and the model's actual class names are never verified | Swapping in a model with a different class order fails silently | `ModelClass` in `detect/basket_detector.py` |
| Weight loading goes through pickle with no signature; the checksum must be passed by hand, and there is a TOCTOU window between verification and loading | A `.pt` from an uncontrolled source executes arbitrary code on load | `BasketDetector.__init__` in `detect/basket_detector.py` |
| `_box_overlap`'s `margin` is not configurable | Tuning the false-positive rate requires a source change | `_box_overlap` in `events/scoring_event.py` |
| No tests | No regression protection when changing the scoring logic | Whole repository |
| `tqdm` is a dependency but unused | No progress bar, so long videos give no feedback | `requirements.txt` |
| No logging, everything goes through `print` | Cannot filter by level or retain run records | Whole repository |

## 6. Improvement path (unattended)

This project has no alerting and no on-call rotation. For long-term maintenance, in order of payoff:

1. Add an entry script `main.py` (a CLI taking the video path and output directory) — removes the largest friction in using it
2. Continue training to 20 epochs and record the metrics — directly reduces missed baskets
3. Add tests for `_box_overlap` and `ScoringEventDetector` — so parameters can be tuned with confidence
4. In `BasketDetector.__init__`, compare the loaded `self.model.names` against `['basketball', 'hoop']` and raise on a mismatch — eliminates the "swapping models silently swaps ball and hoop" trap entirely, which is more reliable than a documentation warning
5. Replace `print` with `logging` and wire up the `tqdm` progress bar
