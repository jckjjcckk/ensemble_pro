"""PDF import that reads itself (feature 002): the route, the `import_pdf` handler, the hand-off to `process_pages`,
and the failures a musician reads. Fake database, PDFs made with PyMuPDF in the test, scripted model; no network."""
from __future__ import annotations

import io
from decimal import Decimal

import pymupdf
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import worker
from app.agent.fake import fake_client
from app.auth import User
from app.librarian import Job, ScoreFailure
from app.librarian import import_pdf as import_pdf_mod
from app.librarian.import_pdf import import_pdf
from app.librarian.process_pages import process_pages
from app.main import app
from app.routes import scores as scores_routes
from app.spend import require_budget
from tests.test_part_cut import HEADER, Ctx, FakeDB, synth_page
from tests.test_signature import LABELS, PagesCtx, sig

SCORE = "11111111-1111-1111-1111-111111111111"
KEY = f"{SCORE}/source.pdf"
OWNER = User("u1", "owner@muse.test", "Owner", Decimal("5"), Decimal("0"))


def make_pdf(pages: int = 3, size: tuple[float, float] = (612, 792), png: bytes | None = None, password: str | None = None) -> bytes:
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page(width=size[0], height=size[1])
        if png:
            page.insert_image(page.rect, stream=png)
        else:
            page.draw_line((50, 100), (size[0] - 50, 100))
    kw = {"encryption": pymupdf.PDF_ENCRYPT_AES_256, "user_pw": password, "owner_pw": password} if password else {}
    return doc.tobytes(**kw)


def pdf_world(data: bytes, n_source_pages: int | None = None) -> tuple[Job, Ctx, FakeDB]:
    db = FakeDB()
    db.rows["scores"] = [{"id": SCORE, "title": "Synth", "composer": None, "work": None, "status": "processing"}]
    db.rows["sources"] = [{"id": "src1", "score_id": SCORE, "kind": "pdf", "created_by": "u1", "storage_paths": [KEY], "page_order": None,
                           "page_count": n_source_pages, "meta": {"filename": "synth.pdf"}}]
    job = Job("job1", "import_pdf", {"score_id": SCORE, "source_id": "src1"}, SCORE, "u1", 1, 3)
    db.rows["jobs"] = [{"id": "job1", "kind": "import_pdf", "status": "running", "result": {}, "payload": job.payload}]
    return job, Ctx(job, db, {KEY: data}), db


# ---------------------------------------------------------------- the handler

async def test_import_pdf_renders_every_page_and_queues_the_reading():
    job, ctx, db = pdf_world(make_pdf(3))
    out = await import_pdf(job, ctx)
    assert sorted(ctx.uploads) == [f"{SCORE}/pages/{i}.png" for i in (1, 2, 3)]
    im = Image.open(io.BytesIO(ctx.uploads[f"{SCORE}/pages/1.png"]))
    assert im.mode == "L" and im.size == (1275, 1650)                       # letter at 150 dpi, greyscale
    src = db.rows["sources"][0]
    assert src["page_order"] == [1, 2, 3] and src["page_count"] == 3
    assert src["meta"]["filename"] == "synth.pdf" and src["meta"]["render"]["dpi"] == [150.0] and src["meta"]["render"]["px"][0] == [1275, 1650]
    follow = [j for j in db.rows["jobs"] if j.get("kind") == "process_pages"]
    assert len(follow) == 1 and follow[0]["payload"] == {"score_id": SCORE, "source_id": "src1"} and follow[0]["created_by"] == "u1"
    assert out["pages"] == 3 and out["process_job_id"] == follow[0]["id"]
    # a retried import (same source) does not queue a second reading while the first is waiting
    db.rows["jobs"][-1]["status"] = "queued"
    out2 = await import_pdf(job, ctx)
    assert out2["process_job_id"] == follow[0]["id"] and len([j for j in db.rows["jobs"] if j.get("kind") == "process_pages"]) == 1


async def test_small_and_huge_pages_are_scaled_into_the_working_band():
    job, ctx, _ = pdf_world(make_pdf(1, size=(298, 420)))                   # A6: 621 px at 150 dpi, too small for the geometry
    await import_pdf(job, ctx)
    assert Image.open(io.BytesIO(ctx.uploads[f"{SCORE}/pages/1.png"])).width == 1100
    job, ctx, _ = pdf_world(make_pdf(1, size=(2000, 2600)))                 # a poster-sized page (4167 px at 150 dpi)
    await import_pdf(job, ctx)
    assert Image.open(io.BytesIO(ctx.uploads[f"{SCORE}/pages/1.png"])).width == 3200


