"""Guard: the clean 130-case text set (voice_text/cases.py) through this folder's v4d and v4e, one run each, minimal.
v4e is given book A's groups but no landmarks ("none listed"), because that set's ground truth puts every landmark
at `position: mark` (its fixture has none): this checks that the new rule text costs nothing where (a) cannot help.

    uv run python -m experiments.voice_text.messy100.clean130 v4d|v4e     # calls (resumes) then scores
"""

from __future__ import annotations

import asyncio
import json
import sys

from ...voice_stream import common
from .. import run as base
from ..cases import CASES
from .cases import FIX
from .prompts import BUILD, ScoreFactsE
from .run import HERE, RESULTS  # noqa: F401  (re-points the ledger at this folder)

common.LEDGER = HERE / "spend.jsonl"
F = FIX["A"]
FACTS = ScoreFactsE(parts=F.parts, members=F.members, bar_first=1, bar_last=240, rehearsal_marks=F.rehearsal_marks,
                    landmarks=[], groups=F.groups)


async def call(prompt: str) -> None:
    dst = RESULTS / f"clean130_raw_{prompt}.json"
    done = json.loads(dst.read_text()) if dst.exists() else {}
    sem = asyncio.Semaphore(6)

    async def one(c):
        if c["id"] in done:
            return
        s, u = BUILD[prompt](c["text"], FACTS)
        async with sem:
            r = await common.spark_chat(s, u, tag=f"messy100:clean130_{prompt}", uid=c["id"], effort="minimal")
        done[c["id"]] = {k: r[k] for k in ("text", "seconds", "first_object", "usd", "input_tokens", "cached_tokens",
                                           "output_tokens", "reasoning_tokens")}

    await asyncio.gather(*(one(c) for c in CASES))
    dst.write_text(json.dumps(done, ensure_ascii=False, indent=1))
    rows = [base.score_case(c, done.get(c["id"])) for c in CASES]
    (RESULTS / f"clean130_score_{prompt}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    ins = [r for r in rows if r["instruction"]]
    neg = [r for r in rows if not r["instruction"]]
    print(prompt, "right", sum(r["ok"] for r in ins), "/100; +text", sum(r["text_all"] for r in ins),
          "; FP", [r["id"] for r in neg if not r["ok"]], "; wrong", [r["id"] for r in ins if not r["ok"]],
          f"; ledger ${common.spent():.4f}")


if __name__ == "__main__":
    asyncio.run(call(sys.argv[1]))
