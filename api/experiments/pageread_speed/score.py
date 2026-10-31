"""Step 3: score every chain against the ground truth and against A, print markdown tables.

Ground truth: bars per page (004's by-eye table; geometry, so the same in every variant), the 016 corpus label GT
(the piano / soprano staves per system, mapped onto `page_measures`' staff numbers: Rach 1 aligns 1:1; Beethoven 9's
page-edge fakes are masked so the soprano is staff 12 of 16 on every page, checked by eye on p173), first bars as
printed (Goldberg, Rach 1, Chopin; Beethoven 9 prints none), and the landmarks of today's eval (013 v4e, counted by
eye on the annotated pages, same boxes: the geometry here is identical to that run's).

    cd api && uv run python -m experiments.pageread_speed.score
"""
from __future__ import annotations

import json
import statistics as st
from collections import defaultdict

from .common import RESULTS

RUNS = RESULTS / "runs"
BARS = {"goldberg-bga-p01": 28, "goldberg-bga-p02": 20, "goldberg-bga-p03": 21, "rach1-gutheil-p01": 4, "rach1-gutheil-p02": 9,
        "rach1-gutheil-p03": 9, "beethoven9-p172": 9, "beethoven9-p173": 5, "beethoven9-p174": 9, "beethoven9-p175": 6,
        "chopin-p14": 18, "chopin-p15": 16, "chopin-p16": None}
FIRST = {"goldberg-bga-p01": 1, "goldberg-bga-p02": 29, "goldberg-bga-p03": 17, "rach1-gutheil-p01": 1, "rach1-gutheil-p02": 5,
         "rach1-gutheil-p03": 14, "chopin-p14": 20, "chopin-p15": 38, "chopin-p16": 54}
# system -> 1-based staves of the instrument inside the system, or None (absent)
LABEL_GT = {"rach1-gutheil-p01": ("piano", {1: [11, 12]}), "rach1-gutheil-p02": ("piano", {1: [1, 2], 2: [11, 12]}),
            "rach1-gutheil-p03": ("piano", {1: [6, 7], 2: None}),
            **{f"beethoven9-p{n}": ("soprano", {1: [12]}) for n in (172, 173, 174, 175)},
            **{p: ("piano", {s: [1, 2] for s in range(1, 7 if p.startswith("goldberg") else 6)})
               for p in ("goldberg-bga-p01", "goldberg-bga-p02", "goldberg-bga-p03", "chopin-p14", "chopin-p15", "chopin-p16")}}
# landmarks: (kinds, boxes, name). A double bar at an end repeat's box is that barline named the wrong way ("half").
LM_TRUTH = {
    "goldberg-bga-p02": [("repeat:end", {4}, "end repeat 4"), ("section", {5}, "Var. 1"), ("tempo", {5}, "Allegro moderato"),
                         ("repeat:end", {20}, "end repeat 20")],
    "goldberg-bga-p03": [("repeat:start", {1}, "start repeat 1"), ("repeat:end", {16}, "end repeat 16"), ("section", {17}, "Var. 2"),
                         ("tempo", {17}, "Allegretto"), ("meter_change", {17}, "2/4")],
    "chopin-p14": [("tempo", {10}, "ritenuto 10"), ("tempo", {16}, "ritenuto 16"), ("repeat:end", {18}, "end repeat 18"),
                   ("fine", {18}, "Fine"), ("key_change", {19}, "key change (5 flats)")],
    "chopin-p15": [("repeat:start", {1}, "start repeat 1"), ("tempo", {1}, "meno mosso"), ("tempo", {8, 9}, "ritenuto 8"),
                   ("repeat:end", {14}, "end repeat 14")],
    "chopin-p16": [("repeat:start", {1}, "start repeat 1"), ("tempo", {15}, "ritenuto 15")],
}
# printed but not a landmark the eval counted, so neither found nor invented: the 3/4 at Var. 1 (same meter), a metronome
# mark listed apart from its tempo word
LM_NEUTRAL = {"goldberg-bga-p02": [("meter_change", 5)]}
KEYBOARD = {"goldberg", "chopin"}


def kind_of(d):
    if d["kind"] == "repeat":
        return "repeat:start" if "start" in d["text"].lower() else "repeat:end"
    return d["kind"]


