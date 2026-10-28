"""Score an OMR result against ground truth, by global bar number.

  text   dynamics and direction words per bar against goldberg_bga_text_gt.json: tokens lower-cased with the
         dots stripped ("cresc." = "cresc"), multisets per bar. Strict = the right bar; near = the right bar or
         a neighbour (the p1-3 run's metric was near). Precision counts every predicted word in the range.
  notes  per bar against the Open Goldberg Aria ground truth (gt.json from the p1-3 run, bars 1-32): pitch,
         onset+pitch, full (onset+pitch+duration), ornaments, and bars where every voice adds up to 3/4;
         staves merged per bar (editions differ in which staff a middle voice is engraved on).

Usage:
  uv run python experiments/omr/compare.py OUT.json --text-gt GT.json [--notes-gt gt.json]
      --score final.musicxml[:offset] [more files with offsets, e.g. final-mvt2.musicxml:32] [--bars 1-69]
      [--reread reread.json]   also score the placement methods on Spark's own answers (x refined, Spark x, label)
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from fractions import Fraction
from pathlib import Path

ORN_NAMES = ("Mordent", "InvertedMordent", "Trill", "Turn", "InvertedTurn", "Schleifer", "Shake")


def norm(word: str) -> str:
    return re.sub(r"\.", "", word.strip().lower())


def text_score(pred: dict[int, list[str]], gold: dict[int, list[str]], bars: range, near: int = 0) -> dict:
    """Multiset match per bar; with near=1 a predicted word may also match a gold word one bar away (exact bar
    first). Returns tp, pred, gold, P/R/F1."""
    P = {b: Counter(norm(w) for w in pred.get(b, [])) for b in bars}
    G = {b: Counter(norm(w) for w in gold.get(b, [])) for b in bars}
    tp = 0
    for b in bars:
        hit = P[b] & G[b]
        tp += sum(hit.values())
        P[b] -= hit
        G[b] -= hit
    if near:
        for b in bars:
            for nb in range(b - near, b + near + 1):
                if nb == b or nb not in G:
                    continue
                hit = P[b] & G[nb]
                tp += sum(hit.values())
                P[b] -= hit
                G[nb] -= hit
    n_pred = sum(len(pred.get(b, [])) for b in bars)
    n_gold = sum(len(gold.get(b, [])) for b in bars)
    p = tp / n_pred if n_pred else 0.0
    r = tp / n_gold if n_gold else 0.0
    return {"tp": tp, "pred": n_pred, "gold": n_gold, "p": round(p, 3), "r": round(r, 3),
            "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0}


def load_scores(specs: list[str]):
    """[(music21 score, offset)] from "path[:offset]" specs."""
    from music21 import converter
    out = []
    for spec in specs:
        path, _, off = spec.rpartition(":") if re.search(r":\d+$", spec) else (spec, "", "0")
        out.append((converter.parse(path), int(off or 0)))
    return out


def text_of(scores) -> dict[int, list[str]]:
    from music21 import dynamics, expressions, stream
    out: dict[int, list[str]] = {}
    for sc, off in scores:
        for part in sc.parts:
            for m in part.getElementsByClass(stream.Measure):
                for el in m.recurse():
                    if isinstance(el, dynamics.Dynamic):
                        out.setdefault(m.number + off, []).append(el.value)
                    elif isinstance(el, expressions.TextExpression):
                        if str(getattr(el.style, "fontWeight", "") or "").lower() == "bold":
                            continue                       # a tempo heading (v2 writes it bold on bar 1): not text in the ground truth
                        out.setdefault(m.number + off, []).extend(el.content.split())
    return out


def bar_count(scores) -> int:
    from music21 import stream
    return sum(len(list(sc.parts[0].getElementsByClass(stream.Measure))) for sc, _ in scores)


def notes_score(scores, gt: dict) -> dict:
    from music21 import chord, note, stream
    bars = {}
    for sc, off in scores:
        ps = list(sc.parts)
        for staff, part in (("upper", ps[0]), ("lower", ps[1])):
            for m in part.getElementsByClass(stream.Measure):
                bars.setdefault(m.number + off, {})[staff] = m
    cats = ("pitch", "onset_pitch", "full", "ornaments")
    tot = {c: [0, 0, 0] for c in cats}
    rhythm_ok, n = 0, 0
    for key in sorted(gt["bars"], key=int):
        b = int(key)
        n += 1
        G = {c: Counter() for c in cats}
        O = {c: Counter() for c in cats}
        ok = True
        for staff in ("upper", "lower"):
            for r in gt["bars"][key][staff]:
                if r["midi"] is None or r["grace"]:
                    continue
                for _ in r["ornaments"]:
                    G["ornaments"][r["midi"]] += 1
                if r["tie_stop"]:
                    continue
                on, d = Fraction(r["onset"]), Fraction(r["dur"])
                G["pitch"][r["midi"]] += 1
                G["onset_pitch"][(on, r["midi"])] += 1
                G["full"][(on, r["midi"], d)] += 1
            m = bars.get(b, {}).get(staff)
            if m is None:
                ok = False
                continue
            longest = Fraction(0)
            for v in (list(m.voices) if m.voices else [m]):
                total = Fraction(0)
                for el in v.notesAndRests:
                    if el.duration.isGrace:
                        continue
                    total = max(total, Fraction(el.offset) + Fraction(el.duration.quarterLength))
                    ns = el.notes if isinstance(el, chord.Chord) else ([el] if isinstance(el, note.Note) else [])
                    for nn in ns:
                        if any(type(e).__name__ in ORN_NAMES for e in el.expressions):
                            O["ornaments"][nn.pitch.midi] += 1
                        if nn.tie is not None and nn.tie.type in ("stop", "continue"):
                            continue
                        on, d = Fraction(el.offset), Fraction(el.duration.quarterLength)
                        O["pitch"][nn.pitch.midi] += 1
                        O["onset_pitch"][(on, nn.pitch.midi)] += 1
                        O["full"][(on, nn.pitch.midi, d)] += 1
                if total > 3:
                    ok = False
                longest = max(longest, total)
            if longest != 3:
                ok = False
        rhythm_ok += ok
        for c in cats:
            tot[c][0] += sum((O[c] & G[c]).values())
            tot[c][1] += sum(O[c].values())
            tot[c][2] += sum(G[c].values())
    out = {}
    for c, (tp, np_, ng) in tot.items():
        p, r = (tp / np_ if np_ else 0.0), (tp / ng if ng else 0.0)
        out[c] = {"tp": tp, "pred": np_, "gold": ng, "p": round(p, 3), "r": round(r, 3),
                  "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0}
    out["rhythm_ok_bars"] = [rhythm_ok, n]
    return out


def reread_methods(reread: list[dict]) -> dict[str, dict[int, list[str]]]:
    """Spark's words placed three ways: x refined by geometry (what the run writes), Spark's x alone, Spark's
    bar label alone."""
    out = {"x+geometry": {}, "spark_x": {}, "label": {}}
    for r in reread:
        for it in r.get("placed", []):
            out["x+geometry"].setdefault(it["number"], []).append(it["text"])
        for it in r.get("placed_spark_x", []):
            out["spark_x"].setdefault(it["number"], []).append(it["text"])
        for it in (r["answer"].get("text") or []) if isinstance(r["answer"].get("text"), list) else []:
            b = it.get("bar") if isinstance(it, dict) else None
            if isinstance(b, int) and b in r["numbers"] and str(it.get("text", "")).strip():
                out["label"].setdefault(b, []).append(str(it["text"]).strip())
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--score", nargs="+", required=True)
    ap.add_argument("--text-gt", required=True)
    ap.add_argument("--notes-gt")
    ap.add_argument("--bars", help="global bar range for text, e.g. 1-69 (default: the GT range)")
    ap.add_argument("--reread")
    ap.add_argument("--label", default="")
    a = ap.parse_args()
    tg = json.load(open(a.text_gt))
    gold = {int(k): v for k, v in tg["bars"].items()}
    lo, hi = (int(x) for x in a.bars.split("-")) if a.bars else tg["range"]
    bars = range(lo, hi + 1)
    scores = load_scores(a.score)
    pred = text_of(scores)
    res = {"label": a.label, "bars": [lo, hi], "bar_count": bar_count(scores),
           "text_strict": text_score(pred, gold, bars), "text_near": text_score(pred, gold, bars, near=1),
           "text_by_bar": {b: {"pred": pred.get(b, []), "gold": gold.get(b, [])} for b in bars if pred.get(b) or gold.get(b)}}
    if a.notes_gt:
        res["aria_notes"] = notes_score(scores, json.load(open(a.notes_gt)))
    if a.reread:
        methods = reread_methods(json.load(open(a.reread)))
        res["placement_methods"] = {k: {"strict": text_score(v, gold, bars), "near": text_score(v, gold, bars, near=1)}
                                    for k, v in methods.items()}
    Path(a.out).write_text(json.dumps(res, indent=1))
    print(f"== {a.label} bars {lo}..{hi}, {res['bar_count']} bars in the file(s)")
    for k in ("text_strict", "text_near"):
        print(f"  {k:12s} {res[k]}")
    if "aria_notes" in res:
        for k, v in res["aria_notes"].items():
            print(f"  aria {k:12s} {v}")
    for k, v in res.get("placement_methods", {}).items():
        print(f"  placement {k:11s} strict {v['strict']['f1']} ({v['strict']['tp']}/{v['strict']['pred']}/{v['strict']['gold']})"
              f"  near {v['near']['f1']}")


if __name__ == "__main__":
    main()
