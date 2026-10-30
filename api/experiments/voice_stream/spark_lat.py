"""Q2 + Q3: Spark latency per prompt/effort/streaming, and a confidence field for the gate.

    uv run python -m experiments.voice_stream.spark_lat probe
    uv run python -m experiments.voice_stream.spark_lat lat               # the five lines, every variant, x2
    uv run python -m experiments.voice_stream.spark_lat full v4c low      # every clip (realtime transcripts) + negatives

Prompts (all hold out the scored line from the few-shot, as the eval did):
  v4   the chosen prompt (eval builder, 8 examples)
  v4c  v4 + a `confidence` field per mark and on {"none": true}
  v4sc the same rules condensed (same topics, same schema) + 4 examples + confidence
Transcripts are the realtime ENDPOINTING ones (`results/realtime_endpointing.json`), the always-on path.
"""

from __future__ import annotations

import asyncio
import json
import statistics as st
import sys

from app.librarian.voice_prompt import checked_marks, parse_answer

from ..voice import prompts
from ..voice.voice_eval import few_shot_pool, score_line
from .common import FACTS, RESULTS, base_id, labels, spark_chat, spark_stream, spent

FIVE = ["v02", "v08", "v11", "v15", "v21"]

CONF_RULE = """- confidence: your probability (0.0 to 1.0) that this mark is what the conductor meant to be written on
  the music, with these bars and this audience. With {"none": true} give the probability that nothing was meant to
  be written: {"none": true, "confidence": 0.9}."""

SCHEMA_C = ('[{"position": "bar|range|mark|global", "bar_from": int|null, "bar_to": int|null, '
            '"audience": ["ensemble" | "part:<part name>" | "member:<name>", ...], '
            '"kind": "cut|dynamic|marking|text|breath|bowing", "text": "<the one-line mark for the stand>", '
            '"quote": "<verbatim span of the transcript the mark comes from>", "confidence": 0.0-1.0}, ...]')

RULES_S = """Rules:
- Not a mark, answer {"none": true}: where to start playing with nothing to write ("from the top", "letter A, off we
  go", "once more from 57"), logistics, praise. A start point with something to remember ("from 57, keep it light")
  is a mark there; a part's entry is a mark.
- Self-corrections ("18, no, 19"): the last version wins and replaces only what it corrects. Ignore filler and
  false starts.
- position: "bar" = one bar (bar_to = bar_from) or a pickup and its bar (80-81); "range" = from X to Y (bar_to null
  for "to the end"); "mark" = a rehearsal letter, double bar, key change, coda or section (bars null, name it in
  text); "global" = the whole piece or its very start or end (bars null).
- audience: "ensemble" for everyone (tutti, whole choir) or nobody named. firsts = Violin I, seconds = Violin II,
  fiddles = both violins. "Everyone except X" = the other parts of X's group (strings Violin I, Violin II, Viola,
  Cello; voices Soprano, Alto, Tenor, Bass). "member:<name>" only when the name is clearly said.
- kind: dynamic = loudness; marking = a symbol or technique (pizz., arco, mute, accent, fermata, vibrato); bowing =
  up/down bow; breath; cut = a cut or skipped repeat; text = anything else (tempo, rit., character, rhythm, pitch).
- text: the short pencil mark with its place ("mf at bar 9", "Cut 130–137", "From E: lighter").
- quote: an exact contiguous span of the transcript.
- One object per audience; several places for one audience in one breath are one mark covering them.
- Speech recognition mishears: a word that sounds like a part, nickname or member ("Chelos", "Violets", "Lynn") is
  that part or person; "accept" or "stop" before a part may be "except". Numbers are usually right."""


def _ex(holdout: set[str], n: int) -> str:
    keep = prompts.EXAMPLES_N
    prompts.EXAMPLES_N = n
    try:
        return prompts._examples(few_shot_pool(), holdout)
    finally:
        prompts.EXAMPLES_N = keep


