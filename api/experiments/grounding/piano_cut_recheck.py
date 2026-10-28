# /// script
# requires-python = ">=3.12"
# dependencies = ["anthropic>=2.3.0"]
# ///
"""Piano-cut experiment, step 4: the loop's second opinion. Spark sees one crop alone (no page context, no
numbered overlay) and names the instrument. A crop whose answer is not the piano fails verification.

Usage (from api/):  uv run experiments/grounding/piano_cut_recheck.py [--score <pdf stem>] [page ...]
Reads crop-p<NN>-s<k>.png (from piano_cut_build.py), writes recheck-p<NN>-s<k>.json. Same spend cap/tally
as piano_cut_label.py.
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
import time

from common import PIANO_CUT_TITLE
from piano_cut_label import DEFAULT_PAGES, PC, SYSTEM, complete, model_name, parse, spend_add, spend_check

PROMPT = """This image is a block of staves cut from a scanned orchestral full score ({title}). The left margin may carry the instrument label; if it does not, judge from the clefs, the brace or bracket, and the writing.

Which instrument or section is this block? Is it the solo piano part (a two-staff grand staff, usually treble over bass, with keyboard writing: chords in both hands, runs, octaves, pedal marks)? A pair of violin staves, a pair of horn staves, or a pair of trombone staves is not the piano.

Return only JSON: {{"instrument": "short name", "is_piano": true|false, "staves": 2, "clefs": ["treble", "bass"], "label_seen": "text of any margin label or empty", "confidence": "high|medium|low", "why": "one sentence"}}""".format(title=PIANO_CUT_TITLE)


async def run(n: int) -> None:
    for crop in sorted(PC.glob(f"crop-p{n:02d}-s*.png")):
        k = crop.stem.split("-s")[-1]
        spend_check(crop.name)
        t0 = time.perf_counter()
        text, charge = await complete(PROMPT, system=SYSTEM, effort="low", max_tokens=2048,
                                      image_png_b64=base64.b64encode(crop.read_bytes()).decode())
        dt = time.perf_counter() - t0
        parsed, err, repaired = parse(text)
        out = {"page": n, "system": int(k), "crop": crop.name, "model": model_name(), "latency_s": round(dt, 1),
               "cost_usd": charge["cost_usd"], "charge": charge, "raw_text": text, "parsed": parsed,
               "parse_error": err, "json_repaired": repaired}
        (PC / f"recheck-p{n:02d}-s{k}.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
        total = spend_add({"page": n, "system": int(k), "kind": "recheck", "cost_usd": charge["cost_usd"],
                           "latency_s": round(dt, 1), "model": model_name()})
        print(json.dumps({"crop": crop.name, "latency_s": round(dt, 1), "cost_usd": charge["cost_usd"],
                          "running_total_usd": total, "parse_error": err,
                          "instrument": (parsed or {}).get("instrument"), "is_piano": (parsed or {}).get("is_piano"),
                          "label_seen": (parsed or {}).get("label_seen")}))


async def main() -> None:
    for n in [int(a) for a in sys.argv[1:]] or DEFAULT_PAGES:
        await run(n)


if __name__ == "__main__":
    asyncio.run(main())
