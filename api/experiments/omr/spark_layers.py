"""The two Muse Spark insertions on top of Audiveris, run over the whole page set (calls in parallel).

A  verify   one closed question per symbol under the grade gate (model.json `doubtful`): a context crop with
            the symbol boxed in red, "what is it really?", one of four options. The answer becomes a
            deterministic MusicXML edit in apply_edits.py.
B  reread   one call per system: the system crop with every bar boxed and labelled with its global number.
            Spark lists every dynamic and direction word with its centre on its 0-1000 grid (and the bar label
            as a cross-check), and the ornament signs per bar with the notehead they sit on. text_place.py
            puts each word on the bar whose x range holds it and on the nearer staff.

Spark never reads or judges notes. Effort low, output budget 8k (spark.MIN_OUTPUT).

Usage: uv run python experiments/omr/spark_layers.py RUN_DIR [--only verify,reread] [--cap 2.0] [--workers 6]
RUN_DIR holds model.json and scan/page300-0N.png; writes verify.json, reread.json, spend.json there.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import spark  # noqa: E402
from crops import Cropper, png_bytes  # noqa: E402
from text_place import place  # noqa: E402

VERIFY_SYSTEM = "You are a music engraver checking symbols on a scanned page of piano music. Answer with strict JSON only."
OPTIONS = {
    "tuplet": ["tuplet_number", "fingering_digit", "letter_of_word", "nothing_else"],
    "dynamics": ["dynamic_marking", "fingering_digit", "letters_of_word", "nothing_else"],
    "fermata": ["fermata", "slur_or_tie_end", "fingering_or_bracket", "nothing_else"],
    "rest": ["rest", "fingering_digit", "letters_of_word", "nothing_else"],
    "augmentation-dot": ["augmentation_dot", "staccato_dot", "noise_or_nothing", "part_of_text"],
    "ornament": ["ornament", "fingering_digit", "letters_of_word", "nothing_else"],
    "wedge": ["hairpin_wedge", "slur_or_beam", "nothing_else"],
}
VERIFY_PROMPT = """This crop comes from a scanned page of printed piano music (300 dpi). The red box marks one symbol that an OMR engine read as "{shape}" with low confidence.
Look only inside the red box (use the surroundings as context). What is it really? Pick exactly one of: {options}.
If it is a dynamic marking, give its text (p, pp, mp, mf, f, ff, sf, fp, rf, cresc, dim). If it is a digit or letters, give them.
Return only JSON: {{"verdict": "<one option>", "value": "<text, digit, or dynamic as printed, else empty>", "confidence": "high|medium|low"}}"""

REREAD_SYSTEM = "You are a music engraver reading a scanned page of printed piano music. Answer with strict JSON only, no prose."
REREAD_PROMPT = """This is one system (treble + bass staff) of a scanned page of printed piano music, 300 dpi. Blue boxes with yellow numbers mark the measures {first}..{last}; a measure's box covers both staves.

1. "text": every dynamic marking and direction word printed in or around this system, exactly as printed, one item per word (examples: "p", "mf", "f", "rf", "cresc.", "dim.", "dolce", "poco"). For each give where its ink is, on a 0-1000 grid over this image ((0,0) top-left, (1000,1000) bottom-right): "x" = horizontal centre of the word, "y" = vertical centre. Also give "bar" = the yellow number of the box it sits in or under. Do NOT include fingering digits, the yellow labels, measure numbers, tempo headings (e.g. "Allegretto") or movement titles (e.g. "Var. 2").
2. "ornaments": per measure, every ornament sign (mordent = short zigzag with a vertical stroke through it; inverted mordent / pralltriller = short zigzag without stroke; trill = "tr" or long zigzag; turn = sideways S; schleifer = slanted small zigzag with a tail). For each give "staff" ("upper" or "lower"), "note_index" = which notehead it sits on counting noteheads left to right in that staff of that measure (1-based; a chord counts once; skip small grace notes), and "kind" (one of mordent, inverted_mordent, trill, turn, schleifer).

