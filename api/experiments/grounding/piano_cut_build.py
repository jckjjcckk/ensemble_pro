# /// script
# requires-python = ">=3.12"
# dependencies = ["opencv-python-headless", "numpy", "pillow"]
# ///
"""Piano-cut experiment, step 3: cut the labelled staves out, verify the cut, build the HTML.

For every system where Spark named the wanted staves, crop them as one block (padding above for tempo and
dynamics, the left margin for the label, clipped to the neighbouring staves), stack the blocks into one part
page per source page, and one tall strip for the whole run. A page where the instrument is absent or resting
gets a "tacet" placeholder.

The cut itself is piano_cut_clean.clean_crop (a wide band with the neighbours' ink erased, fitted to the
piano's own ink) unless run with --no-clean, which keeps the plain fixed-margin crop (crop_box) for comparison.
With cleaning on, clean-compare.html shows the plain crop above the cleaned one for every system.

Verify (no model): on the crop, geometry must find exactly the instrument's staff count (header.json, else
the number Spark named), a brace or bracket at the left of a multi-staff block (informational, skipped for a
single staff), and every system barline (x positions from geom-p<NN>.json) as a vertical dark run through the
block within +-4 px. The bar count is inherited from the system, not re-detected: re-detection inside a dense piano
system found beams and aligned stems as extra barlines (p. 3 s1, p. 4 s1 and s2) and failed honest cuts.
If recheck-p<NN>-s<k>.json exists in the run folder (piano_cut_recheck.py: Spark looks at the crop alone and
names the instrument) it is the fourth check. Reads geometry from the score folder, labels from the run folder
(common.PIANO_CUT_RUN), writes everything else to the run folder. edge_ink_top / edge_ink_bottom (clean mode) flag kept ink on the
crop's first or last row: the band itself clipped it, so something is still cut; informational, not a fail.

Usage (from api/):  uv run experiments/grounding/piano_cut_build.py [--score <pdf stem>] [--instrument "..."] [--no-clean] [page ...]
Writes crop-p<NN>-s<k>.png, clean-debug-p<NN>-s<k>.png, highlight-p<NN>.png, part-p<NN>.png, strip.png,
results.json, piano-cut.html, clean-compare.html
"""

from __future__ import annotations

import argparse
import base64
import html
import io
import json

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from common import PIANO_CUT_INSTRUMENT, PIANO_CUT_RUN, PIANO_CUT_TITLE
from fallback_cv import binarise, rotate, vertical_cover
from piano_cut_clean import clean_crop
from piano_cut_geometry import PC, PAGES_DIR, DEFAULT_PAGES
from piano_cut_label import instrument_staves, is_voice

RUN = PIANO_CUT_RUN
INSTRUMENT = PIANO_CUT_INSTRUMENT
TEXT_MODE = "overlap"  # text-line grouping for the lyric rule (piano_cut_clean.text_lines); --text-mode baseline to compare


def voice_flags(geom: dict, system: dict, ans: dict, wanted: list[int], instrument: str) -> tuple[bool, bool]:
    """(target is a vocal staff, the staff above the target is a vocal staff), from the header's families through
    the names Spark gave the staves on this page (by score order when the system is full and a staff is unnamed)."""
    idxs = system["staff_indices"]
    names = {int(s.get("n")): s.get("instrument") for s in (ans.get("staves") or []) if isinstance(s, dict) and s.get("n") is not None}
    pos = idxs.index(min(wanted)) if min(wanted) in idxs else 0
    voice = is_voice(instrument, pos + 1, len(idxs))
    above = None
    if pos > 0:
        above = idxs[pos - 1]
    else:
        prev_sys = next((s for s in geom["systems"] if s["index"] == system["index"] - 1), None)
        if prev_sys:
            above = prev_sys["staff_indices"][-1]
    if above is None:
        return voice, False
    voice_above = is_voice(names.get(above), idxs.index(above) + 1 if above in idxs else None, len(idxs))
    return voice, voice_above


