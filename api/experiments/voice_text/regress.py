"""Regression on real speech: CK's 40 recorded lines + the 23 negatives (realtime ENDPOINTING transcripts from
voice_stream), scored exactly as voice_stream.spark_lat.cmd_full, with v4d at effort minimal. Compared against
voice_stream/results/full_v4c_minimal.json. Calls go to this folder's ledger ($3 cap).

    uv run python -m experiments.voice_text.regress            # calls (resumes), then the comparison
"""

from __future__ import annotations

import asyncio
import json
import statistics as st

from app.librarian.voice_prompt import checked_marks, parse_answer

from ..voice.voice_eval import score_line
from ..voice_stream import common
from ..voice_stream.spark_lat import transcripts
from . import run as _run  # noqa: F401  (switches common's ledger and cap to this folder)
from .prompt_v4d import build_v4d

OLD = common.RESULTS / "full_v4c_minimal.json"
DST = _run.RESULTS / "full_v4d_minimal.json"


async def main() -> None:
    tr = transcripts()
    lab = common.labels()
    done = {r["id"]: r for r in json.loads(DST.read_text())} if DST.exists() else {}
    sem = asyncio.Semaphore(6)

    async def one(uid: str) -> dict:
        if uid in done:
            return done[uid]
        t = tr[uid]
        if not t:
            return {"id": uid, "transcript": "", "skipped": True, "marks": [], "score": {"negative": True, "ok": True}}
        s, u = build_v4d(t, uid)
        async with sem:
            r = await common.spark_chat(s, u, tag="regress:v4d_minimal", uid=uid, effort="minimal")
        try:
            ans = parse_answer(r["text"])
            marks, refused = checked_marks(ans, t, common.FACTS)
        except Exception as e:  # noqa: BLE001
            ans, marks, refused = None, [], [f"unparseable: {e}"]
        none_conf = ans.get("confidence") if isinstance(ans, dict) and ans.get("none") else None
        sc = ({"negative": True, "ok": not marks} if uid.startswith("n")
              else score_line(common.base_id(uid), lab[common.base_id(uid)], marks))
        return {"id": uid, "transcript": t, "reply": r["text"], "answer": ans, "marks": marks, "refused": refused,
                "score": sc, "confs": [m.get("confidence") for m in marks], "none_conf": none_conf,
                **{k: r[k] for k in ("seconds", "usd", "input_tokens", "output_tokens")}}

    rows = await asyncio.gather(*(one(u) for u in sorted(tr)))
    DST.write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    old = {r["id"]: r for r in json.loads(OLD.read_text())}
    for name, rs in (("v4c minimal (2026-10-30)", list(old.values())), ("v4d minimal", rows)):
        pos = [r for r in rs if not r["score"]["negative"]]
        neg = [r for r in rs if r["score"]["negative"]]
        b = [r for r in pos if not r["id"].endswith("c")]
        c = [r for r in pos if r["id"].endswith("c")]
        called = [r for r in rs if "seconds" in r]
        secs = sorted(r["seconds"] for r in called)
        auto = {t: [(r["id"], bool(r["score"].get("all_fields")) if not r["score"]["negative"] else False)
                    for r in rs for cf in (r.get("confs") or []) if isinstance(cf, (int, float)) and cf >= t]
                for t in (0.9, 0.95)}
        print(f"| {name} | {sum(bool(r['score'].get('all_fields')) for r in b)}/{len(b)} | "
              f"{sum(bool(r['score'].get('all_fields')) for r in c)}/{len(c)} | {sum(r['score']['ok'] for r in neg)}/{len(neg)} | "
              + " | ".join(f"{len(a)} ({sum(not ok for _, ok in a)} wrong)" for a in auto.values())
              + f" | {st.median(secs):.2f} | {secs[min(len(secs) - 1, round(0.9 * (len(secs) - 1)))]:.2f} | "
              f"${st.mean(r['usd'] for r in called):.4f} |")
    new = {r["id"]: r for r in rows}
    for uid in sorted(new):
        a, b = old[uid]["score"], new[uid]["score"]
        ka = a["ok"] if a["negative"] else bool(a.get("all_fields"))
        kb = b["ok"] if b["negative"] else bool(b.get("all_fields"))
        if ka != kb:
            print("CHANGED", uid, "v4c", ka, "-> v4d", kb, new[uid]["transcript"], "\n   ", new[uid].get("reply"))
    print(f"ledger ${common.spent():.4f}")


if __name__ == "__main__":
    asyncio.run(main())
