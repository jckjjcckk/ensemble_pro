"""Step 3 of the speed pass: the render proofreading question (omr_verify) at effort low vs minimal, paired.

The pair images (scan system above the engraved system) a real convert asked about are dumped by `OMR_VERIFY_DUMP`
with their measure numbers; each is asked again here with the app's prompt and system, `runs` times at each effort,
through the app's `ask.ask_model` (minimal goes to chat completions). Reported: per system the yes/no of every run,
whether the decision (same / not same, and the measures named) agrees across efforts, and agreement low-vs-low as the
noise floor.

    uv run python -m experiments.speed_pass.verify_replay <dump_dir> [--runs 2]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics as st
import time
from pathlib import Path

from app.librarian.ask import ask_model
from app.librarian.omr_verify import VERIFY_RENDER_PROMPT, VERIFY_RENDER_SYSTEM, _same
from app.llm import _client
from app.settings import settings

from . import ledger


class Ctx:
    def __init__(self, tag: str):
        self.tag, self.usd = tag, 0.0

    def charge(self, c):
        self.usd += float(c.cost_usd)
        ledger.log(source="script", tag=self.tag, model=c.model, input_tokens=c.input_tokens, output_tokens=c.output_tokens, usd=float(c.cost_usd))

    png_b64 = staticmethod(lambda b: __import__("base64").b64encode(b).decode())


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dump")
    ap.add_argument("--runs", type=int, default=2)
    a = ap.parse_args()
    dump = Path(a.dump)
    items = sorted(dump.glob("*.json"))
    client, model = _client("meta"), settings.meta_model
    sem = asyncio.Semaphore(12)
    out_path = dump.parent / f"{dump.name}_replay.json"
    done = json.loads(out_path.read_text()) if out_path.exists() else {}

    async def one(f: Path, effort: str, run: int) -> None:
        key = f"{f.stem}|{effort}|{run}"
        if key in done:
            return
        meta = json.loads(f.read_text())
        png = f.with_suffix(".png").read_bytes()
        prompt = VERIFY_RENDER_PROMPT.format(first=meta["first"], last=meta["last"])
        ledger.guard(0.02)
        async with sem:
            t0 = time.monotonic()
            ans = await ask_model(Ctx(f"step3 verify_replay {effort}"), client, model, prompt, png, max_tokens=8000, effort=effort,
                                  retries=1, system=VERIFY_RENDER_SYSTEM)
            secs = time.monotonic() - t0
        same, reason, named = _same(ans, meta["numbers"])
        done[key] = {"same": same, "named": named, "reason": reason, "secs": round(secs, 2), "usd": ans.get("_cost_usd"), "api": ans.get("_api")}

    await asyncio.gather(*(one(f, e, r) for f in items for e in ("low", "minimal") for r in range(1, a.runs + 1)))
    out_path.write_text(json.dumps(done, indent=1))
    systems = sorted({k.split("|")[0] for k in done})

    def verdict(sysname: str, effort: str, run: int):
        d = done[f"{sysname}|{effort}|{run}"]
        return (d["same"], tuple(d["named"]) if d["same"] is False else ())

    rows = []
    for s in systems:
        low = [verdict(s, "low", r) for r in range(1, a.runs + 1)]
        mn = [verdict(s, "minimal", r) for r in range(1, a.runs + 1)]
        rows.append((s, low, mn))
        print(s, "low", [v[0] for v in low], "minimal", [v[0] for v in mn], "named low", [v[1] for v in low], "minimal", [v[1] for v in mn])
    for effort in ("low", "minimal"):
        secs = [d["secs"] for k, d in done.items() if k.split("|")[1] == effort]
        usd = [d["usd"] or 0 for k, d in done.items() if k.split("|")[1] == effort]
        nos = sum(1 for k, d in done.items() if k.split("|")[1] == effort and d["same"] is False)
        print(f"{effort}: {len(secs)} calls, median {st.median(secs):.2f} s, p90 {sorted(secs)[round(0.9 * (len(secs) - 1))]:.2f} s, "
              f"${sum(usd):.4f}, 'no' {nos}")
    yes_no = lambda vs: [v[0] for v in vs]
    print("systems where every run agrees on yes/no, low:", sum(len(set(yes_no(l))) == 1 for _, l, _ in rows), "/", len(rows))
    print("systems where every run agrees on yes/no, minimal:", sum(len(set(yes_no(m))) == 1 for _, _, m in rows), "/", len(rows))
    print("low run 1 vs minimal run 1, yes/no equal:", sum(l[0][0] == m[0][0] for _, l, m in rows), "/", len(rows))
    print("low run 1 vs low run 2, yes/no equal:", sum(l[0][0] == l[-1][0] for _, l, _ in rows), "/", len(rows))
    print("minimal run 1 vs minimal run 2, yes/no equal:", sum(m[0][0] == m[-1][0] for _, _, m in rows), "/", len(rows))
    print("majority low == majority minimal (ties count as disagreement):",
          sum((sum(x[0] is True for x in l) * 2 > len(l)) == (sum(x[0] is True for x in m) * 2 > len(m)) for _, l, m in rows), "/", len(rows))
    print(f"ledger ${ledger.spent():.4f}")


if __name__ == "__main__":
    asyncio.run(main())
