# /// script
# requires-python = ">=3.12"
# dependencies = ["anthropic>=2.3.0"]
# ///
"""Piano-cut experiment, step 0: the score header. One Spark call on the first music page returns the
instrument list in score order (full label, abbreviations, staves per instrument, clef per staff), key, time,
tempo text and any movement/section start. The staff total is validated against geometry's count for that
page's first system and stored in out/piano-cut/<stem>/header.json. Geometry then knows how many staves a full
system should have (and searches for the missing ones), and the labeller gets staff -> instrument by order.

Usage (from api/):  uv run experiments/grounding/score_header.py [--score <pdf stem>] [page]
Needs geom-p<NN>.json / overlay-p<NN>.png from piano_cut_geometry.py for that page (default page 1).
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import PIANO_CUT_TITLE  # noqa: E402
from piano_cut_label import PC, SYSTEM, complete_json, model_name, spend_add, spend_check  # noqa: E402

PROMPT = """This is page {page} of a scanned orchestral full score ({title}), the first page of music. A geometry detector has drawn a blue box around every staff it found and a yellow tag with the staff number at the left end of each box (staves {first}..{last}, top to bottom, {n_staves} boxes in system 1). It may have missed a staff: trust the printed page, not the boxes.

Read the margin labels (full names on this first page) and list every instrument in score order, top to bottom, with the yellow box numbers it occupies on this page (count the boxes: a piano or harp has 2, a wind pair written on one shared staff is one instrument with 1 box, "Violoncello e Basso" on one staff is 1; a label spanning two boxes with a bracket means 2), the clef of each staff, and the abbreviation this edition is likely to use on later pages (e.g. "Fl.", "Ob.", "Cor.", "Pno.", "Klav.", "Vl. I"). Every box number from {first} to {last} must appear exactly once, in order; a staff with no box is "boxes": [] and "staves": 1. Also give the key signature, the time signature, the tempo text, and any movement or section heading visible.

Return only JSON of this shape:
{{"instruments": [{{"label": "Flauti I. II.", "abbreviations": ["Fl."], "boxes": [1], "staves": 1, "clefs": ["treble"], "family": "woodwind|brass|percussion|keyboard|strings|voice|other"}}],
 "staff_total": 13,
 "key": "C minor (3 flats)", "time": "4/4", "tempo": "Allegro con brio",
 "sections": ["I."],
 "piano_present": true,
 "notes": "one sentence if anything is odd"}}"""


async def run(page: int) -> dict:
    spend_check(f"header page {page}")
    geom = json.loads((PC / f"geom-p{page:02d}.json").read_text())
    png = (PC / f"overlay-p{page:02d}.png").read_bytes()
    first_sys = geom["systems"][0]["staff_indices"] if geom["systems"] else []
    prompt = PROMPT.format(page=page, title=PIANO_CUT_TITLE, first=first_sys[0] if first_sys else 1,
                           last=first_sys[-1] if first_sys else len(geom["staves"]), n_staves=len(first_sys))
    t0 = time.perf_counter()
    text, charge, parsed, parse_error, retries = await complete_json(
        prompt, system=SYSTEM, effort="low", max_tokens=8000, image_png_b64=base64.b64encode(png).decode())
    dt = time.perf_counter() - t0
    header = parsed or {}
    inst = header.get("instruments") or []
    # reconcile: the box numbers anchor the count to what is on the page. When every instrument's boxes form the
    # sequence first..last exactly once, staves = len(boxes) (Spark said "2 staves" for the Rach 1 wind pairs that
    # share one staff; their boxes say 1). Otherwise keep Spark's staff counts and flag the mismatch.
    boxes = [b for i in inst for b in (i.get("boxes") or [])]
    boxes_ok = bool(first_sys) and boxes == list(first_sys)
    if boxes_ok:
        for i in inst:
            if i.get("boxes"):
                i["staves_said"], i["staves"] = i.get("staves"), len(i["boxes"])
    header_total = sum(int(i.get("staves") or 0) for i in inst) or header.get("staff_total")
    out = {"page": page, "model": model_name(), "latency_s": round(dt, 1), "cost_usd": charge["cost_usd"],
           "retries": retries, "parse_error": parse_error, "raw_text": text,
           **{k: v for k, v in header.items()},
           "validation": {"geometry_staves_system1": len(first_sys), "header_staves": header_total,
                          "boxes_in_order": boxes_ok, "match": header_total == len(first_sys)}}
    out["expected_staves"] = header_total
    (PC / "header.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    spend_add({"page": page, "kind": "header", "cost_usd": charge["cost_usd"], "latency_s": round(dt, 1),
               "model": model_name(), "retries": retries})
    print(json.dumps({"page": page, "latency_s": round(dt, 1), "cost_usd": charge["cost_usd"], "retries": retries,
                      "parse_error": parse_error, "instruments": [(i.get("label"), i.get("staves")) for i in inst],
                      "validation": out["validation"]}))
    return out


if __name__ == "__main__":
    asyncio.run(run(int(sys.argv[1]) if len(sys.argv) > 1 else 1))
