# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx", "pillow"]
# ///
"""Fallback path, step 2: Spark numbers and labels what OpenCV found.

Spark sees the page with the detected measure boxes drawn and numbered provisionally (1..N top-left to
bottom-right), and is asked only for things geometry cannot know:
  - the number of the first measure on the page (printed measure numbers, pickup bars);
  - the part name of each staff / system (Piano I, Piano II, Violin ...);
  - rehearsal marks and which provisional measure they sit on;
  - provisional measures that it thinks are not real measures (and why), as a confidence flag.
It never moves a box. Output: out/final-<page>.json in the measures-record shape proposed in the README.

Usage (from api/):  uv run experiments/grounding/label_with_spark.py [--effort low] [page ...]
"""

from __future__ import annotations

import argparse
import base64
import io
import json

from PIL import Image, ImageDraw, ImageFont

from common import OUT, PAGE_NAMES, PAGES, PRICE, client, dump, output_text, responses
from run_spark import extract_json

PROMPT = """This is a scanned page of printed sheet music. Blue boxes with provisional numbers (1..{n}, reading left to right, top to bottom) mark the measures that a geometry detector found. Dashed boxes mark staff systems.

Answer these questions about the page. Do not re-locate anything; only label what is drawn.
1. first_measure_number: the real measure number of provisional measure 1, using printed measure numbers, rehearsal letters or the musical context if visible; if the page starts with an incomplete pickup bar say so (is_pickup true). If nothing on the page tells you, answer 1 with confidence "low".
2. parts: for each system, the part names of its staves top to bottom (e.g. ["Piano I", "Piano II"] for a two-piano score where each part has two staves; ["Piano"] for a piano grand staff). Give staves_per_part.
3. rehearsal_marks: any boxed numbers or letters, with the provisional measure they are attached to.
4. doubtful_measures: provisional measure numbers that do not look like real measures (for example a box that spans only a clef or key signature, or two boxes that are really one bar split by a note stem), each with a reason.
5. title and composer if printed.

Return only JSON:
{{"first_measure_number": 1, "is_pickup": false, "confidence": "high|medium|low",
 "systems": [{{"index": 1, "parts": ["Piano"], "staves_per_part": [2]}}],
 "rehearsal_marks": [{{"mark": "1", "provisional_measure": 9}}],
 "doubtful_measures": [{{"provisional_measure": 5, "reason": "..."}}],
 "title": "", "composer": ""}}"""


def annotated_png(page: str, cv: dict) -> bytes:
    im = Image.open(PAGES / f"{page}.png").convert("RGB")
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 28)
    except Exception:
        font = ImageFont.load_default()
    for s in cv["systems"]:
        b = s["box"]
        d.rectangle([b["x0"], b["y0"], b["x1"], b["y1"]], outline=(90, 90, 90), width=2)
    for m in cv["measures"]:
        b = m["box"]
        d.rectangle([b["x0"], b["y0"], b["x1"], b["y1"]], outline=(0, 110, 220), width=3)
        d.rectangle([b["x0"] + 3, b["y0"] + 3, b["x0"] + 52, b["y0"] + 36], fill=(255, 255, 255))
        d.text((b["x0"] + 6, b["y0"] + 2), str(m["number"]), fill=(0, 110, 220), font=font)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def run_page(c, page: str, effort: str) -> dict:
    cv = json.loads((OUT / f"cv-{page}.json").read_text())
    png = annotated_png(page, cv)
    (OUT / f"label-input-{page}.png").write_bytes(png)
    body = {
        "model": "muse-spark-1.3",
        "reasoning": {"effort": effort},
        "input": [{"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": PROMPT.format(n=len(cv["measures"]))},
            {"type": "input_image", "image_url": "data:image/png;base64," + base64.b64encode(png).decode()},
        ]}],
        "max_output_tokens": 8000,
    }
    resp, dt = responses(c, body)
    text = output_text(resp)
    usage = resp.get("usage", {})
    price = PRICE["muse-spark-1.3"]
    cost = usage.get("input_tokens", 0) / 1e6 * price["input_per_m"] + usage.get("output_tokens", 0) / 1e6 * price["output_per_m"]
    labels = extract_json(text)
    first = int(labels.get("first_measure_number") or 1)
    offset = first - 1
    doubtful = {d["provisional_measure"]: d.get("reason") for d in labels.get("doubtful_measures", [])}
    parts_by_system = {s["index"]: s for s in labels.get("systems", [])}
    marks = {m["provisional_measure"]: m["mark"] for m in labels.get("rehearsal_marks", [])}
    measures = []
    for m in cv["measures"]:
        sysinfo = parts_by_system.get(m["system"], {})
        parts = sysinfo.get("parts") or []
        measures.append({
            "measure_number": m["number"] + offset,
            "page": 1,
            "system": m["system"],
            "part": parts if len(parts) > 1 else (parts[0] if parts else None),
            "box": m["box"],
            "box_norm": {k: round(v / (cv["image_px"][0] if k[0] == "x" else cv["image_px"][1]), 4) for k, v in m["box"].items()},
            "confidence": "low" if m["number"] in doubtful else "high",
            "flag": doubtful.get(m["number"]),
            "rehearsal_mark": marks.get(m["number"]),
        })
    final = {
        "page": page, "engine": "opencv-geometry + muse-spark-1.3 labels", "effort": effort,
        "latency_s": round(dt, 1), "usage": usage, "cost_usd": round(cost, 4), "cv_skew_deg": cv.get("skew_deg"),
        "labels": labels, "raw_text": text,
        "systems": [{**s, "parts": parts_by_system.get(s["index"], {}).get("parts")} for s in cv["systems"]],
        # same shape as the other outputs so build_overlay.py and grade.py work unchanged
        "measures": [{"number": x["measure_number"], "system": x["system"], "box": x["box"],
                      "uncertain": x["confidence"] != "high"} for x in measures],
        "records": measures,
    }
    dump(OUT / f"final-{page}.json", final)
    print(json.dumps({"page": page, "latency_s": final["latency_s"], "cost_usd": final["cost_usd"], "usage": usage,
                      "first_measure": first, "parts": [s.get("parts") for s in labels.get("systems", [])],
                      "marks": labels.get("rehearsal_marks"), "doubtful": labels.get("doubtful_measures"),
                      "title": labels.get("title"), "composer": labels.get("composer")}))
    return final


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--effort", default="low")
    ap.add_argument("pages", nargs="*", default=PAGE_NAMES)
    a = ap.parse_args()
    c = client()
    for page in a.pages:
        run_page(c, page, a.effort)


if __name__ == "__main__":
    main()