def font(size: int):
    try:
        return ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size)
    except Exception:
        return ImageFont.load_default()


def crop_box(geom: dict, system: dict, wanted: list[int]) -> dict:
    """Pixel box for the wanted staves inside this system, clipped to the neighbouring staves."""
    staves = {s["index"]: s for s in geom["staves"]}
    w, h = geom["image_px"]
    ss = [staves[i] for i in sorted(wanted)]
    sp = float(np.median([s["spacing"] for s in ss]))
    idxs = system["staff_indices"]
    prev = staves[idxs[idxs.index(ss[0]["index"]) - 1]] if idxs.index(ss[0]["index"]) > 0 else None
    nxt_pos = idxs.index(ss[-1]["index"]) + 1
    nxt = staves[idxs[nxt_pos]] if nxt_pos < len(idxs) else None
    y0 = ss[0]["y_top"] - 6 * sp
    if prev:
        y0 = max(y0, prev["y_bottom"] + 1.5 * sp)
    else:
        y0 = min(y0, system["box"]["y0"] - 4 * sp)  # top of the system: bar numbers / rehearsal figures
    y1 = ss[-1]["y_bottom"] + 6 * sp
    if nxt:
        y1 = min(y1, nxt["y_top"] - 1.5 * sp)
    return {"x0": 0, "y0": int(max(0, y0)), "x1": int(min(w - 1, system["box"]["x1"] + 2 * sp)), "y1": int(min(h - 1, y1))}


def verify(crop: Image.Image, geom: dict, system: dict, wanted: list[int], box: dict, expect_staves: int | None = None) -> dict:
    """Geometric checks on the crop as shipped (its own binarisation, so erased ink is really gone)."""
    staves = {s["index"]: s for s in geom["staves"]}
    inside = [s for s in geom["staves"] if s["y_top"] >= box["y0"] and s["y_bottom"] <= box["y1"]]
    ss = [staves[i] for i in sorted(wanted)]
    a, b = ss[0], ss[-1]
    sp = float(np.median([s["spacing"] for s in ss]))
    cbw = binarise(np.array(crop.convert("L")))
    oy, ox = box["y0"], box["x0"]
    ya, yb = a["y_top"] - oy, b["y_bottom"] - oy
    x_left = int(min(s["x0"] for s in ss)) - ox
    expect = expect_staves or len(wanted)
    # brace or bracket (multi-staff blocks only): a vertical dark run left of the staves spanning them all
    if expect >= 2:
        brace_cols = [x for x in range(max(0, x_left - int(5 * sp)), x_left - 1)
                      if vertical_cover(cbw, x, ya, yb, tol=2) >= 0.9]
        brace = {"value": bool(brace_cols), "pass": bool(brace_cols), "informational": True}
    else:
        brace = {"value": None, "pass": True, "informational": True, "note": "single staff: not checked"}
    # every system barline must cross the block (a piano's barlines run through the gap between its staves)
    tol = 4
    present = []
    for bx0, bx1 in system["barlines"]:
        cols = range(max(0, bx0 - tol - ox), min(cbw.shape[1], bx1 + tol + 1 - ox))
        present.append(any(vertical_cover(cbw, x, ya, yb, tol=1) >= 0.9 for x in cols))
    checks = {
        "staves_in_crop": {"value": len(inside), "expect": expect, "pass": len(inside) == expect},
        "brace_or_bracket": brace,
        "barlines_present": {"system_x": system["barlines"], "present": present,
                             "missing": [bl for bl, ok in zip(system["barlines"], present) if not ok],
                             "pass": all(present)},
        "bar_count": {"value": system["n_measures"], "source": "system geometry; crop re-detection dropped "
                      "(beams and aligned stems in dense piano systems faked extra barlines)", "pass": True,
                      "informational": True},
    }
    return checks


