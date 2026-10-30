"""Speech half: CK's 40 recorded lines through Voice Transcribe realtime (ENDPOINTING, the always-on path, client
`voice_stream.realtime`) once with today's keywords (`transcribe_voice.Score.keywords()` for the eval book) and once
with today's plus a music glossary; WER overall and on term words; then each transcript set through v4d once
(minimal) and scored as the recorded eval (`voice_eval.score_line`, base 26 / retakes 9).

    uv run python -m experiments.voice_text.messy100.asr asr        # 80 streams (resumes)
    uv run python -m experiments.voice_text.messy100.asr spark      # 80 Spark calls (resumes)
    uv run python -m experiments.voice_text.messy100.asr report

Meta documents no limit on the number or length of `keywords` (schemas, speech-to-text and transcribe pages,
fetched 2026-10-30: "array of string", "Biasing does not guarantee an exact spelling"); every handshake is checked
for an error event.
"""

from __future__ import annotations

import asyncio
import json
import sys

from app.librarian.transcribe_voice import Score
from app.librarian.voice_prompt import checked_marks, parse_answer

from ...voice.textnorm import wer, words
from ...voice.voice_eval import score_line
from ...voice_stream import common, realtime
from .prompts import build_v4d
from .run import HERE, RESULTS

common.LEDGER = HERE / "spend.jsonl"
common.BUDGET_USD = 3.0


def today_keywords() -> list[str]:
    s = Score.__new__(Score)
    s.parts, s.members = common.FACTS.parts, {"Lin": "m1", "Inès": "m2"}
    s.letters = {c: i for i, c in enumerate(common.FACTS.rehearsal_marks)}
    return s.keywords()


GLOSSARY = ["pizzicato", "pizz", "arco", "fermata", "ritardando", "ritard", "a tempo", "sforzando", "subito",
            "crescendo", "diminuendo", "staccato", "legato", "tenuto", "marcato", "accent", "sordino", "mute",
            "divisi", "tutti", "pickup", "downbeat", "double bar", "coda", "segno", "key change", "vibrato",
            "harmonic", "up bow", "down bow", "breath mark", "cut", "letter", "bar", "repeat", "forte", "piano",
            "fortissimo", "pianissimo", "mezzo"]
TODAY = today_keywords()
PLUS = list(dict.fromkeys(TODAY + GLOSSARY))
SETS = {"today": TODAY, "glossary": PLUS, "today2": TODAY, "glossary2": PLUS}   # *2 = a second run, for ASR noise
# term words scored: every glossary token, less the ones today's list already biases and function words
TERM_TOKENS = {t for g in GLOSSARY for t in words(g)} - {"a", "bar", "letter", "pickup", "mark"}


def ids() -> list[str]:
    return sorted(p.stem for p in common.WAVS.glob("v*.wav"))


async def cmd_asr() -> None:
    sem = asyncio.Semaphore(6)
    for name, kw in SETS.items():
        dst = RESULTS / f"asr_{name}.json"
        done = json.loads(dst.read_text()) if dst.exists() else {}

        async def one(uid, kw=kw, name=name, done=done):
            if uid in done:
                return
            async with sem:
                x = realtime.clip(uid)
                res = await realtime.stream(x, "ENDPOINTING", keywords=kw, tag=f":messy100_{name}", uid=uid)
            s = realtime.summarise(res, x, "ENDPOINTING")
            errs = [e for e in res["events"] if e.get("type") == "error"]
            done[uid] = {"transcript": s["transcript"], "errors": errs, "close": res["close"], "ack": res["ack"]}
            print(name, uid, res["close"], errs[:1], s["transcript"])

        await asyncio.gather(*(one(u) for u in ids()))
        dst.write_text(json.dumps(done, ensure_ascii=False, indent=1))
    print(f"ledger ${common.spent():.4f}")


def align(ref: list[str], hyp: list[str]) -> list[tuple[str | None, str | None]]:
    n, m = len(ref), len(hyp)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]))
    out, i, j = [], n, m
    while i or j:
        if i and j and d[i][j] == d[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]):
            out.append((ref[i - 1], hyp[j - 1])); i -= 1; j -= 1
        elif i and d[i][j] == d[i - 1][j] + 1:
            out.append((ref[i - 1], None)); i -= 1
        else:
            out.append((None, hyp[j - 1])); j -= 1
    return out[::-1]


def term_errors(ref: str, hyp: str) -> tuple[int, int, list[str]]:
    pairs = align(words(ref), words(hyp))
    terms = [(r, h) for r, h in pairs if r in TERM_TOKENS]
    bad = [f"{r}->{h}" for r, h in terms if r != h]
    return len(bad), len(terms), bad


