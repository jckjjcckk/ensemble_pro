"""Q4 follow-up: what the chunk boundaries do to the marks. Meta ENDPOINTING turns of long.wav go to Spark
(v4c, minimal, chat stream) two ways:
  A  each turn alone;
  B  a turn that starts within JOIN_S of the previous turn's end is also sent joined with it ("prev cur"); each
     turn keeps the marks of the latest reading that contains it (joined with the next turn, else joined with the
     previous, else alone), a mark belonging to the turn its quote comes from. In the app: the card of turn k is
     replaced when turn k+1 arrives within JOIN_S and the joined reading says otherwise.
Scored per spoken line with the eval's score_line (union of the marks of the turns that overlap it).

    uv run python -m experiments.voice_stream.stream_eval
"""

from __future__ import annotations

import asyncio
import json

from app.librarian.voice_prompt import checked_marks, parse_answer

from ..voice.voice_eval import score_line
from .common import FACTS, LOCAL, RESULTS, base_id, labels, spent
from .chunk import meta_turns, overlap
from .spark_lat import call

JOIN_S = 2.0
GROUP_GAP_S = 1.0       # C: turns closer than this form one group, re-read whole each time a turn completes
GROUP_MAX_TURNS = 3


async def run() -> None:
    truth = json.loads((LOCAL / "long_truth.json").read_text())["segments"]
    turns = meta_turns(0)
    lab = labels()
    sem = asyncio.Semaphore(6)

    cache_p = RESULTS / "stream_eval_cache.json"
    cache = json.loads(cache_p.read_text()) if cache_p.exists() else {}

    async def spark(text: str, key: str) -> list[dict]:
        if text not in cache:
            async with sem:
                r = await call("v4c", "chat", "minimal", "muse-spark-1.3", text, key, "stream_eval")
            cache[text] = {"reply": r["text"], "seconds": r["seconds"]}
        try:
            marks, _ = checked_marks(parse_answer(cache[text]["reply"]), text, FACTS)
        except Exception:  # noqa: BLE001
            marks = []
        return marks

    def owner(t: dict) -> str:
        best = max(truth, key=lambda u: overlap(t, u))
        return best["id"] if overlap(t, best) > 0 else "x"

    marks_a = await asyncio.gather(*(spark(t["text"], owner(t)) for t in turns))
    jidx = [i for i, t in enumerate(turns) if i and t["start"] - turns[i - 1]["end"] <= JOIN_S]
    jtext = {i: f"{turns[i - 1]['text']} {turns[i]['text']}" for i in jidx}
    jmarks = dict(zip(jidx, await asyncio.gather(*(spark(jtext[i], owner(turns[i])) for i in jidx))))
    cache_p.write_text(json.dumps(cache, ensure_ascii=False, indent=1))

    def side(m: dict, i: int) -> str:
        """'prev' or 'cur': where in the joined reading i the mark's quote sits (most of it)."""
        f = lambda x: " ".join(x.lower().split())
        prev, joined, q = f(turns[i - 1]["text"]), f(jtext[i]), f(m.get("quote", "")).strip(" \"'.,;:!?")
        k = joined.find(q)
        if k < 0:
            return "cur"
        return "prev" if (k + len(q) / 2) < len(prev) else "cur"

    marks_b = []
    for j in range(len(turns)):
        if j + 1 in jmarks:
            marks_b.append([m for m in jmarks[j + 1] if side(m, j + 1) == "prev"])
        elif j in jmarks:
            marks_b.append([m for m in jmarks[j] if side(m, j) == "cur"])
        else:
            marks_b.append(marks_a[j])

    # C: rolling groups. Each turn completing within GROUP_GAP_S of the last joins the group (at most
    # GROUP_MAX_TURNS); the group's latest reading replaces its cards. A mark goes to the turn its quote sits in.
    groups, cur = [], [0]
    for i in range(1, len(turns)):
        if turns[i]["start"] - turns[i - 1]["end"] <= GROUP_GAP_S and len(cur) < GROUP_MAX_TURNS:
            cur.append(i)
        else:
            groups.append(cur)
            cur = [i]
    groups.append(cur)
    gtext = [" ".join(turns[i]["text"] for i in g) for g in groups]
    gmarks = await asyncio.gather(*(spark(t, owner(turns[g[-1]])) for g, t in zip(groups, gtext)))
    cache_p.write_text(json.dumps(cache, ensure_ascii=False, indent=1))
    marks_c = [[] for _ in turns]
    for g, t, ms in zip(groups, gtext, gmarks):
        f = lambda x: " ".join(x.lower().split())
        bounds, k = [], 0
        for i in g:
            k += len(f(turns[i]["text"])) + 1
            bounds.append(k)
        for m in ms:
            q = f(m.get("quote", "")).strip(" \"'.,;:!?")
            at = f(t).find(q)
            mid = at + len(q) / 2 if at >= 0 else bounds[-1] - 1
            marks_c[g[next(n for n, b in enumerate(bounds) if mid < b)]].append(m)
    extra_calls_c = sum(len(g) - 1 for g in groups)

    out = {"turns": [{**t, "A": marks_a[i], "B": marks_b[i], "joined": i in jmarks, "C": marks_c[i]} for i, t in enumerate(turns)],
           "lines": []}
    for u in truth:
        if not u["utterance"]:
            continue
        idx = [i for i, t in enumerate(turns) if overlap(t, u) > 0.1]
        row = {"id": u["id"], "turns": idx}
        for name, mk in (("A", marks_a), ("B", marks_b), ("C", marks_c)):
            ms = [m for i in idx for m in mk[i]]
            if u["negative"]:
                row[name] = {"negative": True, "ok": not ms}
            else:
                row[name] = score_line(base_id(u["id"]), lab[base_id(u["id"])], ms)
        out["lines"].append(row)
    # marks on turns that overlap no line (music, stray): false positives
    out["stray_marks"] = {n: sum(len(mk[i]) for i, t in enumerate(turns)
                                 if not any(overlap(t, u) > 0.1 and u["utterance"] for u in truth))
                          for n, mk in (("A", marks_a), ("B", marks_b), ("C", marks_c))}
    out["groups"] = groups
    out["extra_calls"] = {"A": 0, "B": len(jidx), "C": extra_calls_c}
    (RESULTS / "stream_eval.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    for r in out["lines"]:
        f = lambda s: ("ok" if s["ok"] else "FP") if s["negative"] else ("all ok" if s["all_fields"] else
              " ".join(k for k in ("produced", "position", "bar_from", "bar_to", "audience", "kind") if not s.get(k)))
        print(f"{r['id']:5} turns={r['turns']} A: {f(r['A']):30} B: {f(r['B']):30} C: {f(r['C'])}")
    print("groups", groups)
    for n in ("A", "B", "C"):
        pos = [r[n] for r in out["lines"] if not r[n]["negative"]]
        neg = [r[n] for r in out["lines"] if r[n]["negative"]]
        print(n, f"all fields {sum(bool(s['all_fields']) for s in pos)}/{len(pos)}, negatives ok "
                 f"{sum(s['ok'] for s in neg)}/{len(neg)}, stray {out['stray_marks'][n]}")
    print(f"spent ${spent():.4f}")


if __name__ == "__main__":
    asyncio.run(run())