def score_landmarks(page, kept):
    truth = LM_TRUTH[page]
    used, found, half, missed = set(), [], [], []
    for k, boxes, name in truth:
        hit = next((i for i, d in enumerate(kept) if i not in used and kind_of(d) == k and d["provisional"] in boxes), None)
        if hit is not None:
            used.add(hit); found.append(name); continue
        alt = {"repeat:end": "double_bar", "repeat:start": "double_bar"}.get(k)
        hit = next((i for i, d in enumerate(kept) if i not in used and d["kind"] == alt and d["provisional"] in boxes), None)
        if hit is not None:
            used.add(hit); half.append(name); continue
        missed.append(name)
    invented = []
    for i, d in enumerate(kept):
        if i in used:
            continue
        if d["kind"] == "tempo" and any(d["provisional"] in b for k, b, _ in truth if k == "tempo"):
            continue        # metronome mark given apart from its tempo word
        if d["kind"] == "double_bar" and any(d["provisional"] in b for k, b, _ in truth if k.startswith("repeat")):
            continue        # the same barline as a repeat already counted
        if (d["kind"], d["provisional"]) in LM_NEUTRAL.get(page, []):
            continue
        invented.append(f"{d['kind']} '{d['text']}' box {d['provisional']}")
    return {"n": len(truth), "found": len(found), "half": len(half), "missed": missed, "half_names": half, "invented": invented}


def span_of(parts, spp, pos):
    s = 1
    for name, k in zip(parts, spp):
        if s <= pos < s + k:
            return name, list(range(s, s + k))
        s += k
    return None, []


def score_labels(page, labels):
    inst, gt = LABEL_GT[page]
    sysmap = {int(s.get("index", 0)): s for s in labels["systems"]}
    ok, n, bad = 0, 0, []
    for si, staves in gt.items():
        n += 1
        s = sysmap.get(si)
        if not s:
            bad.append(f"system {si} missing"); continue
        parts, spp = [str(p) for p in s.get("parts") or []], [int(x) for x in s.get("staves_per_part") or []]
        if len(spp) != len(parts):
            spp = [1] * len(parts) if len(parts) else []
        if staves is None:
            if any("piano" in p.lower() for p in parts):
                bad.append(f"system {si}: piano named where it rests")
            else:
                ok += 1
            continue
        name, span = span_of(parts, spp, staves[0])
        low = (name or "").lower()
        if inst == "piano":
            good = name is not None and ("piano" in low or "klav" in low or "pf" in low) and span == staves
        else:
            good = name is not None and (("sopran" in low and span == staves) or (any(w in low for w in ("coro", "chor")) and "alt" not in low
                                                                                  and "ten" not in low and "bass" not in low and span[0] == staves[0]))
        if good:
            ok += 1
        else:
            bad.append(f"system {si}: staff {staves[0]} read as {name!r} (staves {span})")
    return ok, n, bad


def load():
    recs = []
    for f in sorted(RUNS.glob("*.json")):
        book = f.stem.split("-", 2)[2]
        for r in json.loads(f.read_text()):
            r["book"] = book
            recs.append(r)
    return recs


def pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return float("nan")
    k = (len(xs) - 1) * q
    lo = int(k)
    return xs[lo] + (xs[min(lo + 1, len(xs) - 1)] - xs[lo]) * (k - lo)


