"""Convert to Digital (feature 005): queue the transcription of a PDF book into a second, digital version of it.
One action, a busy state, a result row, like Split by instrument: the browser watches the returned job row."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db import db
from ..librarian import omr_convert  # noqa: F401  (registers the `omr_convert` handler with the worker)
from ..spend import BudgetedUser
from .scores import assert_can_edit

router = APIRouter()
BUSY = ("queued", "running")


class ConvertBody(BaseModel):
    pages: list[int] | None = None   # 1-based PDF pages; the whole PDF when omitted


@router.post("/scores/{score_id}/convert")
def convert(score_id: str, user: BudgetedUser, body: ConvertBody | None = None) -> dict:
    """Owner or admin only (403), the score must exist (404), the caller must have budget (402). 400 when the book has
    no `pdf` source or a transcription of it is already queued or running. Returns the `omr_convert` job row.

    The job keeps the score in `payload.score_id` and leaves `jobs.score_id` empty, so a failed or running conversion
    never moves the PDF book's own status or meter (the browser finds it by kind and `payload->>score_id`).
    `max_attempts` is 1: a retry would pay for the Spark passes again."""
    assert_can_edit(user, score_id)
    sources = db().table("sources").select("id,kind,created_at").eq("score_id", score_id).eq("kind", "pdf").order("created_at").execute().data or []
    pdf = [s for s in sources if s.get("kind") == "pdf"]
    if not pdf:
        raise HTTPException(400, "This book has no PDF to convert")
    jobs = db().table("jobs").select("id,status").eq("kind", "omr_convert").eq("payload->>score_id", score_id).execute().data or []
    if any(j.get("status") in BUSY for j in jobs):
        raise HTTPException(400, "A transcription of this book is already in progress")
    payload: dict = {"score_id": score_id, "source_id": pdf[0]["id"]}
    pages = sorted({int(n) for n in (body.pages if body else None) or [] if int(n) >= 1})
    if pages:
        payload["pages"] = pages
    return db().table("jobs").insert({"kind": "omr_convert", "status": "queued", "score_id": None, "created_by": user.id, "max_attempts": 1,
                                      "payload": payload}).execute().data[0]
