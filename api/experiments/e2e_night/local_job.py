"""One job on main's code, in this process, against the hosted chain, without yoga's worker: for a fix in a handler
yoga runs (`part_cut`, `omr_convert`) while yoga stays on its own commit. The row goes in as `running` with a fresh
`locked_at` (`claim_job` takes only `queued`, and yoga requeues a running row only after 15 minutes, so yoga leaves it
alone) with exactly the payload the API would give it (`routes/jobs.answer_job`, `routes/convert.convert`), then
`worker.run_one` runs it here. The OMR box is reached as `OMR_HOST` (the `yoga` alias; the run folder is the job's own).

    PYTHONPATH=. OMR_HOST=yoga uv run python -m experiments.e2e_night.local_job answer <slug> <job_id> '<json>'
    PYTHONPATH=. OMR_HOST=yoga uv run python -m experiments.e2e_night.local_job convert <slug> [pages]
    PYTHONPATH=. uv run python -m experiments.e2e_night.local_job cut <slug> <instrument> [instrument ...] [--pages 8-12]
    PYTHONPATH=. uv run python -m experiments.e2e_night.local_job again <slug> <job_id>     (a failed job's payload, again)

Answer only questions a local run parked: a parked agent's transcript carries the Meta key's redacted_thinking, which
another key cannot replay.

The book's results file gets the same steps as `book.py` (label `local:` in front), and a question exits 3 as there.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone

# As yoga runs it: Spark. The Mac's api/.env says LLM_PROVIDER=anthropic (the dev API's own default), and the first
# three local runs of the night went to Claude by it ($4.00, two Goldberg cuts and the Moscheles convert).
os.environ["LLM_PROVIDER"] = "meta"

from app.db import db
from app.librarian import load_handlers, omr_convert  # noqa: F401  (registers omr_convert, as routes/convert.py does)
from app.routes.live_jobs import parts_key
from app.worker import run_one

from .book import cmd_waitjob, state
from .common import As, guard, save


def _insert_running(row: dict) -> dict:
    t = datetime.now(timezone.utc).isoformat()
    # max_attempts 1: a failure here must not requeue the row for yoga's worker to pick up on its own commit (a resume of
    # a transcript yoga's key wrote is refused by Meta with a 400 on its redacted_thinking blocks, and yoga then ran it)
    row = {**row, "status": "running", "attempts": 1, "max_attempts": 1, "locked_at": t, "started_at": t}
    return db().table("jobs").insert(row).execute().data[0]


def answer(slug: str, job_id: str, body: dict) -> dict:
    a = As()
    job = db().table("jobs").select("id,kind,status,score_id,payload,result").eq("id", job_id).single().execute().data
    result = job.get("result") or {}
    assert job["status"] == "done" and result.get("question"), "not a parked question"
    payload = {k: v for k, v in (job.get("payload") or {}).items() if k not in ("answer", "resume_from")}
    q = result.get("question_payload") or {}
    if q.get("interpretation_id") and not payload.get("interpretation_id"):
        payload["interpretation_id"] = q["interpretation_id"]
    payload.update({"answer": body["answer"] if set(body) == {"answer"} else body, "resume_from": job_id})
    if job["kind"] == "part_cut" and payload.get("parts_key") is None:
        payload["parts_key"] = parts_key(payload.get("instruments") or [payload["instrument"]])
    row = _insert_running({"kind": job["kind"], "score_id": job["score_id"], "created_by": a.uid, "payload": payload})
    if job["kind"] == "part_cut" and q.get("interpretation_id"):
        db().table("interpretations").update({"status": "running"}).eq("id", q["interpretation_id"]).eq("status", "needs_review").execute()
    s = state(slug)
    for x in s["questions"]:
        if x["job"] == job_id:
            x.update(answer=body, answered_at=datetime.now().isoformat(timespec="seconds"), follow_up=row["id"], local=True)
    s["jobs"][row["id"]] = {"kind": row["kind"], "created_at": row["created_at"], "local": True}
    save(slug, s)
    return row


def convert(slug: str, pages: list[int] | None = None) -> dict:
    guard(1.0)
    a = As()
    s = state(slug)
    src = db().table("sources").select("id").eq("score_id", s["score_id"]).eq("kind", "pdf").order("created_at").execute().data
    payload: dict = {"score_id": s["score_id"], "source_id": src[0]["id"]}
    if pages:
        payload["pages"] = pages
    row = _insert_running({"kind": "omr_convert", "score_id": None, "created_by": a.uid, "max_attempts": 1, "payload": payload})
    s["jobs"][row["id"]] = {"kind": row["kind"], "created_at": row["created_at"], "local": True}
    save(slug, s)
    return row


def cut(slug: str, instruments: list[str], pages: list[int] | None = None) -> dict:
    guard(0.5)
    a = As()
    s = state(slug)
    payload = {"score_id": s["score_id"], "parts_key": parts_key(instruments), "instruments": instruments}
    if pages:
        payload["pages"] = pages      # an excerpt (the experiment budget: 3-5 pages a file)
    row = _insert_running({"kind": "part_cut", "score_id": s["score_id"], "created_by": a.uid, "payload": payload})
    s["jobs"][row["id"]] = {"kind": row["kind"], "created_at": row["created_at"], "local": True}
    s["cut_label"] = "cut:" + "+".join(instruments)
    save(slug, s)
    return row


def again(slug: str, job_id: str) -> dict:
    """A failed job of any kind run again with its own payload (the import of the Lied's .mxl, fixed after yoga's try)."""
    old = db().table("jobs").select("kind,score_id,payload,created_by").eq("id", job_id).single().execute().data
    row = _insert_running({"kind": old["kind"], "score_id": old["score_id"], "created_by": old["created_by"], "payload": old["payload"]})
    s = state(slug)
    s["jobs"][row["id"]] = {"kind": row["kind"], "created_at": row["created_at"], "local": True, "again": job_id}
    save(slug, s)
    return row


def main() -> None:
    cmd, slug, *rest = sys.argv[1:]
    load_handlers()
    if cmd == "answer":
        row = answer(slug, rest[0], json.loads(rest[1]))
        label = "local:" + state(slug).get("cut_label", row["kind"])
    elif cmd == "cut":
        pages = None
        if "--pages" in rest:
            k = rest.index("--pages")
            a, _, b = rest[k + 1].partition("-")
            pages = list(range(int(a), int(b or a) + 1))
            rest = rest[:k] + rest[k + 2:]
        row = cut(slug, rest, pages)
        label = "local:" + state(slug)["cut_label"]
    elif cmd == "again":
        row = again(slug, rest[0])
        label = "local:" + row["kind"]
    elif cmd == "convert":
        pages = [int(p) for p in rest[0].split(",")] if rest else None
        row = convert(slug, pages)
        label = "local:convert"
    else:
        sys.exit(__doc__)
    t0 = time.time()
    print("running here", row["id"], row["kind"])
    asyncio.run(run_one(db().table("jobs").select("*").eq("id", row["id"]).single().execute().data))
    cmd_waitjob(slug, row["id"], label=label, t0=t0, timeout=time.time() - t0 + 60)


if __name__ == "__main__":
    main()