def main():
    recs = load()
    by = defaultdict(list)
    for r in recs:
        r["group"] = "keyboard" if r["book"] in KEYBOARD else "orchestral"
        if r.get("labels"):
            r["lab"] = score_labels(r["page"], r["labels"])
            fm = FIRST.get(r["page"])
            r["first_ok"] = None if fm is None else int(r["labels"]["first_measure_number"] == fm)
            if r["page"] in LM_TRUTH:
                r["lm"] = score_landmarks(r["page"], r["labels"]["landmarks"])
        by[r["variant"]].append(r)

    print("## Speed and cost\n")
    print("| variant | pages | group | median s | p90 s | median out tok | median reasoning tok | $/page | parse fails |")
    print("|---|---|---|---|---|---|---|---|---|")
    for v in "ABCD":
        for g in ("all", "keyboard", "orchestral", "trimmed pages only"):
            rs = [r for r in by[v] if g == "all" or r["group"] == g or (g == "trimmed pages only" and not r["first_page"])]
            if not rs:
                continue
            secs = [r["seconds"] for r in rs]
            outs = [r["output_tokens"] for r in rs]
            rea = [r["reasoning_tokens"] for r in rs if r.get("reasoning_tokens") is not None]
            print(f"| {v} | {len(rs)} | {g} | {st.median(secs):.1f} | {pct(secs, .9):.1f} | {st.median(outs):.0f} | "
                  f"{st.median(rea) if rea else '-'} | {sum(r['usd'] for r in rs) / len(rs):.4f} | {sum(1 for r in rs if r['parse_error'] or len(r['attempts']) > 1)} |")

    print("\n## Accuracy\n")
    print("| variant | label systems right | pages that would park | first bar right (book's first page) | first bar right (all pages with GT) | Spark-doubted boxes | landmarks found (+ named wrong) of 20 per run | invented |")
    print("|---|---|---|---|---|---|---|---|")
    for v in "ABCD":
        rs = [r for r in by[v] if r.get("labels")]
        lab_ok = sum(r["lab"][0] for r in rs); lab_n = sum(r["lab"][1] for r in rs)
        park = sum(1 for r in rs if r.get("question"))
        fb1 = [r["first_ok"] for r in rs if r["first_page"] and r["first_ok"] is not None]
        fba = [r["first_ok"] for r in rs if r["first_ok"] is not None]
        dbt = sum(len(r["labels"]["doubtful"]) for r in rs)
        lm = defaultdict(lambda: [0, 0, 0])
        for r in rs:
            if "lm" in r:
                lm[r["run"]][0] += r["lm"]["found"]; lm[r["run"]][1] += r["lm"]["half"]; lm[r["run"]][2] += len(r["lm"]["invented"])
        lms = ", ".join(f"r{k}: {a[0]} (+{a[1]})" for k, a in sorted(lm.items()))
        inv = ", ".join(f"r{k}: {a[2]}" for k, a in sorted(lm.items()))
        print(f"| {v} | {lab_ok}/{lab_n} | {park} | {sum(fb1)}/{len(fb1)} | {sum(fba)}/{len(fba)} | {dbt} | {lms} | {inv} |")

    print("\n## Per page, per run (labels ok/n, first bar, doubted boxes, landmarks found/half/invented, s, out tok)\n")
    pages = list(dict.fromkeys(r["page"] for r in recs))
    order = sorted(pages, key=lambda p: (p.split("-")[0], p))
    print("| page | bars (geometry / truth) | " + " | ".join(f"{v}{k}" for v in "ABCD" for k in (1, 2)) + " |")
    print("|---|---|" + "---|" * 8)
    for p in order:
        cells = []
        nb = None
        for v in "ABCD":
            for k in (1, 2):
                r = next((x for x in by[v] if x["page"] == p and x["run"] == k), None)
                if not r or not r.get("labels"):
                    cells.append("parse fail" if r else "-"); continue
                nb = r["n_boxes"]
                L = r["labels"]
                c = f"{r['lab'][0]}/{r['lab'][1]}, {L['first_measure_number']}, d{len(L['doubtful'])}"
                if "lm" in r:
                    c += f", lm {r['lm']['found']}/{r['lm']['half']}/{len(r['lm']['invented'])}"
                if r.get("question"):
                    c += ", PARK"
                c += f", {r['seconds']:.1f}s, {r['output_tokens']}"
                cells.append(c)
        print(f"| {p} | {nb} / {BARS.get(p) or '-'} | " + " | ".join(cells) + " |")

    print("\n## Every difference from A (labels, first bar, doubted boxes, landmarks, parking)\n")
    for p in order:
        a = [x for x in by["A"] if x["page"] == p and x.get("labels")]
        for v in "BCD":
            for r in [x for x in by[v] if x["page"] == p and x.get("labels")]:
                diffs = []
                L = r["labels"]
                if r["lab"][2] and not any(x["lab"][2] == r["lab"][2] for x in a):
                    diffs.append("labels: " + "; ".join(r["lab"][2]))
                staves = [[int(n) for n in s.get("staves_per_part") or []] for s in L["systems"]]
                if all(staves != [[int(n) for n in s.get("staves_per_part") or []] for s in x["labels"]["systems"]] for x in a):
                    diffs.append(f"staves per part {staves} (A: {[[s.get('staves_per_part') for s in x['labels']['systems']] for x in a]})")
                if all(L["first_measure_number"] != x["labels"]["first_measure_number"] for x in a):
                    diffs.append(f"first bar {L['first_measure_number']} (A: {[x['labels']['first_measure_number'] for x in a]})")
                dset = sorted(int(k) for k in L["doubtful"])
                if all(dset != sorted(int(k) for k in x["labels"]["doubtful"]) for x in a):
                    diffs.append(f"doubted boxes {dset} (A: {[sorted(int(k) for k in x['labels']['doubtful']) for x in a]})")
                if "lm" in r:
                    for key in ("missed", "invented", "half_names"):
                        if all(sorted(r["lm"][key]) != sorted(x["lm"][key]) for x in a):
                            diffs.append(f"landmarks {key} {r['lm'][key]} (A: {[x['lm'][key] for x in a]})")
                if r.get("question"):
                    diffs.append(f"would park: {r['question'][:160]}")
                if diffs:
                    print(f"- **{p} {v}{r['run']}**: " + " | ".join(diffs))

    (RESULTS / "scored.json").write_text(json.dumps(recs, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
