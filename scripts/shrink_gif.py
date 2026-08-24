"""Resize + palette-optimise the demo GIF for GitHub embed (<10 MB target)."""
from pathlib import Path

from PIL import Image

SRC = Path(__file__).resolve().parents[1] / "results" / "demo_chennai_hour_sweep.gif"
OUT = SRC.with_name(SRC.stem + "_small.gif")

target_width = 800  # from 1200 → 800
scale = target_width / Image.open(SRC).width

frames, durations = [], []
im = Image.open(SRC)
for i in range(im.n_frames):
    im.seek(i)
    f = im.convert("RGBA").resize(
        (target_width, int(im.height * scale)),
        Image.LANCZOS,
    ).convert("P", palette=Image.ADAPTIVE, colors=128)
    frames.append(f)
    durations.append(im.info.get("duration", 220))

frames[0].save(
    OUT, save_all=True, append_images=frames[1:],
    duration=durations, loop=0, optimize=True, disposal=2,
)
print(f"✔ {OUT}  ({OUT.stat().st_size / 1024:.0f} KB, {len(frames)} frames)")
