"""Scores: the API's part of intake. The browser creates the score row and uploads files through RLS;
these routes record the source and queue the job that reads it."""
import asyncio
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..auth import User
from ..db import db
from ..librarian import HANDLERS, load_handlers
from ..spend import BudgetedUser
from ..worker import run_one

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


class PartsBody(BaseModel):
    instruments: list[str]          # the parts to export together, e.g. ["Soprano", "Alto"]
    pages: list[int] | None = None  # 1-based into the source's page order; every page when omitted


class ImportBody(BaseModel):
    path: str                       # object key inside the scores bucket: {score_id}/source.musicxml or {score_id}/source.pdf
    filename: str | None = None     # the file's own name, for the title when the MusicXML has none
    kind: Literal["musicxml", "pdf"] | None = None   # from the key's extension when omitted (.pdf is a PDF)


READING_KINDS = ("import_pdf", "process_pages")


@router.post("/scores/{score_id}/import")
def import_score(score_id: str, body: ImportBody, user: BudgetedUser) -> dict:
    """Queue the import. MusicXML (Path A): records the source, queues `import_musicxml`. PDF (002): the browser has
    uploaded `{score_id}/source.pdf` and inserted the `pdf` source row (the route records one itself when it finds
    none); queues `import_pdf`, which renders every page and queues `process_pages` with no ordering step. Either
    way the score goes `processing` now and `ready` or `failed` later. Returns `{source_id, job_id, kind}`."""
    assert_can_edit(user, score_id)
    if not body.path.startswith(f"{score_id}/"):
        raise HTTPException(400, "Path must be inside the score's folder")
    kind = body.kind or ("pdf" if body.path.lower().endswith(".pdf") else "musicxml")
    if kind == "pdf":
        return import_pdf(score_id, body, user)
    src = db().table("sources").insert({"score_id": score_id, "kind": "musicxml", "storage_paths": [body.path], "meta": {"filename": body.filename}, "created_by": user.id}).execute().data[0]
    job = db().table("jobs").insert({"kind": "import_musicxml", "score_id": score_id, "created_by": user.id, "payload": {"score_id": score_id, "source_id": src["id"]}}).execute().data[0]
    db().table("scores").update({"status": "processing", "progress": 0}).eq("id", score_id).execute()
    return {"source_id": src["id"], "job_id": job["id"], "kind": "import_musicxml"}


def import_pdf(score_id: str, body: ImportBody, user: User) -> dict:
    busy = [j for j in db().table("jobs").select("id,kind,status").eq("score_id", score_id).execute().data or []
            if j.get("kind") in READING_KINDS and j.get("status") in ("queued", "running")]
    if busy:
        raise HTTPException(409, "This score is already being read")
    sources = [s for s in db().table("sources").select("id,kind,storage_paths,created_at").eq("score_id", score_id).execute().data or []
               if s.get("kind") == "pdf" and body.path in (s.get("storage_paths") or [])]
    if sources:
        src = max(sources, key=lambda s: s.get("created_at") or "")
    else:
        src = db().table("sources").insert({"score_id": score_id, "kind": "pdf", "storage_paths": [body.path],
                                            "meta": {"filename": body.filename}, "created_by": user.id}).execute().data[0]
    job = db().table("jobs").insert({"kind": "import_pdf", "status": "queued", "score_id": score_id, "created_by": user.id,
                                     "payload": {"score_id": score_id, "source_id": src["id"]}}).execute().data[0]
    db().table("scores").update({"status": "processing", "progress": 0, "failure_reason": None}).eq("id", score_id).execute()
    return {"source_id": src["id"], "job_id": job["id"], "kind": "import_pdf"}


@router.post("/scores/{score_id}/parts")
def cut_parts(score_id: str, body: PartsBody, user: BudgetedUser) -> dict:
    """Split by instrument (feature 008), one action for both kinds of book. Owner or admin only. Returns the job row.

    A PDF book (a `pdf` or `images` source): queues a `part_cut` job, the chosen instruments' staves out of the scanned
    pages, one strip per system; the browser watches the row (a parked question lands in result.question).
    A Digital book (an imported `musicxml` source): the names must be the score's `parts.name` rows (400 naming the
    available parts otherwise); the `part_split` job runs here and now, no model, and the row comes back `done` with
    `result = {source_id, instruments, storage_path}`. Should the process die mid-split, the row is `running` and
    the worker's stale sweep queues it again."""
    assert_can_edit(user, score_id)
    instruments: list[str] = []
    for name in body.instruments:
        name = (name or "").strip()
        if name and name not in instruments:
            instruments.append(name)
    if not instruments:
        raise HTTPException(400, "Name at least one instrument")
    pages = sorted({int(n) for n in (body.pages or []) if int(n) >= 1}) or None
    sources = db().table("sources").select("id,kind,meta").eq("score_id", score_id).execute().data or []
    if not any(s["kind"] in ("pdf", "images") for s in sources):
        xml = [s for s in sources if s["kind"] == "musicxml" and not (s.get("meta") or {}).get("split_from")]
        if not xml:
            raise HTTPException(400, "This score has no scanned pages or MusicXML to split")
        return split_now(score_id, instruments, user)
    payload: dict = {"score_id": score_id, "instruments": instruments}
    if pages:
        payload["pages"] = pages
    return db().table("jobs").insert({"kind": "part_cut", "score_id": score_id, "created_by": user.id, "payload": payload}).execute().data[0]


def split_now(score_id: str, instruments: list[str], user: User) -> dict:
    """The Digital book's split: check the names against the score's parts, record the job as running, run the
    `part_split` handler in this request (about a second for a quartet movement) and return the finished row."""
    names = [r["name"] for r in db().table("parts").select("name,position").eq("score_id", score_id).order("position").execute().data or []]
    unknown = [i for i in instruments if i not in names]
    if unknown:
        raise HTTPException(400, f"Not in this score: {', '.join(unknown)}. The parts are {', '.join(names) or 'not read yet'}.")
    now = datetime.now(timezone.utc).isoformat()
    row = db().table("jobs").insert({"kind": "part_split", "status": "running", "attempts": 1, "score_id": score_id, "created_by": user.id,
                                     "payload": {"score_id": score_id, "instruments": instruments}, "locked_at": now, "started_at": now}).execute().data[0]
    if "part_split" not in HANDLERS:
        load_handlers()
    asyncio.run(run_one(row))   # a sync route runs in a worker thread: no event loop here, so this is safe
    return db().table("jobs").select("*").eq("id", row["id"]).single().execute().data
