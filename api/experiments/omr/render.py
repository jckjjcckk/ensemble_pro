"""Render MusicXML to PNG on the Mac: Verovio (one tall page per file) -> SVG -> PNG via resvg, then flattened
onto white (resvg leaves the background transparent, which turns black when a viewer drops the alpha).
Each file renders in a subprocess because Verovio segfaults on some input; a failure is reported, not fatal.

Usage: uv run --with verovio --with resvg-py python experiments/omr/render.py OUT_DIR file1.musicxml [file2 ...]
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

WORKER = r'''
import io, sys, verovio, resvg_py
from PIL import Image
src, svg_path, png_path = sys.argv[1:4]
tk = verovio.toolkit()
tk.setOptions({"pageHeight": 60000, "pageWidth": 2100, "adjustPageHeight": True, "scale": 40,
               "breaks": "auto", "footer": "none", "header": "none", "svgViewBox": True,
               "pageMarginLeft": 50, "pageMarginRight": 50, "pageMarginTop": 50, "pageMarginBottom": 50})
if not tk.loadFile(src):
    print("verovio could not load", src); sys.exit(2)
n = tk.getPageCount()
svg = tk.renderToSVG(1)
open(svg_path, "w").write(svg)
png = bytes(resvg_py.svg_to_bytes(svg_string=svg, width=1600))
im = Image.open(io.BytesIO(png)).convert("RGBA")
flat = Image.new("RGB", im.size, (255, 255, 255))
flat.paste(im, mask=im.getchannel("A"))
flat.save(png_path)
print(f"ok pages={n} {flat.size[0]}x{flat.size[1]}")
'''


def render(src: Path, out_dir: Path) -> tuple[bool, str]:
    svg, png = out_dir / f"{src.stem}.svg", out_dir / f"{src.stem}.png"
    try:
        r = subprocess.run([sys.executable, "-c", WORKER, str(src), str(svg), str(png)], capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return False, f"{src.name}: TIMEOUT"
    if r.returncode != 0:
        return False, f"{src.name}: FAILED rc={r.returncode} {r.stderr.strip()[-300:]} {r.stdout.strip()[-200:]}"
    return True, f"{src.name}: {r.stdout.strip()} -> {png.name}"


if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    for f in sys.argv[2:]:
        print(render(Path(f), out)[1])