@pytest.mark.parametrize("data,words", [
    (b"<score-partwise/>", "not a PDF"),
    (b"%PDF-1.7\n garbage that is no PDF", "damaged"),
    (make_pdf(1, password="secret"), "password"),
])
async def test_files_a_musician_can_fix_fail_with_a_sentence(data, words):
    job, ctx, db = pdf_world(data)
    with pytest.raises(ScoreFailure, match=words):
        await import_pdf(job, ctx)
    assert ctx.uploads == {} and not [j for j in db.rows["jobs"] if j.get("kind") == "process_pages"]


async def test_too_many_pages_fails_before_rendering(monkeypatch):
    monkeypatch.setattr(import_pdf_mod.settings, "pdf_max_pages", 2)
    job, ctx, _ = pdf_world(make_pdf(3))
    with pytest.raises(ScoreFailure, match="3 pages; Folio reads up to 2"):
        await import_pdf(job, ctx)
    assert ctx.uploads == {}


async def test_the_pdf_reads_itself_end_to_end():
    """import_pdf, then process_pages on the pages it rendered: no page order from anyone, the score ends ready."""
    job, ctx, db = pdf_world(make_pdf(2, png=synth_page()))
    await import_pdf(job, ctx)
    follow = [j for j in db.rows["jobs"] if j.get("kind") == "process_pages"][0]
    pjob = Job(follow["id"], "process_pages", follow["payload"], SCORE, "u1", 1, 3)
    pctx = PagesCtx(pjob, db, dict(ctx.uploads), labels=[LABELS, LABELS])
    c, _ = fake_client([sig(accidental="none", count=0, mode="major", name="C major", symbol="common"), HEADER])
    out = await process_pages(pjob, pctx, client=c, model="muse-spark-1.3")
    score = db.rows["scores"][0]
    assert score["status"] == "ready" and score["pages"] == 2 and score["bars"] == 8 and (score["key_sig"], score["meter"]) == ("C major", "4/4")
    assert out["pages"] == 2 and out["measures"] == 8


async def test_title_and_blank_pages_first_the_signature_reads_the_first_music():
    """A whole PDF opens with a title page and a blank page: no call on them, the key and meter come from page 3."""
    doc = pymupdf.open()
    for i in range(3):
        page = doc.new_page(width=612, height=792)
        if i == 0:
            page.insert_text((200, 300), "CONCERTO No. 1", fontsize=24)
        if i == 2:
            page.insert_image(page.rect, stream=synth_page())
    job, ctx, db = pdf_world(doc.tobytes())
    await import_pdf(job, ctx)
    follow = [j for j in db.rows["jobs"] if j.get("kind") == "process_pages"][0]
    pjob = Job(follow["id"], "process_pages", follow["payload"], SCORE, "u1", 1, 3)
    pctx = PagesCtx(pjob, db, dict(ctx.uploads), labels=[LABELS])
    c, t = fake_client([sig(accidental="sharps", count=3, mode="minor", name="F# minor", symbol="common"), HEADER])
    await process_pages(pjob, pctx, client=c, model="muse-spark-1.3")
    score = db.rows["scores"][0]
    assert len(t.calls) == 2 and (score["key_sig"], score["meter"], score["status"]) == ("F# minor", "4/4", "ready")
    summary = db.rows["interpretations"][0]["summary"]
    assert summary["signature"]["page"] == 3 and summary["signature"]["crop_key"] == f"{SCORE}/signature/p003-s1.png"
    assert summary["log"][0] == "Page 3, first system: F# minor, 4/4" and summary["flagged"]["pages_unreadable"] == 2
    assert summary["log"][1].startswith("Page 3, score header: 6 staves per full system") and summary["header"]["page"] == 3


async def test_process_pages_fails_with_a_sentence_when_no_page_has_staves():
    buf = io.BytesIO()
    Image.new("L", (1275, 1650), 255).save(buf, format="PNG")
    job, ctx, db = pdf_world(b"")
    db.rows["sources"][0].update({"page_order": [1, 2], "page_count": 2})
    pjob = Job("job2", "process_pages", {"score_id": SCORE, "source_id": "src1"}, SCORE, "u1", 1, 3)
    pctx = PagesCtx(pjob, db, {f"{SCORE}/pages/1.png": buf.getvalue(), f"{SCORE}/pages/2.png": buf.getvalue()}, labels=[])
    c, t = fake_client([])
    with pytest.raises(ScoreFailure, match="no staves on the 2 pages"):
        await process_pages(pjob, pctx, client=c, model="muse-spark-1.3")
    assert t.calls == [] and pctx.charges == [] and db.rows["interpretations"][0]["status"] == "failed"


# ---------------------------------------------------------------- the worker's failure words

