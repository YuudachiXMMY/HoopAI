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

### 继续训练（从中断处恢复）

```bash
yolo detect train resume=True model=runs/detect/data/models/basketball/weights/last.pt
```

`args.yaml` 中 `resume` 已指向 `last.pt`，恢复会沿用原有全部超参。

### 从零重训

先确认数据集图片目录已就位（[§4](#数据集-yaml-路径)），然后：

```bash
yolo detect train \
  data=data/basketball_dataset/hoopai.yaml \
  model=yolov8n.pt \
  epochs=20 imgsz=416 batch=4 \
  device=cpu workers=0 patience=5 \
  project=data/models name=basketball exist_ok=True
```

CPU 上按实测速度，20 轮需数十小时。有 GPU 时改 `device=0 workers=8`，并可提高 `batch` 与 `imgsz`。

### 部署新权重

```bash
# 备份现有权重（带时间戳，便于回滚）
cp data/models/basketball.pt "data/models/basketball.pt.bak.$(date +%Y%m%d-%H%M%S)"

# 用新的 best.pt 替换
cp runs/detect/data/models/basketball/weights/best.pt data/models/basketball.pt

# 记下校验和：权重不在 git 里，这是之后唯一能确认文件没被换过的依据
shasum -a 256 data/models/basketball.pt | tee -a data/models/CHECKSUMS.txt
```

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

> 此前四个 YAML 的路径全部失效，现已修复。**别改回绝对路径。**

四个 dataset YAML 的 `train:` / `val:` / `test:` 现在都是**相对 YAML 自身所在目录**的子路径：

```yaml
train: train/images
val: valid/images
test: test/images
```

**为什么省略 `path:`：** ultralytics 解析 `path:` 的规则是 —— 绝对路径按原样用；**相对路径按 `datasets_dir` 设置解析，不是按仓库根**。所以 `path: data/basketball_dataset` 只在 `datasets_dir` 恰好等于仓库根时才成立，换机器就断。完全省掉 `path:` 时 ultralytics 回退到 YAML 文件自身的父目录（绝对路径），这才是跨机器稳定的写法。

> 本仓库没装 ultralytics、数据集图片也不在版本控制里，所以上面的写法**没有跑一次真实训练验证过**，只是依据 ultralytics 的路径解析规则推出的。第一次重训时若仍报图片数为 0，先确认 `data/basketball_dataset/{train,valid,test}/images/` 确实存在（需从 Roboflow 重新下载）。

**此前的问题**（`git log` 可查）：`hoopai.yaml` 与 `data_fixed.yaml` 写的是另一台机器的绝对路径 `/Users/user/HoopAI (Execute Plan)/...`；两个 `data.yaml` 沿用 Roboflow 导出默认的 `../train/images`，而本仓库把导出内容多放了一层，于是解析到不存在的 `data/train/images`。

**不要**把本机绝对路径提交回仓库 —— `docs/CONTRIBUTING.md` 的 PR 清单对此有一条自查项。

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
| 数据集 YAML 路径改成相对写法后未经真实训练验证 | 重训前需先确认图片目录存在 | `data/*_dataset/*.yaml` |
| 类别索引硬编码，且不校验模型实际类别名 | 换模型时若类别顺序变化会静默出错 | `detect/basket_detector.py` 的 `ModelClass` |
| 权重加载走 pickle，无签名；校验和需手工传入 | 来源不可控的 `.pt` 加载即执行任意代码 | `detect/basket_detector.py` 的 `BasketDetector.__init__` |
| `_box_overlap` 的 `margin` 不可配置 | 调误报率需改源码 | `events/scoring_event.py:20` |
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
