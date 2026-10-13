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
clips.clip_exporter.export_clips(video, events, output_dir, pre_roll, post_roll)
    → List[str]（mp4 路径）
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

# 续训（args.yaml 的 resume 已指向 last.pt）
yolo detect train resume=True model=runs/detect/data/models/basketball/weights/last.pt

# 仅跑检测，可视化标注，不做进球判定
yolo detect predict model=data/models/basketball.pt source=<视频> conf=0.35
```

## 陷阱

1. **类别 ID 硬编码** —— `detect/basket_detector.py` 里 `BALL_CLASS = 0` / `HOOP_CLASS = 1`。
   换模型时若类别顺序变了，球和框会被静默互换，流水线输出零事件且不报错。

2. **`sample_every_n` 与 `min_downward_frames` 耦合** —— 下落判定统计的是**被采样帧**，不是视频帧。
   调大 `sample_every_n` 加速时必须同步调小 `min_downward_frames`，否则连续下降帧数永远凑不够，全程漏判。

3. **`_box_overlap` 的 `margin=1.4` 不可配置** —— 写死在 `events/scoring_event.py` 的函数默认参数里，
   不是 `ScoringEventDetector` 的构造参数。调误报率只能改源码。

4. **进球判定要求球和框同帧可见** —— `ScoringEventDetector.update` 中任一为 `None` 就直接返回。
   篮框被遮挡或出画的整个区间都不会产生事件。

5. **数据集 YAML 路径全部失效** —— `data/basketball_dataset/` 下三个 YAML 写的是
   `/Users/user/HoopAI (Execute Plan)/...`（另一台机器）或解析不到的相对路径。
   修复方式见 [RUNBOOK](docs/RUNBOOK.md#数据集-yaml-路径全部失效)。**修好后不要把本机绝对路径提交回仓库。**

6. **模型欠训练** —— 只完成 2/20 轮，mAP50≈0.76。排查漏判时先怀疑这个，而不是判定逻辑。

7. **样本视频文件名含空格** —— 如 `data/samples/IMG_2362 2.MOV`，shell 里必须加引号。

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