@pytest.fixture
def worker_db(monkeypatch):
    db = FakeDB()
    db.rows["scores"] = [{"id": SCORE, "status": "processing"}]
    monkeypatch.setattr(worker, "db", lambda: db)
    return db


async def test_worker_does_not_retry_a_score_failure_and_writes_its_sentence(worker_db, monkeypatch):
    async def boom(job, ctx):
        raise ScoreFailure("This PDF is locked with a password. Save a copy without the password and import that.")
    monkeypatch.setitem(worker.HANDLERS, "import_pdf", boom)
    worker_db.rows["jobs"] = [{"id": "j1", "kind": "import_pdf", "status": "running"}]
    await worker.run_one({"id": "j1", "kind": "import_pdf", "payload": {}, "score_id": SCORE, "created_by": "u1", "attempts": 1, "max_attempts": 3})
    assert worker_db.rows["jobs"][0]["status"] == "failed" and "ScoreFailure" in worker_db.rows["jobs"][0]["error"]
    assert worker_db.rows["scores"][0] == {"id": SCORE, "status": "failed", "failure_reason": "This PDF is locked with a password. Save a copy without the password and import that."}


async def test_worker_retries_a_fault_then_says_it_in_plain_words(worker_db, monkeypatch):
    async def boom(job, ctx):
        raise KeyError("systems")
    monkeypatch.setitem(worker.HANDLERS, "process_pages", boom)
    row = {"id": "j1", "kind": "process_pages", "payload": {}, "score_id": SCORE, "created_by": "u1", "attempts": 1, "max_attempts": 3}
    worker_db.rows["jobs"] = [{"id": "j1", "kind": "process_pages", "status": "running"}]
    await worker.run_one(row)
    assert worker_db.rows["jobs"][0]["status"] == "queued" and worker_db.rows["scores"][0]["status"] == "processing"
    await worker.run_one({**row, "attempts": 3})
    assert worker_db.rows["jobs"][0]["status"] == "failed" and worker_db.rows["jobs"][0]["error"] == "KeyError: 'systems'"
    assert worker_db.rows["scores"][0]["failure_reason"] == "Folio could not finish reading the pages. Try the import again."


# ---------------------------------------------------------------- the route

@pytest.fixture
def client(monkeypatch):
    db = FakeDB()
    db.rows["scores"] = [{"id": SCORE, "owner_user_id": "u1", "ensemble_id": None, "status": "uploaded"}]
    db.rows["members"] = []
    monkeypatch.setattr(scores_routes, "db", lambda: db)
    app.dependency_overrides[require_budget] = lambda: OWNER
    yield db, TestClient(app)
    app.dependency_overrides.clear()


def test_route_queues_import_pdf_on_the_browsers_source_row(client):
    db, c = client
    db.rows["sources"] = [{"id": "srcB", "score_id": SCORE, "kind": "pdf", "storage_paths": [KEY], "created_by": "u1", "created_at": "2026-10-28T10:00:00Z"}]
    r = c.post(f"/scores/{SCORE}/import", json={"path": KEY, "filename": "Op18.pdf"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source_id"] == "srcB" and body["kind"] == "import_pdf" and len(db.rows["sources"]) == 1
    job = db.rows["jobs"][0]
    assert job["id"] == body["job_id"] and job["kind"] == "import_pdf" and job["payload"] == {"score_id": SCORE, "source_id": "srcB"} and job["created_by"] == "u1"
    assert db.rows["scores"][0]["status"] == "processing" and db.rows["scores"][0]["progress"] == 0
    # a second call while the first is still reading
    assert c.post(f"/scores/{SCORE}/import", json={"path": KEY}).status_code == 409


def test_route_records_the_pdf_source_when_the_browser_did_not(client):
    db, c = client
    r = c.post(f"/scores/{SCORE}/import", json={"path": f"{SCORE}/Scan.PDF", "filename": "Scan.PDF"})
    assert r.status_code == 200, r.text
    src = db.rows["sources"][0]
    assert src["kind"] == "pdf" and src["storage_paths"] == [f"{SCORE}/Scan.PDF"] and src["created_by"] == "u1" and r.json()["source_id"] == src["id"]


def test_route_still_imports_musicxml(client):
    db, c = client
    r = c.post(f"/scores/{SCORE}/import", json={"path": f"{SCORE}/source.musicxml", "filename": "op18.musicxml"})
    assert r.status_code == 200 and r.json()["kind"] == "import_musicxml"
    assert db.rows["jobs"][0]["kind"] == "import_musicxml" and db.rows["sources"][0]["kind"] == "musicxml"
    assert c.post(f"/scores/{SCORE}/import", json={"path": "elsewhere/source.pdf"}).status_code == 400
