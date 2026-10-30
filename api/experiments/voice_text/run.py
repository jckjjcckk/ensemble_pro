"""Run the text set through Spark (v4c, /v1/chat/completions, streamed) and score it with code.

    uv run python -m experiments.voice_text.run call minimal     # one call per case; resumes from results/
    uv run python -m experiments.voice_text.run call low
    uv run python -m experiments.voice_text.run call minimal v4d # the fixed prompt (prompt_v4d.py)
    uv run python -m experiments.voice_text.run score minimal    # no calls: prints the tables, writes results/score_<effort>.json

The prompt is the always-on experiment's v4c (`voice_stream.spark_lat.build`): v4 rules + the eval's first eight
worked examples (none of this set's lines is among them, so nothing is held out and the examples equal the app's)
+ the confidence rule and field. Spend goes to this folder's spend.jsonl, capped at $3.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import re
import statistics as st
import sys
import unicodedata
from pathlib import Path

from app.librarian.voice_prompt import checked_marks, parse_answer

from ..voice_stream import common
from ..voice_stream.spark_lat import build
from .cases import CASES

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
common.LEDGER = HERE / "spend.jsonl"     # this task's own ledger and cap; spark_chat logs and guards through these
common.BUDGET_USD = 3.0
FACTS = common.FACTS
LAST = FACTS.bar_last


# ---------- calls ----------

def tag_of(effort: str, prompt: str) -> str:
    return effort if prompt == "v4c" else f"{prompt}_{effort}"


def prompt_for(prompt: str, text: str, uid: str) -> tuple[str, str]:
    if prompt == "v4d":
        from .prompt_v4d import build_v4d
        return build_v4d(text, uid)
    return build(prompt, text, uid)


async def cmd_call(effort: str, prompt: str = "v4c") -> None:
    dst = RESULTS / f"raw_{tag_of(effort, prompt)}.json"
    done = json.loads(dst.read_text()) if dst.exists() else {}
    sem = asyncio.Semaphore(6)

    async def one(c: dict) -> None:
        if c["id"] in done:
            return
        system, user = prompt_for(prompt, c["text"], c["id"])
        async with sem:
            try:
                r = await common.spark_chat(system, user, tag=f"text_eval:{tag_of(effort, prompt)}", uid=c["id"], effort=effort)
            except RuntimeError as e:
                print(c["id"], "ERROR", e)
                return
        done[c["id"]] = {k: r[k] for k in ("text", "seconds", "first_object", "usd", "input_tokens", "cached_tokens",
                                           "output_tokens", "reasoning_tokens")}
        print(f"{c['id']:5} {r['seconds']:.2f}s ${r['usd']:.4f} {r['text'][:110]!r}")

    await asyncio.gather(*(one(c) for c in CASES))
    dst.write_text(json.dumps(done, ensure_ascii=False, indent=1))
    print(f"{len(done)}/{len(CASES)} done; ledger total ${common.spent():.4f}")


# ---------- scoring ----------

ABBR = {"pizzicato": "pizz", "crescendo": "cresc", "ritardando": "rit", "ritard": "rit", "ritenuto": "rit",
        "rallentando": "rit", "rall": "rit", "diminuendo": "dim", "decrescendo": "dim", "decresc": "dim",
        "staccato": "stacc", "staccatissimo": "stacc", "marcato": "marc", "vibrato": "vib", "sforzando": "sfz",
        "sforzato": "sfz", "sf": "sfz", "forte": "f", "fortissimo": "ff", "piano": "p", "pianissimo": "pp",
        "fortepiano": "fp", "tenuto": "ten", "ponticello": "pont", "vibr": "vib"}


def norm_tokens(s: str) -> list[str]:
    s = "".join(ch for ch in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(ch))
    s = s.replace("mezzo forte", "mf").replace("mezzo-forte", "mf").replace("mezzo piano", "mp").replace("mezzo-piano", "mp")
    return [ABBR.get(t, t) for t in re.findall(r"[a-z0-9]+", s)]


def text_ok(keys: list[str], text: str) -> bool:
    toks = norm_tokens(text)
    joined = " ".join(toks)

    def hit(k: str) -> bool:
        if " " in k:
            return k in joined
        return k in toks if len(k) <= 3 else any(t.startswith(k) for t in toks)

    return all(any(hit(alt) for alt in key.split("|")) for key in keys)


def fields(g: dict, p: dict) -> dict:
    bt = p.get("bar_to")
    if bt is None and p.get("position") == "bar":
        bt = p.get("bar_from")
    want_bt = [x for x in g["bar_to"]]
    if "end" in want_bt:
        want_bt = [x for x in want_bt if x != "end"] + [None, LAST]
    aud = p.get("audience")
    aud = sorted(set(aud if isinstance(aud, list) else [aud]))
    f = {"position": p.get("position") in g["position"], "bar_from": p.get("bar_from") in g["bar_from"],
         "bar_to": bt in want_bt, "audience": aud in g["audience"], "kind": p.get("kind") in g["kind"],
         "text": text_ok(g["keys"], p.get("text") or "")}
    f["bars"] = f["bar_from"] and f["bar_to"]
    f["core"] = f["position"] and f["bars"] and f["audience"] and f["kind"]
    return f


NOF = {"position": False, "bar_from": False, "bar_to": False, "audience": False, "kind": False, "text": False,
       "bars": False, "core": False}


def match(answer: list[dict], marks: list[dict]):
    """Best one-to-one pairing of expected marks to produced ones: (pairs [(g, p|None, fields)], extras)."""
    n = len(answer)
    idx = list(range(len(marks))) + [None] * n
    best = None
    for perm in set(itertools.permutations(idx, n)):
        pairs = [(g, marks[i] if i is not None else None, fields(g, marks[i]) if i is not None else NOF)
                 for g, i in zip(answer, perm)]
        used = {i for i in perm if i is not None}
        key = (sum(f["core"] for *_, f in pairs), sum(sum(f.values()) for *_, f in pairs))
        if best is None or key > best[0]:
            best = (key, pairs, [m for i, m in enumerate(marks) if i not in used])
    return best[1], best[2]


def score_case(c: dict, raw: dict | None) -> dict:
    row = {"id": c["id"], "cat": c["cat"], "diff": c["diff"], "text": c["text"], "instruction": c["instruction"]}
    if raw is None:
        return {**row, "missing": True}
    reply = raw["text"]
    try:
        ans = parse_answer(reply)
        marks, refused = checked_marks(ans, c["text"], FACTS)
    except Exception as e:  # noqa: BLE001
        ans, marks, refused = None, [], [f"unparseable: {e}"]
    none_conf = ans.get("confidence") if isinstance(ans, dict) and ans.get("none") is True else None
    row.update(reply=reply, marks=marks, refused=refused, none_conf=none_conf, seconds=raw["seconds"], usd=raw["usd"],
               output_tokens=raw["output_tokens"])
    if not c["instruction"]:
        row.update(ok=not marks, mark_conf=[(m.get("confidence"), False) for m in marks])
        return row
    best = None
    for ai, answer in enumerate(c["answers"]):
        pairs, extras = match(answer, marks)
        right = not extras and all(f["core"] for *_, f in pairs)
        key = (right, sum(f["core"] for *_, f in pairs), sum(sum(f.values()) for *_, f in pairs), -ai)
        if best is None or key > best[0]:
            best = (key, ai, pairs, extras)
    _, ai, pairs, extras = best
    right = not extras and all(f["core"] for *_, f in pairs)
    row.update(answer_index=ai, n_expected=len(c["answers"][ai]), n_produced=len(marks), extras=len(extras),
               produced=bool(marks), ok=right, text_all=right and all(f["text"] for *_, f in pairs),
               field_hits=[{k: f[k] for k in ("position", "bars", "audience", "kind", "text", "core")} for *_, f in pairs],
               pair_text=[(g["text"], p.get("text") if p else None, f["text"]) for g, p, f in pairs],
               mark_conf=[(p.get("confidence"), f["core"]) for g, p, f in pairs if p is not None]
               + [(m.get("confidence"), False) for m in extras])
    return row


def med(xs):
    return st.median(xs) if xs else float("nan")


def p90(xs):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(0.9 * (len(xs) - 1))))] if xs else float("nan")


def cmd_score(effort: str, prompt: str = "v4c") -> dict:
    effort = tag_of(effort, prompt)
    raw = json.loads((RESULTS / f"raw_{effort}.json").read_text())
    rows = [score_case(c, raw.get(c["id"])) for c in CASES]
    (RESULTS / f"score_{effort}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    ins = [r for r in rows if r["instruction"] and not r.get("missing")]
    neg = [r for r in rows if not r["instruction"] and not r.get("missing")]
    marks_exp = [fh for r in ins for fh in r["field_hits"]]
    print(f"== {effort}: {len(ins)} instructions, {len(neg)} non-instructions, {len(marks_exp)} expected marks")
    print("cases fully right:", sum(r["ok"] for r in ins), "/", len(ins), "; with stand text:", sum(r["text_all"] for r in ins))
    for k in ("position", "bars", "audience", "kind", "text", "core"):
        print(f"  field {k:9} {sum(f[k] for f in marks_exp)}/{len(marks_exp)}")
    print("false negatives (no mark):", [r["id"] for r in ins if not r["produced"]])
    print("refused by check:", [(r["id"], r["refused"]) for r in rows if r.get("refused")])
    print("false positives:", [r["id"] for r in neg if not r["ok"]])
    cats = sorted({r["cat"] for r in ins}, key=lambda x: [c["cat"] for c in CASES].index(x))
    for cat in cats:
        rs = [r for r in ins if r["cat"] == cat]
        print(f"  {cat:14} {sum(r['ok'] for r in rs)}/{len(rs)}  text {sum(r['text_all'] for r in rs)}")
    for d in ("easy", "medium", "hard"):
        rs = [r for r in ins if r["diff"] == d]
        print(f"  {d:8} {sum(r['ok'] for r in rs)}/{len(rs)}")
    secs = [r["seconds"] for r in rows if not r.get("missing")]
    print(f"latency median {med(secs):.2f} p90 {p90(secs):.2f}; cost ${sum(r['usd'] for r in rows if not r.get('missing')):.4f}")
    return {"rows": rows}


def main() -> None:
    cmd, effort, prompt = sys.argv[1], sys.argv[2], (sys.argv[3:4] or ["v4c"])[0]
    if cmd == "call":
        asyncio.run(cmd_call(effort, prompt))
    elif cmd == "score":
        cmd_score(effort, prompt)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
