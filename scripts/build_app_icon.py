#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow>=10"]
# ///
"""Generate the helper bundle's AppIcon.iconset PNGs from the
pixel-art logo-mark.

The logo lives in `docs/design/diting-design/assets/logo-mark.svg`
as 11 hand-placed rectangles on a 72x56 grid. Instead of pulling in
an SVG rasteriser, we re-draw the same rectangles directly with
Pillow — the design owner committed to pixel-perfect crispness in
CLAUDE.md ("the pixel-art beast is the only mark; do not redesign
it"), and a real renderer would resample the edges anyway.

Output: helper/Resources/AppIcon.iconset/icon_<size><@2x>.png
covering the macOS standard set:

  icon_16x16.png    (16)         icon_16x16@2x.png    (32)
  icon_32x32.png    (32)         icon_32x32@2x.png    (64)
  icon_128x128.png  (128)        icon_128x128@2x.png  (256)
  icon_256x256.png  (256)        icon_256x256@2x.png  (512)
  icon_512x512.png  (512)        icon_512x512@2x.png  (1024)

`helper/build.sh` runs `iconutil --convert icns` over the iconset
directory to produce the bundle's `AppIcon.icns`.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

# Brand palette from docs/design/diting-design/colors_and_type.css
ORANGE = (0xfe, 0xa6, 0x2b, 0xff)
DARK_PIXEL = (0x12, 0x12, 0x12, 0xff)
# Near-black canvas matching the diting TUI background. RGBA so we
# can sit on translucent surfaces (Finder dark mode, Notification
# Centre); the alpha=255 means it reads as opaque on light
# backgrounds too.
BG = (0x12, 0x12, 0x12, 0xff)

# Re-encoded from docs/design/diting-design/assets/logo-mark.svg.
# Format: (x, y, w, h, color). Coordinates are in the SVG's
# 72x56 design grid. Order matches the SVG so the one dark pixel
# at (8,24) overlays the orange band underneath.
RECTS: list[tuple[int, int, int, int, tuple[int, int, int, int]]] = [
    (16, 0,  8,  16, ORANGE),
    (0,  16, 64, 8,  ORANGE),
    (0,  24, 72, 8,  ORANGE),
    (0,  32, 72, 8,  ORANGE),
    (8,  40, 8,  8,  ORANGE),
    (16, 40, 8,  8,  ORANGE),
    (48, 40, 8,  8,  ORANGE),
    (56, 40, 8,  8,  ORANGE),
    (8,  24, 8,  8,  DARK_PIXEL),
    (0,  50, 72, 2,  ORANGE),
]

# Master render: scale each design pixel by this factor, then
# center the 72x56 mark on a 1024x1024 canvas. Scale 13 puts the
# mark at 936x728, taking up ~91% of the icon width — comfortable
# for the macOS Big Sur+ icon style without crowding the edges.
MASTER = 1024
SCALE = 13
MARK_W = 72 * SCALE     # 936
MARK_H = 56 * SCALE     # 728
PAD_X = (MASTER - MARK_W) // 2   # 44
PAD_Y = (MASTER - MARK_H) // 2   # 148

# (filename, pixel-size) pairs that macOS's iconutil expects.
ICONSET_FILES: list[tuple[str, int]] = [
    ("icon_16x16.png",      16),
    ("icon_16x16@2x.png",   32),
    ("icon_32x32.png",      32),
    ("icon_32x32@2x.png",   64),
    ("icon_128x128.png",    128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png",    256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png",    512),
    ("icon_512x512@2x.png", 1024),
]


def render_master() -> Image.Image:
    img = Image.new("RGBA", (MASTER, MASTER), BG)
    draw = ImageDraw.Draw(img)
    for x, y, w, h, color in RECTS:
        x0 = PAD_X + x * SCALE
        y0 = PAD_Y + y * SCALE
        x1 = x0 + w * SCALE
        y1 = y0 + h * SCALE
        draw.rectangle([x0, y0, x1 - 1, y1 - 1], fill=color)
    return img


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    iconset = repo_root / "helper" / "Resources" / "AppIcon.iconset"
    iconset.mkdir(parents=True, exist_ok=True)

    master = render_master()
    for name, size in ICONSET_FILES:
        # Lanczos on the way down keeps the orange + dark-pixel
        # transitions clean at small sizes; at 16x16 the mark
        # becomes a recognisable orange creature without ringing
        # artefacts.
        out = master.resize((size, size), Image.Resampling.LANCZOS)
        out.save(iconset / name, format="PNG", optimize=True)
        print(f"  wrote {iconset / name}")
    print(f"==> 10 PNG files in {iconset}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
