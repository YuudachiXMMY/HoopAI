# CLAUDE.md

篮球进球检测与高光剪辑流水线。纯 Python，离线批处理，不是服务。

## 最重要的一件事

**没有入口脚本。** 仓库里只有四个库模块，没有 `main.py`、没有 CLI、没有 `if __name__ == "__main__"`。
不要去找、也不要假设它存在。要跑流水线必须手写串联代码 —— 可用片段见 [README 的「用法」](README.md#用法)。

## 代码检索

`.codegraph/` 已建索引 → 定位或理解代码时先用 `codegraph_explore`，不要先 grep。

## 架构

四段流水线，单向数据流：

```
ingest.frame_extractor.extract_frames(video, sample_every_n)
    → yield (frame_index, timestamp_seconds, frame)
detect.basket_detector.BasketDetector.detect(frame)
    → {"ball": det|None, "hoop": det|None, "frame_shape": (h, w)}
events.scoring_event.ScoringEventDetector.update(frame_index, timestamp, detection)
    → ScoringEvent | None   （命中时同时追加到 .events）
clips.clip_exporter.export_clips(video, events, output_dir, pre_roll, post_roll, timeout)
    → List[str]（mp4 路径，可能短于 events —— 失败的片段被跳过）
```

阶段间契约是裸 dict，没有 schema 校验。`det` 的形状固定为
`{"box": [x1,y1,x2,y2], "confidence": float, "center": (cx, cy)}` —— 改动任一端都要同步另一端。

模型：自训练 YOLOv8，两类 `['basketball', 'hoop']`，权重在 `data/models/basketball.pt`（被 gitignore，不在仓库里）。

## 命令

无 `Makefile` / `pyproject.toml` / `package.json`，没有封装脚本。

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
brew install ffmpeg                    # clips/ 通过命令行调用 ffmpeg

# 续训。必须显式补 data=：检查点里存的是训练机的绝对路径，本机不存在会被丢弃
yolo detect train resume=True \
  model=runs/detect/data/models/basketball/weights/last.pt \
  data="$PWD/data/basketball_dataset/hoopai.yaml"

# 仅跑检测，可视化标注，不做进球判定
yolo detect predict model=data/models/basketball.pt source=<视频> conf=0.35
```

## 陷阱

1. **类别索引硬编码** —— `detect/basket_detector.py` 的 `ModelClass`（`BALL = 0` / `HOOP = 1`，
   `BALL_CLASS` / `HOOP_CLASS` 是其别名）。加载后**不会**校验模型实际的类别名，
   换模型时若类别顺序变了，球和框会被静默互换，流水线输出零事件且不报错。

2. **`sample_every_n` 与 `min_downward_frames` 耦合** —— 下落判定统计的是**被采样帧**，不是视频帧。
   调大 `sample_every_n` 加速时必须同步调小 `min_downward_frames`，否则连续下降帧数永远凑不够，全程漏判。

3. **`_box_overlap` 的 `margin=1.4` 不可配置** —— 写死在 `events/scoring_event.py` 的函数默认参数里，
   不是 `ScoringEventDetector` 的构造参数。调误报率只能改源码。

4. **进球判定要求球和框同帧可见** —— `ScoringEventDetector.update` 中任一为 `None` 就直接返回。
   篮框被遮挡或出画的整个区间都不会产生事件。

5. **训练时 `data=` 必须传绝对路径** —— 四个 YAML 写成 `train: train/images` 且不设 `path:`，
   数据集根因此取自 `data=` 实参的父目录。而 `check_file` 原样返回你传入的字符串，所以相对的
   `data=` 会让根也是相对的，继而被 ultralytics ≤8.3.133 **无条件**改写到它自己的 `datasets_dir`
   设置下（≥8.3.134 才加了 `path.exists()` 守卫）。`requirements.txt` 允许 `>=8.0.0`，所以只有
   `data="$PWD/..."` 在全范围成立。完整规则与源码出处见
   [RUNBOOK](docs/RUNBOOK.md#数据集-yaml-路径)。**不要把本机绝对路径提交进 YAML。**
   （注：省略 `path:` 与写相对 `path:` 走同一行代码，没有不对称 —— 本文件早先的相反说法已更正。）

6. **模型欠训练** —— 只完成 2/20 轮，mAP50≈0.76。排查漏判时先怀疑这个，而不是判定逻辑。

7. **样本视频文件名含空格** —— 如 `data/samples/IMG_2362 2.MOV`，shell 里必须加引号。

8. **`.pt` 权重加载即执行代码** —— `YOLO(path)` 走 pickle 形式的 `torch.load`。权重不在仓库、无签名，
   放进 `data/models/` 的文件要和「愿意直接执行的脚本」同等对待。来源不可控时给
   `BasketDetector(expected_sha256=...)` 传校验和（校验与加载之间仍有 TOCTOU 窗口，无法消除）。

9. **有两棵权重目录** —— `runs/detect/data/models/basketball/weights/` 是历史那次 2 轮训练的残留，
   `data/models/basketball/weights/` 才是新训练的输出（`save_dir = project / name`，按 cwd 解析）。
   从旧目录 `cp` 会静默部署 2 轮的旧权重，见 [RUNBOOK](docs/RUNBOOK.md#两棵权重目录先搞清楚谁是谁)。

## 代码风格

无 linter / formatter / pre-commit hook。现有约定：

- 模块首行 docstring 写模块路径，次行写职责
- 公开函数带类型注解；返回 `dict` 的在 docstring 描述结构
- 私有辅助函数单下划线前缀（`_box_overlap`、`_check_ffmpeg`）
- 路径用 `pathlib.Path`
- 状态输出用 `print`，缩进两空格（`  Video : ...`）—— 无 `logging`
- 结构化数据用 `@dataclass`

## 测试

**没有任何测试**，`pytest` 也不在 `requirements.txt` 里。改动判定逻辑时没有回归保护 —— 动
`events/scoring_event.py` 之前建议先补测试，它是纯标准库、可用构造好的 dict 直接驱动，最容易测。

## 文档同步

README / CONTRIBUTING / RUNBOOK 中有 4 处 `<!-- AUTO-GENERATED -->` 区块，各自的真理源：

| 区块位置 | 真理源 |
|----------|--------|
| README「Python 依赖」 | `requirements.txt` |
| README「模块参考」 | 各模块的导出符号与签名 |
| CONTRIBUTING「命令参考」 | `requirements.txt` + `runs/detect/data/models/basketball/args.yaml` |
| RUNBOOK「当前模型状态」 | `runs/.../args.yaml` + `runs/.../results.csv` |

改动真理源时同步重新生成对应区块，不要手改区块内容。

## Git

- 提交信息用 Conventional Commits（`feat:` / `fix:` / `docs:` / `refactor:` / `test:` / `chore:`）
- 千万别提交：模型权重（`*.pt`）、视频（`*.mp4` / `*.MOV`）、数据集图片、`runs/`、本机绝对路径
