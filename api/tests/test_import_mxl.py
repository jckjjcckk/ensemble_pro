"""A compressed MusicXML file (.mxl) imported from the iPad (E2E night 2026-10-31): the browser stores any notation file at
{score}/source.musicxml, so the import finds a zip there. It reads the score inside, stores it back as plain MusicXML
under the same key and names the export after it. No model, no network: the fake bucket of test_part_split."""
from __future__ import annotations

import io
import zipfile

from app.librarian import Job
from app.librarian.import_musicxml import import_musicxml
from tests.test_part_split import BACH, FIXTURES, SCORE, StoreCtx, StoreDB

CONTAINER = (b'<?xml version="1.0" encoding="UTF-8"?><container><rootfiles>'
             b'<rootfile full-path="score.xml" media-type="application/vnd.recordare.musicxml+xml"/></rootfiles></container>')


def mxl(xml: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("META-INF/container.xml", CONTAINER)
        z.writestr("score.xml", xml)
    return buf.getvalue()


def book(data: bytes, filename: str) -> StoreDB:
    path = f"{SCORE}/source.musicxml"
    db = StoreDB({path: data})
    db.rows["scores"] = [{"id": SCORE, "owner_user_id": "u1", "ensemble_id": None, "title": "", "composer": None, "work": None}]
    db.rows["sources"] = [{"id": "x1", "score_id": SCORE, "kind": "musicxml", "storage_paths": [path], "meta": {"filename": filename}, "created_by": "u1"}]
    db.rows["parts"], db.rows["members"] = [], []
    return db


async def test_an_mxl_is_read_and_stored_back_as_plain_musicxml():
    xml = (FIXTURES / BACH).read_bytes()
    db = book(mxl(xml), "bwv66-6.mxl")
    j = Job("j1", "import_musicxml", {"score_id": SCORE, "source_id": "x1"}, SCORE, "u1", 1, 3)
    out = await import_musicxml(j, StoreCtx(j, db, {}))
    assert out["measures"] > 0 and out["parts"] == ["Soprano", "Alto", "Tenor", "Bass"]
    assert db.rows["scores"][0]["status"] == "ready"
    stored = db.storage.files[f"{SCORE}/source.musicxml"]
    assert stored == xml and db.storage.types[f"{SCORE}/source.musicxml"] == "application/vnd.recordare.musicxml+xml"
    assert db.rows["sources"][0]["meta"] == {"filename": "bwv66-6.musicxml", "unzipped_from": "bwv66-6.mxl"}
    assert out["playback"]["ok"]


async def test_a_plain_file_is_left_as_it_is():
    xml = (FIXTURES / BACH).read_bytes()
    db = book(xml, "bwv66-6.musicxml")
    j = Job("j1", "import_musicxml", {"score_id": SCORE, "source_id": "x1"}, SCORE, "u1", 1, 3)
    await import_musicxml(j, StoreCtx(j, db, {}))
    assert db.rows["sources"][0]["meta"] == {"filename": "bwv66-6.musicxml"}
    assert not [op for op in db.ops if op[0] == "sources" and op[1] == "update"]
