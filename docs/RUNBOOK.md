# 运行手册

HoopAI 是**离线批处理工具**，不是服务：没有部署流程、没有常驻进程、没有健康检查端点或监控告警。本手册覆盖实际存在的运维场景 —— 跑流水线、训练/重训模型、排查故障、回滚权重。

## 1. 跑一次流水线

### 前置检查

```bash
source .venv/bin/activate
python -c "import cv2, ultralytics, numpy; print('deps ok')"
ffmpeg -version | head -1
ls -lh data/models/basketball.pt
```

四项都通过才继续。缺权重见 [§2](#2-训练与重训模型)，缺 FFmpeg 见 [§4](#4-故障排查)。

### 执行

仓库没有入口脚本，需手动串联四个模块 —— 完整代码见 [README 的「用法」](../README.md#用法)。

建议先用短视频（<30 秒）验证，再跑完整录像：CPU 推理很慢，长视频可能跑几十分钟到数小时。

### 验证输出

```bash
ls -lh output/clips/
```

每个进球对应一个 `{视频名}_basket_{序号}_t{时间戳}s.mp4`，默认时长 6 秒（事件前 4 秒 + 后 2 秒）。
抽查两三个片段：进球动作应落在片段尾部约 2 秒处。若片段里没有进球，见 [§4 误报](#误报多进球判定不准)。

## 2. 训练与重训模型

### 当前模型状态

<!-- AUTO-GENERATED: 由 runs/detect/data/models/basketball/{args.yaml,results.csv} 生成，勿手改 -->

| 项 | 值 |
|----|-----|
| 训练数据 | `data/basketball_dataset/hoopai.yaml`（1218 train / 114 valid / 57 test） |
| 类别 | `['basketball', 'hoop']`（`nc=2`） |
| 计划轮数 | 20（`patience=5`） |
| **实际完成轮数** | **2** —— `results.csv` 只有 2 行，训练被中断 |
| 输入尺寸 | `imgsz=416`，`batch=4` |
| 设备 | `device=cpu`，`workers=0` |
| 单轮耗时 | 第 1 轮 1013 s，第 2 轮 11629 s（约 3.2 小时） |
| 权重输出 | `runs/detect/data/models/basketball/weights/{best,last}.pt` |

最后一轮验证指标：

| 指标 | epoch 1 | epoch 2 |
|------|---------|---------|
| precision(B) | 0.692 | 0.793 |
| recall(B) | 0.728 | 0.636 |
| mAP50(B) | 0.763 | 0.756 |
| mAP50-95(B) | 0.446 | 0.450 |

<!-- END AUTO-GENERATED -->

> **模型欠训练。** 只跑了 2/20 轮，mAP50 约 0.76 且第 2 轮 recall 从 0.73 掉到 0.64。
> 漏判进球多半源于此，而非判定逻辑。继续训练是最直接的提升手段。

### 权重输出路径：用绝对 `project=`

和 `data=` 同一个教训：**相对的 `project=` 落点随 ultralytics 版本变**。实测 `get_save_dir`：

| ultralytics | `project=data/models`（相对） | `project="$PWD/data/models"`（绝对） |
|-------------|-------------------------------|--------------------------------------|
| 8.3.133 | `data/models/<name>` —— 相对 cwd | `<仓库根>/data/models/<name>` |
| 8.4.177 | `runs/detect/data/models/<name>` —— 被嵌进 `runs_dir/<task>/` | `<仓库根>/data/models/<name>` |

8.4.x 的 `get_save_dir` 多了一步：`if not Path(project).is_absolute(): project = Path(SETTINGS["runs_dir"]) / task / project`。绝对路径跳过这一步，两版一致。

所以下面的训练命令一律写 `project="$PWD/data/models"`，输出确定落在 `data/models/<name>/weights/`。
（注：历史 `args.yaml` 记录的是相对的 `project: data/models`，这里有意偏离，换取落点可预测。）

**现存的那棵旧目录：** `runs/detect/data/models/basketball/weights/` 里是历史那次中断训练的 **2 轮检查点**（`best.pt` / `last.pt`，各 89 MB，2026-06-12），与 8.4.x 的相对-project 行为吻合。用上面的绝对 `project=` 重训时**不会覆盖它**，所以别从那里 `cp` —— 会成功但部署的是旧权重，不报任何错。续训要从它恢复则是对的（那才是中断点）。

### 继续训练（从中断处恢复）

```bash
yolo detect train \
  resume=True \
  model=runs/detect/data/models/basketball/weights/last.pt \
  data="$PWD/data/basketball_dataset/hoopai.yaml"
```

必须显式补 `data=`：检查点里存的是训练机的绝对路径
`/Users/user/HoopAI (Execute Plan)/data/basketball_dataset/hoopai.yaml`，在本机不存在，ultralytics 会丢弃它。
除 `data` 外其余超参沿用检查点里的记录。

### 从零重训

先确认数据集图片目录已就位（[§4](#数据集-yaml-路径)），然后在**仓库根**执行：

```bash
yolo detect train \
  data="$PWD/data/basketball_dataset/hoopai.yaml" \
  model=yolov8n.pt \
  epochs=20 imgsz=416 batch=4 \
  device=cpu workers=0 patience=5 \
  project="$PWD/data/models" name=basketball exist_ok=True
```

`data=` 与 `project=` 都用绝对路径的理由见 [§4](#数据集-yaml-路径) 与
[上文](#权重输出路径用绝对-project)。输出确定落在 `data/models/basketball/weights/`。
ultralytics 启动时也会把实际的 `save_dir` 打印出来，照它复制最稳妥。

CPU 上按实测速度，20 轮需数十小时。有 GPU 时改 `device=0 workers=8`，并可提高 `batch` 与 `imgsz`。

### 部署新权重

```bash
# 备份现有权重（带时间戳，便于回滚）
cp data/models/basketball.pt "data/models/basketball.pt.bak.$(date +%Y%m%d-%H%M%S)"

# 用上面那条训练命令刚产出的 best.pt 替换。路径应与训练启动时打印的 save_dir 一致；
# 先看 mtime 确认是本次训练的，别拿到 runs/detect/... 那棵旧目录里的 2 轮权重。
ls -l data/models/basketball/weights/best.pt
cp data/models/basketball/weights/best.pt data/models/basketball.pt

# 记下校验和，供 BasketDetector(expected_sha256=...) 校验
shasum -a 256 data/models/basketball.pt | tee -a data/models/CHECKSUMS.txt
```

`CHECKSUMS.txt` 已在 `.gitignore` 里开了白名单（`!data/models/CHECKSUMS.txt`），**需要提交**才能让拿到权重的人核对——否则它只是本机记录，分发权重时必须另走带外渠道告知校验和。

替换后必须用已知有进球的视频回归验证一遍，确认检出数量没有下降。

`detect/basket_detector.py` 中 `ModelClass.BALL = 0` / `ModelClass.HOOP = 1` 是硬编码。
**若新模型的类别顺序或数量与 `['basketball', 'hoop']` 不同，必须同步改这个枚举**，否则球和框会被互换，流水线静默输出零结果。

### 权重文件的信任边界

`YOLO(model_path)` 通过 pickle 形式的 `torch.load` 加载 `.pt`，**加载即执行文件里嵌入的代码**。权重不在仓库中、也没有签名，按 CONTRIBUTING 的说法是「向维护者索取或自行重训」—— 这意味着放进 `data/models/` 的文件必须和你愿意直接执行的脚本同等对待。

来源不完全可控时，把校验和传给构造器，不匹配就在加载前抛 `ValueError`：

```python
detector = BasketDetector(
    model_path="data/models/basketball.pt",
    expected_sha256="<上面 CHECKSUMS.txt 里记下的值>",
)
```

默认 `expected_sha256=None` 不做校验，行为与以前一致。

## 3. 回滚

权重与代码分开回滚。

### 回滚模型权重

```bash
ls -lt data/models/basketball.pt.bak.*
cp data/models/basketball.pt.bak.<时间戳> data/models/basketball.pt
```

权重不在 git 中（`*.pt` 被 `.gitignore` 排除），**只有上面手动创建的 `.bak` 备份可回滚**。替换前务必备份。

### 回滚代码

```bash
git log --oneline
git revert <commit>     # 已推送的提交用 revert
```

## 4. 故障排查

### 数据集 YAML 路径

**症状：** `yolo detect train` 报找不到数据集，或图片数为 0。

**关键结论：把 `data=` 传成绝对路径。**

```bash
yolo detect train data="$PWD/data/basketball_dataset/hoopai.yaml" ...
```

#### ultralytics 实际的解析规则

以下逐条核对过上游 `check_det_dataset`（`ultralytics/data/utils.py`，查了 v8.2.0 / v8.3.133 / v8.3.134 / main）与 `check_file`（`ultralytics/utils/checks.py`）：

```python
path = Path(extract_dir or data.get("path") or Path(data.get("yaml_file", "")).parent)
if not path.is_absolute():                      # <= 8.3.133
    path = (DATASETS_DIR / path).resolve()
# >= 8.3.134 改为： if not path.exists() and not path.is_absolute():
```

1. **数据集根** = `path:`（若 YAML 里有），否则 = `data=` 实参的**父目录字符串**。
2. `check_file()` 在文件已存在时**原样返回你传入的字符串**，不转绝对路径。所以传相对的 `data=` 时，根也是相对的。
3. 根是相对路径时：**≤ 8.3.133 无条件**改写到 ultralytics 自己的 `datasets_dir` 设置下；**≥ 8.3.134** 只在该相对路径对当前工作目录不存在时才改写。
4. 根是绝对路径时，两种版本都原样使用。

`requirements.txt` 只写 `ultralytics>=8.0.0`，涵盖 ≤8.3.133，所以**绝对 `data=` 是唯一在整个允许范围内都成立的形式**。相对 `data=` 要求同时满足「≥8.3.134」且「在仓库根执行」。

#### 实测结果

不只是读源码——用真实的 1218 / 114 / 57 张图片，对两个版本各跑了一遍 `check_det_dataset`：

| ultralytics | `data=` 绝对路径 | `data=` 相对路径（cwd = 仓库根） | `data=` 相对路径（cwd 在别处） |
|-------------|------------------|----------------------------------|--------------------------------|
| 8.4.177 | ✅ 解析正确 | ✅ 解析正确（`path.exists()` 守卫生效） | ❌ 连 YAML 文件都找不到 |
| 8.3.133 | ✅ 解析正确 | ❌ `missing path '<datasets_dir>/data/basketball_dataset/valid/images'` | ❌ 连 YAML 文件都找不到 |

8.3.133 那格的报错原文就是 `DATASETS_DIR / path` 拼接的结果，与上面的源码一致。**绝对 `data=` 是三种情形里唯一全绿的一列。**

顺带一个容易踩的点：`datasets_dir` 默认值**不是**固定的 —— 本机实测 8.4.177 读到 `~/Desktop/datasets`，而旁装的 8.3.133 重置设置后读到 `<cwd>/datasets`。别指望它指向任何特定位置。

> **更正：** 本仓库早先的文档曾声称「省略 `path:` 会回退到 YAML 自身父目录（绝对路径），而相对 `path:` 才按 `datasets_dir` 解析」。**这是错的**——两者走的是同一行代码（上面第 1 行的 `or`），没有任何不对称；而且回退得到的父目录与 `data=` 实参一样是相对的，不是绝对的。因此 `docs/CONTRIBUTING.md` 与 `CLAUDE.md` 里「不要加相对 `path:`」那条禁令也随之放宽：真正要避免的是**提交本机绝对路径**，以及**依赖相对 `data=`**。

#### YAML 当前内容

四个 YAML 都不设 `path:`，键值为相对数据集根的子路径：

```yaml
train: train/images
val: valid/images
test: test/images
```

本机的 `data/basketball_dataset/{train,valid,test}/images/` 确实存在（1218 / 114 / 57 张），上表的实测就是对着这份真实数据跑的。

**此前的问题**（`git log` 可查）：`hoopai.yaml` 与 `data_fixed.yaml` 写的是另一台机器的绝对路径 `/Users/user/HoopAI (Execute Plan)/...`，那是真实故障。至于两个 `data.yaml` 原本的 `../train/images` —— 它**并没有坏**：`check_det_dataset` 在首次拼接的路径不存在时会去掉 `../` 再试一次（上述所有版本都有这段回退），所以它本来就能解析到位。那两处改动只是去掉一次多余跳转，不是 bug 修复。

**不要**把本机绝对路径提交进 YAML —— `docs/CONTRIBUTING.md` 的 PR 清单对此有一条自查项。

### `hoopal_dataset` 没有验证集

`data/hoopal_dataset/` 只有 42 张训练图，`valid/` 与 `test/` 为空，单独用它训练无法验证。
它是 42 帧单段视频（`IMG_2362 2.MOV`）的标注，适合作为补充数据合并进 `basketball_dataset`，不适合独立训练。
注意其类别名首字母大写（`['Basketball', 'Hoop']`），但顺序与主数据集一致，类别 ID 映射不受影响。

### `ffmpeg not found`

```
OSError: ffmpeg not found. Install it with:  brew install ffmpeg
```

`clips/clip_exporter.py` 在导出前用 `shutil.which("ffmpeg")` 检查。安装后重开终端，确认 `ffmpeg` 在 `PATH` 中。

### `⚠️  FFmpeg timed out after 120s on clip N/M`

单个片段的 ffmpeg 调用超过了 `export_clips(timeout=)`（默认 120 秒）。该片段被跳过、半成品文件被删除，整批继续 —— 所以**返回的列表会短于 `events`**，结尾的汇总行会列出丢掉的时间戳。

常见原因与处理：

| 原因 | 处理 |
|------|------|
| `pre_roll` / `post_roll` 调得很大，片段本身就长 | 调高 `timeout` |
| 源视频在网络盘 / 外置盘上，读取慢 | 先把视频拷到本地再跑，或调高 `timeout` |
| 源文件损坏，ffmpeg 卡在解码上 | 按下面「`RuntimeError: Could not open video`」转码后重试 |

超时前整批会一直卡住不动而且不报错，这正是加 `timeout` 的原因；若确实需要无限等待，传一个很大的值而不是去掉它。

### `FileNotFoundError: Video not found`

路径不对。注意 `data/samples/` 下的文件名含空格（`IMG_2362 2.MOV`），在 shell 里必须加引号。

### `RuntimeError: Could not open video`

OpenCV 无法解码该容器/编码。先确认文件完整，再转成 H.264 mp4：

```bash
ffmpeg -i "输入.MOV" -c:v libx264 -crf 20 -c:a aac 输出.mp4
```

### `RuntimeError: Video reports unusable fps (0.0)`

文件能打开，但 OpenCV 读到的帧率是 0 —— 常见于可变帧率（VFR）的手机录屏/`.MOV`，或容器元数据损坏。
所有时间戳都由 fps 推算，拿不到就无法定位进球时刻，所以这里直接抛错而不是凑一个假值
（否则片段会被剪在错误位置，且不报错）。

先确认 OpenCV 读到了什么：

```bash
python3 -c "import cv2; c=cv2.VideoCapture('输入.MOV'); print(c.get(cv2.CAP_PROP_FPS))"
```

输出 `0.0` 则转成固定帧率再跑（`-r` 强制 CFR）：

```bash
ffmpeg -i "输入.MOV" -r 30 -c:v libx264 -crf 20 -c:a aac 输出.mp4
```

### 漏判（进球没被检出）

按可能性从高到低排查：

1. **模型欠训练** —— 最可能的原因，见 [§2](#当前模型状态)。先继续训练。
2. **`sample_every_n` 过大** —— 下落判定统计的是被采样帧。`sample_every_n` 调大时须同步调小 `min_downward_frames`，否则连续下降帧数永远凑不够。
3. **置信度阈值过高** —— 把 `BasketDetector(confidence=)` 从 `0.35` 降到 `0.25` 试试。
4. **篮框未被检出** —— `ScoringEventDetector.update` 要求球和框**同帧都可见**才判定。篮框被遮挡、出画或逆光时整段都不会出事件。可临时打印每帧 `detection["hoop"]` 确认框的检出率。
5. **cooldown 吞掉了事件** —— 连续快攻进球间隔小于 `cooldown_seconds`（默认 3 秒）时，后一个会被抑制。

### 误报多（进球判定不准）

1. **`margin` 过宽** —— `events/scoring_event.py` 的 `_box_overlap(margin=1.4)` 把篮框区域放大了 1.4 倍，擦框不进可能被算作进球。该值硬编码，需改源码；调小会同时降低召回。
2. **下落帧数要求过低** —— 提高 `min_downward_frames`（默认 3），要求更长的下落轨迹。
3. **仅看球心** —— 判定只用球的中心点是否落在放大后的框内，不考虑球的直径，远景小球更容易误判。

### 推理太慢

- 调大 `extract_frames(sample_every_n=)`（记得同步调小 `min_downward_frames`）
- 在 GPU 上跑：`BasketDetector` 透传给 `ultralytics`，设置 `CUDA_VISIBLE_DEVICES` 或在 `YOLO` 调用处指定 device
- 先用短片段验证参数，再跑全长视频

## 5. 已知问题

| 问题 | 影响 | 位置 |
|------|------|------|
| 没有流水线入口脚本 | 每次使用都要手写串联代码 | 仓库根目录 |
| 模型只训练了 2/20 轮 | 漏判率偏高 | `data/models/basketball.pt` |
| 数据集路径依赖调用方式：`data=` 必须传绝对路径 | 用相对 `data=` 且 ultralytics < 8.3.134 时训练直接失败 | `data/*_dataset/*.yaml`、[§4](#数据集-yaml-路径) |
| 相对 `project=` 的输出落点随 ultralytics 版本变；旧目录还留着 2 轮检查点 | 从旧路径 `cp` 会静默部署旧权重 | `runs/detect/data/models/` 与 `data/models/`，[§2](#权重输出路径用绝对-project) |
| 类别索引硬编码，且不校验模型实际类别名 | 换模型时若类别顺序变化会静默出错 | `detect/basket_detector.py` 的 `ModelClass` |
| 权重加载走 pickle，无签名；校验和需手工传入，且校验与加载之间有 TOCTOU 窗口 | 来源不可控的 `.pt` 加载即执行任意代码 | `detect/basket_detector.py` 的 `BasketDetector.__init__` |
| `_box_overlap` 的 `margin` 不可配置 | 调误报率需改源码 | `events/scoring_event.py` 的 `_box_overlap` |
| 没有测试 | 改动判定逻辑无回归保护 | 全仓库 |
| `tqdm` 在依赖中但未使用 | 无进度条，长视频无进展反馈 | `requirements.txt` |
| 无日志，全部用 `print` | 无法按级别过滤或留存运行记录 | 全仓库 |

## 6. 升级路径（无人值守）

本项目无告警与值班机制。若要长期维护，按收益排序：

1. 加入口脚本 `main.py`（CLI 接视频路径与输出目录）—— 消除最大的使用摩擦
2. 继续训练到 20 轮并记录指标 —— 直接降低漏判
3. 为 `_box_overlap` 和 `ScoringEventDetector` 补测试 —— 调参时才敢动
4. `BasketDetector.__init__` 里把加载后的 `self.model.names` 与 `['basketball', 'hoop']` 比一遍并在不符时报错 —— 彻底消掉「换模型静默互换球和框」这个陷阱，比靠文档提醒可靠
5. 用 `logging` 替换 `print`，接上 `tqdm` 进度条
