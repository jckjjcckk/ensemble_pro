"""Tables for docs/features/013-text-eval.md from results/score_<effort>.json (no calls).

    uv run python -m experiments.voice_text.run score minimal && uv run python -m experiments.voice_text.run score low
    uv run python -m experiments.voice_text.report
"""

from __future__ import annotations

import json
import statistics as st
from collections import Counter
from pathlib import Path

from .cases import CASES

RES = Path(__file__).resolve().parent / "results"
CATS = list(dict.fromkeys(c["cat"] for c in CASES))
FIELDS = ["position", "bars", "audience", "kind", "text", "core"]


def md(head, rows):
    return "\n".join(["| " + " | ".join(map(str, head)) + " |", "|" + "---|" * len(head)]
                     + ["| " + " | ".join(map(str, r)) + " |" for r in rows])


def p90(xs):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(0.9 * (len(xs) - 1))))]


def load(e):
    return json.loads((RES / f"score_{e}.json").read_text())


def main() -> None:
    runs = {e: load(e) for e in ("minimal", "low")}
    out = []
    # headline
    rows = []
    for e, rs in runs.items():
        ins = [r for r in rs if r["instruction"]]
        neg = [r for r in rs if not r["instruction"]]
        fh = [f for r in ins for f in r["field_hits"]]
        secs = [r["seconds"] for r in rs]
        rows.append([e, f"{sum(r['ok'] for r in ins)}/100", f"{sum(r['text_all'] for r in ins)}/100",
                     *[f"{sum(f[k] for f in fh)}/{len(fh)}" for k in FIELDS],
                     f"{sum(not r['ok'] for r in neg)}/30", f"{sum(not r['produced'] for r in ins)}/100",
                     f"{st.median(secs):.2f}", f"{p90(secs):.2f}", f"${sum(r['usd'] for r in rs):.3f}",
                     f"${sum(r['usd'] for r in rs) / len(rs):.4f}", round(st.mean(r["output_tokens"] for r in rs))])
    out.append(md(["effort", "cases fully right", "+ stand text", *[f"field {k}" for k in FIELDS],
                   "false positives", "false negatives", "median s", "p90 s", "cost", "$/call", "out tok"], rows))
    # per category
    rows = []
    for cat in CATS:
        if cat == "non_instruction":
            continue
        r = [cat, sum(c["cat"] == cat for c in CASES)]
        for e, rs in runs.items():
            sub = [x for x in rs if x["cat"] == cat]
            fh = [f for x in sub for f in x["field_hits"]]
            r += [f"{sum(x['ok'] for x in sub)}", f"{sum(x['text_all'] for x in sub)}",
                  "/".join(str(sum(f[k] for f in fh)) for k in ("bars", "audience", "kind")) + f" of {len(fh)}"]
        rows.append(r)
    out.append(md(["category", "n", "min right", "min +text", "min bars/aud/kind", "low right", "low +text",
                   "low bars/aud/kind"], rows))
    # difficulty and audience type
    rows = []
    for d in ("easy", "medium", "hard"):
        rows.append([d, sum(c["diff"] == d and c["instruction"] for c in CASES)]
                    + [sum(x["ok"] for x in rs if x["diff"] == d and x["instruction"]) for rs in runs.values()])
    out.append(md(["difficulty", "n", "minimal right", "low right"], rows))

    def aud_type(c):
        a = {x for ans in c["answers"][:1] for m in ans for s in m["audience"][:1] for x in s}
        if any(x.startswith("member:") for x in a):
            return "named member"
        if a == {"ensemble"}:
            return "everyone"
        return "part(s)"
    rows = []
    for t in ("everyone", "part(s)", "named member"):
        ids = {c["id"] for c in CASES if c["instruction"] and aud_type(c) == t}
        rows.append([t, len(ids)] + [sum(x["ok"] for x in rs if x["id"] in ids) for rs in runs.values()])
    out.append(md(["audience (first answer)", "n", "minimal right", "low right"], rows))
    # multi
    rows = []
    for e, rs in runs.items():
        sub = [x for x in rs if x["cat"] == "multi"]
        alt = Counter((x["id"], x["answer_index"], x["n_produced"]) for x in sub)
        rows.append([e, f"{sum(x['ok'] for x in sub)}/10", ", ".join(f"{i}: {n} mark(s), answer {a}" for (i, a, n) in sorted(alt))])
    out.append(md(["effort", "multi right", "marks produced per case (answer 0 = first listed)"], rows))
    # confidence
    for e, rs in runs.items():
        right = [c for x in rs if x["instruction"] for c, ok in x["mark_conf"] if ok]
        wrong = [c for x in rs if x["instruction"] for c, ok in x["mark_conf"] if not ok]
        fp = [c for x in rs if not x["instruction"] for c, _ in x["mark_conf"]]
        neg_none = [x["none_conf"] for x in rs if not x["instruction"] and x["none_conf"] is not None]
        fn_none = [x["none_conf"] for x in rs if x["instruction"] and not x["produced"]]
        rows = []
        for name, xs in [("right marks", right), ("wrong marks", wrong), ("marks on non-instructions", fp),
                         ("none on non-instructions (none-confidence)", neg_none),
                         ("none on instructions (missed; none-confidence)", fn_none)]:
            xs = [x for x in xs if x is not None]
            rows.append([name, len(xs), min(xs) if xs else "", st.median(xs) if xs else "", max(xs) if xs else "",
                         ", ".join(f"{k}: {v}" for k, v in sorted(Counter(xs).items()))])
        out.append(f"**{e}**\n\n" + md(["group", "n", "min", "median", "max", "values (value: count)"], rows))
        rows = []
        for t in (0.8, 0.9, 0.95):
            auto = [(c, ok) for x in rs for c, ok in (x["mark_conf"] if x["instruction"] else [(c, False) for c, _ in x["mark_conf"]])
                    if c is not None and c >= t]
            cases_all = [x for x in rs if x["instruction"] and x["mark_conf"] and all((c or 0) >= t for c, _ in x["mark_conf"])]
            rows.append([f"≥ {t}", f"{len(auto)}/{len(right) + len(wrong) + len(fp)}", sum(not ok for _, ok in auto),
                         f"{sum(ok for _, ok in auto) / len(auto):.3f}" if auto else "",
                         f"{len(cases_all)}/100", sum(not x["ok"] for x in cases_all)])
        out.append(md(["threshold", "marks auto-applied", "of those wrong", "precision", "instructions wholly auto-applied",
                       "of those not fully right"], rows))
    # run-to-run disagreement
    a, b = ({x["id"]: x for x in rs} for rs in runs.values())
    dis = [i for i in a if a[i]["ok"] != b[i]["ok"]]
    out.append("Cases scored differently by minimal and low: " + ", ".join(
        f"{i} (minimal {'right' if a[i]['ok'] else 'wrong'}, low {'right' if b[i]['ok'] else 'wrong'})" for i in dis))
    # text flags
    flags = []
    for e, rs in runs.items():
        for x in rs:
            if x["instruction"]:
                for g, p, ok in x["pair_text"]:
                    if p is not None and not ok:
                        flags.append([e, x["id"], x["text"], g, p])
    out.append(md(["effort", "id", "said", "reference", "Spark's stand text"], flags))
    print("\n\n".join(out))


if __name__ == "__main__":
    main()