def tacet_image(w: int, text: str) -> Image.Image:
    warn = "NEEDS REVIEW" in text
    im = Image.new("RGB", (w, 160), (253, 236, 236) if warn else (250, 248, 242))
    d = ImageDraw.Draw(im)
    d.rectangle([8, 8, w - 9, 151], outline=(180, 40, 40) if warn else (150, 140, 120), width=3 if warn else 2)
    d.text((28, 56), text, fill=(150, 30, 30) if warn else (90, 80, 60), font=font(30 if warn else 34))
    return im


def jpeg_data_uri(im: Image.Image, max_w: int, quality: int = 82) -> str:
    if im.width > max_w:
        im = im.resize((max_w, int(im.height * max_w / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.convert("RGB").save(buf, format="JPEG", quality=quality, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def build_page(n: int, clean: bool = True) -> dict:
    geom = json.loads((PC / f"geom-p{n:02d}.json").read_text())
    label = json.loads((RUN / f"label-p{n:02d}.json").read_text())
    instrument = label.get("instrument") or INSTRUMENT
    expect_staves = instrument_staves(instrument)
    page_im = Image.open(PAGES_DIR / f"p{n:02d}.png").convert("RGB")
    w, h = page_im.size
    gray = cv2.imread(str(PAGES_DIR / f"p{n:02d}.png"), cv2.IMREAD_GRAYSCALE)
    bw = binarise(gray)
    if abs(geom["skew_deg"]) >= 0.1:
        bw = rotate(bw, geom["skew_deg"], 0)
    deskewed = Image.fromarray(rotate(gray, geom["skew_deg"], 255)) if abs(geom["skew_deg"]) >= 0.1 else page_im
    deskewed = deskewed.convert("RGB")

    parsed = label.get("parsed") or {}
    by_index = {s.get("index"): s for s in parsed.get("systems", [])}
    highlight = deskewed.copy()
    hd = ImageDraw.Draw(highlight, "RGBA")
    blocks: list[Image.Image] = []
    compare: list[dict] = []
    systems_out = []
    for system in geom["systems"]:
        ans = by_index.get(system["index"], {})
        wanted = [i for i in (ans.get("wanted_staves") or []) if i in system["staff_indices"]]
        status = ans.get("status") or ("absent" if not wanted else "playing")
        rec = {"system": system["index"], "wanted_staves": wanted, "status": status, "n_measures": system["n_measures"]}
        recheck_path = RUN / f"recheck-p{n:02d}-s{system['index']}.json"
        if wanted:
            plain_box = crop_box(geom, system, wanted)
            plain = deskewed.crop((plain_box["x0"], plain_box["y0"], plain_box["x1"] + 1, plain_box["y1"] + 1))
            if clean:
                voice, voice_above = voice_flags(geom, system, ans, wanted, instrument)
                crop, box, cstats, dbg = clean_crop(bw, deskewed, geom, system, wanted, debug=True, voice=voice,
                                                    voice_above=voice_above, text_mode=TEXT_MODE)
                dbg.save(RUN / f"clean-debug-p{n:02d}-s{system['index']}.png")
                cstats.pop("detail", None)
                rec["clean"] = cstats
                rec["crop_box_plain"] = plain_box
                compare.append({"system": system["index"], "plain": plain, "clean": crop, "debug": dbg, "stats": cstats})
            else:
                crop, box = plain, plain_box
            rec["crop_box"] = box
            crop_path = RUN / f"crop-p{n:02d}-s{system['index']}.png"
            crop.save(crop_path)
            rec["crop"] = crop_path.name
            rec["verify"] = verify(crop, geom, system, wanted, box, expect_staves)
            if clean:
                rec["verify"]["edge_ink"] = {"top": cstats["edge_ink_top"], "bottom": cstats["edge_ink_bottom"],
                                             "cols": cstats["edge_ink_cols"], "erased": cstats["erased"], "kept": cstats["kept"],
                                             "pass": not (cstats["edge_ink_top"] or cstats["edge_ink_bottom"]),
                                             "informational": True}
            if recheck_path.exists():
                rc = json.loads(recheck_path.read_text())
                rp = rc.get("parsed") or {}
                said = rp.get("instrument") or ""
                is_wanted = rp.get("is_wanted", rp.get("is_piano"))  # older recheck files say is_piano
                rec["verify"]["spark_recheck"] = {"instrument": said, "is_wanted": is_wanted,
                                                  "cost_usd": rc.get("cost_usd"), "latency_s": rc.get("latency_s"),
                                                  "pass": bool(is_wanted)}
            rec["verify"]["pass"] = all(c["pass"] for k, c in rec["verify"].items()
                                        if isinstance(c, dict) and not c.get("informational"))
            hd.rectangle([box["x0"], box["y0"], box["x1"], box["y1"]], fill=(255, 170, 0, 70), outline=(230, 120, 0, 255), width=4)
            if status == "resting":
                blocks.append(tacet_image(crop.width, f"p. {n}, system {system['index']}: {instrument} rests (staves printed, rests only)"))
            if not rec["verify"]["pass"]:
                # the loop's outcome: a cut that fails verification is shipped flagged, never silently
                failed = [k for k, c in rec["verify"].items() if isinstance(c, dict) and not c.get("informational") and not c["pass"]]
                said = rec["verify"].get("spark_recheck", {}).get("instrument")
                rec["status"] = "needs_review"
                blocks.append(tacet_image(crop.width, f"p. {n}, system {system['index']}: NEEDS REVIEW, failed {failed}"
                                          + (f" (crop re-read as '{said}')" if said else "")))
            blocks.append(crop)
        else:
            blocks.append(tacet_image(w, f"p. {n}, system {system['index']}: {instrument} tacet (staves not printed)"))
        systems_out.append(rec)
    highlight_path = RUN / f"highlight-p{n:02d}.png"
    highlight.save(highlight_path)
    # part page: the blocks stacked
    gap = 24
    pw = max(b.width for b in blocks)
    ph = sum(b.height for b in blocks) + gap * (len(blocks) + 1)
    part = Image.new("RGB", (pw, ph), (255, 255, 255))
    y = gap
    for b in blocks:
        part.paste(b, (0, y))
        y += b.height + gap
    part_path = RUN / f"part-p{n:02d}.png"
    part.save(part_path)
    return {"page": n, "image_px": [w, h], "skew_deg": geom["skew_deg"], "n_staves": len(geom["staves"]),
            "grouping": geom["grouping"], "spark": {"latency_s": label["latency_s"], "cost_usd": label["cost_usd"],
            "page_status": parsed.get("page_status"), "confidence": parsed.get("confidence"),
            "json_repaired": label.get("json_repaired"), "parse_error": label.get("parse_error")},
            "instrument": instrument, "expect_staves": expect_staves,
            "systems": systems_out, "highlight": highlight_path.name, "part": part_path.name, "blocks": blocks,
            "label_parsed": parsed, "compare": compare, "clean": clean}


def build_html(results: list[dict]) -> None:
    css = """
    body{font:15px/1.45 -apple-system,Helvetica,Arial,sans-serif;margin:0;padding:24px;background:#f4f1ea;color:#222}
    h1{font-size:22px;margin:0 0 4px} h2{font-size:18px;margin:36px 0 8px} .sub{color:#666;margin-bottom:20px}
    .page{display:grid;grid-template-columns:1fr 1fr;gap:20px;align-items:start}
    .page img{width:100%;height:auto;border:1px solid #cbc3b4;background:#fff}
    .crops img{margin-bottom:12px} pre{background:#fff;border:1px solid #ddd;padding:10px;font-size:12px;overflow:auto;max-height:340px}
    .pass{color:#1a7f37;font-weight:600} .fail{color:#b42318;font-weight:600} .info{color:#666} .warn{color:#b35c00;font-weight:600}
    table{border-collapse:collapse;font-size:13px;background:#fff} td,th{border:1px solid #d6d0c4;padding:4px 8px;text-align:left}
    """
    instrument = results[0]["instrument"] if results else INSTRUMENT
    parts = [f"<!doctype html><meta charset='utf-8'><title>Part cut: {html.escape(instrument)}, {html.escape(PIANO_CUT_TITLE)}</title><style>{css}</style>",
             f"<h1>Part cut, no OMR: “{html.escape(instrument)}” from the {html.escape(PIANO_CUT_TITLE)} full score</h1>",
             f"<div class='sub'>Left: source page (deskewed) with the staves Spark named as “{html.escape(instrument)}” highlighted. "
             "Right: the cut, then Spark's answer and the verify result. OpenCV finds staves, systems and barlines; "
             "Muse Spark 1.3 (effort low) names the staves on a numbered overlay; the verify step re-measures the crop. "
             + ("Cut: wide band, neighbours' ink erased, fitted to the instrument's own ink (piano_cut_clean.py; see clean-compare.html)."
                if results and results[0].get("clean") else "Cut: plain fixed-margin crop (--no-clean).") + "</div>"]
    total_cost = sum(r["spark"]["cost_usd"] for r in results)
    parts.append(f"<table><tr><th>page</th><th>staves</th><th>systems (bars)</th><th>Spark: {html.escape(instrument)} staves per system</th>"
                 "<th>status</th><th>latency</th><th>cost</th><th>verify</th></tr>")
    for r in results:
        sysdesc = ", ".join(f"{s['system']}: {s['wanted_staves'] or '—'} ({s['status']})" for s in r["systems"])
        ver = "; ".join(("pass" if s.get("verify", {}).get("pass") else ("fail" if s.get("verify") else "n/a"))
                        for s in r["systems"])
        parts.append(f"<tr><td>{r['page']}</td><td>{r['n_staves']}</td>"
                     f"<td>{', '.join(str(s['n_measures']) for s in r['systems'])}</td><td>{html.escape(sysdesc)}</td>"
                     f"<td>{r['spark']['page_status']}</td><td>{r['spark']['latency_s']} s</td><td>${r['spark']['cost_usd']:.4f}</td><td>{ver}</td></tr>")
    parts.append(f"<tr><td colspan='6'>total Spark cost (labelling)</td><td>${total_cost:.4f}</td><td></td></tr></table>")
    for r in results:
        n = r["page"]
        parts.append(f"<h2>Page {n}</h2><div class='page'>")
        parts.append(f"<div><img src='{jpeg_data_uri(Image.open(RUN / r['highlight']), 900)}' alt='page {n}'></div>")
        parts.append("<div class='crops'>")
        for b in r["blocks"]:
            parts.append(f"<img src='{jpeg_data_uri(b, 1100)}' alt='cut'>")
        ans = dict(r["label_parsed"])
        parts.append("<div><b>Spark answer</b> (" + ("JSON repaired" if r["spark"]["json_repaired"] else "JSON as returned") + ")</div>")
        parts.append(f"<pre>{html.escape(json.dumps(ans, indent=1, ensure_ascii=False))}</pre>")
        for s in r["systems"]:
            v = s.get("verify")
            if not v:
                parts.append(f"<div class='info'>system {s['system']}: no crop ({s['status']})</div>")
                continue
            lines = [f"<div>system {s['system']} verify: <span class='{'pass' if v['pass'] else 'fail'}'>{'PASS' if v['pass'] else 'FAIL'}</span></div><ul>"]
            for k, c in v.items():
                if not isinstance(c, dict):
                    continue
                cls = ("info" if c["pass"] else "warn") if c.get("informational") else ("pass" if c["pass"] else "fail")
                detail = {kk: vv for kk, vv in c.items() if kk not in ("pass", "informational")}
                lines.append(f"<li><span class='{cls}'>{k}</span>: {html.escape(json.dumps(detail))}</li>")
            lines.append("</ul>")
            parts.append("".join(lines))
        parts.append("</div></div>")
    (RUN / "piano-cut.html").write_text("\n".join(parts))


def build_compare(results: list[dict]) -> None:
    css = """
    body{font:15px/1.45 -apple-system,Helvetica,Arial,sans-serif;margin:0;padding:24px;background:#f4f1ea;color:#222}
    h1{font-size:22px;margin:0 0 4px} h2{font-size:18px;margin:36px 0 8px} .sub{color:#666;margin-bottom:20px;max-width:1100px}
    img{width:100%;max-width:1200px;height:auto;border:1px solid #cbc3b4;background:#fff;display:block;margin:6px 0 14px}
    .lbl{font-size:13px;color:#666;margin-top:10px} .stats{font-size:13px;background:#fff;border:1px solid #d6d0c4;padding:8px 10px;max-width:1180px}
    .warn{color:#b35c00;font-weight:600} .ok{color:#1a7f37;font-weight:600}
    table{border-collapse:collapse;font-size:13px;background:#fff;margin-bottom:20px} td,th{border:1px solid #d6d0c4;padding:4px 8px;text-align:left}
    """
    instrument = results[0]["instrument"] if results else INSTRUMENT
    parts = [f"<!doctype html><meta charset='utf-8'><title>Part cut ({html.escape(instrument)}): plain crop vs cleaned crop</title><style>{css}</style>",
             f"<h1>Part cut (“{html.escape(instrument)}”), before / after the clean-and-extend pass</h1>",
             "<div class='sub'>Per system: the plain fixed-margin crop (the staves + ~1.5 spaces), then the cleaned crop "
             "(wide band between the neighbouring staves, neighbour ink erased, fitted to the instrument's own ink), then the band "
             "with every ink component tinted by class: <span style='color:#28a046'>green</span> target (overlaps the staff region), "
             "<span style='color:#dc3232'>red</span> neighbour (erased), <span style='color:#be28be'>magenta</span> both "
             "(target ink that also reaches the neighbour's region, kept and logged), <span style='color:#0096c8'>blue</span> gap ink "
             "resolved to the target by nearest ink or as the next word of a kept text line, <span style='color:#f08c00'>orange</span> gap ink resolved to the neighbour (erased), "
             "<span style='color:#a03c00'>brown</span> gap/margin ink over a bar where the target has only rests (erased), "
             "<span style='color:#78003c'>plum</span> floating pieces of a kept component over resting bars (ledger notes, sf: erased). "
             "Resting bars (own ink inside the staff lines below the floor) are shaded grey. "
             "Blue horizontal lines mark the final crop. edge_ink_top/bottom = kept ink on the crop's first/last row (still cut).</div>"]
    parts.append("<table><tr><th>page</th><th>system</th><th>plain crop (y0..y1)</th><th>clean crop (y0..y1)</th><th>extended px top / bottom (vs plain)</th>"
                 "<th>components</th><th>erased</th><th>kept</th><th>both</th><th>resting bars</th><th>rest-bar erased</th><th>pieces erased</th><th>edge ink top</th><th>edge ink bottom</th></tr>")
    for r in results:
        for c in r["compare"]:
            st = c["stats"]
            rec = next(s for s in r["systems"] if s["system"] == c["system"])
            pb, cb = rec["crop_box_plain"], rec["crop_box"]
            parts.append(f"<tr><td>{r['page']}</td><td>{c['system']}</td><td>{pb['y0']}..{pb['y1']}</td><td>{cb['y0']}..{cb['y1']}</td>"
                         f"<td>{pb['y0'] - cb['y0']:+d} / {cb['y1'] - pb['y1']:+d}</td><td>{st['components']}</td>"
                         f"<td>{st['erased']}</td><td>{st['kept']}</td><td>{len(st['both'])}</td>"
                         f"<td>{st.get('rest_bars')}</td><td>{st.get('erased_rest_bar')}</td><td>{st.get('erased_pieces')}</td>"
                         f"<td class='{'warn' if st['edge_ink_top'] else 'ok'}'>{st['edge_ink_top']}</td>"
                         f"<td class='{'warn' if st['edge_ink_bottom'] else 'ok'}'>{st['edge_ink_bottom']}</td></tr>")
    parts.append("</table>")
    for r in results:
        for c in r["compare"]:
            st = c["stats"]
            parts.append(f"<h2>Page {r['page']}, system {c['system']}</h2>")
            parts.append(f"<div class='lbl'>plain crop</div><img src='{jpeg_data_uri(c['plain'], 1200)}' alt='plain'>")
            parts.append(f"<div class='lbl'>cleaned crop</div><img src='{jpeg_data_uri(c['clean'], 1200)}' alt='clean'>")
            parts.append(f"<div class='lbl'>band, components by class</div><img src='{jpeg_data_uri(c['debug'], 1200)}' alt='debug'>")
            slim = {k: v for k, v in st.items() if k not in ("both", "gap_resolved", "bars", "pieces")}
            slim["bars"] = [f"{'REST' if b['resting'] else 'play'} x{b['x']} {b['ink_sp2']} sp²" for b in st.get("bars", [])]
            slim["pieces"] = [f"{p['bbox']} {p['area']} px of {p['of']} ({p['how']})" for p in st.get("pieces", [])]
            slim["both"] = st["both"]
            slim["gap_resolved"] = [f"{g['class']} {g['bbox']} ({g['how']})" for g in st["gap_resolved"]]
            parts.append(f"<div class='stats'><pre style='margin:0;white-space:pre-wrap'>{html.escape(json.dumps(slim, indent=1))}</pre></div>")
    (RUN / "clean-compare.html").write_text("\n".join(parts))


def main(pages: list[int], clean: bool = True) -> None:
    results = [build_page(n, clean) for n in pages]
    # one tall strip
    blocks = [b for r in results for b in r["blocks"]]
    gap = 30
    sw = max(b.width for b in blocks)
    strip = Image.new("RGB", (sw, sum(b.height for b in blocks) + gap * (len(blocks) + 1)), (255, 255, 255))
    y = gap
    for b in blocks:
        strip.paste(b, (0, y))
        y += b.height + gap
    strip.save(RUN / "strip.png")
    build_html(results)
    if clean:
        build_compare(results)
    slim = [{k: v for k, v in r.items() if k not in ("blocks", "label_parsed", "compare")} for r in results]
    (RUN / "results.json").write_text(json.dumps(slim, indent=2))
    for r in slim:
        print(json.dumps({"page": r["page"], "systems": [{k: v for k, v in s.items() if k in ("system", "wanted_staves", "status", "n_measures")}
                          | ({"verify": {k: (c["pass"] if isinstance(c, dict) else c) for k, c in s["verify"].items()}} if s.get("verify") else {})
                          | ({"clean": {k: s["clean"].get(k) for k in ("erased", "kept", "edge_ink_top", "edge_ink_bottom", "voice", "voice_above")}
                              | {"lyric_lines": [(l["class"], l["words"]) for l in s["clean"].get("lyric_lines", [])]}} if s.get("clean") else {})
                          for s in r["systems"]]}))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-clean", action="store_true", help="plain fixed-margin crop (the old behaviour), no clean-compare.html")
    ap.add_argument("--text-mode", default=TEXT_MODE, choices=("overlap", "baseline"), help="text-line grouping for the lyric rule")
    ap.add_argument("pages", nargs="*", type=int, default=DEFAULT_PAGES)
    a = ap.parse_args()
    RUN.mkdir(parents=True, exist_ok=True)
    TEXT_MODE = a.text_mode
    main(a.pages, clean=not a.no_clean)
