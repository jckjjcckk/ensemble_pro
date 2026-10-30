"""Repeat the cases that changed between v4c and v4d, 5 calls each per prompt (effort minimal), to tell noise from
effect. Writes results/repeats.json; calls on this folder's ledger.

    uv run python -m experiments.voice_text.repeat
"""

from __future__ import annotations

import asyncio
import json

from app.librarian.voice_prompt import checked_marks, parse_answer

from ..voice_stream import common
from ..voice_stream.spark_lat import build, transcripts
from . import run
from .cases import CASES
from .prompt_v4d import build_v4d

N = 5
TEXT = {c["id"]: c for c in CASES}


async def main() -> None:
    tr = transcripts()
    items = [("v15", tr["v15"]), ("f04", TEXT["f04"]["text"]), ("n16", TEXT["n16"]["text"])]
    sem = asyncio.Semaphore(6)

    async def one(uid, text, prompt, k):
        s, u = build_v4d(text, uid) if prompt == "v4d" else build("v4c", text, uid)
        async with sem:
            r = await common.spark_chat(s, u, tag=f"repeat:{prompt}", uid=uid, effort="minimal")
        try:
            marks, _ = checked_marks(parse_answer(r["text"]), text, common.FACTS)
        except Exception:  # noqa: BLE001
            marks = []
        if uid in TEXT:
            ok = run.score_case(TEXT[uid], {**r})["ok"]
        else:
            ok = {tuple(sorted(a for m in marks for a in m["audience"]))} == {("part:Viola", "part:Violin I", "part:Violin II")}
        return {"id": uid, "prompt": prompt, "k": k, "ok": ok, "reply": r["text"]}

    rows = await asyncio.gather(*(one(u, t, p, k) for u, t in items for p in ("v4c", "v4d") for k in range(N)))
    (run.RESULTS / "repeats.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    for u, _ in items:
        for p in ("v4c", "v4d"):
            print(u, p, f"{sum(r['ok'] for r in rows if r['id'] == u and r['prompt'] == p)}/{N} right")
    print(f"ledger ${common.spent():.4f}")


if __name__ == "__main__":
    asyncio.run(main())
