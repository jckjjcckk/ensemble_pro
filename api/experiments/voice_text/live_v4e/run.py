"""The app's live v4e prompt (`app.librarian.voice_prompt.build_prompt`, with the always-on confidence field the
messy100 eval adds) on the messy100 set's 20 landmark and 9 concerto group cases, and on the clean 130 set, one run
each, effort minimal. The facts are built the way `transcribe_voice.Score` builds them: groups by `derive_groups`
from the part names, landmarks as `scores.landmarks` dicts rendered by `landmark_lines` (a double bar "between bars
64 and 65", tempo headings as ranges); the messy100 eval's hand-written strings ("double bar after bar 64",
"Adagio (the slow section) bars 121-160") are not used. The (c) musical-terms line is not in the app prompt.

    cd api && uv run python -m experiments.voice_text.live_v4e.run messy     # 29 calls, resumes
    cd api && uv run python -m experiments.voice_text.live_v4e.run clean     # 130 calls, resumes

Reads the messy100 eval's cases and scoring (`experiments/voice_text/messy100/`, another agent's folder, not edited).
Spend goes to this folder's spend.jsonl.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from app.librarian.voice_prompt import ScoreFacts, build_prompt, derive_groups

from ...voice_stream import common
from .. import run as base
from ..cases import CASES as CLEAN
from ..messy100 import run as messy_run
from ..messy100.cases import CASES, FIX
from ..messy100.prompts import _conf

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
common.LEDGER = HERE / "spend.jsonl"         # the imports above point it at their own folders
common.BUDGET_USD = 2.8                      # the task's cap is $3, $0.155 of it spent on the page-read eval


def lm(kind: str, label: str, bar: int, after: int | None = None) -> dict:
    return {"kind": kind, "label": label, "bar": bar, "bar_after": after, "source": "musicxml"}


# The messy100 fixture books' landmarks as the app stores them.
LANDMARKS = {
    "A": [lm("segno", "segno", 17), lm("double_bar", "double bar", 64, 65), lm("key_change", "E-flat major", 97),
          lm("tempo", "Adagio", 121), lm("tempo", "Tempo primo", 161), lm("coda", "To Coda", 200), lm("coda", "Coda", 221)],
    "B": [lm("key_change", "F major", 75), lm("double_bar", "double bar", 150, 151), lm("tempo", "Andante", 151),
          lm("tempo", "Allegro (Tempo I)", 211), lm("section", "Cadenza", 268), lm("coda", "Coda", 281)],
}


def facts(book: str, landmarks: bool = True) -> ScoreFacts:
    f = FIX[book]
    return ScoreFacts(parts=f.parts, members=f.members, bar_first=f.bar_first, bar_last=f.bar_last,
                      rehearsal_marks=f.rehearsal_marks, groups=derive_groups(f.parts),
                      landmarks=LANDMARKS[book] if landmarks else [])


def live(transcript: str, f: ScoreFacts) -> tuple[str, str]:
    system, user = build_prompt(transcript, f)
    return system, _conf(user)


async def call(cases: list[dict], dst: Path, facts_of, tag: str) -> dict:
    done = json.loads(dst.read_text()) if dst.exists() else {}
    sem = asyncio.Semaphore(6)

    async def one(c: dict) -> None:
        if c["id"] in done:
            return
        s, u = live(c["text"], facts_of(c))
        async with sem:
            r = await common.spark_chat(s, u, tag=tag, uid=c["id"], effort="minimal")
        done[c["id"]] = {k: r[k] for k in ("text", "seconds", "first_object", "usd", "input_tokens", "cached_tokens",
                                           "output_tokens", "reasoning_tokens")}

    await asyncio.gather(*(one(c) for c in cases))
    dst.write_text(json.dumps(done, ensure_ascii=False, indent=1))
    return done


async def messy() -> None:
    cases = [c for c in CASES if c["cat"] == "landmark" or (c["cat"] == "group" and c["fix"] == "B")]
    raw = await call(cases, RESULTS / "messy_raw.json", lambda c: facts(c["fix"]), "live_v4e:messy")
    rows = [messy_run.score_case(c, raw.get(c["id"])) for c in cases]
    (RESULTS / "messy_score.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    for cat in ("landmark", "group"):
        sub = [r for r in rows if r["cat"] == cat]
        print(cat, sum(r.get("ok", False) for r in sub), "/", len(sub), "wrong:", [r["id"] for r in sub if not r.get("ok")])
    lm15 = next(r for r in rows if r["id"] == "lm15")
    print("lm15", lm15.get("ok"), [(m.get("position"), m.get("bar_from"), m.get("bar_to")) for m in lm15.get("marks", [])])
    print(f"ledger ${common.spent():.4f}")


async def clean() -> None:
    raw = await call(CLEAN, RESULTS / "clean130_raw.json", lambda c: facts("A", landmarks=False), "live_v4e:clean130")
    rows = [base.score_case(c, raw.get(c["id"])) for c in CLEAN]
    (RESULTS / "clean130_score.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    ins = [r for r in rows if r["instruction"]]
    neg = [r for r in rows if not r["instruction"]]
    print("clean130 right", sum(r["ok"] for r in ins), "/", len(ins), "; +text", sum(r["text_all"] for r in ins),
          "; FP", [r["id"] for r in neg if not r["ok"]], f"of {len(neg)}", "; wrong", [r["id"] for r in ins if not r["ok"]],
          f"; ledger ${common.spent():.4f}")


if __name__ == "__main__":
    asyncio.run({"messy": messy, "clean": clean}[sys.argv[1]]())
