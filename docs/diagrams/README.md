# Presentation diagrams

Three slide-ready diagrams for explaining HoopAI to a non-technical audience (originally made for
presenting to children).

| File | Shows |
|------|-------|
| `1-tech-stack.svg` / `.png` | The tech stack, grouped as 眼睛 (eyes, sees the video) / 大脑 (brain, recognizes and decides) / ✋ 手 (hands, cuts the clips) |
| `2-workflow.svg` / `.png` | The 5-step pipeline, with a zoom-in on the 3 conditions for calling a basket, and a side panel on how the model was trained |
| `3-features.svg` / `.png` | What works today versus what is still missing |

**These three files are deliberately written in Chinese**, unlike the rest of the documentation. They
are a teaching aid for a Chinese-speaking audience, not reference documentation. Everything else in
`docs/` is English.

## Regenerating the PNGs

The `.svg` files are the source; the `.png` files are 3200×1800 exports (2× of the 1600×900 canvas) for
dropping into slides. After editing an SVG, re-export with headless Chrome:

```bash
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
for f in 1-tech-stack 2-workflow 3-features; do
  "$CHROME" --headless --disable-gpu --hide-scrollbars \
    --force-device-scale-factor=2 --default-background-color=FFFFFF \
    --window-size=1600,900 \
    --screenshot="docs/diagrams/$f.png" "docs/diagrams/$f.svg"
done
```

The SVGs have no auto-wrapping: each line of text is its own `<text>` element at a fixed `y`. When
editing copy, keep the line lengths roughly as they are or the text will overflow its card.

Chinese text uses `PingFang SC` with `Hiragino Sans GB` / `Microsoft YaHei` / `Noto Sans CJK SC`
fallbacks, so the SVGs render correctly on macOS and Windows without embedded fonts.

## Numbers shown in the diagrams

These come from the repository and will go stale if the project moves on — check them against the
"current model status" section of the [RUNBOOK](../RUNBOOK.md) before presenting:

- 1389 annotated training images (1218 train / 114 valid / 57 test)
- `data/models/basketball.pt` is 23 MB
- 2 of 20 planned training epochs completed
- Scoring rule: hoop box enlarged 1.4×, 3 descending steps out of the last 4 sampled frames, 3-second cooldown
- Clips are pre-roll 4 s + post-roll 2 s, with a 120 s per-clip ffmpeg timeout
