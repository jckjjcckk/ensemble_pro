# /// script
# requires-python = ">=3.12"
# ///
"""Tap test: for every ground-truth measure, the centre of the measure is 'tapped'; the smallest predicted box
containing that point must carry the right number. Every predicted box must also be hit exactly once.

Usage (from api/):  uv run experiments/grounding/grade.py out/spark-goldberg-bga-p01.json [...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from common import HERE

GT = json.loads((HERE / "ground_truth.json").read_text())


def gt_measures(page: str) -> list[dict]:
    g = GT[page]
    n = g["first_measure"]
    out = []
    for si, s in enumerate(g["systems"], start=1):
        xs = [s["x0"]] + s["barlines"] + [s["x1"]]
        for a, b in zip(xs, xs[1:]):
            out.append({"number": n, "system": si, "cx": (a + b) / 2, "cy": (s["y0"] + s["y1"]) / 2,
                        "box": {"x0": a, "x1": b, "y0": s["y0"], "y1": s["y1"]}})
            n += 1
    return out


def grade(path: Path) -> dict:
    data = json.loads(path.read_text())
    page = data["page"]
    truth = gt_measures(page)
    pred = data.get("measures", [])
    hits = {id(p): 0 for p in pred}
    right, wrong, missed, detail = 0, 0, 0, []
    for t in truth:
        inside = [p for p in pred if p["box"]["x0"] <= t["cx"] <= p["box"]["x1"] and p["box"]["y0"] <= t["cy"] <= p["box"]["y1"]]
        if not inside:
            missed += 1
            detail.append(f"m{t['number']}: no box under tap")
            continue
        p = min(inside, key=lambda b: (b["box"]["x1"] - b["box"]["x0"]) * (b["box"]["y1"] - b["box"]["y0"]))
        hits[id(p)] += 1
        if p["number"] == t["number"]:
            right += 1
        else:
            wrong += 1
            detail.append(f"m{t['number']}: tap selects {p['number']}")
    extra = sum(1 for p in pred if hits[id(p)] == 0)
    passed = wrong == 0 and missed == 0 and extra == 0 and len(pred) == len(truth)
    res = {"file": path.name, "page": page, "truth": len(truth), "predicted": len(pred), "right": right, "wrong": wrong,
           "missed": missed, "unhit_boxes": extra, "pass": passed, "latency_s": data.get("latency_s"), "cost_usd": data.get("cost_usd"),
           "detail": detail[:12]}
    print(json.dumps(res))
    return res


if __name__ == "__main__":
    for p in sys.argv[1:]:
        grade(Path(p))
