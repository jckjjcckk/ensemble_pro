"""Split by instrument for a Digital book (feature 008): music21 keeps the chosen parts of the imported MusicXML. No
model, no network: the fixture MusicXML in web/public/fixtures, the fake database and an in-memory bucket."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from music21 import converter, layout

from app import librarian, worker
from app.auth import User
from app.librarian import Job
from app.librarian.import_musicxml import part_groups
from app.librarian.part_split import UnknownInstrument, part_split, split_score
from app.main import app
from app.routes import scores as scores_routes
from app.spend import require_budget
from tests.test_part_cut import Ctx, FakeDB

SCORE = "11111111-1111-1111-1111-111111111111"
FIXTURES = Path(__file__).resolve().parents[2] / "web" / "public" / "fixtures"
QUARTET, CHOPIN, BACH = "beethoven-op18no1-mv1.musicxml", "piano-chopin-mazurka06-2.musicxml", "bach-bwv66-6.musicxml"
OWNER = User("u1", "owner@muse.test", "Owner", Decimal("5"), Decimal("0"))


def parse(name: str):
    return converter.parse((FIXTURES / name).read_bytes(), format="musicxml")


def test_part_groups_name_parts_as_the_import_does():
    assert [n for n, _ in part_groups(parse(QUARTET))] == ["Violin I", "Violin II", "Viola", "Cello"]
    chopin = part_groups(parse(CHOPIN))
    assert [n for n, _ in chopin] == ["Piano"] and len(chopin[0][1]) == 2          # two staves, one part
    assert [n for n, _ in part_groups(parse(BACH))] == ["Soprano", "Alto", "Tenor", "Bass"]


def test_split_keeps_the_chosen_parts_in_score_order():
    data, chosen = split_score(parse(QUARTET), ["Cello", "Violin I"])
    assert chosen == ["Violin I", "Cello"]
    back = converter.parse(data, format="musicxml")
    assert [p.partName for p in back.parts] == ["Violin I", "Cello"]
    assert [len(p.getElementsByClass("Measure")) for p in back.parts] == [313, 313]
    src = parse(QUARTET)
    assert [m.number for m in back.parts[1].getElementsByClass("Measure")][:5] == [m.number for m in src.parts[3].getElementsByClass("Measure")][:5]
    assert back.metadata.title == src.metadata.title


def test_split_keeps_a_piano_whole_with_its_brace_and_a_choir_bracket():
    data, chosen = split_score(parse(CHOPIN), ["Piano"])
    back = converter.parse(data, format="musicxml")
    assert chosen == ["Piano"] and len(back.parts) == 2
    assert any(g.symbol == "brace" for g in back.getElementsByClass(layout.StaffGroup))
    data, chosen = split_score(parse(BACH), ["Tenor", "Soprano"])
    back = converter.parse(data, format="musicxml")
    assert [p.partName for p in back.parts] == ["Soprano", "Tenor"]
    assert any(g.symbol == "bracket" for g in back.getElementsByClass(layout.StaffGroup))
    data, _ = split_score(parse(BACH), ["Alto"])
    assert not converter.parse(data, format="musicxml").getElementsByClass(layout.StaffGroup)   # a bracket around one part is no bracket


def test_split_refuses_unknown_names_with_the_available_ones():
    with pytest.raises(UnknownInstrument) as e:
        split_score(parse(QUARTET), ["Violin I", "Flute"])
    assert e.value.unknown == ["Flute"] and e.value.available == ["Violin I", "Violin II", "Viola", "Cello"]


class Bucket:
    def __init__(self, files: dict[str, bytes]):
        self.files, self.types = files, {}

    def from_(self, bucket: str) -> "Bucket":
        assert bucket == "scores"
        return self

    def download(self, path: str) -> bytes:
        return self.files[path]

    def upload(self, path: str, data: bytes, opts: dict) -> None:
        self.files[path], self.types[path] = data, opts.get("content-type")


class StoreDB(FakeDB):
    def __init__(self, files: dict[str, bytes]):
        super().__init__()
        self.storage = Bucket(files)


def digital_book(fixture: str = QUARTET) -> StoreDB:
    path = f"{SCORE}/source.musicxml"
    db = StoreDB({path: (FIXTURES / fixture).read_bytes()})
    db.rows["scores"] = [{"id": SCORE, "owner_user_id": "u1", "ensemble_id": None}]
    db.rows["sources"] = [{"id": "x1", "score_id": SCORE, "kind": "musicxml", "storage_paths": [path], "meta": {"filename": fixture}, "created_by": "u1"}]
    db.rows["parts"] = [{"score_id": SCORE, "name": n, "position": i} for i, (n, _) in enumerate(part_groups(parse(fixture)))]
    db.rows["members"] = []
    return db


class StoreCtx(Ctx):
    def storage_download(self, path):
        return self.db.storage.download(path)

    def storage_upload(self, path, data, content_type):
        self.db.storage.upload(path, data, {"content-type": content_type})


async def test_handler_uploads_the_split_and_records_a_musicxml_source_once():
    db = digital_book()
    j = Job("j1", "part_split", {"score_id": SCORE, "instruments": ["Cello", "Violin I"]}, SCORE, "u1", 1, 3)
    out = await part_split(j, StoreCtx(j, db, {}))
    key = f"{SCORE}/parts/violin-i+cello.musicxml"
    assert out["instruments"] == ["Violin I", "Cello"] and out["storage_path"] == key
    assert key in db.storage.files and db.storage.types[key] == "application/vnd.recordare.musicxml+xml"
    row = next(r for r in db.rows["sources"] if r["id"] == out["source_id"])
    assert row["kind"] == "musicxml" and row["storage_paths"] == [key]
    assert row["meta"] == {"instruments": ["Violin I", "Cello"], "split_from": "x1", "slug": "violin-i+cello"}
    again = await part_split(j, StoreCtx(j, db, {}))                     # the same selection: same file, same row
    assert again["source_id"] == out["source_id"] and len(db.rows["sources"]) == 2
    assert not [op for op in db.ops if op[0] in ("scores", "parts", "usage_events") and op[1] != "select"]   # no cost, the book untouched


@pytest.fixture
def client(monkeypatch):
    holder: dict[str, StoreDB] = {}

    def use(db: StoreDB) -> TestClient:
        holder["db"] = db
        monkeypatch.setattr(scores_routes, "db", lambda: db)
        monkeypatch.setattr(worker, "db", lambda: db)
        monkeypatch.setattr(librarian, "_db", lambda: db)
        app.dependency_overrides[require_budget] = lambda: OWNER
        return TestClient(app)
    yield use
    app.dependency_overrides.clear()


def test_route_splits_a_digital_book_at_once(client):
    db = digital_book()
    r = client(db).post(f"/scores/{SCORE}/parts", json={"instruments": ["Viola", "Violin II"]})
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["kind"] == "part_split" and job["status"] == "done" and job["created_by"] == "u1"
    res = job["result"]
    assert res["instruments"] == ["Violin II", "Viola"] and res["storage_path"] == f"{SCORE}/parts/violin-ii+viola.musicxml"
    assert res["source_id"] in {s["id"] for s in db.rows["sources"]}
    assert db.rows["jobs"][0]["finished_at"]


def test_route_refuses_unknown_names_with_the_parts_in_the_detail(client):
    db = digital_book()
    r = client(db).post(f"/scores/{SCORE}/parts", json={"instruments": ["Violin I", "Flute"]})
    assert r.status_code == 400
    assert r.json()["detail"] == "Not in this score: Flute. The parts are Violin I, Violin II, Viola, Cello."
    assert db.rows.get("jobs", []) == []


def test_route_still_cuts_a_pdf_book_and_ignores_split_sources(client):
    db = digital_book()
    db.rows["sources"].append({"id": "img", "score_id": SCORE, "kind": "images"})
    r = client(db).post(f"/scores/{SCORE}/parts", json={"instruments": ["Flute"]})
    assert r.status_code == 200 and r.json()["kind"] == "part_cut" and r.json().get("status", "queued") == "queued"
    db = digital_book()
    db.rows["sources"] = [{"id": "s2", "score_id": SCORE, "kind": "musicxml", "meta": {"split_from": "x0"}}]   # only a split: nothing to split from
    assert client(db).post(f"/scores/{SCORE}/parts", json={"instruments": ["Cello"]}).status_code == 400
