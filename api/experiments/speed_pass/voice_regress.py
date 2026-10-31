"""Step 2 of the speed pass: the app's own voice Spark call, before and after.

CK's 40 recorded lines + 23 negatives (realtime ENDPOINTING transcripts, `voice_stream/results/realtime_endpointing.json`),
prompted with the app's `voice_prompt.build_prompt` (v4e) on facts built the way `transcribe_voice.Score` builds them
(the eval's parts and members, `derive_groups`, no landmarks: the eval book has none), sent through the app's
`llm.complete` exactly as `transcribe_voice` sends it:

- before: effort low, Messages, not streamed (HEAD before this step);
- after: effort minimal, chat completions, streamed (this step).

Scored with `voice_eval.score_line` (all five fields) and the negatives as "no mark", as `voice_text.regress` does.

    uv run python -m experiments.speed_pass.voice_regress low
    uv run python -m experiments.speed_pass.voice_regress minimal
    uv run python -m experiments.speed_pass.voice_regress report
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import statistics as st
import sys
import time

from app import llm
from app.librarian.voice_prompt import build_prompt, checked_marks, derive_groups, parse_answer

from ..voice.voice_eval import score_line
from ..voice_stream import common
from ..voice_stream.spark_lat import transcripts
from . import ledger

RESULTS = ledger.HERE / "results"
FACTS = dataclasses.replace(common.FACTS, groups=derive_groups(common.FACTS.parts), landmarks=[])


async def run(effort: str) -> None:
    RESULTS.mkdir(exist_ok=True)
    dst = RESULTS / f"voice_{effort}.json"
    tr, lab = transcripts(), common.labels()
    done = {r["id"]: r for r in json.loads(dst.read_text())} if dst.exists() else {}
    sem = asyncio.Semaphore(6)

    async def one(uid: str) -> dict:
        if uid in done:
            return done[uid]
        t = tr[uid]
        if not t:
            return {"id": uid, "skipped": True, "score": {"negative": True, "ok": True}}
        system, user = build_prompt(t, FACTS)
        async with sem:
            ledger.guard(0.02)
            t0 = time.monotonic()
            c = await llm.complete(user, system=system, effort=effort, max_tokens=8192, provider="meta", stream=effort == "minimal")
            secs = time.monotonic() - t0
        ledger.log(source="script", tag=f"step2 voice_regress {effort}", id=uid, api=c.api, effort=effort, model=c.charge.model,
                   input_tokens=c.charge.input_tokens, output_tokens=c.charge.output_tokens, usd=float(c.charge.cost_usd), secs=round(secs, 2))
        try:
            marks, refused = checked_marks(parse_answer(c.text), t, FACTS)
        except Exception as e:  # noqa: BLE001
            marks, refused = [], [f"unparseable: {e}"]
        sc = ({"negative": True, "ok": not marks} if uid.startswith("n")
              else score_line(common.base_id(uid), lab[common.base_id(uid)], marks))
        return {"id": uid, "transcript": t, "reply": c.text, "marks": marks, "refused": refused, "score": sc,
                "seconds": secs, "first_token": c.first_token_s, "usd": float(c.charge.cost_usd),
                "output_tokens": c.charge.output_tokens}

    rows = await asyncio.gather(*(one(u) for u in sorted(tr)))
    dst.write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    print(f"{effort}: {len(rows)} rows, ledger ${ledger.spent():.4f}")


def report() -> None:
    out = {}
    print("| variant | base lines all fields | retakes | negatives clean | median s | p90 s | median out tok | $/line |")
    print("|---|---|---|---|---|---|---|---|")
    for eff in ("low", "minimal"):
        rs = json.loads((RESULTS / f"voice_{eff}.json").read_text())
        out[eff] = {r["id"]: r for r in rs}
        pos = [r for r in rs if not r["score"]["negative"]]
        neg = [r for r in rs if r["score"]["negative"]]
        b = [r for r in pos if not r["id"].endswith("c")]
        c = [r for r in pos if r["id"].endswith("c")]
        called = [r for r in rs if "seconds" in r]
        secs = sorted(r["seconds"] for r in called)
        print(f"| {eff} | {sum(bool(r['score'].get('all_fields')) for r in b)}/{len(b)} | "
              f"{sum(bool(r['score'].get('all_fields')) for r in c)}/{len(c)} | {sum(r['score']['ok'] for r in neg)}/{len(neg)} | "
              f"{st.median(secs):.2f} | {secs[round(0.9 * (len(secs) - 1))]:.2f} | "
              f"{st.median(r['output_tokens'] for r in called):.0f} | ${st.mean(r['usd'] for r in called):.4f} |")
    for uid in sorted(out["low"]):
        a, b = out["low"][uid]["score"], out["minimal"][uid]["score"]
        ka = a["ok"] if a["negative"] else bool(a.get("all_fields"))
        kb = b["ok"] if b["negative"] else bool(b.get("all_fields"))
        if ka != kb:
            print("DIFF", uid, "low", ka, "minimal", kb, "|", out["minimal"][uid].get("transcript"))


if __name__ == "__main__":
    report() if sys.argv[1] == "report" else asyncio.run(run(sys.argv[1]))
