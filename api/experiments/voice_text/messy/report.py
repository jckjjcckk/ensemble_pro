"""Tables for docs/features/013-messy-eval.md from results/score_r1.json and score_r2.json (no calls).

    uv run python -m experiments.voice_text.messy.report
"""

from __future__ import annotations

import json
import statistics as st
from collections import Counter
from pathlib import Path

from .. import run as base

R = Path(__file__).resolve().parent / "results"
TH = (0.8, 0.9, 0.95)


def load(n):
    return json.loads((R / f"score_r{n}.json").read_text())


def t(rows, head):
    print("| " + " | ".join(head) + " |\n|" + "---|" * len(head))
    for r in rows:
        print("| " + " | ".join(str(x) for x in r) + " |")
    print()


def main() -> None:
    runs = {1: load(1), 2: load(2)}
    ins = {n: [r for r in rs if r["cat"] != "unrec"] for n, rs in runs.items()}
    un = {n: [r for r in rs if r["cat"] == "unrec"] for n, rs in runs.items()}
    fh = {n: [f for r in ins[n] for f in r["field_hits"]] for n in runs}
    print("## overall")
    t([[n, f"{sum(r['ok'] for r in ins[n])}/40", f"{sum(r['text_all'] for r in ins[n])}/40",
        *[f"{sum(f[k] for f in fh[n])}/{len(fh[n])}" for k in ("position", "bars", "audience", "kind", "text", "core")],
        f"{sum(r['ok'] for r in un[n])}/10", f"{sum(r['ok'] for r in runs[n])}/50",
        [r["id"] for r in ins[n] if not r["produced"]], [r["id"] for r in ins[n] if r.get("extras")]]
       for n in runs],
      ["run", "instr right", "+text", "position", "bars", "audience", "kind", "text", "core", "unrec right", "all 50",
       "no mark", "extra marks"])
    both = sum(a["ok"] and b["ok"] for a, b in zip(*runs.values()))
    print(f"right in both runs: {both}/50; instructions {sum(a['ok'] and b['ok'] for a, b in zip(*ins.values()))}/40\n")

    print("## per group / sub / difficulty (r1, r2)")
    for key in ("cat", "sub", "diff"):
        vals = list(dict.fromkeys(r[key] for r in runs[1]))
        t([[v, sum(r[key] == v for r in runs[1]), *[sum(r["ok"] for r in runs[n] if r[key] == v) for n in runs],
            *[sum(r["text_all"] for r in runs[n] if r[key] == v) for n in runs]] for v in vals],
          [key, "n", "r1 right", "r2 right", "r1 +text", "r2 +text"])

    print("## run-to-run")
    a, b = runs[1], runs[2]
    same_struct = [x["id"] for x, y in zip(a, b) if x["canon"] == y["canon"]]
    same_verdict = sum(x["ok"] == y["ok"] for x, y in zip(a, b))
    same_text = sum([m["text"] for m in x["marks"]] == [m["text"] for m in y["marks"]] for x, y in zip(a, b))
    cd = [abs(p - q) for x, y in zip(a, b) for p, q in zip(x["confs"], y["confs"]) if x["canon"] == y["canon"]]
    nd = [abs(x["none_conf"] - y["none_conf"]) for x, y in zip(a, b) if x["none_conf"] is not None and y["none_conf"] is not None]
    print(f"same structured marks {len(same_struct)}/50 (differ: {[x['id'] for x in a if x['id'] not in same_struct]}); "
          f"same verdict {same_verdict}/50; identical stand text {same_text}/50; mark-confidence |r1-r2| over "
          f"{len(cd)} paired marks: median {st.median(cd):.2f}, max {max(cd):.2f}, equal {sum(d == 0 for d in cd)}; "
          f"none-confidence |diff| {nd}")
    gate_flip = [(x["id"], th) for x, y in zip(a, b) for th in TH for p, q in zip(x["confs"], y["confs"])
                 if x["canon"] == y["canon"] and (p >= th) != (q >= th)]
    print("marks that cross a threshold between runs:", Counter(th for _, th in gate_flip), gate_flip, "\n")

    print("## unrecoverable")
    t([[x["id"], x["sub"], x["gt"], next(c["also"] for c in base_cases() if c["id"] == x["id"]),
        *[("none %s" % r["none_conf"]) if not r["marks"] else "; ".join(
            f"{m['position']} {m['bar_from']} {','.join(m['audience'])} {m['kind']} \"{m['text']}\" {m.get('confidence')}"
            for m in r["marks"]) for r in (x, y)], x["ok"], y["ok"]] for x, y in zip(un[1], un[2])],
      ["id", "sub", "gt", "also", "r1", "r2", "r1 ok", "r2 ok"])
    for n in runs:
        neg = [r for r in un[n] if r["gt"] == "none"]
        print(f"r{n}: marks on the 5 'none' cases: {sum(bool(r['marks']) for r in neg)}; marks on any of the 10 at "
              + ", ".join(f">={th}: {sum(x >= th for r in un[n] for x in r['confs'])}" for th in TH))
    print()

    print("## confidence gate (all 50 cases; wrong = not core-right, an extra, or any mark on an unrecoverable case)")
    rows = []
    for n in runs:
        mc = [(c, ok) for r in runs[n] for c, ok in r["mark_conf"]]
        for th in TH:
            app = [(c, ok) for c, ok in mc if (c or 0) >= th]
            whole = [r for r in ins[n] if r["marks"] and all((c or 0) >= th for c in r["confs"])]
            rows.append([f"r{n}", f">= {th}", f"{len(app)}/{len(mc)}", sum(not ok for _, ok in app),
                         f"{len(whole)}/40", sum(not r["ok"] for r in whole),
                         [r["id"] for r in runs[n] for c, ok in r["mark_conf"] if (c or 0) >= th and not ok]])
    t(rows, ["run", "threshold", "marks auto-applied", "of those wrong", "instructions wholly auto-applied",
             "of those not right", "wrong ids"])
    for n in runs:
        right = [c for r in runs[n] for c, ok in r["mark_conf"] if ok]
        wrong = [c for r in runs[n] for c, ok in r["mark_conf"] if not ok]
        nn_ins = [r["none_conf"] for r in ins[n] if r["none_conf"] is not None]
        nn_un = [(r["id"], r["none_conf"]) for r in un[n] if r["none_conf"] is not None]
        print(f"r{n}: right marks n={len(right)} median {st.median(right)} min {min(right)}; "
              f"conf hist {sorted(Counter(right).items())}; wrong marks {sorted(wrong)}; "
              f"none on instructions {nn_ins}; none on unrec {nn_un}")
    print()

    print("## latency / cost")
    for n in runs:
        s = [r["seconds"] for r in runs[n]]
        print(f"r{n}: median {st.median(s):.2f}s p90 {base.p90(s):.2f}s max {max(s):.2f}s; cost ${sum(r['usd'] for r in runs[n]):.4f} "
              f"(${sum(r['usd'] for r in runs[n]) / 50:.4f}/call); out tok median {st.median(r['output_tokens'] for r in runs[n])}")
    raw = [json.loads((R / f"raw_r{n}.json").read_text()) for n in runs]
    print("cached tokens median:", st.median(v["cached_tokens"] for d in raw for v in d.values()),
          "input median:", st.median(v["input_tokens"] for d in raw for v in d.values()))


def base_cases():
    from .cases import CASES
    return CASES


if __name__ == "__main__":
    main()
