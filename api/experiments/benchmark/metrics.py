"""Scoring for the benchmark. Pure functions, no I/O, no model: each takes a parsed answer and the manifest's
ground truth and returns a small dict of counts that `aggregate` sums over a grid cell.

  header   staff count and instrument count against the page, plus per-box family accuracy
  labels   per system: the wanted staves exactly right ("absent" = empty list)
  text     dynamics/direction words per bar, precision/recall/F1 with placement fuzzy by one bar (005's rule)
  closed   verdict in the accepted set (and the printed value for a dynamic)
  omr      pitch and onset+pitch multisets per bar, both staves merged (005's compare.py)
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from typing import Any

from app.librarian.header import family as _family


def prf(tp: int, pred: int, gold: int) -> tuple[float, float, float]:
    p = tp / pred if pred else 0.0
    r = tp / gold if gold else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return round(p, 3), round(r, 3), round(f, 3)


def multiset_tp(pred: Counter, gold: Counter) -> tuple[int, int, int]:
    return sum((pred & gold).values()), sum(pred.values()), sum(gold.values())


# ---------------------------------------------------------------- header

def entry_family(inst: dict) -> str | None:
    """The family key of one header entry: its label, then its abbreviations, then its family field
    (keyboard -> piano, voice -> chorus); None for an entry the model marked as no instrument."""
    for name in [inst.get("label") or inst.get("name") or "", *(inst.get("abbreviations") or [])]:
        f = _family(name) if name else None
        if f:
            return f
    fam = (inst.get("family") or "").lower()
    return {"keyboard": "piano", "voice": "chorus", "vocal": "chorus"}.get(fam)


def score_header(reconciled: dict, gt: dict) -> dict[str, Any]:
    """`reconciled` is app.librarian.header.reconcile(answer, geom). Entries the model itself calls no instrument
    (no known name and family other, e.g. "page edge, no staff") are not counted; a real instrument put on a fake
    box still counts (its staff is real, the box assignment is wrong and box accuracy says so)."""
    real = [i for i in reconciled.get("instruments") or []
            if not (entry_family(i) is None and (i.get("family") or "").lower() in ("other", ""))]
    staves = sum(int(i.get("staves") or 1) for i in real)
    box_fam = {b: entry_family(i) for i in reconciled.get("instruments") or [] for b in (i.get("boxes") or [])}
    gt_boxes = {int(k): v for k, v in (gt.get("boxes") or {}).items()}
    box_ok = sum(1 for b, ok in gt_boxes.items() if box_fam.get(b) in ok)
    return {"staves_ok": int(staves == gt["staves"]), "instruments_ok": int(len(real) in gt["instruments"]),
            "staves": staves, "instruments": len(real), "box_ok": box_ok, "box_n": len(gt_boxes), "header_n": 1}


# ---------------------------------------------------------------- labels

def normalise_systems(gt_systems: dict) -> dict[int, list[int]]:
    return {int(k): ([] if v == "absent" or v is None else sorted(int(x) for x in v)) for k, v in gt_systems.items()}


def score_labels(answer: dict, gt: dict) -> dict[str, Any]:
    """Per system: the answer's wanted_staves equal the GT list (status "absent" or an empty list = absent).
    A system missing from the answer counts as wrong."""
    want = normalise_systems(gt["systems"])
    got: dict[int, list[int]] = {}
    for s in answer.get("systems") or []:
        try:
            idx = int(s.get("index"))
        except (TypeError, ValueError):
            continue
        staves = s.get("wanted_staves") or []
        if str(s.get("status", "")).lower() == "absent":
            staves = []
        try:
            got[idx] = sorted(int(x) for x in staves)
        except (TypeError, ValueError):
            got[idx] = [-1]
    ok = sum(1 for k, v in want.items() if got.get(k) == v)
    return {"systems_ok": ok, "systems_n": len(want), "page_ok": int(ok == len(want)),
            "wrong": {k: got.get(k) for k, v in want.items() if got.get(k) != v}}


# ---------------------------------------------------------------- text layer

def norm_word(w: str) -> str:
    w = w.strip().lower()
    return w.rstrip(".") + ("." if w.endswith(".") else "")


def split_words(items: Iterable[str]) -> set[str]:
    out = set()
    for t in items:
        for w in re.split(r"\s+", str(t or "").strip()):
            if w:
                out.add(norm_word(w))
    return out


def score_text(answer_bars: dict[int, Iterable[str]], gt_bars: dict, bars: Iterable[int]) -> dict[str, int]:
    """005's rule, per bar in `bars`: predicted words are a set; tp = words that sit in this bar's GT or a
    neighbour's (placement is fuzzy by a bar), capped at this bar's GT size. Summed over the bars."""
    gt = {int(k): {norm_word(w) for w in v} for k, v in gt_bars.items()}
    tp = pred = gold = 0
    for n in bars:
        words = split_words(answer_bars.get(n, []))
        tgt = gt.get(n, set())
        near = tgt | gt.get(n - 1, set()) | gt.get(n + 1, set())
        tp += min(len(words & near), len(tgt)) if tgt else 0
        pred += len(words)
        gold += len(tgt)
    return {"tp": tp, "pred": pred, "gold": gold}


def text_answer_bars(answer: dict) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for m in answer.get("measures") or []:
        try:
            out[int(m.get("number"))] = [str(t) for t in (m.get("text") or [])]
        except (TypeError, ValueError):
            continue
    return out


# ---------------------------------------------------------------- closed questions

def score_closed(answer: dict, gt: dict) -> dict[str, int]:
    verdict = str(answer.get("verdict") or "").strip().lower()
    ok = verdict in [a.lower() for a in gt["accept"]]
    if ok and gt.get("value"):
        ok = str(answer.get("value") or "").strip().lower().rstrip(".") == str(gt["value"]).lower()
    return {"right": int(ok), "n": 1}


# ---------------------------------------------------------------- OMR

def score_omr_bars(pred_bars: dict[int, dict[str, Counter]], gold_bars: dict[int, dict[str, Counter]],
                   bars: Iterable[int]) -> dict[str, int]:
    """pred/gold: bar -> {"pitch": Counter(midi), "onset_pitch": Counter((onset, midi))}, staves merged."""
    out = {"pitch_tp": 0, "pitch_pred": 0, "pitch_gold": 0, "op_tp": 0, "op_pred": 0, "op_gold": 0}
    for n in bars:
        p, g = pred_bars.get(n, {}), gold_bars.get(n, {})
        for key, pre in (("pitch", "pitch"), ("onset_pitch", "op")):
            tp, np_, ng = multiset_tp(p.get(key, Counter()), g.get(key, Counter()))
            out[f"{pre}_tp"] += tp
            out[f"{pre}_pred"] += np_
            out[f"{pre}_gold"] += ng
    return out


def gold_omr_bars(gt: dict, bars: Iterable[int]) -> dict[int, dict[str, Counter]]:
    """From gt/goldberg-aria.json (ly_gt.py): skip rests, grace notes and tie continuations."""
    from fractions import Fraction

    out = {}
    for n in bars:
        pitch, op = Counter(), Counter()
        for staff in ("upper", "lower"):
            for r in gt["bars"].get(str(n), {}).get(staff, []):
                if r["midi"] is None or r["grace"] or r["tie_stop"]:
                    continue
                pitch[r["midi"]] += 1
                op[(Fraction(r["onset"]), r["midi"])] += 1
        out[n] = {"pitch": pitch, "onset_pitch": op}
    return out


# ---------------------------------------------------------------- aggregation

SUMMED = ("header_n", "staves_ok", "instruments_ok", "box_ok", "box_n", "systems_ok", "systems_n", "page_ok", "tp", "pred", "gold",
          "right", "n", "pitch_tp", "pitch_pred", "pitch_gold", "op_tp", "op_pred", "op_gold")


def aggregate(records: list[dict]) -> dict[str, Any]:
    """One grid cell's numbers from its call records (status ok / json_fail / error / refusal)."""
    done = [r for r in records if r.get("status") in ("ok", "json_fail", "refusal")]
    tot: Counter = Counter()
    for r in done:
        for k, v in (r.get("score") or {}).items():
            if k in SUMMED and isinstance(v, (int, float)):
                tot[k] += v
    calls = len(done)
    out: dict[str, Any] = {
        "calls": calls, "errors": sum(1 for r in records if r.get("status") == "error"),
        "cost_usd": round(sum(float(r.get("cost_usd") or 0) for r in records), 5),
        "latency_s_mean": round(sum(float(r.get("latency_s") or 0) for r in done) / calls, 1) if calls else None,
        "json_fail_rate": round(sum(1 for r in done if r.get("json_fail_first")) / calls, 3) if calls else None,
        "json_fail_final": sum(1 for r in done if r.get("status") in ("json_fail", "refusal")),
        "items": calls,
    }
    out["accuracy"] = accuracy(dict(tot))
    return out


def accuracy(t: dict) -> dict[str, Any]:
    """Headline numbers from summed counts; only the keys a task produced appear."""
    acc: dict[str, Any] = {}
    if "box_n" in t:
        acc["staves_ok"] = f"{t.get('staves_ok', 0)}/{t.get('header_n', 0)}"
        acc["instruments_ok"] = f"{t.get('instruments_ok', 0)}/{t.get('header_n', 0)}"
        acc["box_acc"] = round(t["box_ok"] / t["box_n"], 3) if t["box_n"] else None
    if "systems_n" in t:
        acc["label_acc"] = round(t["systems_ok"] / t["systems_n"], 3) if t["systems_n"] else None
        acc["pages_ok"] = t.get("page_ok", 0)
    if "gold" in t:
        acc["text_prf"] = prf(t.get("tp", 0), t.get("pred", 0), t["gold"])
    if "n" in t:
        acc["closed_acc"] = round(t["right"] / t["n"], 3) if t["n"] else None
    if "pitch_gold" in t:
        acc["pitch_prf"] = prf(t["pitch_tp"], t["pitch_pred"], t["pitch_gold"])
        acc["onset_pitch_prf"] = prf(t["op_tp"], t["op_pred"], t["op_gold"])
    return acc