def build(version: str, transcript: str, uid: str) -> tuple[str, str]:
    hold = {uid, base_id(uid)}
    if version in ("v4", "v4c"):
        system, user = prompts.v4(transcript, FACTS, hold, few_shot_pool())
        if version == "v4c":
            user = user.replace(prompts.SCHEMA_LIST, SCHEMA_C)
            user = user.replace("\n\nWorked examples", f"\n{CONF_RULE}\n\nWorked examples")
            user = user.replace('{"none": true}.', '{"none": true, "confidence": <0.0-1.0>}.')
            assert CONF_RULE in user and SCHEMA_C in user
        return system, user
    if version == "app":                         # production: fixed examples, so the prefix is the same every call
        from app.librarian.voice_prompt import build_prompt
        return build_prompt(transcript, FACTS)
    if version == "v4sc":
        system = prompts.SYSTEM if hasattr(prompts, "SYSTEM") else (
            "You turn a conductor's spoken rehearsal instruction into proposed marks on the players' parts. "
            "Answer with JSON only.")
        user = (f"Score facts:\n{FACTS.as_text()}\n\n{RULES_S}\n{CONF_RULE}\n\n"
                f"Examples (other instructions, same score):\n\n{_ex(hold, 4)}\n\n"
                f"Transcript:\n\"{transcript}\"\n\n"
                f"Answer a JSON array of marks:\n{SCHEMA_C}\nor {{\"none\": true, \"confidence\": <0.0-1.0>}}.")
        return system, user
    raise ValueError(version)


def transcripts() -> dict[str, str]:
    rt = json.loads((RESULTS / "realtime_endpointing.json").read_text())
    return {k: v["transcript"] for k, v in rt.items()}


async def cmd_probe() -> None:
    t = transcripts()["v02"]
    for v in ("v4", "v4sc"):
        s, u = build(v, t, "v02")
        r = await spark_stream(s, u, tag=f"probe:{v}", uid="v02")
        print(v, len(u), json.dumps({k: r[k] for k in r if k != "text"}), r["text"][:300])
    print(f"spent ${spent():.4f}")


VARIANTS = [  # (name, prompt, api, effort, model)
    ("today: app prompt, messages, low", "app", "messages", "low", "muse-spark-1.3"),
    ("v4 held-out, messages, low", "v4", "messages", "low", "muse-spark-1.3"),
    ("v4, chat stream, low", "v4", "chat", "low", "muse-spark-1.3"),
    ("v4, chat stream, minimal", "v4", "chat", "minimal", "muse-spark-1.3"),
    ("app prompt, chat stream, minimal", "app", "chat", "minimal", "muse-spark-1.3"),
    ("v4sc, chat stream, low", "v4sc", "chat", "low", "muse-spark-1.3"),
    ("v4sc, chat stream, minimal", "v4sc", "chat", "minimal", "muse-spark-1.3"),
    ("v4sc, chat stream, minimal, contributor", "v4sc", "chat", "minimal", "muse-spark-1.3-contributor"),
]


async def call(ver: str, api: str, effort: str, model: str, transcript: str, uid: str, tag: str) -> dict:
    s, u = build(ver, transcript, uid)
    if api == "messages":
        r = await spark_stream(s, u, tag=tag, uid=uid, effort=effort, model=model, stream=False)
    else:
        r = await spark_chat(s, u, tag=tag, uid=uid, effort=effort, model=model)
    r["prompt_chars"] = len(u)
    return r


