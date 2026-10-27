"""Job handlers: the librarian's work. One function per job kind, registered with @handler.

The worker (app/worker.py) claims jobs and calls these. See docs/librarian-contract.md for what a handler
may touch and what it must write. Handlers for the intelligence thread live beside this file.
"""
from __future__ import annotations

import base64
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..db import db as _db
from ..llm import Completion, complete as _complete
from ..auth import User, load_user
from ..spend import Charge, charge as _charge


@dataclass(frozen=True)
class Job:
    id: str
    kind: str
    payload: dict[str, Any]
    score_id: str | None
    created_by: str | None
    attempts: int
    max_attempts: int

    @staticmethod
    def from_row(r: dict[str, Any]) -> "Job":
        return Job(r["id"], r["kind"], r.get("payload") or {}, r.get("score_id"), r.get("created_by"), r.get("attempts", 1), r.get("max_attempts", 3))


@dataclass
class JobContext:
    job: Job
    result: dict[str, Any] = field(default_factory=dict)

    @property
    def db(self):
        return _db()

    @property
    def user(self) -> User | None:
        return load_user(self.job.created_by) if self.job.created_by else None

    async def progress(self, fraction: float, note: str | None = None) -> None:
        if note:
            self.result["note"] = note
        self.db.table("jobs").update({"progress": max(0.0, min(1.0, fraction)), "result": self.result}).eq("id", self.job.id).execute()
        if self.job.score_id:
            self.db.table("scores").update({"progress": max(0.0, min(1.0, fraction))}).eq("id", self.job.score_id).execute()

    def charge(self, c: Charge) -> dict:
        u = self.user
        return _charge(u, c, job_id=self.job.id) if u else {}

    async def complete(self, user_text: str, **kw) -> Completion:
        c = await _complete(user_text, **kw)
        self.charge(c.charge)
        return c

    def storage_download(self, path: str) -> bytes:
        return self.db.storage.from_("scores").download(path)

    def storage_upload(self, path: str, data: bytes, content_type: str) -> None:
        self.db.storage.from_("scores").upload(path, data, {"content-type": content_type, "upsert": "true"})

    def needs_review(self, question: str, payload: dict[str, Any] | None = None, interpretation_id: str | None = None) -> dict:
        """Park the run on a question for the admin. The job finishes; the answer queues a follow-up job."""
        self.result["question"] = question
        self.result["question_payload"] = payload or {}
        if interpretation_id:
            self.db.table("interpretations").update({"status": "needs_review"}).eq("id", interpretation_id).execute()
        return self.result

    @staticmethod
    def png_b64(data: bytes) -> str:
        return base64.b64encode(data).decode()

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat()


Handler = Callable[[Job, JobContext], Awaitable[dict[str, Any] | None]]
HANDLERS: dict[str, Handler] = {}


def handler(kind: str) -> Callable[[Handler], Handler]:
    def wrap(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn
    return wrap


def load_handlers() -> None:
    """Import every handler module so it registers. Add new modules here."""
    from . import import_musicxml  # noqa: F401
    try:
        from . import process_pages, transcribe_voice, brief  # noqa: F401  (intelligence thread)
    except ImportError:
        pass
