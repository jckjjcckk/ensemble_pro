# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx", "pillow"]
# ///
"""Meta-only variant: SAM 3.1 system boxes crop the page, Spark grounds measures inside each crop.

SAM prompts that worked: "musical staff" on the clean page returns one box per system; "line of music" on the
noisy page returns one box per grand staff (two per system), merged here when their vertical gap is under 30 px (gaps inside a system are ~13 px, between systems 54+ px).
Spark then sees one system at a time (more pixels per barline) and reports measures on the crop's 0-1000 grid.

Usage (from api/):  uv run experiments/grounding/run_spark_crops.py [--effort low] [page ...]
Writes out/spark-crops-<page>.json in the shared measures shape.
"""

from __future__ import annotations

import argparse
import base64
import io
import json

from PIL import Image

from common import OUT, PAGE_NAMES, PAGES, PRICE, client, dump, output_text, responses
from run_spark import SYSTEM_PROMPT, extract_json

SAM_PROMPT_FOR_PAGE = {"goldberg-bga-p01": "musical_staff", "rach1-2pf-gutheil-p03": "line_of_music"}

CROP_PROMPT = """This image is one staff system cut from a scanned page of printed sheet music ({staves} staves played together).
Find every measure (bar) in it, left to right, by its barlines. The first measure starts after the clef, key signature and time signature; the last ends at the final barline on the right. A box spans the full height of the image.
Number them starting at {first}. Flag a measure "uncertain": true if you are not sure its right barline is real.
Return only JSON: {{"measures":[{{"number":{first},"bbox":{{"x_min":0,"y_min":0,"x_max":0,"y_max":0}},"uncertain":false}}]}}"""


def sam_system_boxes(page: str) -> list[dict]:
    data = json.loads((OUT / f"sam-{page}-{SAM_PROMPT_FOR_PAGE[page]}.json").read_text())
    boxes = sorted(data["boxes"], key=lambda b: b["y1"])
    merged: list[dict] = []
    for b in boxes:
        if merged and b["y1"] - merged[-1]["y2"] < 30:
            m = merged[-1]
            m["x1"], m["y1"], m["x2"], m["y2"] = min(m["x1"], b["x1"]), min(m["y1"], b["y1"]), max(m["x2"], b["x2"]), max(m["y2"], b["y2"])
            m["parts"] += 1
        else:
            merged.append({**b, "parts": 1})
    return merged


def run_page(c, page: str, effort: str) -> dict:
    im = Image.open(PAGES / f"{page}.png")
    systems = sam_system_boxes(page)
    measures, out_systems, total_cost, total_latency, usage_sum = [], [], 0.0, 0.0, {"input_tokens": 0, "output_tokens": 0}
    n = 1
    for si, s in enumerate(systems, start=1):
        pad = 12
        x0, y0, x1, y1 = max(0, s["x1"] - pad), max(0, s["y1"] - pad), min(im.width, s["x2"] + pad), min(im.height, s["y2"] + pad)
        crop = im.crop((x0, y0, x1, y1))
        buf = io.BytesIO()
        crop.save(buf, format="PNG")
        staves = 2 * s["parts"] if page.startswith("rach") else 2
        body = {
            "model": "muse-spark-1.3", "reasoning": {"effort": effort}, "instructions": SYSTEM_PROMPT,
            "input": [{"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": CROP_PROMPT.format(staves=staves, first=n)},
                {"type": "input_image", "image_url": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()},
            ]}],
            "max_output_tokens": 6000,
        }
        resp, dt = responses(c, body)
        usage = resp.get("usage", {})
        usage_sum["input_tokens"] += usage.get("input_tokens", 0)
        usage_sum["output_tokens"] += usage.get("output_tokens", 0)
        total_latency += dt
        price = PRICE["muse-spark-1.3"]
        total_cost += usage.get("input_tokens", 0) / 1e6 * price["input_per_m"] + usage.get("output_tokens", 0) / 1e6 * price["output_per_m"]
        text = output_text(resp)
        try:
            parsed = extract_json(text)
        except Exception as e:
            print("  parse error system", si, repr(e), text[:200])
            parsed = {"measures": []}
        cw, ch = crop.size
        found = 0
        for m in parsed.get("measures", []):
            b = m["bbox"]
            box = {"x0": x0 + round(b["x_min"] * cw / 1000), "y0": y0 + round(b["y_min"] * ch / 1000),
                   "x1": x0 + round(b["x_max"] * cw / 1000), "y1": y0 + round(b["y_max"] * ch / 1000)}
            measures.append({"number": n, "system": si, "box": box, "uncertain": bool(m.get("uncertain"))})
            n += 1
            found += 1
        out_systems.append({"index": si, "box": {"x0": x0, "y0": y0, "x1": x1, "y1": y1}, "n_measures": found, "sam_parts": s["parts"]})
        print(f"  system {si}: {found} measures, {dt:.1f}s")
    result = {"page": page, "engine": "sam-3.1 systems + muse-spark-1.3 per-system grounding", "effort": effort,
              "latency_s": round(total_latency, 1), "usage": usage_sum, "cost_usd": round(total_cost + len(systems) * 0 + PRICE["sam-3.1"]["per_image"], 4),
              "systems": out_systems, "measures": measures}
    dump(OUT / f"spark-crops-{page}.json", result)
    print(json.dumps({k: result[k] for k in ("page", "latency_s", "usage", "cost_usd")}), [s["n_measures"] for s in out_systems])
    return result


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
