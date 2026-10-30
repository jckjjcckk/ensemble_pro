"""Voice notes (013): the admin's push-to-talk take in, proposed marks out.

The browser sends the take as the raw request body (16 kHz mono 16-bit WAV, at most two minutes). The route stores
it, records a `transcribe_voice` job and runs it in this process right after answering, so the proposals arrive in
about six seconds instead of waiting for the worker's next poll; the row is `running` with `locked_at` set, so the
worker's stale sweep requeues it if this process dies first. The browser watches the job row and the proposed
`annotations` rows."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from ..auth import User
from ..db import db
from ..librarian import load_handlers
from ..librarian.transcribe_voice import MAX_SECONDS
from ..spend import BudgetedUser
from ..worker import run_one

router = APIRouter()

MAX_BYTES = 24000 * 2 * MAX_SECONDS + 1024   # two and a half minutes at the highest rate Voice Transcribe takes


def assert_can_lead(user: User, score_id: str, group: str | None) -> dict:
    """The mark layer's leader, as `can_lead_layer` decides it: a group's admin on its own or a shared book, or the
    owner of a personal book."""
    s = db().table("scores").select("id,owner_user_id,ensemble_id").eq("id", score_id).limit(1).execute().data
    if not s:
        raise HTTPException(404, "No such score")
    s = s[0]

    def admin(g: str) -> bool:
        m = db().table("members").select("role").eq("ensemble_id", g).eq("user_id", user.id).limit(1).execute().data
        return bool(m) and m[0]["role"] == "admin"

    if s["ensemble_id"]:
        ok = group in (None, s["ensemble_id"]) and admin(s["ensemble_id"])
    elif group is None:
        ok = s["owner_user_id"] == user.id
    else:
        shared = db().table("score_shares").select("score_id").eq("score_id", score_id).eq("ensemble_id", group).limit(1).execute().data
        ok = bool(shared) and admin(group)
    if not ok:
        raise HTTPException(403, "Only the group's admin can speak notes onto this book")
    return s


@router.post("/scores/{score_id}/voice", status_code=202)
async def voice_note(score_id: str, request: Request, background: BackgroundTasks, user: BudgetedUser,
                     ensemble_id: str | None = None, session_id: str | None = None) -> dict:
    """Store the take and start reading it. Returns `{job_id, utterance_id}`; the job's `result` and the proposed
    rows follow (see `librarian/transcribe_voice.py`)."""
    group = ensemble_id or None
    assert_can_lead(user, score_id, group)
    audio = await request.body()
    if len(audio) < 44 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        raise HTTPException(400, "Send the recording as a WAV file")
    if len(audio) > MAX_BYTES:
        raise HTTPException(400, "That recording is longer than two minutes")
    utterance = str(uuid.uuid4())
    path = f"{score_id}/voice/{utterance}.wav"
    db().storage.from_("scores").upload(path, audio, {"content-type": "audio/wav", "upsert": "true"})
    now = datetime.now(timezone.utc).isoformat()
    job = db().table("jobs").insert({
        "kind": "transcribe_voice", "status": "running", "created_by": user.id, "locked_at": now, "started_at": now,
        "attempts": 1, "payload": {"score_id": score_id, "ensemble_id": group, "session_id": session_id or None,
                                   "utterance_id": utterance, "audio_path": path},
    }).execute().data[0]
    load_handlers()
    background.add_task(run_one, job)
    return {"job_id": job["id"], "utterance_id": utterance}
