# /// script
# requires-python = ">=3.12"
# dependencies = ["anthropic>=2.3.0"]
# ///
"""Piano-cut experiment, step 4: the loop's second opinion. Spark sees one crop alone (no page context, no
numbered overlay) and names the instrument. A crop whose answer is not the wanted instrument fails verification.

Usage (from api/):  uv run experiments/grounding/piano_cut_recheck.py [--score <pdf stem>] [--instrument "..."] [page ...]
Reads crop-p<NN>-s<k>.png (from piano_cut_build.py) in the run folder, writes recheck-p<NN>-s<k>.json there.
Same spend cap/tally as piano_cut_label.py.
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
import time

from common import PIANO_CUT_INSTRUMENT, PIANO_CUT_TITLE
from piano_cut_label import (DEFAULT_PAGES, RUN, SYSTEM, complete_json, instrument_desc, instrument_staves, model_name,
                             spend_add, spend_check)

PROMPT = """This image is a block of staves cut from a scanned orchestral full score ({title}). The left margin may carry the instrument label; if it does not, judge from the clefs, any brace or bracket, and the writing.

Which instrument or section is this block? Is it the "{instrument}" part? {desc} Expect {n_staves} staff{plural} in the block. Another instrument's staff with the same clef is not it (a second violin, a viola or a flute staff is not "Violin I"; a pair of violin or horn staves is not the piano); a staff shared by two players of the wanted instrument ("Flauti I. II." on one staff) is it.

Return only JSON: {{"instrument": "short name", "is_wanted": true|false, "staves": {n_staves}, "clefs": ["treble"], "label_seen": "text of any margin label or empty", "confidence": "high|medium|low", "why": "one sentence"}}"""


def prompt(instrument: str) -> str:
    ns = instrument_staves(instrument) or (2 if "piano" in instrument.lower() else 1)
    return PROMPT.format(title=PIANO_CUT_TITLE, instrument=instrument, desc=instrument_desc(instrument), n_staves=ns,
                         plural="s" if ns != 1 else "")


async def run(n: int, instrument: str = PIANO_CUT_INSTRUMENT) -> None:
    for crop in sorted(RUN.glob(f"crop-p{n:02d}-s*.png")):
        k = crop.stem.split("-s")[-1]
        spend_check(crop.name)
        t0 = time.perf_counter()
        # 4000 tokens and one retry: on the Dvořák flute crops Spark's reasoning ate a 2048 budget three times
        # in nine calls and returned no text at all (stop_reason max_tokens)
        text, charge, parsed, err, retries = await complete_json(
            prompt(instrument), system=SYSTEM, effort="low", max_tokens=4000,
            image_png_b64=base64.b64encode(crop.read_bytes()).decode())
        dt = time.perf_counter() - t0
        repaired = charge.get("json_repaired", False)
        out = {"page": n, "system": int(k), "crop": crop.name, "instrument": instrument, "model": model_name(),
               "latency_s": round(dt, 1), "cost_usd": charge["cost_usd"], "charge": charge, "retries": retries,
               "raw_text": text, "parsed": parsed, "parse_error": err, "json_repaired": repaired}
        (RUN / f"recheck-p{n:02d}-s{k}.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
        total = spend_add({"page": n, "system": int(k), "kind": "recheck", "cost_usd": charge["cost_usd"],
                           "latency_s": round(dt, 1), "model": model_name(), "retries": len(retries)})
        print(json.dumps({"crop": crop.name, "latency_s": round(dt, 1), "cost_usd": charge["cost_usd"],
                          "running_total_usd": total, "parse_error": err,
                          "instrument": (parsed or {}).get("instrument"), "is_wanted": (parsed or {}).get("is_wanted"),
                          "label_seen": (parsed or {}).get("label_seen")}))


async def main() -> None:
    for n in [int(a) for a in sys.argv[1:]] or DEFAULT_PAGES:
        await run(n)


if __name__ == "__main__":
    asyncio.run(main())
