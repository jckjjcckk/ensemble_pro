# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx"]
# ///
"""Tap test read back from the LOCAL database: the placements `process_pages` wrote for a score must pass the
same test as the experiment (grade.py), page by page, against ground_truth.json.

    cd api && uv run experiments/grounding/tap_test_db.py --score <id> [--pages goldberg-bga-p01 rach1-2pf-gutheil-p03]

`--pages` names the ground-truth page for each page of the score in reading order (default: the two
experiment pages). Boxes come back as fractions; they are scaled to the ground truth's pixel frame.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
GT = json.loads((HERE / "ground_truth.json").read_text())
SIZES = {"goldberg-bga-p01": (1274, 1624), "rach1-2pf-gutheil-p03": (1416, 1907)}


def gt_measures(page: str) -> list[dict]:
    g = GT[page]
    out, n = [], g["first_measure"]
    for si, s in enumerate(g["systems"], start=1):
        xs = [s["x0"]] + s["barlines"] + [s["x1"]]
        for a, b in zip(xs, xs[1:]):
            out.append({"number": n, "cx": (a + b) / 2, "cy": (s["y0"] + s["y1"]) / 2})
            n += 1
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--score", required=True)
    ap.add_argument("--pages", nargs="*", default=["goldberg-bga-p01", "rach1-2pf-gutheil-p03"])
    a = ap.parse_args()
    status = json.loads(subprocess.check_output(["supabase", "status", "-o", "json"], cwd=HERE.parents[2], stderr=subprocess.DEVNULL))
    c = httpx.Client(base_url=status["API_URL"] + "/rest/v1", headers={"apikey": status["SECRET_KEY"], "Authorization": f"Bearer {status['SECRET_KEY']}"})
    score = c.get(f"/scores?id=eq.{a.score}&select=status,bars,current_interpretation_id").json()[0]
    iid = score["current_interpretation_id"]
    rows = c.get(f"/measure_placements?interpretation_id=eq.{iid}&select=page,box,confidence,measures(number)").json()
    print(f"score status {score['status']}, bars {score['bars']}, placements {len(rows)}")
    # measure numbers continue across pages: offset each page by the count of the pages before it
    offset, all_pass = 0, True
    for pno, page in enumerate(a.pages, start=1):
        W, H = SIZES[page]
        truth = gt_measures(page)
        pred = [{"number": r["measures"]["number"] - offset, "box": {k: r["box"][k] * (W if k[0] == "x" else H) for k in r["box"]}} for r in rows if r["page"] == pno]
        hits = [0] * len(pred)
        right = wrong = missed = 0
        detail = []
        for t in truth:
            inside = [i for i, p in enumerate(pred) if p["box"]["x0"] <= t["cx"] <= p["box"]["x1"] and p["box"]["y0"] <= t["cy"] <= p["box"]["y1"]]
            if not inside:
                missed += 1
                detail.append(f"m{t['number']}: no box under tap")
                continue
            i = min(inside, key=lambda i: (pred[i]["box"]["x1"] - pred[i]["box"]["x0"]) * (pred[i]["box"]["y1"] - pred[i]["box"]["y0"]))
            hits[i] += 1
            if pred[i]["number"] == t["number"]:
                right += 1
            else:
                wrong += 1
                detail.append(f"m{t['number']}: tap selects {pred[i]['number']}")
        ok = wrong == 0 and missed == 0 and hits.count(0) == 0 and len(pred) == len(truth)
        all_pass &= ok
        print(f"page {pno} {page}: truth {len(truth)} placed {len(pred)} right {right} wrong {wrong} missed {missed} unhit {hits.count(0)} -> {'PASS' if ok else 'FAIL'} {detail[:6]}")
        offset += len(truth)
    print("ALL PASS" if all_pass else "FAIL")
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
