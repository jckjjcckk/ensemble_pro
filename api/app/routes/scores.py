"""Scores: the API's part of intake. The browser creates the score row and uploads files through RLS;
these routes record the source and queue the job that reads it."""
import asyncio
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..auth import CurrentUser, User
from ..db import db
from ..librarian import HANDLERS, load_handlers
from ..librarian.signature import canonical_key, canonical_meter
from ..spend import BudgetedUser
from ..worker import run_one
from .live_jobs import insert_job, parts_key, refuse_if_live

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


class DetailsBody(BaseModel):
    """Details (F_Details): every field optional; only the ones sent change. Empty strings clear a text field."""
    title: str | None = None
    composer: str | None = None
    key_sig: str | None = None          # any spelling canonical_key reads: "G minor", "B-flat major", "E- major"
    meter: str | None = None            # "3/4", "C", "cut"
    tempo_bpm: int | None = None
    tempo_text: str | None = None
    cover_clef: Literal["treble", "bass", "alto", "grand"] | None = None
    first_bar: int | None = None        # the first bar on first_bar_page carries this number
    first_bar_page: int | None = None


@router.patch("/scores/{score_id}")
def update_details(score_id: str, body: DetailsBody, user: CurrentUser) -> dict:
    """Save Details. Owner or admin only. Key and meter are canonicalised (400 for a name that is not a key or a
    meter) and confirming either sets `signature_confirmed`, so a re-read never overwrites the owner. Bar numbering
    renumbers the book's `measures` (marks keep their bar: they point at measures.id) so that the first bar placed on
    `first_bar_page` in the current interpretation carries `first_bar`; a book with a Digital copy keeps the numbers
    of its notation (409), because its engraved pages are joined to them. Returns the score row and the shift."""
    assert_can_edit(user, score_id)
    sent = body.model_dump(exclude_unset=True)
    facts: dict = {}
    for f in ("title", "composer", "tempo_text"):
        if f in sent:
            v = (sent[f] or "").strip()
            if f == "title" and not v:
                raise HTTPException(400, "A book needs a title")
            facts[f] = v or None
    if "key_sig" in sent:
        k = canonical_key(sent["key_sig"]) if sent["key_sig"] else None
        if sent["key_sig"] and not k:
            raise HTTPException(400, f"Not a key: {sent['key_sig']}")
        facts["key_sig"] = k
    if "meter" in sent:
        m = canonical_meter(sent["meter"]) if sent["meter"] else None
        if sent["meter"] and not m:
            raise HTTPException(400, f"Not a time signature: {sent['meter']}")
        facts["meter"] = m
    if "key_sig" in facts or "meter" in facts:
        facts["signature_confirmed"] = True
    if "tempo_bpm" in sent:
        bpm = sent["tempo_bpm"]
        if bpm is not None and not 10 <= bpm <= 400:
            raise HTTPException(400, "Speed is between 10 and 400 beats a minute")
        facts["tempo_bpm"] = bpm
    if "cover_clef" in sent:
        facts["cover_clef"] = sent["cover_clef"]
    shift = 0
    if "first_bar" in sent or "first_bar_page" in sent:
        first, page = sent.get("first_bar"), sent.get("first_bar_page") or 1
        if first is None or not -10 <= first <= 10000 or page < 1:
            raise HTTPException(400, "Bar numbering needs a first bar number and a page")
        shift = renumber_shift(score_id, first, page)
        facts.update({"first_bar": first, "first_bar_page": page})
    if shift:
        db().rpc("shift_measures", {"s": score_id, "delta": shift}).execute()
    if facts:
        db().table("scores").update(facts).eq("id", score_id).execute()
    row = db().table("scores").select("*").eq("id", score_id).single().execute().data
    return {"score": row, "shifted_by": shift}


def renumber_shift(score_id: str, first: int, page: int) -> int:
    """How far to shift the book's bar numbers so the first bar placed on `page` is bar `first`."""
    kinds = {s["kind"] for s in db().table("sources").select("kind").eq("score_id", score_id).execute().data or []}
    if kinds & {"musicxml", "engraving"}:
        raise HTTPException(409, "This book has a Digital copy; its bar numbers come from the notation")
    score = db().table("scores").select("current_interpretation_id").eq("id", score_id).single().execute().data or {}
    interp = score.get("current_interpretation_id")
    if not interp:
        raise HTTPException(409, "The book has not been read yet")
    rows = db().table("measure_placements").select("page,system,box,measures(number)").eq("interpretation_id", interp).eq("page", page).execute().data or []
    numbers = [r["measures"]["number"] for r in rows if r.get("measures") and r.get("system") is not None]
    if not numbers:
        raise HTTPException(400, f"No bars were found on page {page}")
    return first - min(numbers)


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
        raise HTTPException(409, {"message": "This book is already being read.", "job_id": busy[0]["id"], "kind": busy[0]["kind"], "status": busy[0]["status"]})
    refuse_if_live(score_id, "process_pages")   # a reading parked on a question is still this book's reading
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
    the worker's stale sweep queues it again.

    One live split per set of parts (CK 2026-10-31): while a `part_cut` taking the same parts is queued, running or
    parked on a question, 409 `{message, job_id, kind, status}`; `payload.parts_key` is what the index compares."""
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
    key = parts_key(instruments)
    refuse_if_live(score_id, "part_cut", key)
    payload: dict = {"score_id": score_id, "instruments": instruments, "parts_key": key}
    if pages:
        payload["pages"] = pages
    return insert_job({"kind": "part_cut", "status": "queued", "score_id": score_id, "created_by": user.id, "payload": payload}, key)


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
