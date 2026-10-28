"""The durable job loop. Runs inside the API process; the database is the queue.

Polls `claim_job()` (SKIP LOCKED, so a second API process is safe), runs the handler registered for the
job's kind, and writes the outcome. A handler that raises is retried with backoff until max_attempts, then
the job fails with the error text and the score, if any, is marked failed. Survives a restart: a job that
was `running` when the process died is re-queued after a stale timeout.
"""
from __future__ import annotations

import asyncio
import logging
import traceback
from datetime import datetime, timedelta, timezone

from .db import db
from .librarian import HANDLERS, Job, JobContext, ScoreFailure, load_handlers

log = logging.getLogger("folio.worker")
POLL_S = 2.0
STALE_MIN = 15

# What the musician reads on the cover when a job fails for a reason that is not theirs to fix (the technical
# text stays in jobs.error). A ScoreFailure's own sentence is used instead when the handler raised one.
FAILURE_WORDS = {
    "import_pdf": "Folio could not open this PDF. Try the import again.",
    "process_pages": "Folio could not finish reading the pages. Try the import again.",
    "import_musicxml": "Folio could not read this MusicXML file. Export it again and import the new copy.",
    "engrave": "Folio could not draw the pages of this book. The notation still opens on the device.",
}
GENERIC_FAILURE = "Something went wrong while Folio was working on this score. Try again."


def failure_reason(kind: str, exc: Exception) -> str:
    if isinstance(exc, ScoreFailure):
        return str(exc)[:300]
    return FAILURE_WORDS.get(kind, GENERIC_FAILURE)


def context_for(job_id: str) -> JobContext:
    row = db().table("jobs").select("*").eq("id", job_id).single().execute().data
    return JobContext(Job.from_row(row))


async def run_one(row: dict) -> None:
    job = Job.from_row(row)
    ctx = JobContext(job)
    fn = HANDLERS.get(job.kind)
    try:
        if fn is None:
            raise RuntimeError(f"no handler for job kind {job.kind!r}")
        out = await fn(job, ctx)
        result = {**ctx.result, **(out or {})}
        db().table("jobs").update({"status": "done", "progress": 1.0, "result": result, "finished_at": ctx.now()}).eq("id", job.id).execute()
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
        log.warning("job %s (%s) attempt %d failed: %s\n%s", job.id, job.kind, job.attempts, err, traceback.format_exc())
        if job.attempts < job.max_attempts and fn is not None and not isinstance(e, ScoreFailure):
            delay = timedelta(seconds=10 * 2 ** (job.attempts - 1))
            db().table("jobs").update({"status": "queued", "error": err, "run_after": (datetime.now(timezone.utc) + delay).isoformat()}).eq("id", job.id).execute()
        else:
            db().table("jobs").update({"status": "failed", "error": err, "finished_at": ctx.now()}).eq("id", job.id).execute()
            if job.score_id:
                db().table("scores").update({"status": "failed", "failure_reason": failure_reason(job.kind, e)}).eq("id", job.score_id).execute()


def requeue_stale() -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=STALE_MIN)).isoformat()
    db().table("jobs").update({"status": "queued", "error": "worker died; requeued"}).eq("status", "running").lt("locked_at", cutoff).execute()


async def loop(stop: asyncio.Event) -> None:
    load_handlers()
    log.info("worker up, handlers: %s", sorted(HANDLERS))
    try:
        requeue_stale()
    except Exception as e:  # noqa: BLE001
        log.warning("requeue_stale: %s", e)
    while not stop.is_set():
        try:
            row = db().rpc("claim_job", {}).execute().data
            if row and row.get("id"):
                await run_one(row)
                continue
        except Exception as e:  # noqa: BLE001
            log.warning("worker poll: %s", e)
        try:
            await asyncio.wait_for(stop.wait(), POLL_S)
        except asyncio.TimeoutError:
            pass
