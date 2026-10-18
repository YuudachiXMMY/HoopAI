# Presentation diagrams

Three slide-ready diagrams for explaining HoopAI to a non-technical audience (originally made for
presenting to children). Each one exists in **English** and **Chinese**; the two versions are
otherwise identical in layout and content.

| Topic | English | Chinese | Shows |
|-------|---------|---------|-------|
| Tech stack | `1-tech-stack-en.svg` | `1-tech-stack.svg` | The stack grouped as 👀 eyes (sees the video) / 🧠 brain (recognizes and decides) / ✋ hands (cuts the clips), over a foundation strip |
| Workflow | `2-workflow-en.svg` | `2-workflow.svg` | The 5-step pipeline, a zoom-in on the three conditions that make a basket count, and a side panel on how the model was trained |
| Features | `3-features-en.svg` | `3-features.svg` | What works today (8 items, each naming the module that implements it) versus what is still missing (7 items) |

Each `.svg` has a matching `.png` next to it. The eyes / brain / hands metaphor and its colour coding
carry across all three diagrams, so an audience that has seen the first one can follow the second by
colour alone.

The Chinese versions are the only Chinese documents in the repository — everything else in `docs/` is
English. They are a teaching aid for a Chinese-speaking audience, not reference documentation.

## Regenerating the PNGs

The `.svg` files are the source; the `.png` files are 3200×1800 exports (2× of the 1600×900 canvas) for
dropping into slides. After editing an SVG, re-export with headless Chrome:

```bash
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
for f in 1-tech-stack 2-workflow 3-features \
         1-tech-stack-en 2-workflow-en 3-features-en; do
  "$CHROME" --headless --disable-gpu --hide-scrollbars \
    --force-device-scale-factor=2 --default-background-color=FFFFFF \
    --window-size=1600,900 \
    --screenshot="docs/diagrams/$f.png" "docs/diagrams/$f.svg"
done
```

## Editing caveats

- **SVG has no auto-wrapping.** Every line of text is its own `<text>` element at a fixed `y`. When
  editing copy, keep each line roughly its current length or it will overflow its card.
- **English runs about twice as wide as Chinese per character** (~0.55em versus ~1em). The two language
  versions therefore break their lines at different points, and the English column headers in
  `1-tech-stack-en.svg` use a smaller font than the Chinese ones. Do not translate a line in place
  without re-checking its width.
- Fonts are referenced, not embedded. Chinese uses `PingFang SC` with `Hiragino Sans GB` /
  `Microsoft YaHei` / `Noto Sans CJK SC` fallbacks; English uses `Inter` with `Helvetica Neue` / Arial
  fallbacks. Both render correctly on macOS and Windows without extra installs.

## Numbers shown in the diagrams

These come from the repository and will go stale if the project moves on — check them against the
"current model status" section of the [RUNBOOK](../RUNBOOK.md) before presenting:

- 1389 annotated training images (1218 train / 114 valid / 57 test)
- `data/models/basketball.pt` is 23 MB
- 2 of 20 planned training epochs completed
- Scoring rule: hoop box enlarged 1.4×, 3 descending steps out of the last 4 sampled frames, 3-second cooldown
- Clips are pre-roll 4 s + post-roll 2 s, with a 120 s per-clip ffmpeg timeout
