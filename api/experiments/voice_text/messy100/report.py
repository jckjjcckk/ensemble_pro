"""Tables for docs/features/013-v4e-eval.md from results/score_*.json (no calls).

    uv run python -m experiments.voice_text.messy100.run score && uv run python -m experiments.voice_text.messy100.report
"""

from __future__ import annotations

import json
import statistics as st
from collections import Counter

from .cases import CASES
from .run import RESULTS

CATS = list(dict.fromkeys(c["cat"] for c in CASES))
P = ("v4d", "v4e")
RUNS = {f"{p}_r{r}": json.loads((RESULTS / f"score_{p}_r{r}.json").read_text()) for p in P for r in (1, 2)}
FIELDS = ["position", "bars", "audience", "kind", "text", "core"]


def md(head, rows):
    return "\n".join(["| " + " | ".join(map(str, head)) + " |", "|" + "---|" * len(head)]
                     + ["| " + " | ".join(map(str, r)) + " |" for r in rows])


def p90(xs):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(0.9 * (len(xs) - 1))))]


def canon(r):
    return json.dumps(sorted(json.dumps({k: m.get(k) for k in ("position", "bar_from", "bar_to", "audience", "kind")},
                                        sort_keys=True) for m in r["marks"]))


def main() -> None:
    out = []
    rows = []
    for tag, rs in RUNS.items():
        fh = [f for r in rs for f in r["field_hits"]]
        none_only = [r for r in rs if not r["instruction"]]
        secs = [r["seconds"] for r in rs]
        rows.append([tag, f"{sum(r['ok'] for r in rs)}/100", f"{sum(r['text_all'] for r in rs)}/100",
                     *[f"{sum(f[k] for f in fh)}/{len(fh)}" for k in FIELDS],
                     f"{sum(not r['ok'] for r in none_only)}/{len(none_only)}",
                     f"{sum(r['instruction'] and not r['none_ok'] and not r['produced'] for r in rs)}",
                     f"{st.median(secs):.2f}", f"{p90(secs):.2f}", f"${sum(r['usd'] for r in rs):.3f}",
                     f"${sum(r['usd'] for r in rs) / len(rs):.4f}", round(st.mean(r["output_tokens"] for r in rs))])
    out.append(md(["run", "cases right", "+ stand text", *[f"field {k}" for k in FIELDS], "false positives (none-only)",
                   "missed (no mark)", "median s", "p90 s", "cost", "$/call", "out tok"], rows))

    def grid(keyf, keys, label):
        rows = []
        for k in keys:
            n = sum(keyf(c) == k for c in CASES)
            rows.append([k, n] + [sum(r["ok"] for r in rs if keyf(r) == k) for rs in RUNS.values()])
        return md([label, "n", *RUNS], rows)
    out.append(grid(lambda c: c["cat"], CATS, "category"))
    out.append(grid(lambda c: c["diff"], [1, 2, 3], "difficulty"))
    out.append(grid(lambda c: c["fix"], ["A", "B"], "book"))
    out.append(grid(lambda c: c["term"] or "-", ["listed", "unlisted", "part"], "term cases"))
    # landmark: v4d unplaced but otherwise right
    out.append("Landmark cases where the answer is wrong only by being left unplaced (position mark, null bars, "
               "audience and kind right): " + ", ".join(
                   f"{t} {sum(r['unplaced_ok'] for r in rs if r['cat'] == 'landmark')}/20" for t, rs in RUNS.items()))
    # agreement
    rows = []
    for p in P:
        a, b = ({r["id"]: r for r in RUNS[f"{p}_r{i}"]} for i in (1, 2))
        same_ok = sum(a[i]["ok"] == b[i]["ok"] for i in a)
        same_out = sum(canon(a[i]) == canon(b[i]) for i in a)
        flips = [i for i in a if a[i]["ok"] != b[i]["ok"]]
        both = sum(a[i]["ok"] and b[i]["ok"] for i in a)
        rows.append([p, f"{same_ok}/100", f"{same_out}/100", both, ", ".join(flips) or "none"])
    out.append(md(["prompt", "same right/wrong", "identical marks (fields)", "right both runs", "flips"], rows))
    # unrecoverable
    rows = []
    for c in [c for c in CASES if c["cat"] == "unrecoverable"]:
        cells = []
        for t, rs in RUNS.items():
            r = next(x for x in rs if x["id"] == c["id"])
            cells.append("none" + (f" {r['none_conf']}" if r["none_conf"] is not None else "") if not r["marks"] else
                         "; ".join(f"{m.get('position')} {m.get('bar_from')} {','.join(a.replace('part:', '') for a in m['audience'])} "
                                   f"\"{m.get('text')}\" {m.get('confidence')}" for m in r["marks"]))
        rows.append([c["id"], "none or mark" if c["instruction"] else "none", c["text"], *cells])
    out.append(md(["id", "truth", "said", *RUNS], rows))
    # confidence, pooled over the two runs
    for p in P:
        rs = RUNS[f"{p}_r1"] + RUNS[f"{p}_r2"]
        allm = [(c, ok) for r in rs for c, ok in r["mark_conf"]]
        right = [c for c, ok in allm if ok]
        wrong = [c for c, ok in allm if not ok]
        rows = []
        for name, xs in (("right marks", right), ("wrong marks", wrong)):
            xs = [x for x in xs if x is not None]
            rows.append([name, len(xs), min(xs) if xs else "", st.median(xs) if xs else "", max(xs) if xs else "",
                         ", ".join(f"{k}: {v}" for k, v in sorted(Counter(xs).items()))])
        t1 = md(["group (2 runs pooled)", "n", "min", "median", "max", "values"], rows)
        rows = []
        for t in (0.8, 0.9, 0.95):
            auto = [(c, ok) for c, ok in allm if c is not None and c >= t]
            whole = [r for r in rs if r["mark_conf"] and all((c or 0) >= t for c, _ in r["mark_conf"])]
            rows.append([f"≥ {t}", f"{len(auto)}/{len(allm)}", sum(not ok for _, ok in auto),
                         f"{sum(ok for _, ok in auto) / len(auto):.3f}" if auto else "", f"{len(whole)}/200",
                         sum(not r["ok"] for r in whole)])
        out.append(f"**{p}**\n\n{t1}\n\n" + md(["threshold", "marks auto-applied", "of those wrong", "precision",
                                                 "cases wholly auto-applied", "of those not fully right"], rows))
    # v4e worse than v4d
    d = {i: sum(r["ok"] for t in ("v4d_r1", "v4d_r2") for r in RUNS[t] if r["id"] == i) for i in (c["id"] for c in CASES)}
    e = {i: sum(r["ok"] for t in ("v4e_r1", "v4e_r2") for r in RUNS[t] if r["id"] == i) for i in d}
    worse = [i for i in d if e[i] < d[i]]
    better = [i for i in d if e[i] > d[i]]
    out.append(f"v4e better than v4d (right in more runs): {len(better)} cases {better}\n\n"
               f"v4e worse than v4d: {len(worse)} cases {worse}\n\n"
               f"wrong in some run for both: {[i for i in d if d[i] < 2 and e[i] < 2]}")
    for i in worse + [i for i in d if e[i] < 2]:
        for t in ("v4d_r1", "v4e_r1", "v4e_r2"):
            r = next(x for x in RUNS[t] if x["id"] == i)
            out.append(f"- {i} {t}: `{r['reply']}`")
    # stand-text misses
    flags = [[t, r["id"], r["text"], g, p] for t, rs in RUNS.items() for r in rs if r["ok"]
             for g, p, ok in r.get("pair_text", []) if p is not None and not ok]
    out.append(md(["run", "id", "said", "reference", "Spark's stand text"], flags))
    print("\n\n".join(out))


if __name__ == "__main__":
    main()
