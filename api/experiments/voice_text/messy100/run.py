"""Calls and code scoring for the 100 messy cases, v4d vs v4e, effort minimal, 2 runs each.

    uv run python -m experiments.voice_text.messy100.run call v4d 1     # resumes from results/raw_v4d_r1.json
    uv run python -m experiments.voice_text.messy100.run score          # scores every raw file -> results/score_*.json

Scoring reuses the text eval's field match, best one-to-one pairing and lenient stand-text keys
(`voice_text.run`), with each case's own fixture book for the app's `checked_marks`.
"""

from __future__ import annotations

import asyncio
import copy
import json
import sys
from pathlib import Path

from app.librarian.voice_prompt import checked_marks, parse_answer

from ...voice_stream import common
from .. import run as base          # importing it points common's ledger at voice_text; re-pointed below
from .cases import CASES, FIX
from .prompts import BUILD

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
common.LEDGER = HERE / "spend.jsonl"
common.BUDGET_USD = 3.0


async def cmd_call(prompt: str, rep: int, ids: list[str] | None = None) -> None:
    dst = RESULTS / f"raw_{prompt}_r{rep}.json"
    done = json.loads(dst.read_text()) if dst.exists() else {}
    sem = asyncio.Semaphore(6)

    async def one(c: dict) -> None:
        if c["id"] in done or (ids and c["id"] not in ids):
            return
        system, user = BUILD[prompt](c["text"], FIX[c["fix"]])
        async with sem:
            try:
                r = await common.spark_chat(system, user, tag=f"messy100:{prompt}_r{rep}", uid=c["id"], effort="minimal")
            except RuntimeError as e:
                print(c["id"], "ERROR", e)
                return
        done[c["id"]] = {k: r[k] for k in ("text", "seconds", "first_object", "usd", "input_tokens", "cached_tokens",
                                           "output_tokens", "reasoning_tokens")}
        print(f"{c['id']:5} {r['seconds']:.2f}s ${r['usd']:.4f} {r['text'][:100]!r}")

    await asyncio.gather(*(one(c) for c in CASES))
    dst.write_text(json.dumps(done, ensure_ascii=False, indent=1))
    print(f"{len(done)}/{len(CASES)} done; ledger total ${common.spent():.4f}")


def _unplaced(answer: list[dict]) -> list[dict]:
    """The same answer with every place turned into an unresolved landmark (position mark, null bars)."""
    out = copy.deepcopy(answer)
    for m in out:
        m["position"], m["bar_from"], m["bar_to"] = ["mark"], [None], [None]
    return out


def best(c: dict, marks: list[dict], answers: list[list[dict]]):
    top = None
    for ai, answer in enumerate(answers):
        pairs, extras = base.match(answer, marks)
        right = not extras and all(f["core"] for *_, f in pairs)
        key = (right, sum(f["core"] for *_, f in pairs), sum(sum(f.values()) for *_, f in pairs), -ai)
        if top is None or key > top[0]:
            top = (key, ai, pairs, extras)
    return top


def score_case(c: dict, raw: dict | None) -> dict:
    row = {k: c[k] for k in ("id", "cat", "diff", "fix", "text", "instruction", "none_ok", "term")}
    if raw is None:
        return {**row, "missing": True}
    facts = FIX[c["fix"]]
    try:
        ans = parse_answer(raw["text"])
        marks, refused = checked_marks(ans, c["text"], facts)
    except Exception as e:  # noqa: BLE001
        ans, marks, refused = None, [], [f"unparseable: {e}"]
    none_conf = ans.get("confidence") if isinstance(ans, dict) and ans.get("none") is True else None
    row.update(reply=raw["text"], marks=marks, refused=refused, none_conf=none_conf, seconds=raw["seconds"],
               usd=raw["usd"], output_tokens=raw["output_tokens"], produced=bool(marks))
    if not c["instruction"]:
        row.update(ok=not marks, text_all=not marks, mark_conf=[(m.get("confidence"), False) for m in marks],
                   field_hits=[], unplaced_ok=False)
        return row
    if not marks and c["none_ok"]:
        row.update(ok=True, text_all=True, mark_conf=[], field_hits=[], answer_index=None, unplaced_ok=False)
        return row
    _, ai, pairs, extras = best(c, marks, c["answers"])
    right = not extras and all(f["core"] for *_, f in pairs)
    up = best(c, marks, [_unplaced(a) for a in c["answers"]])
    row.update(answer_index=ai, n_produced=len(marks), extras=len(extras), ok=right,
               text_all=right and all(f["text"] for *_, f in pairs),
               field_hits=[{k: f[k] for k in ("position", "bars", "audience", "kind", "text", "core")} for *_, f in pairs],
               pair_text=[(g["text"], p.get("text") if p else None, f["text"]) for g, p, f in pairs],
               mark_conf=[(p.get("confidence"), f["core"]) for g, p, f in pairs if p is not None]
               + [(m.get("confidence"), False) for m in extras],
               unplaced_ok=bool(up[0][0]) and not right)
    return row


def cmd_score() -> None:
    for f in sorted(RESULTS.glob("raw_*.json")):
        tag = f.stem[4:]
        raw = json.loads(f.read_text())
        rows = [score_case(c, raw.get(c["id"])) for c in CASES]
        (RESULTS / f"score_{tag}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
        ok = sum(r.get("ok", False) for r in rows)
        print(f"{tag}: {ok}/100 right, {sum(r.get('text_all', False) for r in rows)} with text, "
              f"missing {sum(r.get('missing', False) for r in rows)}")


def main() -> None:
    cmd = sys.argv[1]
    if cmd == "call":
        asyncio.run(cmd_call(sys.argv[2], int(sys.argv[3]), sys.argv[4:] or None))
    elif cmd == "score":
        cmd_score()
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
