"""Step 5 of the speed pass: score variant E of `experiments/pageread_speed` (the app's page read after the speed pass:
chat/minimal, a page `process_pages.page_doubts` questions read again at Messages/low) with that experiment's own scoring
(`score.score_labels`, `score.score_landmarks`), count the fallbacks, and copy E's spend into this task's ledger.

    uv run python -m experiments.speed_pass.pageread_e [--run 1]
"""
from __future__ import annotations

import json
import statistics as st
import sys

from ..pageread_speed import score as S
from . import ledger


def main(run: int = 1) -> None:
    rows = []
    for f in sorted(S.RUNS.glob(f"E-r{run}-*.json")):
        book = f.stem.split("-", 2)[2]
        for r in json.loads(f.read_text()):
            r["book"] = book
            rows.append(r)
    if not (ledger.HERE / "results" / f".pageread_e_r{run}_logged").exists():
        for r in rows:
            for a in r["attempts"]:
                ledger.log(source="pageread_speed E", tag=f"step5 pageread E r{run}{' fallback' if a.get('fallback') else ''}", id=r["page"],
                           api=a.get("api"), usd=a["usd"], secs=round(a["seconds"], 2), output_tokens=a["output_tokens"])
        (ledger.HERE / "results" / f".pageread_e_r{run}_logged").write_text("1")
    ok = n = 0
    lm = {"found": 0, "half": 0, "n": 0, "invented": []}
    print("| page | group | fallback | why | labels | seconds | $ |")
    print("|---|---|---|---|---|---|---|")
    for r in rows:
        group = "keyboard" if r["book"] in S.KEYBOARD else "orchestral"
        a, b, bad = S.score_labels(r["page"], r["labels"])
        ok, n = ok + a, n + b
        if r["page"] in S.LM_TRUTH:
            s = S.score_landmarks(r["page"], r["labels"]["landmarks"])
            lm["found"] += s["found"]; lm["half"] += s["half"]; lm["n"] += s["n"]; lm["invented"] += [f"{r['page']}: {x}" for x in s["invented"]]
        why = "; ".join(r.get("fallback") or [])[:110]
        print(f"| {r['page']} | {group} | {'yes' if r.get('fallback') else 'no'} | {why} | {a}/{b}{' ' + str(bad) if bad else ''} | {r['seconds']:.1f} | {r['usd']:.4f} |")
    orch = [r for r in rows if r["book"] not in S.KEYBOARD]
    keys = [r for r in rows if r["book"] in S.KEYBOARD]
    fired = lambda rs: sum(1 for r in rs if r.get("fallback"))
    print(f"labels {ok}/{n}; fallback on {fired(rows)}/{len(rows)} pages (orchestral {fired(orch)}/{len(orch)}, keyboard {fired(keys)}/{len(keys)})")
    print(f"landmarks found {lm['found']} (+{lm['half']} named as a double bar) of {lm['n']}; invented {lm['invented']}")
    secs = [r["seconds"] for r in rows]
    print(f"seconds median {st.median(secs):.1f} (orchestral {st.median([r['seconds'] for r in orch]):.1f}, keyboard {st.median([r['seconds'] for r in keys]):.1f}), "
          f"p90 {S.pct(secs, 0.9):.1f}; $ {sum(r['usd'] for r in rows):.4f} ({sum(r['usd'] for r in rows) / len(rows):.4f} a page)")
    print(f"ledger ${ledger.spent():.4f}")


if __name__ == "__main__":
    main(int(sys.argv[sys.argv.index("--run") + 1]) if "--run" in sys.argv else 1)
