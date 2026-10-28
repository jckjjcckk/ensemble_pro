"""Write a self-contained HTML page that engraves a MusicXML with OpenSheetMusicDisplay the way the
iPad app's ScoreStage does (same constructor options, setPageFormat + zoom, SVG backend), one OSMD page
per printed page, 1024 CSS px wide. `osmd_render.sh` prints it to PDF with headless Chrome.

Usage: python osmd_page.py in.musicxml out.html [--osmd path/to/opensheetmusicdisplay.min.js]
       [--width 1024] [--aspect 1.414] [--zoom 1.0]

The MusicXML is inlined as a JS string (file:// pages cannot fetch). When OSMD is done the page sets
<body data-done="ms" data-pages="n"> (load + engrave time) or data-error, which `--dump-dom` can read.
"""
import argparse
import json
from pathlib import Path

DEFAULT_OSMD = "/Users/ckjiang/Documents/muse/web/node_modules/opensheetmusicdisplay/build/opensheetmusicdisplay.min.js"

p = argparse.ArgumentParser()
p.add_argument("src")
p.add_argument("out")
p.add_argument("--osmd", default=DEFAULT_OSMD)
p.add_argument("--width", type=int, default=1024)
p.add_argument("--aspect", type=float, default=1.414)
p.add_argument("--zoom", type=float, default=1.0)
a = p.parse_args()

xml = Path(a.src).read_text(encoding="utf-8")
h = round(a.width * a.aspect)
html = f"""<!doctype html><html><head><meta charset="utf-8">
<style>
@page {{ size: {a.width}px {h}px; margin: 0; }}
html, body {{ margin: 0; padding: 0; background: #fff; }}
#osmd {{ width: {a.width}px; }}
#osmd > div {{ width: {a.width}px; height: {h}px; overflow: hidden; break-after: page; }}
#osmd svg {{ width: {a.width}px !important; height: {h}px !important; }}
</style>
<script src="file://{a.osmd}"></script></head>
<body><div id="osmd"></div>
<script>
const xml = {json.dumps(xml)};
const t0 = performance.now();
// Same constructor options as web/src/app/ScoreStage.tsx
const osmd = new opensheetmusicdisplay.OpenSheetMusicDisplay(document.getElementById('osmd'), {{
  autoResize: false, backend: 'svg', drawTitle: false, drawComposer: false, drawSubtitle: false,
  drawLyricist: false, drawPartNames: true, drawMeasureNumbers: true, pageFormat: 'A4_P',
}});
osmd.load(xml).then(() => {{
  osmd.setPageFormat('1000x{round(1000 * a.aspect)}');
  osmd.zoom = {a.zoom};
  osmd.render();
  document.body.dataset.done = String(Math.round(performance.now() - t0));
  document.body.dataset.pages = String(document.querySelectorAll('#osmd svg').length);
}}).catch(e => {{ document.body.dataset.error = String(e); }});
</script></body></html>"""
Path(a.out).write_text(html, encoding="utf-8")
print(a.out, len(html))
