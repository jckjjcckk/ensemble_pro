"""Jobs: answering a parked question (feature 011). A handler that cannot decide parks its job `done` with
`result.question` and a typed `result.question_payload`; the admin's answer queues a follow-up job of the same
kind with the same payload plus `answer` and `resume_from`, which the handler resumes from the saved state."""
from typing import Any

from fastapi import APIRouter, HTTPException

from ..db import db
from ..spend import BudgetedUser
from .scores import assert_can_edit

router = APIRouter()


@router.post("/jobs/{job_id}/answer")
def answer_job(job_id: str, body: dict[str, Any], user: BudgetedUser) -> dict:
    """Answer a parked job. The body is the answer in the shape `result.question_payload.answer_format` gives
    (`{"staves": [11, 12]}`, `{"blocks": [[11], [13]]}`, `{"staves": "absent"}`). Returns the new job row."""
    rows = db().table("jobs").select("id,kind,status,score_id,payload,result").eq("id", job_id).limit(1).execute().data
    if not rows:
        raise HTTPException(404, "No such job")
    job = rows[0]
    if not job.get("score_id"):
        raise HTTPException(400, "This job has no score")
    assert_can_edit(user, job["score_id"])
    result = job.get("result") or {}
    if job["status"] != "done" or not result.get("question"):
        raise HTTPException(409, "This job is not waiting for an answer")
    if not isinstance(body, dict) or not body or not ("staves" in body or "blocks" in body or "answer" in body):
        raise HTTPException(400, "The answer must be an object with staves, blocks or answer")
    already = db().table("jobs").select("id").eq("payload->>resume_from", job_id).limit(1).execute().data
    if already:
        raise HTTPException(409, "This question was already answered")
    payload = {k: v for k, v in (job.get("payload") or {}).items() if k not in ("answer", "resume_from")}
    q = result.get("question_payload") or {}
    if q.get("interpretation_id") and not payload.get("interpretation_id"):
        payload["interpretation_id"] = q["interpretation_id"]
    payload.update({"answer": body["answer"] if set(body) == {"answer"} else body, "resume_from": job_id})
    return db().table("jobs").insert({"kind": job["kind"], "score_id": job["score_id"], "created_by": user.id, "payload": payload}).execute().data[0]
