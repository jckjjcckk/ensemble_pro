"""Run the messy set through Spark (v4d = the app's rules + confidence, effort minimal, /v1/chat/completions,
streamed), twice per case, and score it with code (the parent eval's matching and lenient stand-text test).

    uv run python -m experiments.voice_text.messy.run call 1     # run 1 -> results/raw_r1.json (resumes)
    uv run python -m experiments.voice_text.messy.run call 2
    uv run python -m experiments.voice_text.messy.run score      # results/score_r1.json, score_r2.json, summary.json
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from app.librarian.voice_prompt import checked_marks, parse_answer

from ...voice_stream import common
from .. import run as base
from ..prompt_v4d import build_v4d
from .cases import CASES, _Any

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
common.LEDGER = HERE / "spend.jsonl"      # importing ..run pointed these at the parent's; this task has its own
common.BUDGET_USD = 2.0
FACTS, LAST = base.FACTS, base.LAST
GATE = 0.9                                 # a 'flag' card must come in below this to reach the admin
THRESHOLDS = (0.8, 0.9, 0.95)


async def cmd_call(n: int) -> None:
    dst = RESULTS / f"raw_r{n}.json"
    done = json.loads(dst.read_text()) if dst.exists() else {}
    sem = asyncio.Semaphore(6)

    async def one(c: dict) -> None:
        if c["id"] in done:
            return
        system, user = build_v4d(c["text"], c["id"])
        async with sem:
            try:
                r = await common.spark_chat(system, user, tag=f"messy:v4d_minimal:r{n}", uid=c["id"], effort="minimal")
            except RuntimeError as e:
                print(c["id"], "ERROR", e)
                return
        done[c["id"]] = {k: r[k] for k in ("text", "seconds", "first_object", "usd", "input_tokens", "cached_tokens",
                                           "output_tokens", "reasoning_tokens")}
        print(f"{c['id']:5} {r['seconds']:.2f}s ${r['usd']:.4f} {r['text'][:110]!r}")

    await asyncio.gather(*(one(c) for c in CASES))
    dst.write_text(json.dumps(done, ensure_ascii=False, indent=1))
    print(f"{len(done)}/{len(CASES)} done; ledger total ${common.spent():.4f}")


_base_fields = base.fields


def fields(g: dict, p: dict) -> dict:
    """The parent's field test, with 'any value' fields for the uncertain field of a flag case."""
    if not any(isinstance(g[k], _Any) for k in ("position", "bar_from", "bar_to", "audience", "kind")):
        return _base_fields(g, p)
    g2 = {k: (v if not isinstance(v, _Any) else None) for k, v in g.items()}
    f = _base_fields({**g2, **{k: (v if v is not None else [p.get(k)]) for k, v in g2.items()
                              if k in ("position", "bar_from", "kind")},
                     "bar_to": g["bar_to"] if not isinstance(g["bar_to"], _Any) else [p.get("bar_to"), p.get("bar_from")],
                     "audience": g["audience"] if not isinstance(g["audience"], _Any) else
                     [sorted(set(p.get("audience") if isinstance(p.get("audience"), list) else [p.get("audience")]))]},
                    p)
    return f


base.fields = fields                      # match() looks the name up at call time


def score_case(c: dict, raw: dict | None) -> dict:
    row = {"id": c["id"], "cat": c["cat"], "sub": c["sub"], "diff": c["diff"], "text": c["text"], "gt": c["gt"]}
    if raw is None:
        return {**row, "missing": True}
    reply = raw["text"]
    try:
        ans = parse_answer(reply)
        marks, refused = checked_marks(ans, c["text"], FACTS)
    except Exception as e:  # noqa: BLE001
        ans, marks, refused = None, [], [f"unparseable: {e}"]
    none_conf = ans.get("confidence") if isinstance(ans, dict) and ans.get("none") is True else None
    confs = [m.get("confidence") if isinstance(m.get("confidence"), (int, float)) else 0.0 for m in marks]
    row.update(reply=reply, marks=marks, refused=refused, none_conf=none_conf, confs=confs, seconds=raw["seconds"],
               usd=raw["usd"], output_tokens=raw["output_tokens"], n_produced=len(marks),
               canon=sorted(json.dumps({k: m.get(k) for k in ("position", "bar_from", "bar_to", "kind")} |
                                       {"audience": sorted(m["audience"] if isinstance(m.get("audience"), list)
                                                           else [m.get("audience")])}, sort_keys=True) for m in marks))
    if c["cat"] == "unrec":
        below = all(x < GATE for x in confs)
        if c["gt"] == "none":
            right = not marks or (c["also"] == "flag" and below)
            row.update(ok=right, core=right, mark_conf=[(x, False) for x in confs])
        else:
            pairs, extras = base.match(c["answers"][0], marks)
            core = bool(marks) and not extras and all(f["core"] for *_, f in pairs)
            right = (core and below) or (not marks and c["also"] == "none")
            row.update(ok=right, core=core, flagged=below, mark_conf=[(x, False) for x in confs])
        row["text_all"] = row["ok"]
        return row
    best = None
    for ai, answer in enumerate(c["answers"]):
        pairs, extras = base.match(answer, marks)
        right = not extras and all(f["core"] for *_, f in pairs)
        key = (right, sum(f["core"] for *_, f in pairs), sum(sum(f.values()) for *_, f in pairs), -ai)
        if best is None or key > best[0]:
            best = (key, ai, pairs, extras)
    _, ai, pairs, extras = best
    right = not extras and all(f["core"] for *_, f in pairs)
    row.update(answer_index=ai, n_expected=len(c["answers"][ai]), extras=len(extras), produced=bool(marks), ok=right,
               core=right, text_all=right and all(f["text"] for *_, f in pairs),
               field_hits=[{k: f[k] for k in ("position", "bars", "audience", "kind", "text", "core")} for *_, f in pairs],
               pair_text=[(g["text"], p.get("text") if p else None, f["text"]) for g, p, f in pairs],
               mark_conf=[(p.get("confidence"), f["core"]) for g, p, f in pairs if p is not None]
               + [(m.get("confidence"), False) for m in extras])
    return row


def cmd_score() -> None:
    out = {}
    for n in (1, 2):
        raw = json.loads((RESULTS / f"raw_r{n}.json").read_text())
        rows = [score_case(c, raw.get(c["id"])) for c in CASES]
        (RESULTS / f"score_r{n}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
        out[n] = rows
        ins = [r for r in rows if r["cat"] != "unrec"]
        un = [r for r in rows if r["cat"] == "unrec"]
        print(f"run {n}: instructions right {sum(r['ok'] for r in ins)}/{len(ins)} (+text {sum(r['text_all'] for r in ins)}); "
              f"unrec right {sum(r['ok'] for r in un)}/{len(un)}; no-mark on instructions "
              f"{[r['id'] for r in ins if not r['produced']]}; refused {[(r['id'], r['refused']) for r in rows if r['refused']]}")
        for r in rows:
            if not r["ok"]:
                print(f"   x {r['id']} {r['reply'][:300]!r}")


def main() -> None:
    if sys.argv[1] == "call":
        asyncio.run(cmd_call(int(sys.argv[2])))
    elif sys.argv[1] == "score":
        cmd_score()
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