async def cmd_lat(reps: int = 2) -> None:
    tr = transcripts()
    out = []
    for rep in range(reps):
        for name, ver, api, eff, model in VARIANTS:
            for uid in FIVE:
                r = await call(ver, api, eff, model, tr[uid], uid, f"lat:{name}")
                try:
                    marks, refused = checked_marks(parse_answer(r["text"]), tr[uid], FACTS)
                except Exception:  # noqa: BLE001
                    marks, refused = [], ["unparseable"]
                sc = score_line(base_id(uid), labels()[base_id(uid)], marks)
                out.append({"variant": name, "uid": uid, "rep": rep, **r, "all_fields": sc.get("all_fields")})
                print(f"{name:42} {uid} {r['seconds']:.2f}s tok1={r['first_token'] and round(r['first_token'], 2)} "
                      f"obj1={r['first_object'] and round(r['first_object'], 2)} in={r['input_tokens']}/{r['cached_tokens']}c "
                      f"out={r['output_tokens']} ok={sc.get('all_fields')}")
            (RESULTS / "spark_latency.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"spent ${spent():.4f}")
    for name, *_ in VARIANTS:
        rows = [r for r in out if r["variant"] == name]
        print(f"{name:42} median {st.median(r['seconds'] for r in rows):.2f}s "
              f"obj1 {st.median([r['first_object'] or r['seconds'] for r in rows]):.2f}s "
              f"out {st.median(r['output_tokens'] for r in rows)} ok {sum(bool(r['all_fields']) for r in rows)}/{len(rows)}")


async def cmd_full(version: str, effort: str, model: str = "muse-spark-1.3", api: str = "chat") -> None:
    tr = transcripts()
    lab = labels()
    sem = asyncio.Semaphore(6)
    tag = f"{version}_{effort}" + ("_contrib" if "contributor" in model else "")

    async def one(uid: str) -> dict:
        t = tr[uid]
        if not t:                                    # piano / instrument: no turn, Spark is never called
            return {"id": uid, "transcript": "", "skipped": True, "marks": [], "score": {"negative": True, "ok": True}}
        async with sem:
            r = await call(version, api, effort, model, t, uid, f"full:{tag}")
        try:
            ans = parse_answer(r["text"])
            marks, refused = checked_marks(ans, t, FACTS)
        except Exception as e:  # noqa: BLE001
            ans, marks, refused = None, [], [f"unparseable: {e}"]
        none_conf = ans.get("confidence") if isinstance(ans, dict) and ans.get("none") else None
        if uid.startswith("n"):
            sc = {"negative": True, "ok": not marks}
        else:
            sc = score_line(base_id(uid), lab[base_id(uid)], marks)
        return {"id": uid, "transcript": t, "answer": ans, "marks": marks, "refused": refused, "score": sc,
                "confs": [m.get("confidence") for m in marks], "none_conf": none_conf,
                **{k: r[k] for k in ("seconds", "first_object", "usd", "input_tokens", "output_tokens")}}

    rows = await asyncio.gather(*(one(u) for u in sorted(tr)))
    (RESULTS / f"full_{tag}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    pos = [r for r in rows if not r["score"]["negative"]]
    neg = [r for r in rows if r["score"]["negative"]]
    print(f"{tag}: all fields {sum(bool(r['score'].get('all_fields')) for r in pos)}/{len(pos)}, "
          f"produced {sum(bool(r['score'].get('produced')) for r in pos)}/{len(pos)}, negatives ok "
          f"{sum(r['score']['ok'] for r in neg)}/{len(neg)}, median s "
          f"{st.median(r['seconds'] for r in rows if 'seconds' in r):.2f}, spent ${spent():.4f}")
    for r in rows:
        s = r["score"]
        flag = ("ok" if s["ok"] else "FALSE POSITIVE") if s["negative"] else (
            " ".join(k for k in ("position", "bar_from", "bar_to", "audience", "kind") if not s.get(k)) or "all ok")
        print(f"{r['id']:5} {flag:40} conf={r.get('confs')} none={r.get('none_conf')} {r['transcript'][:70]}")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "probe":
        asyncio.run(cmd_probe())
    elif cmd == "lat":
        asyncio.run(cmd_lat())
    elif cmd == "full":
        asyncio.run(cmd_full(sys.argv[2], sys.argv[3], *(sys.argv[4:5] or [])))
