# /// script
# requires-python = ">=3.12"
# dependencies = ["pillow"]
# ///
"""Before/after sheet of the Beethoven 9 choir cuts (feature 008, the three choir defects).

One row per voice and page: the crop of the earlier run on the left (any RGBA flattened onto white, halved when
it came from the 2x render), the crop of the current run on the right, the geometry and clean stats under each.
The "before" crops are read from a snapshot folder (an earlier copy of the run folders), the "after" ones from
the live run folders.

Usage (from api/):  uv run experiments/grounding/choir_sheet.py <before-snapshot-dir> [--score <stem>] [voices...]
Writes out/piano-cut/<stem>/choir-before-after.html (data URIs, self-contained).
"""

from __future__ import annotations

import base64
import html
import io
import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import PIANO_CUT_OUT, PIANO_CUT_TITLE, instrument_slug  # noqa: E402


def flatten(im: Image.Image) -> Image.Image:
    """Any RGBA (or palette with transparency) onto white."""
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        bg.alpha_composite(im)
        return bg.convert("RGB")
    return im.convert("RGB")


def data_uri(im: Image.Image, max_w: int = 1400, quality: int = 85) -> str:
    im = flatten(im)
    if im.width > max_w:
        im = im.resize((max_w, int(im.height * max_w / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=quality, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def crops_of(results: list[dict], page: int) -> list[dict]:
    for pg in results:
        if pg["page"] == page:
            return [s for s in pg["systems"] if s.get("crop")]
    return []


def describe(rec: dict) -> str:
    v = rec.get("verify") or {}
    c = rec.get("clean") or {}
    bits = [f"staves {rec.get('wanted_staves')}", f"{rec.get('n_measures')} bars", f"status {rec.get('status')}"]
    if v:
        failed = [k for k, x in v.items() if isinstance(x, dict) and not x.get("informational") and not x.get("pass")]
        bits.append("verify " + ("pass" if not failed else f"FAIL {failed}"))
        rc = v.get("spark_recheck") or {}
        if rc:
            bits.append(f"recheck '{rc.get('instrument')}'")
    if c:
        bits.append(f"erased {c.get('erased')} kept {c.get('kept')}")
        if c.get("voice") is not None:
            bits.append(f"voice {c.get('voice')} / above {c.get('voice_above')}")
        ll = c.get("lyric_lines") or []
        if ll:
            bits.append("lyric lines " + ", ".join(f"{l['class']}({l['words']}w)" for l in ll))
        if c.get("lyric_pieces"):
            bits.append(f"{len(c['lyric_pieces'])} glued word piece(s) kept")
    return "; ".join(bits)


def main(before_dir: Path, voices: list[str]) -> None:
    after_base = PIANO_CUT_OUT
    before_geom = {p: json.loads((before_dir / f"geom-p{p}.json").read_text()) for p in range(172, 177) if (before_dir / f"geom-p{p}.json").exists()}
    after_geom = {p: json.loads((after_base / f"geom-p{p:02d}.json").read_text()) for p in range(172, 177) if (after_base / f"geom-p{p:02d}.json").exists()}
    hb = json.loads((before_dir / "header.json").read_text()) if (before_dir / "header.json").exists() else {}
    ha = json.loads((after_base / "header.json").read_text()) if (after_base / "header.json").exists() else {}
    parts = [f"<html><head><meta charset='utf-8'><title>Choir cuts before/after: {html.escape(PIANO_CUT_TITLE)}</title>",
             "<style>body{font-family:-apple-system,Helvetica,sans-serif;margin:20px;background:#fafaf7}img{max-width:100%;border:1px solid #ccc;background:#fff}"
             "td{vertical-align:top;padding:6px 10px}th{text-align:left;padding:6px 10px;background:#eee}.stats{font:12px/1.4 monospace;color:#333;white-space:pre-wrap}"
             "h2{margin-top:36px}.geo{font:13px/1.5 monospace}</style></head><body>",
             f"<h1>Choir cuts before / after: {html.escape(PIANO_CUT_TITLE)}, pages 172 to 176</h1>",
             "<p>Before: the run at 150 dpi (page upscaled 2.08x, shadows in, header 18) halved for display. After: native resolution "
             "(1513x1920), page-edge shadows masked, header 16, hole-filling staff recovery, lyric text-line rule.</p>",
             f"<p class='geo'>Header before: expected_staves {hb.get('expected_staves')} ({hb.get('validation')}); after: expected_staves {ha.get('expected_staves')} ({ha.get('validation')})</p>",
             "<h2>Geometry per page</h2><table><tr><th>page</th><th>before</th><th>after</th></tr>"]
    for p in range(172, 177):
        gb, ga = before_geom.get(p, {}), after_geom.get(p, {})

        def geo(g: dict) -> str:
            if not g:
                return "-"
            sh = g.get("prepare", {}).get("edge_shadows", {})
            shadows = [k for k, e in sh.items() if e.get("shadow")]
            return (f"{g.get('image_px')} skew {g.get('skew_deg')} staves {len(g.get('staves', []))} before recovery {g.get('staves_before_recovery')} "
                    f"recovered {[(r['index'], r['fit']) for r in g.get('recovered', [])]} systems {[(len(s['staff_indices']), s['n_measures']) for s in g.get('systems', [])]}"
                    + (f" shadows masked {shadows}" if shadows else "") + (f" scale x{g['prepare']['scale']}" if g.get("prepare", {}).get("scale", 1) > 1 else ""))
        parts.append(f"<tr><td>{p}</td><td class='geo'>{html.escape(geo(gb))}</td><td class='geo'>{html.escape(geo(ga))}</td></tr>")
    parts.append("</table>")
    for voice in voices:
        slug = instrument_slug(voice)
        rb = json.loads((before_dir / slug / "results.json").read_text()) if (before_dir / slug / "results.json").exists() else []
        ra = json.loads((after_base / slug / "results.json").read_text()) if (after_base / slug / "results.json").exists() else []
        parts.append(f"<h2>{html.escape(voice)}</h2>")
        for p in range(172, 177):
            cb, ca = crops_of(rb, p), crops_of(ra, p)
            parts.append(f"<h3>Page {p}</h3><table><tr><th>before</th><th>after</th></tr><tr>")
            for recs, base, halve in ((cb, before_dir / slug, True), (ca, after_base / slug, False)):
                parts.append("<td>")
                if not recs:
                    parts.append("<i>no crop (absent)</i>")
                for rec in recs:
                    im = Image.open(base / rec["crop"])
                    if halve and im.width > 2000:
                        im = flatten(im).resize((im.width // 2, im.height // 2), Image.LANCZOS)
                    parts.append(f"<img src='{data_uri(im)}' alt='{html.escape(rec['crop'])}'>")
                    parts.append(f"<div class='stats'>{html.escape(rec['crop'])}: {html.escape(describe(rec))}</div>")
                parts.append("</td>")
            parts.append("</tr></table>")
    parts.append("</body></html>")
    out = after_base / "choir-before-after.html"
    out.write_text("\n".join(parts))
    print(out, f"{out.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    before = Path(args[0]).expanduser().resolve()
    main(before, args[1:] or ["Soprano", "Alto", "Tenor"])
