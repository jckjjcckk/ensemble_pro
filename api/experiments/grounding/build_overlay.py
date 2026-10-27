# /// script
# requires-python = ">=3.12"
# dependencies = ["pillow"]
# ///
"""Static HTML page with one tappable overlay per measure, plus a PNG render.

Usage (from api/):  uv run experiments/grounding/build_overlay.py out/spark-goldberg-bga-p01.json [more.json ...]
Input JSON must have: page (name), measures: [{number, box:{x0,y0,x1,y1}, uncertain?, system?}], optional systems.
Writes out/<stem>.html and out/<stem>.png next to the input.
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from common import PAGES

TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  body {{ margin: 0; font: 15px/1.4 -apple-system, system-ui, sans-serif; background: #f3f1ec; color: #222; }}
  header {{ padding: 10px 16px; display: flex; gap: 16px; align-items: baseline; }}
  header b {{ font-size: 18px; }}
  #sel {{ font-variant-numeric: tabular-nums; }}
  .page {{ position: relative; margin: 0 auto; max-width: 1000px; }}
  .page img {{ display: block; width: 100%; height: auto; }}
  .m {{ position: absolute; box-sizing: border-box; border: 2px solid rgba(0,110,220,.55); background: rgba(0,110,220,.07); cursor: pointer; }}
  .m.unc {{ border-color: rgba(220,120,0,.8); background: rgba(220,120,0,.10); }}
  .m:hover {{ background: rgba(0,110,220,.18); }}
  .m.on {{ border-color: #d2232a; background: rgba(210,35,42,.22); z-index: 2; }}
  .m span {{ position: absolute; left: 2px; top: 2px; font-size: 12px; font-weight: 600; padding: 0 4px; background: rgba(255,255,255,.85); border-radius: 3px; color: #0a4; }}
  .m.unc span {{ color: #b60; }}
  .m.on span {{ color: #d2232a; }}
  .sys {{ position: absolute; box-sizing: border-box; border: 1px dashed rgba(0,0,0,.35); pointer-events: none; }}
</style></head>
<body>
<header><b>{title}</b><span>{n} measures ({engine})</span><span id="sel">tap a measure</span></header>
<div class="page">
  <img src="{img}" alt="{title}">
{systems}
{measures}
</div>
<script>
  const sel = document.getElementById('sel');
  document.querySelectorAll('.m').forEach(el => el.addEventListener('click', () => {{
    document.querySelectorAll('.m.on').forEach(o => o.classList.remove('on'));
    el.classList.add('on');
    sel.textContent = 'selected measure ' + el.dataset.n + (el.classList.contains('unc') ? ' (flagged uncertain)' : '');
  }}));
</script>
</body></html>
"""


def pct(v, total):
    return f"{100.0 * v / total:.3f}%"


def build(json_path: Path):
    data = json.loads(json_path.read_text())
    page = data["page"]
    png = PAGES / f"{page}.png"
    with Image.open(png) as im:
        w, h = im.size
    measures = data.get("measures", [])
    engine = data.get("engine") or data.get("model") or "?"
    divs = []
    for m in measures:
        b = m["box"]
        cls = "m unc" if m.get("uncertain") else "m"
        style = f"left:{pct(b['x0'], w)};top:{pct(b['y0'], h)};width:{pct(b['x1'] - b['x0'], w)};height:{pct(b['y1'] - b['y0'], h)}"
        divs.append(f'  <div class="{cls}" data-n="{m["number"]}" style="{style}"><span>{m["number"]}</span></div>')
    sysdivs = []
    for s in data.get("systems", []):
        b = s["box"]
        style = f"left:{pct(b['x0'], w)};top:{pct(b['y0'], h)};width:{pct(b['x1'] - b['x0'], w)};height:{pct(b['y1'] - b['y0'], h)}"
        sysdivs.append(f'  <div class="sys" style="{style}"></div>')
    out_html = json_path.with_suffix(".html")
    rel_img = Path("..") / "pages" / png.name
    out_html.write_text(TEMPLATE.format(title=html.escape(json_path.stem), n=len(measures), engine=html.escape(str(engine)),
                                        img=rel_img.as_posix(), systems="\n".join(sysdivs), measures="\n".join(divs)))

    # PNG render for the README
    im = Image.open(png).convert("RGBA")
    ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 26)
    except Exception:
        font = ImageFont.load_default()
    for s in data.get("systems", []):
        b = s["box"]
        d.rectangle([b["x0"], b["y0"], b["x1"], b["y1"]], outline=(0, 0, 0, 90), width=1)
    for m in measures:
        b = m["box"]
        col = (220, 120, 0) if m.get("uncertain") else (0, 110, 220)
        d.rectangle([b["x0"], b["y0"], b["x1"], b["y1"]], outline=col + (200,), width=3, fill=col + (20,))
        d.rectangle([b["x0"] + 3, b["y0"] + 3, b["x0"] + 46, b["y0"] + 32], fill=(255, 255, 255, 220))
        d.text((b["x0"] + 6, b["y0"] + 3), str(m["number"]), fill=col + (255,), font=font)
    Image.alpha_composite(im, ov).convert("RGB").save(json_path.with_suffix(".png"))
    print(out_html.name, json_path.with_suffix(".png").name, len(measures), "measures")


if __name__ == "__main__":
    for p in sys.argv[1:]:
        build(Path(p))