async def cmd_spark() -> None:
    lab = common.labels()
    sem = asyncio.Semaphore(6)
    for name in SETS:
        tr = json.loads((RESULTS / f"asr_{name}.json").read_text())
        dst = RESULTS / f"asr_spark_{name}.json"
        done = json.loads(dst.read_text()) if dst.exists() else {}

        async def one(uid, tr=tr, name=name, done=done):
            if uid in done:
                return
            t = tr[uid]["transcript"]
            r = None
            if t:
                s, u = build_v4d(t, common.FACTS)
                async with sem:
                    r = await common.spark_chat(s, u, tag=f"messy100:asr_{name}", uid=uid, effort="minimal")
            try:
                ans = parse_answer(r["text"]) if r else {"none": True}
                marks, refused = checked_marks(ans, t, common.FACTS)
            except Exception as e:  # noqa: BLE001
                marks, refused = [], [f"unparseable: {e}"]
            done[uid] = {"transcript": t, "reply": r["text"] if r else None, "marks": marks, "refused": refused,
                         "score": score_line(common.base_id(uid), lab[common.base_id(uid)], marks),
                         "usd": r["usd"] if r else 0, "seconds": r["seconds"] if r else None}

        await asyncio.gather(*(one(u) for u in ids()))
        dst.write_text(json.dumps(done, ensure_ascii=False, indent=1))
    print(f"ledger ${common.spent():.4f}")


def cmd_report() -> None:
    lab = common.labels()
    print("keywords today", len(TODAY), TODAY)
    print("keywords +glossary", len(PLUS))
    per = {}
    for name in SETS:
        tr = json.loads((RESULTS / f"asr_{name}.json").read_text())
        e = n = te = tn = 0
        rows = {}
        for uid in ids():
            ref = lab[common.base_id(uid)]["text"]
            a, b = wer(ref, tr[uid]["transcript"])
            x, y, bad = term_errors(ref, tr[uid]["transcript"])
            e, n, te, tn = e + a, n + b, te + x, tn + y
            rows[uid] = (a, b, x, y, bad, tr[uid]["transcript"])
        errs = sum(bool(tr[u]["errors"]) for u in tr)
        per[name] = rows
        sp = json.loads((RESULTS / f"asr_spark_{name}.json").read_text()) if (RESULTS / f"asr_spark_{name}.json").exists() else {}
        pos = [(u, r) for u, r in sp.items() if not r["score"]["negative"]]
        neg = [(u, r) for u, r in sp.items() if r["score"]["negative"]]
        base_ok = sum(bool(r["score"].get("all_fields")) for u, r in pos if not u.endswith("c"))
        ret_ok = sum(bool(r["score"].get("all_fields")) for u, r in pos if u.endswith("c"))
        nb = sum(not u.endswith("c") for u, _ in pos)
        print(f"{name}: WER {e}/{n} = {e / n:.3f}; term words {te}/{tn} = {te / max(tn, 1):.3f}; error events {errs}; "
              f"v4d all fields base {base_ok}/{nb} retakes {ret_ok}/{len(pos) - nb} negatives "
              f"{sum(r['score']['ok'] for _, r in neg)}/{len(neg)}; spark ${sum(r['usd'] for r in sp.values()):.4f}")
    for x, y in (("today", "today2"), ("glossary", "glossary2"), ("today2", "glossary2")):
        diff = [u for u in ids() if per[x][u][0] != per[y][u][0] or per[x][u][2] != per[y][u][2]]
        print(f"{x} vs {y}: lines with a different WER or term count: {len(diff)}", diff)
    a, b = per["today"], per["glossary"]
    for uid in ids():
        if a[uid][:4] != b[uid][:4] or a[uid][5] != b[uid][5]:
            if "-v" not in sys.argv and not (b[uid][0] > a[uid][0] or b[uid][2] > a[uid][2] or b[uid][2] < a[uid][2]):
                continue
            flag = "WORSE" if b[uid][0] > a[uid][0] or b[uid][2] > a[uid][2] else ("better" if b[uid][0] < a[uid][0] or b[uid][2] < a[uid][2] else "same-count")
            print(f"{uid} {flag} wer {a[uid][0]}->{b[uid][0]} terms {a[uid][2]}->{b[uid][2]} {a[uid][4]} -> {b[uid][4]}\n"
                  f"   today:    {a[uid][5]}\n   glossary: {b[uid][5]}")
    for name in SETS:
        p = RESULTS / f"asr_spark_{name}.json"
        if p.exists():
            sp = json.loads(p.read_text())
            print(name, "not all-fields:", [u for u, r in sorted(sp.items()) if not r["score"]["negative"] and not r["score"].get("all_fields")],
                  "neg wrong:", [u for u, r in sorted(sp.items()) if r["score"]["negative"] and not r["score"]["ok"]])


if __name__ == "__main__":
    {"asr": lambda: asyncio.run(cmd_asr()), "spark": lambda: asyncio.run(cmd_spark()), "report": cmd_report}[sys.argv[1]]()
