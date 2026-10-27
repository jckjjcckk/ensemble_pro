"""Scores: the API's part of intake. The browser creates the score row and uploads files through RLS;
these routes record the source and queue the job that reads it."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..auth import User
from ..db import db
from ..spend import BudgetedUser

router = APIRouter()


def assert_can_edit(user: User, score_id: str) -> dict:
    s = db().table("scores").select("id,owner_user_id,ensemble_id").eq("id", score_id).limit(1).execute().data
    if not s:
        raise HTTPException(404, "No such score")
    s = s[0]
    if s["owner_user_id"] == user.id:
        return s
    if s["ensemble_id"]:
        m = db().table("members").select("role").eq("ensemble_id", s["ensemble_id"]).eq("user_id", user.id).limit(1).execute().data
        if m and m[0]["role"] == "admin":
            return s
    raise HTTPException(403, "Only the owner or an admin can change this score")


class ImportBody(BaseModel):
    path: str                       # bucket path the browser uploaded to: scores/{score_id}/source.musicxml


@router.post("/scores/{score_id}/import")
def import_score(score_id: str, body: ImportBody, user: BudgetedUser) -> dict:
    """Queue the MusicXML import (Path A). Returns the source and job ids; the library watches the job row."""
    assert_can_edit(user, score_id)
    if not body.path.startswith(f"scores/{score_id}/"):
        raise HTTPException(400, "Path must be inside the score's folder")
    src = db().table("sources").insert({"score_id": score_id, "kind": "musicxml", "storage_paths": [body.path], "created_by": user.id}).execute().data[0]
    job = db().table("jobs").insert({"kind": "import_musicxml", "score_id": score_id, "created_by": user.id, "payload": {"score_id": score_id, "source_id": src["id"]}}).execute().data[0]
    db().table("scores").update({"status": "processing", "progress": 0}).eq("id", score_id).execute()
    return {"source_id": src["id"], "job_id": job["id"]}
