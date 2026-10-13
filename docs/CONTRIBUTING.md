# 贡献指南

## 开发环境

### 前置条件

| 工具 | 版本 | 必需 | 用途 |
|------|------|------|------|
| Python | 3.11+ | 是 | 运行时 |
| FFmpeg | 近期版本 | 是 | `clips/` 剪辑片段，通过命令行调用 |
| Git | — | 是 | 版本控制 |

### 安装

```bash
git clone https://github.com/YuudachiXMMY/HoopAI.git
cd HoopAI

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

brew install ffmpeg        # macOS
# sudo apt install ffmpeg  # Debian / Ubuntu
```

### 本地所需的仓库外文件

以下内容被 `.gitignore` 排除，clone 后不存在，需自行准备：

| 路径 | 内容 | 获取方式 |
|------|------|----------|
| `data/models/basketball.pt` | YOLOv8 权重 | 向维护者索取，或按 [RUNBOOK](RUNBOOK.md) 重新训练 |
| `data/*_dataset/{train,valid,test}/` | 图片与 YOLO 标签 | 从 Roboflow 重新下载（README 中有链接） |
| `data/samples/*.MOV` | 测试用视频 | 自行录制或向维护者索取 |

## 命令参考

<!-- AUTO-GENERATED: 由 requirements.txt 与 runs/detect/data/models/basketball/args.yaml 生成，勿手改 -->

本项目**没有** `Makefile`、`pyproject.toml` 或 `package.json`，因此没有封装过的脚本。以下是实际可用的命令：

| 命令 | 说明 |
|------|------|
| `pip install -r requirements.txt` | 安装运行依赖 |
| `yolo detect train data=data/basketball_dataset/hoopai.yaml model=yolov8n.pt epochs=20 imgsz=416 batch=4 device=cpu workers=0 patience=5 project=data/models name=basketball exist_ok=True` | 复现模型训练（参数取自上次训练的 `args.yaml`） |
| `yolo detect predict model=data/models/basketball.pt source=<视频路径> conf=0.35` | 仅跑检测、可视化标注结果，不做进球判定 |
| `ffmpeg -version` | 验证 FFmpeg 可用 |

<!-- END AUTO-GENERATED -->

## 环境变量

代码中**不读取任何环境变量**（无 `os.environ` / `os.getenv` / `dotenv` 调用），因此没有 `.env.example`。
所有可配置项通过函数与构造器参数传入 —— 参数清单见 [README 的「调参要点」](../README.md#调参要点)。

若后续引入环境变量，请同时新增 `.env.example`（`.gitignore` 已为其开白名单）并在此处补充说明。

## 代码风格

仓库目前**没有配置 linter、formatter 或 pre-commit hook**。现有代码遵循的约定：

- 每个模块以三引号 docstring 开头，第一行写模块路径，随后一行说明职责
- 公开函数带类型注解；返回 `dict` 的函数在 docstring 里描述结构
- 私有辅助函数以单下划线开头（如 `_box_overlap`、`_check_ffmpeg`）
- 用 `pathlib.Path` 而非字符串拼路径
- 进度与状态用 `print` 输出，缩进两个空格（如 `  Video : ...`）
- 结构化数据优先用 `@dataclass`（见 `ScoringEvent`）

若要引入工具链，建议 `ruff`（lint + format）—— `.gitignore` 已预留 `.ruff_cache/`。

## 测试

**目前没有任何测试。** `.gitignore` 已为 `pytest` 和 coverage 预留缓存路径，但 `pytest` 不在 `requirements.txt` 中。

新增测试时的建议：

```bash
pip install pytest
pytest                      # 全量
pytest tests/test_events.py # 单文件
pytest --cov=. --cov-report=term-missing
```

优先补测的位置（纯逻辑、无需模型或视频，最容易写）：

| 目标 | 为什么值得测 |
|------|--------------|
| `events.scoring_event._box_overlap` | 纯几何函数，输入输出明确；`margin` 边界行为是误判的主要来源 |
| `events.scoring_event.ScoringEventDetector` | 可用构造好的 `detection` 字典直接驱动，无需真实模型；覆盖 cooldown、下落帧数、球或框缺失三类分支 |
| `ingest.frame_extractor.extract_frames` | 文件缺失、无法解码、fps ≤ 0 三条错误路径可直接断言异常类型（后两条需 mock `cv2.VideoCapture`） |

涉及 `BasketDetector` 和 `export_clips` 的测试需要 mock（分别 mock `YOLO` 与 `subprocess.run`），否则会依赖权重文件和 FFmpeg。

## 提交规范

现有历史使用 Conventional Commits：

```
feat: track basketball scoring pipeline and add .gitignore
```

常用前缀：`feat` / `fix` / `docs` / `refactor` / `test` / `chore`。

## PR 清单

提 PR 前自查：

- [ ] 代码能在干净的虚拟环境中 import（`python -c "import ingest, detect, events, clips"`）
- [ ] 未提交被 `.gitignore` 排除的内容 —— 尤其是模型权重（`*.pt`）、视频（`*.mp4` / `*.MOV`）、数据集图片、`runs/`
- [ ] 未提交绝对路径。数据集 YAML 里的 `train:` / `val:` / `test:` 路径若为本机绝对路径，不要提交（见 [RUNBOOK · 数据集 YAML 路径全部失效](RUNBOOK.md#数据集-yaml-路径全部失效)）
- [ ] 改动了模块的公开接口 → 同步更新 README 中 `AUTO-GENERATED` 的「模块参考」表
- [ ] 改动了 `requirements.txt` → 同步更新 README 与本文件中 `AUTO-GENERATED` 的依赖/命令表
- [ ] 改动了默认参数 → 同步更新 README 的「调参要点」表
- [ ] 提交信息遵循 Conventional Commits
