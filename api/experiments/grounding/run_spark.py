# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx", "pillow"]
# ///
"""Muse Spark grounding: systems, measures, measure numbers on the 0-1000 grid.

Usage (from api/):  uv run experiments/grounding/run_spark.py [--effort low] [--model muse-spark-1.3] [page ...]
Writes out/spark-<page>.json (parsed measures in pixels + raw text + usage + latency).
"""

from __future__ import annotations

import argparse
import json
import re

from common import OUT, PAGE_NAMES, PAGES, PRICE, client, dump, image_data_url, image_size, output_text, responses

SYSTEM_PROMPT = """You are a music librarian locating measures on a scanned page of sheet music.
Coordinates: a normalized grid where (0,0) is the top-left corner of the image and (1000,1000) the bottom-right.
Report every box as {"x_min":int,"y_min":int,"x_max":int,"y_max":int} on that grid."""

USER_PROMPT = """Analyse this scanned page of printed sheet music.

1. Find every staff system (a system is one horizontal row of music, spanning all staves that are played together; for piano music a system is the pair of treble and bass staves, for two pianos it is four staves). Give each system's bounding box from the left edge of the staves to the right end of the staff lines.
2. Within each system, find every measure (bar) by its barlines. A measure box spans from its left barline (or the start of the staves, after clef and key signature, for the first measure of a system) to its right barline, and vertically the full height of the system. Measures run left to right within a system, systems top to bottom.
3. Number the measures consecutively starting at {first_measure} for the first measure on the page. Printed measure numbers or rehearsal marks on the page may help; the final barline of a repeat is not a new measure.
4. Flag any region where you are not sure a barline is real (e.g. it could be a stem, a slur, a scan artefact) with "uncertain": true.

Return only JSON of this shape, nothing else:
{{"systems":[{{"index":1,"bbox":{{"x_min":0,"y_min":0,"x_max":0,"y_max":0}},"staves":2,
  "measures":[{{"number":1,"bbox":{{"x_min":0,"y_min":0,"x_max":0,"y_max":0}},"uncertain":false}}]}}],
 "uncertain_regions":[{{"bbox":{{"x_min":0,"y_min":0,"x_max":0,"y_max":0}},"why":"..."}}],
 "total_measures_on_page":0}}"""


def extract_json(text: str) -> dict:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    start = text.find("{")
    end = text.rfind("}")
    return json.loads(text[start : end + 1])


def to_pixels(bbox: dict, w: int, h: int) -> dict:
    def cl(v, hi):
        return max(0, min(hi, round(v * hi / 1000)))

    return {"x0": cl(bbox["x_min"], w), "y0": cl(bbox["y_min"], h), "x1": cl(bbox["x_max"], w), "y1": cl(bbox["y_max"], h)}


def run_page(c, page: str, model: str, effort: str, first_measure: int = 1, tag: str = "spark"):
    png = PAGES / f"{page}.png"
    w, h = image_size(png)
    body = {
        "model": model,
        "reasoning": {"effort": effort},
        "instructions": SYSTEM_PROMPT,
        "input": [{"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": USER_PROMPT.format(first_measure=first_measure)},
            {"type": "input_image", "image_url": image_data_url(png)},
        ]}],
        "max_output_tokens": 16000,
    }
    resp, dt = responses(c, body)
    text = output_text(resp)
    usage = resp.get("usage", {})
    price = PRICE.get(model, PRICE["muse-spark-1.3"])
    cost = usage.get("input_tokens", 0) / 1e6 * price["input_per_m"] + usage.get("output_tokens", 0) / 1e6 * price["output_per_m"]
    result = {"page": page, "model": model, "effort": effort, "latency_s": round(dt, 1), "usage": usage, "cost_usd": round(cost, 4),
              "image_px": [w, h], "raw_text": text, "status": resp.get("status"), "incomplete": resp.get("incomplete_details")}
    try:
        parsed = extract_json(text)
        measures = []
        for s in parsed.get("systems", []):
            for m in s.get("measures", []):
                measures.append({"number": m.get("number"), "system": s.get("index"), "box": to_pixels(m["bbox"], w, h),
                                 "grid": m["bbox"], "uncertain": bool(m.get("uncertain"))})
        result["systems"] = [{"index": s.get("index"), "box": to_pixels(s["bbox"], w, h), "staves": s.get("staves"),
                              "n_measures": len(s.get("measures", []))} for s in parsed.get("systems", [])]
        result["measures"] = measures
        result["uncertain_regions"] = [{"box": to_pixels(u["bbox"], w, h), "why": u.get("why")} for u in parsed.get("uncertain_regions", [])]
        result["total_measures_on_page"] = parsed.get("total_measures_on_page")
    except Exception as e:
        result["parse_error"] = repr(e)
    dump(OUT / f"{tag}-{page}.json", result)
    print(json.dumps({k: v for k, v in result.items() if k in ("page", "model", "effort", "latency_s", "usage", "cost_usd", "status", "parse_error")}))
    for s in result.get("systems", []):
        print("  system", s["index"], s["box"], "measures:", s["n_measures"])
    print("  total measures:", len(result.get("measures", [])), "uncertain:", sum(m["uncertain"] for m in result.get("measures", [])))
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--effort", default="low")
    ap.add_argument("--model", default="muse-spark-1.3")
    ap.add_argument("--tag", default="spark")
    ap.add_argument("pages", nargs="*", default=PAGE_NAMES)
    a = ap.parse_args()
    c = client()
    for page in a.pages:
        run_page(c, page, a.model, a.effort, tag=a.tag)


if __name__ == "__main__":
    main()
