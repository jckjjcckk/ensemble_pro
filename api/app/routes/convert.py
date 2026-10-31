"""Convert to Digital (feature 005): queue the transcription of a PDF book into a second, digital version of it.
One action, a busy state, a result row, like Split by instrument: the browser watches the returned job row."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db import db
from ..librarian import omr_convert  # noqa: F401  (registers the `omr_convert` handler with the worker)
from ..spend import BudgetedUser
from .live_jobs import insert_job, refuse_if_live
from .scores import assert_can_edit

router = APIRouter()


class ConvertBody(BaseModel):
    pages: list[int] | None = None   # 1-based PDF pages; the whole PDF when omitted


@router.post("/scores/{score_id}/convert")
def convert(score_id: str, user: BudgetedUser, body: ConvertBody | None = None) -> dict:
    """Owner or admin only (403), the score must exist (404), the caller must have budget (402). 400 when the book has
    no `pdf` source; 409 `{message, job_id, kind, status}` while a transcription of it is queued, running or parked.
    Returns the `omr_convert` job row.

    The job keeps the score in `payload.score_id` and leaves `jobs.score_id` empty, so a failed or running conversion
    never moves the PDF book's own status or meter (the browser finds it by kind and `payload->>score_id`).
    `max_attempts` is 1: a retry would pay for the Spark passes again."""
    assert_can_edit(user, score_id)
    sources = db().table("sources").select("id,kind,created_at").eq("score_id", score_id).eq("kind", "pdf").order("created_at").execute().data or []
    pdf = [s for s in sources if s.get("kind") == "pdf"]
    if not pdf:
        raise HTTPException(400, "This book has no PDF to convert")
    refuse_if_live(score_id, "omr_convert")    # one conversion at a time (409 naming it, CK 2026-10-31)
    payload: dict = {"score_id": score_id, "source_id": pdf[0]["id"]}
    pages = sorted({int(n) for n in (body.pages if body else None) or [] if int(n) >= 1})
    if pages:
        payload["pages"] = pages
    return insert_job({"kind": "omr_convert", "status": "queued", "score_id": None, "created_by": user.id, "max_attempts": 1, "payload": payload})
