# HoopAI

从一段篮球视频中自动找出进球瞬间，并剪出高光片段。

流程基于自训练的 YOLOv8 双类检测模型（`basketball` / `hoop`）。进球判定不依赖固定机位：它直接用检测到的篮框位置，判断球心是否进入篮框区域且正在下落，因此换角度拍摄也能工作。

## 流水线

```
视频文件
   │
   ├─▶ ingest.frame_extractor.extract_frames        抽帧 + 时间戳
   │
   ├─▶ detect.basket_detector.BasketDetector        每帧检测球与篮框
   │
   ├─▶ events.scoring_event.ScoringEventDetector    球入框 + 下落 → 进球事件
   │
   └─▶ clips.clip_exporter.export_clips             FFmpeg 按事件时间剪片
                                                         │
                                                         ▼
                                                   高光 mp4 片段
```

> **当前状态：没有统一入口。** 仓库里只有上面四个模块，没有 `main.py`、没有 CLI、没有测试。
> 要跑通整条流水线，需要自己按下面的「用法」把四步串起来，或新建一个入口脚本。

## 环境准备

前置条件：

| 依赖 | 版本 | 说明 |
|------|------|------|
| Python | 3.11+ | 本机实测 3.12.13；仓库中残留的 `__pycache__` 是 3.11 编译的，可安全删除 |
| FFmpeg | 任意近期版本 | `clips.clip_exporter` 直接调用 `ffmpeg` 命令行，缺失会抛 `EnvironmentError` |

安装：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# macOS 安装 FFmpeg
brew install ffmpeg
```

<!-- AUTO-GENERATED: 由 requirements.txt 生成，勿手改 -->
### Python 依赖

| 包 | 版本约束 | 用途 |
|----|----------|------|
| `ultralytics` | `>=8.0.0` | YOLOv8 模型加载与推理（`detect/`） |
| `opencv-python` | `>=4.8.0` | 视频解码与抽帧（`ingest/`） |
| `numpy` | `>=1.24.0` | 帧数组类型 |
| `tqdm` | `>=4.65.0` | 进度条（当前代码未实际引用） |
<!-- END AUTO-GENERATED -->

模型权重位于 `data/models/basketball.pt`（已被 `.gitignore` 排除，不在仓库中，需本地自备或重新训练 —— 见 [docs/RUNBOOK.md](docs/RUNBOOK.md)）。

## 用法

目前需要手动串联四个模块：

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
        print(f"进球 @ {event.timestamp_seconds:.1f}s (conf={event.confidence:.2f})")

paths = export_clips(
    video,
    scorer.events,
    output_dir="output/clips",
    pre_roll=4.0,
    post_roll=2.0,
)
print(f"导出 {len(paths)} 个片段")
```

### 调参要点

| 参数 | 默认值 | 影响 |
|------|--------|------|
| `extract_frames(sample_every_n=)` | `1` | 抽帧步长。调大可加速，但会稀释下落轨迹 —— `ScoringEventDetector` 的 `min_downward_frames` 统计的是**被采样帧**，`sample_every_n` 调大时需同步调小 `min_downward_frames`，否则会漏判 |
| `BasketDetector(confidence=)` | `0.35` | 检测置信度阈值。低于此值的框被丢弃；每帧只保留置信度最高的一个球和一个框 |
| `ScoringEventDetector(cooldown_seconds=)` | `3.0` | 两次进球事件的最小间隔，用于抑制同一次进球被重复计数 |
| `ScoringEventDetector(min_downward_frames=)` | `3` | 判定「球在下落」所需的连续下降帧数 |
| `_box_overlap(margin=)` | `1.4` | 篮框判定区域的放大系数（硬编码，非构造参数）。调大更宽容但会把擦框不进误判为进球 |
| `export_clips(pre_roll=, post_roll=)` | `4.0` / `2.0` | 片段在事件时间点前后各截取的秒数 |

<!-- AUTO-GENERATED: 由源码导出符号生成，勿手改 -->
## 模块参考

### `ingest/frame_extractor.py`

| 符号 | 签名 | 说明 |
|------|------|------|
| `extract_frames` | `(video_path: str, sample_every_n: int = 1)` | 生成器，逐帧 yield `(frame_index, timestamp_seconds, frame)`。文件不存在抛 `FileNotFoundError`，无法解码抛 `RuntimeError` |
| `get_video_info` | `(video_path: str) -> dict` | 返回 `fps` / `frame_count` / `width` / `height` / `duration_seconds` |

### `detect/basket_detector.py`

| 符号 | 签名 | 说明 |
|------|------|------|
| `BALL_CLASS` | `= 0` | 自训练模型中 `basketball` 的类别 ID |
| `HOOP_CLASS` | `= 1` | 自训练模型中 `hoop` 的类别 ID |
| `BasketDetector.__init__` | `(model_path: str = "data/models/basketball.pt", confidence: float = 0.35)` | 加载 YOLO 权重 |
| `BasketDetector.detect` | `(frame: np.ndarray) -> dict` | 返回 `{"ball": det \| None, "hoop": det \| None, "frame_shape": (h, w)}`；`det` 为 `{"box": [x1,y1,x2,y2], "confidence": float, "center": (cx, cy)}` |

### `events/scoring_event.py`

| 符号 | 签名 | 说明 |
|------|------|------|
| `ScoringEvent` | `dataclass(frame_index, timestamp_seconds, confidence, ball_center)` | 单次进球事件 |
| `ScoringEventDetector.__init__` | `(cooldown_seconds: float = 3.0, min_downward_frames: int = 3)` | 维护 30 帧滚动历史 |
| `ScoringEventDetector.update` | `(frame_index: int, timestamp: float, detection: dict) -> ScoringEvent \| None` | 喂入一帧检测结果；命中时返回事件并追加到 `.events` |
| `ScoringEventDetector.events` | `List[ScoringEvent]` | 累计的全部进球事件 |

### `clips/clip_exporter.py`

| 符号 | 签名 | 说明 |
|------|------|------|
| `export_clips` | `(video_path: str, events: List[ScoringEvent], output_dir: str, pre_roll: float = 4.0, post_roll: float = 2.0) -> List[str]` | 每个事件剪一个 `libx264 / crf 23 / aac` 的 mp4。单个片段失败只打印警告并跳过，不中断整批 |

输出文件名格式：`{视频名}_basket_{序号:03d}_t{时间戳:.1f}s.mp4`
<!-- END AUTO-GENERATED -->

## 文档

| 文件 | 内容 |
|------|------|
| [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) | 开发环境、代码风格、测试、PR 清单 |
| [docs/RUNBOOK.md](docs/RUNBOOK.md) | 模型训练与重训、常见故障排查、数据集配置 |

## 数据集

训练数据来自 Roboflow，两个版本都在 `data/` 下（图片与标签被 `.gitignore` 排除，仅保留 YAML 与 Roboflow 元数据）：

| 数据集 | 类别名 | 来源 |
|--------|--------|------|
| `data/basketball_dataset/` | `['basketball', 'hoop']` | `hoopai.yaml` 为实际训练所用配置 |
| `data/hoopal_dataset/` | `['Basketball', 'Hoop']` | [Roboflow Universe · yimings-workspace-vykdp/hoopai](https://universe.roboflow.com/yimings-workspace-vykdp/hoopai/dataset/dataset)（CC BY 4.0） |

两个数据集类别顺序一致，因此 `BALL_CLASS=0` / `HOOP_CLASS=1` 对二者都成立。
