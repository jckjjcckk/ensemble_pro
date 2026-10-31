"""One live job of a kind per book (007, CK 2026-10-31: never submit a duplicate job). A Split by instrument
(`part_cut`, per set of parts), a Convert to Digital (`omr_convert`) and the reading of a PDF (`process_pages`) are
live while queued, running, or parked on a question nobody has answered yet. A request for a second one is refused
with 409 naming the live job, so the iPad shows that job instead of starting another. The partial unique index
`jobs_one_live` (migration 20261031120000) holds the same rule for queued and running rows when two requests race."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException


def db():
    """The scores routes' client, looked up at call time, so whatever stands in for it there (a test's fake) is the
    one this module queries too."""
    from . import scores
    return scores.db()

LIVE_KINDS = ("part_cut", "omr_convert", "process_pages")
WORDS = {"part_cut": "This split is already under way", "omr_convert": "This book is already being converted to Digital",
         "process_pages": "This book is already being read"}


def parts_key(instruments: list[str]) -> str:
    """The set of parts a split takes, as the index compares it: trimmed, case-folded, sorted, joined by "|"."""
    return "|".join(sorted({" ".join(str(i).split()).casefold() for i in instruments if str(i).strip()}))


def _score_of(row: dict) -> str | None:
    return row.get("score_id") or (row.get("payload") or {}).get("score_id")


def _question(row: dict) -> str | None:
    return row.get("question") or (row.get("result") or {}).get("question")


def live_job(score_id: str, kind: str, parts: str | None = None) -> dict | None:
    """The live job of `kind` on the book (for `part_cut`, the one taking the same parts), else None. Parked: done with
    a question and no later job resuming from it."""
    rows = db().table("jobs").select("id,kind,status,score_id,payload,created_at,question:result->>question").eq("kind", kind).execute().data or []
    rows = [r for r in rows if _score_of(r) == score_id]
    resumed = {(r.get("payload") or {}).get("resume_from") for r in rows}
    live = []
    for r in rows:
        if parts is not None and parts_key(_instruments(r.get("payload") or {})) != parts:
            continue
        if r.get("status") in ("queued", "running"):
            live.append({**r, "state": r["status"]})
        elif r.get("status") == "done" and _question(r) and r["id"] not in resumed:
            live.append({**r, "state": "needs_review"})
    return max(live, key=lambda r: r.get("created_at") or "") if live else None


def _instruments(payload: dict) -> list[str]:
    raw = payload.get("instruments")
    if raw is None:
        raw = [payload["instrument"]] if payload.get("instrument") else []
    return [str(x) for x in (raw if isinstance(raw, list) else [raw])]


def refusal(job: dict) -> HTTPException:
    """409 with the live job: `{message, job_id, kind, status}` (status queued | running | needs_review)."""
    return HTTPException(409, {"message": f"{WORDS.get(job['kind'], 'This job is already under way')}.", "job_id": job["id"],
                               "kind": job["kind"], "status": job.get("state") or job.get("status")})


def refuse_if_live(score_id: str, kind: str, parts: str | None = None) -> None:
    if (j := live_job(score_id, kind, parts)) is not None:
        raise refusal(j)


def is_unique_violation(e: Exception) -> bool:
    """The index refused the insert (PostgREST relays Postgres 23505)."""
    code = getattr(e, "code", None) or (e.args[0].get("code") if e.args and isinstance(e.args[0], dict) else None)
    return code == "23505" or "23505" in str(e) or "jobs_one_live" in str(e)


def insert_job(row: dict[str, Any], parts: str | None = None) -> dict:
    """Insert a job of a guarded kind; a race lost to the index comes back as the same 409 as the check before it."""
    score_id = row.get("score_id") or (row.get("payload") or {}).get("score_id")
    try:
        return db().table("jobs").insert(row).execute().data[0]
    except Exception as e:  # noqa: BLE001
        if row.get("kind") in LIVE_KINDS and is_unique_violation(e):
            j = live_job(score_id, row["kind"], parts)
            if j is not None:
                raise refusal(j) from e
            raise HTTPException(409, {"message": f"{WORDS.get(row['kind'], 'This job is already under way')}.", "kind": row["kind"]}) from e
        raise