Return only JSON: {{"text": [{{"text": "p", "x": 120, "y": 640, "bar": {first}}}], "measures": [{{"number": {first}, "ornaments": [{{"staff": "upper", "note_index": 3, "kind": "mordent"}}]}}]}}"""


def scan_of(run: Path, model: dict, page: int) -> Image.Image:
    pdf_page = next(p["pdf_page"] for p in model["pages"] if p["page"] == page)
    return Image.open(run / "scan" / f"page300-{pdf_page:02d}.png")


def verify(run: Path, model: dict, workers: int) -> list[dict]:
    croppers = {p["page"]: Cropper(model, p["page"], scan_of(run, model, p["page"])) for p in model["pages"]}
    todo = [d for d in model["doubtful"] if d["tag"] in OPTIONS and d["page"] is not None]
    # answers already paid for (same page, same Audiveris inter) are reused, so moving the gate costs only the
    # symbols it newly lets in
    cached = {}
    if (run / "verify.json").exists():
        cached = {(r["inter"]["page"], r["inter"]["id"]): r for r in json.load(open(run / "verify.json"))
                  if "error" not in r["answer"]}

    def one(d):
        if (d["page"], d["id"]) in cached:
            return cached[(d["page"], d["id"])] | {"inter": d, "usages": [], "cached": True}
        im = croppers[d["page"]].symbol_crop(d)
        shape = d["shape"] or d["tag"]
        ans, usages, raw = spark.ask_json(VERIFY_PROMPT.format(shape=shape, options=", ".join(OPTIONS[d["tag"]])),
                                          system=VERIFY_SYSTEM, image_png=png_bytes(im), tag=f"verify m{d['number']} {shape}")
        return {"inter": d, "answer": ans, "usages": usages, "raw": raw}

    with ThreadPoolExecutor(workers) as ex:
        out = list(ex.map(one, todo))
    for r in out:
        d, ans = r["inter"], r["answer"]
        print(f"  m{d['number']:3d} {d['tag']:16s} {d['shape'] or '':18s} grade={d['grade']:.3f} -> {ans.get('verdict')} "
              f"{ans.get('value')!r} ({ans.get('confidence')})")
    return out


def reread(run: Path, model: dict, workers: int) -> list[dict]:
    croppers = {p["page"]: Cropper(model, p["page"], scan_of(run, model, p["page"])) for p in model["pages"]}

    def one(s):
        cr = croppers[s["page"]]
        ms = [m for m in model["measures"] if m["page"] == s["page"] and m["system"] == s["system"]]
        im, frame = cr.system_crop(s["system"])
        first, last = ms[0]["number"], ms[-1]["number"]
        ans, usages, raw = spark.ask_json(REREAD_PROMPT.format(first=first, last=last), system=REREAD_SYSTEM,
                                          image_png=png_bytes(im), tag=f"reread p{s['page']} sys{s['system']}")
        rec = {"page": s["page"], "system": s["system"], "numbers": [m["number"] for m in ms], "crop": frame,
               "ok": "error" not in ans, "answer": ans, "usages": usages, "raw": raw}
        return rec | place_system(model, rec)

    with ThreadPoolExecutor(workers) as ex:
        out = list(ex.map(one, model["systems"]))
    show_placed(out)
    return out


def place_system(model: dict, rec: dict) -> dict:
    """Spark's words for one system -> bars and staves (text_place), with Audiveris's text glyphs and noteheads
    of that system as the geometry to snap and anchor to."""
    s = next(x for x in model["systems"] if x["page"] == rec["page"] and x["system"] == rec["system"])
    nums = set(rec["numbers"])
    ms = [m for m in model["measures"] if m["number"] in nums]
    mine = [i for i in model["inters"] if i["page"] == rec["page"] and i["number"] in nums]
    glyphs = [i for i in mine if i["tag"] in ("word", "dynamics")]
    heads = [{"x": i["bounds"][0] + i["bounds"][2] / 2, "number": i["number"]} for i in mine if i["tag"] == "head"]
    il = next(p["interline"] for p in model["pages"] if p["page"] == rec["page"])
    items = rec["answer"].get("text") if isinstance(rec["answer"].get("text"), list) else []
    placed, dropped = place(items, ms, s["staves"], rec["crop"], glyphs=glyphs, heads=heads, interline=il)
    raw_x, _ = place(items, ms, s["staves"], rec["crop"])  # Spark's point alone, kept to measure what geometry adds
    return {"placed": placed, "dropped": dropped, "placed_spark_x": raw_x}


def show_placed(out: list[dict]) -> None:
    for r in out:
        def show(p):
            note = "" if p["label_agrees"] in (True, None) else f" (label {p['spark_bar']})"
            return f"{p['text']}@{p['number']}{note}"
        txt = ", ".join(show(p) for p in r["placed"])
        print(f"  p{r['page']} sys{r['system']} bars {r['numbers'][0]}..{r['numbers'][-1]} ok={r['ok']}: {txt}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--only", default="verify,reread")
    ap.add_argument("--cap", type=float, default=1.0, help="Spark spend cap in USD for this run directory")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--place-only", action="store_true", help="re-place the stored reread.json answers, no Spark calls")
    a = ap.parse_args()
    run = Path(a.run)
    spark.configure(run / "spend.json", a.cap)
    model = json.load(open(run / "model.json"))
    if a.place_only:
        recs = json.load(open(run / "reread.json"))
        recs = [r | place_system(model, r) for r in recs]
        show_placed(recs)
        (run / "reread.json").write_text(json.dumps(recs, indent=1))
        return
    timings = {}
    for step in a.only.split(","):
        before = spark.spend()
        t0 = time.perf_counter()
        res = verify(run, model, a.workers) if step == "verify" else reread(run, model, a.workers)
        wall = round(time.perf_counter() - t0, 1)
        (run / f"{step}.json").write_text(json.dumps(res, indent=1))
        calls = [u for r in res for u in r["usages"]]
        timings[step] = {"calls": len(calls), "cost_usd": round(sum(u["cost_usd"] for u in calls), 4),
                         "wall_s": wall, "sum_latency_s": round(sum(u["latency_s"] for u in calls), 1),
                         "output_tokens_max": max((u["output_tokens"] for u in calls), default=0),
                         "truncated": sum(u.get("stop_reason") == "max_tokens" for u in calls),
                         "spend_before": before["total_usd"]}
        print(f"{step}: {timings[step]}")
    prev = json.loads((run / "spark_timings.json").read_text()) if (run / "spark_timings.json").exists() else {}
    (run / "spark_timings.json").write_text(json.dumps(prev | timings, indent=1))
    print(f"spend total ${spark.spend()['total_usd']:.4f}")


if __name__ == "__main__":
    main()
