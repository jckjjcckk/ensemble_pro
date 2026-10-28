"""review.html: per scan page, the scan (left) and the rendered result (right) as data URIs flattened onto
white, the flagged bars with reasons, the text Spark wrote and where, ornaments and symbol verdicts, plus the
run summary on top. Self-contained, no external assets.

Usage: uv run python experiments/omr/build_review.py RUN_DIR   (reads run.json, flags.json; writes review.html)
"""

from __future__ import annotations

import base64
import html
import io
import json
import sys
from pathlib import Path

from PIL import Image


def data_uri(path: Path | None, max_w: int = 1400, fmt: str = "JPEG") -> str | None:
    if not path or not path.exists():
        return None
    im = Image.open(path)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        flat = Image.new("RGB", im.size, (255, 255, 255))
        flat.paste(im, mask=im.getchannel("A"))
        im = flat
    else:
        im = im.convert("RGB")
    if im.width > max_w:
        im = im.resize((max_w, int(im.height * max_w / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format=fmt, quality=82)
    mime = "image/jpeg" if fmt == "JPEG" else "image/png"
    return f"data:{mime};base64,{base64.b64encode(buf.getvalue()).decode()}"


CSS = """
:root{--bg:#fafafa;--fg:#1a1a1a;--muted:#666;--line:#ddd;--head:#f0f0f0;--err:#b00020}
body{font:14px/1.45 -apple-system,Helvetica,Arial,sans-serif;margin:24px;color:var(--fg);background:var(--bg)}
h1{font-size:20px} h2{font-size:17px;margin:36px 0 8px;border-top:2px solid var(--line);padding-top:16px}
h3{font-size:15px;margin:18px 0 6px}
.row{display:grid;grid-template-columns:1fr 1fr;gap:16px;align-items:start}
.row img{width:100%;border:1px solid #ccc;background:#fff}
.cap{font-size:12px;color:var(--muted);margin:4px 0 10px}
table{border-collapse:collapse;margin:8px 0} td,th{border:1px solid var(--line);padding:4px 8px;text-align:left;vertical-align:top}
th{background:var(--head)} .flag td:first-child{font-weight:600;white-space:nowrap}
.muted{color:var(--muted)} code{background:#eee;padding:1px 4px;border-radius:3px} .err{color:var(--err);font-weight:600}
@media (max-width:800px){.row{grid-template-columns:1fr} body{margin:16px}}
"""


def table(rows: list[tuple], head: tuple) -> str:
    return ("<table><tr>" + "".join(f"<th>{html.escape(h)}</th>" for h in head) + "</tr>" +
            "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows) + "</table>")


def main() -> None:
    run = Path(sys.argv[1])
    meta = json.load(open(run / "run.json"))
    pages = json.load(open(run / "flags.json"))
    parts = [f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
             f"<title>{html.escape(meta['title'])}</title><style>{CSS}</style></head><body>",
             f"<h1>{html.escape(meta['title'])}</h1>",
             "<p class='muted'>Left: the scan. Right: the final MusicXML rendered by Verovio (layout differs from the engraving "
             "by design; compare notes, rhythms, dynamics, ornaments). Bars carry the global number of the page set "
             "(feature 004 numbering). Spark never wrote a note: it answered closed questions about Audiveris's "
             "low-grade symbols (A) and re-read the words, dynamics and ornaments per system (B); each word is placed by "
             "its position on the page. Flags are Audiveris's own <code>abnormal</code> bars plus a durations-add-up check "
             "on the final file.</p>"]
    s = meta["summary"]
    parts.append("<h2>Run</h2>" + table([(html.escape(k), html.escape(str(v))) for k, v in s.items()], ("", "")))
    for p in pages:
        info = meta["pages"].get(str(p["page"]), {})
        parts.append(f"<h2>Page {p['page']} (PDF page {p['pdf_page']}): bars {p['first']} to {p['last']} ({p['bars']}), "
                     f"{html.escape(info.get('content', ''))}</h2>")
        scan = data_uri(run / "scan" / f"page300-{p['pdf_page']:02d}.png")
        rend = data_uri(run / "render" / f"final-p{p['page']}.png", fmt="PNG")
        parts.append(f"<div class='row'><div><img src='{scan}' alt='scan page {p['page']}'><div class='cap'>Scan</div></div><div>")
        if rend:
            parts.append(f"<img src='{rend}' alt='render page {p['page']}'><div class='cap'>Rendered result (Verovio)</div>")
        else:
            parts.append(f"<p class='err'>Rendering failed: {html.escape(info.get('render_error', 'unknown'))}</p>")
        parts.append("</div></div>")
        parts.append(f"<h3>Flagged bars ({len(p['flags'])})</h3>")
        parts.append(table([(html.escape(b), "<br>".join(html.escape(w) for w in ws)) for b, ws in p["flags"].items()], ("Bar", "Why"))
                     if p["flags"] else "<p class='muted'>none</p>")
        ta = p["text_added"]
        parts.append(f"<h3>Text and dynamics written by Spark ({sum(len(v) for v in ta.values())} items in {len(ta)} bars)</h3>")
        if ta:
            parts.append(table([(html.escape(b), html.escape("; ".join(v))) for b, v in ta.items()], ("Bar", "Items (staff, how placed)")))
        parts.append(f"<h3>Ornaments written ({len(p['ornaments_added'])}), skipped as ambiguous ({len(p['ornaments_skipped'])})</h3>")
        if p["ornaments_added"]:
            parts.append("<ul>" + "".join(f"<li>{html.escape(x)}</li>" for x in p["ornaments_added"]) + "</ul>")
        parts.append(f"<h3>Symbol verdicts applied ({len(p['symbol_edits'])})</h3>")
        if p["symbol_edits"]:
            parts.append("<ul>" + "".join(f"<li>{html.escape(x)}</li>" for x in p["symbol_edits"]) + "</ul>")
        if info.get("notes"):
            parts.append("<h3>Notes</h3><ul>" + "".join(f"<li>{html.escape(x)}</li>" for x in info["notes"]) + "</ul>")
    parts.append("</body></html>")
    out = run / "review.html"
    out.write_text("".join(parts))
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
