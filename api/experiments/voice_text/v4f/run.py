"""v4e vs v4f (the stand text keeps the conductor's words, CK 2026-10-31) on the three text sets, one run each, Spark
`muse-spark-1.3` at effort minimal on /v1/chat/completions (`voice_stream.common.spark_chat`, which calls Meta
directly whatever `LLM_PROVIDER` says).

The prompt is the app's (`app.librarian.voice_prompt.build_prompt`, now v4f) with the always-on confidence field the
earlier evals add (`messy100.prompts._conf`; the messy 50 set's unrecoverable cases are scored on it). v4e is the same
prompt with v4f's text rule put back (`experiments.voice.prompts.TEXT_V4F_*`, asserted to hit once). Facts as the
live v4e run built them (`live_v4e.run.facts`): clean 130 on book A's parts and groups, no landmarks; messy 100 on
each case's fixture book with its landmarks; messy 50 on the clean set's parts with groups, no landmarks.

    cd api && uv run python -m experiments.voice_text.v4f.run call clean130 v4f     # resumes from results/
    cd api && uv run python -m experiments.voice_text.v4f.run score                 # every raw file, plus words kept

Scoring is each set's own (`voice_text.run`, `messy.run`, `messy100.run`), unchanged except messy pc16's text key,
which now also takes the conductor's words ("drowning", "wall"). "Words kept" is new: a produced mark's stand text
keeps the conductor's words when every content word in it (not a number, a place word or a standard abbreviation)
is in the transcript; it measures the rule, it is not part of right/wrong. Spend goes to this folder's spend.jsonl.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

from app.librarian.voice_prompt import ScoreFacts, build_prompt, derive_groups

from ...voice import prompts as P
from ...voice_stream import common
from .. import run as base
from ..cases import CASES as CLEAN
from ..live_v4e import run as live
from ..messy import run as messy_run
from ..messy.cases import CASES as MESSY50
from ..messy100 import run as m100_run
from ..messy100.cases import CASES as MESSY100
from ..messy100.prompts import _conf

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
common.LEDGER = HERE / "spend.jsonl"          # the imports above point it at their own folders
common.BUDGET_USD = 3.0
MODEL = "muse-spark-1.3"

F50 = common.FACTS
FACTS50 = ScoreFacts(parts=F50.parts, members=F50.members, bar_first=F50.bar_first, bar_last=F50.bar_last,
                     rehearsal_marks=F50.rehearsal_marks, groups=derive_groups(F50.parts), landmarks=[])

SETS = {
    "clean130": (CLEAN, lambda c: live.facts("A", landmarks=False), base.score_case),
    "messy50": (MESSY50, lambda c: FACTS50, messy_run.score_case),
    "messy100": (MESSY100, lambda c: live.facts(c["fix"]), m100_run.score_case),
}


def prompt(name: str, transcript: str, facts: ScoreFacts) -> tuple[str, str]:
    system, user = build_prompt(transcript, facts)
    assert user.count(P.TEXT_V4F_NEW) == 1, "the app prompt is not v4f"
    if name == "v4e":
        user = user.replace(P.TEXT_V4F_NEW, P.TEXT_V4F_OLD)
    elif name != "v4f":
        raise SystemExit(f"prompt {name!r}")
    return system, _conf(user)


async def cmd_call(set_name: str, name: str) -> None:
    cases, facts_of, _ = SETS[set_name]
    dst = RESULTS / f"raw_{set_name}_{name}.json"
    done = json.loads(dst.read_text()) if dst.exists() else {}
    sem = asyncio.Semaphore(6)

    async def one(c: dict) -> None:
        if c["id"] in done:
            return
        s, u = prompt(name, c["text"], facts_of(c))
        async with sem:
            try:
                r = await common.spark_chat(s, u, tag=f"v4f_eval:{set_name}_{name}", uid=c["id"], effort="minimal",
                                            model=MODEL)
            except RuntimeError as e:
                print(c["id"], "ERROR", e)
                return
        done[c["id"]] = {k: r[k] for k in ("text", "seconds", "first_object", "usd", "input_tokens", "cached_tokens",
                                           "output_tokens", "reasoning_tokens")}

    try:
        await asyncio.gather(*(one(c) for c in cases))
    finally:
        dst.write_text(json.dumps(done, ensure_ascii=False, indent=1))
    print(f"{set_name} {name}: {len(done)}/{len(cases)} done; ledger total ${common.spent():.4f}")


# ---------- words kept ----------

NUM_WORDS = set("zero oh one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
                "sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred".split())
PLACE = set("bar bars at from to in on the a an of and before after through till until letter measure m mm "
            "beat beats end top start here next time".split())
SHORT = set(base.ABBR.values()) | {"mf", "mp", "cresc", "dim", "rit", "pizz", "arco", "sfz", "fp", "ff", "pp", "f", "p",
                                   "stacc", "marc", "ten", "vib", "div", "divisi", "sord", "con", "senza", "tempo",
                                   "accel", "cut", "fermata", "breath", "up", "down", "bow", "legato", "accent"}


def words_kept(text: str, transcript: str) -> tuple[bool, list[str]]:
    said = base.norm_tokens(transcript)

    def heard(t: str) -> bool:
        stem = t[:5] if len(t) > 5 else t
        return any(s == t or (len(t) > 3 and len(s) > 3 and (s.startswith(stem) or t.startswith(s[:5])))
                   for s in said)

    added = [t for t in base.norm_tokens(text)
             if not t.isdigit() and t not in NUM_WORDS and t not in PLACE and t not in SHORT and not heard(t)]
    return not added, added


def cmd_score() -> dict:
    out = {}
    for f in sorted(RESULTS.glob("raw_*.json")):
        tag = f.stem[4:]
        set_name = tag.rsplit("_", 1)[0]
        cases, _, score = SETS[set_name]
        raw = json.loads(f.read_text())
        rows = [score(c, raw.get(c["id"])) for c in cases]
        for r in rows:
            r["kept"] = [(m.get("text"), *words_kept(m.get("text") or "", r["text"])) for m in r.get("marks") or []]
        (RESULTS / f"score_{tag}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
        ins = [r for r in rows if not r.get("missing") and (r.get("instruction", r.get("cat") != "unrec"))]
        neg = [r for r in rows if not r.get("missing") and not (r.get("instruction", r.get("cat") != "unrec"))]
        marks = [k for r in rows for k in r["kept"]]
        usd = sum(r.get("usd", 0) for r in rows)
        secs = sorted(r["seconds"] for r in rows if "seconds" in r)
        out[tag] = {"right": sum(r.get("ok", False) for r in ins), "n": len(ins),
                    "text": sum(r.get("text_all", False) for r in ins),
                    "neg_right": sum(r.get("ok", False) for r in neg), "neg_n": len(neg),
                    "kept": sum(k[1] for k in marks), "marks": len(marks), "usd": round(usd, 4),
                    "median_s": round(secs[len(secs) // 2], 2) if secs else None,
                    "missing": sum(r.get("missing", False) for r in rows),
                    "wrong": [r["id"] for r in ins if not r.get("ok")],
                    "text_miss": [r["id"] for r in ins if r.get("ok") and not r.get("text_all")],
                    "neg_wrong": [r["id"] for r in neg if not r.get("ok")]}
        o = out[tag]
        print(f"{tag:18} right {o['right']}/{o['n']}  +text {o['text']}  other {o['neg_right']}/{o['neg_n']}  "
              f"words kept {o['kept']}/{o['marks']}  ${o['usd']:.4f}  median {o['median_s']}s  missing {o['missing']}")
        print(f"{'':18} wrong {o['wrong']}  text miss {o['text_miss']}  other wrong {o['neg_wrong']}")
    (RESULTS / "summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return out


def main() -> None:
    if sys.argv[1] == "call":
        asyncio.run(cmd_call(sys.argv[2], sys.argv[3]))
    elif sys.argv[1] == "score":
        cmd_score()
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
