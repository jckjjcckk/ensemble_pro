"""Convert to Digital (feature 005) against a stubbed OMR box and a stubbed model: no ssh, no network, no Supabase.

The fake box writes what `omr_box.py` leaves on the real one: a one-page Audiveris book (book.xml, sheet#1.xml with
one grand-staff system of two stacks and a few inters), movements.json, book_run.json, the export `book.mxl`, and
a white 300 dpi scan. The fake model answers by prompt: the closed questions and the per-system text re-read."""
from __future__ import annotations

import io
import json
import os
import stat
import zipfile
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from music21 import converter, dynamics, expressions, stream
from PIL import Image

from app.auth import User
from app.librarian import Job
from app.librarian.omr_box import detected_movements, parse_pages
from app.librarian.omr_convert import OFFLINE, EngineOffline, SshBox, clean_name, digital_path, name_parts, omr_convert
from app.librarian.omr_score import merge
from app.librarian.omr_spark import REREAD_SYSTEM, VERIFY_SYSTEM, place
from app.main import app
from app.routes import convert as convert_routes, scores as scores_routes
from app.spend import require_budget
from tests.test_part_split import StoreCtx, StoreDB

SCORE = "11111111-1111-1111-1111-111111111111"
OWNER = User("u1", "owner@muse.test", "Owner", Decimal("5"), Decimal("0"))
OTHER = User("u2", "other@muse.test", "Other", Decimal("5"), Decimal("0"))

BOOK_XML = """<book><sheet number="1"><page id="1" movement-start="true" delta-measure-id="2"/></sheet>
<score id="1"><page sheet-number="1" sheet-page-id="1"/><logical-part name="Aria"/></score></book>"""


def staff(sid: int, top: int) -> str:
    lines = "".join(f'<line><point x="100" y="{top + 20 * i}"/><point x="900" y="{top + 20 * i}"/></line>' for i in range(5))
    return f'<staff id="{sid}" left="100" right="900"><lines>{lines}</lines></staff>'


SHEET_XML = f"""<sheet><picture width="1000" height="1400"/><scale><interline main="20"/></scale>
<page id="1"><system id="1">
  <part id="1">{staff(1, 200)}{staff(2, 400)}<measure id="1" abnormal="true"/></part>
  <stack id="1" left="100" right="500" expected="3/4" duration="1/2" excess="-1/4"/>
  <stack id="2" left="500" right="900" expected="3/4" duration="3/4"/>
  <sig><inters>
    <head id="10" shape="NOTEHEAD_BLACK" grade="0.9" staff="1"><bounds x="200" y="190" w="20" h="20"/></head>
    <dynamics id="11" shape="DYNAMICS_SF" grade="0.38" staff="1"><bounds x="190" y="300" w="30" h="20"/></dynamics>
    <word id="12" grade="0.7" value="dolc"><bounds x="600" y="300" w="60" h="20"/></word>
    <tuplet id="13" shape="TUPLET_THREE" grade="0.3" staff="1"><bounds x="700" y="150" w="15" h="20"/></tuplet>
    <fermata id="14" shape="FERMATA" grade="0.95" staff="1"><bounds x="300" y="150" w="20" h="10"/></fermata>
  </inters></sig>
</system></page></sheet>"""


def note(step: str, octave: int, dur: int, typ: str, staff_no: int, voice: int, extra: str = "") -> str:
    return (f"<note><pitch><step>{step}</step><octave>{octave}</octave></pitch><duration>{dur}</duration><voice>{voice}</voice>"
            f"<type>{typ}</type>{extra}<staff>{staff_no}</staff></note>")


TRIPLET = "<time-modification><actual-notes>3</actual-notes><normal-notes>2</normal-notes></time-modification>"
MUSICXML = f"""<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1"><work><work-title>book</work-title></work>
<part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
<part id="P1">
<measure number="1"><attributes><divisions>6</divisions><key><fifths>1</fifths></key><time><beats>3</beats><beat-type>4</beat-type></time>
<staves>2</staves><clef number="1"><sign>G</sign><line>2</line></clef><clef number="2"><sign>F</sign><line>4</line></clef></attributes>
<direction placement="below"><direction-type><dynamics><sf/></dynamics></direction-type><staff>1</staff></direction>
{note("G", 4, 12, "half", 1, 1)}<backup><duration>12</duration></backup>{note("G", 2, 18, "half", 2, 2, "<dot/>")}
</measure>
<measure number="2"><direction placement="below"><direction-type><words>dolc</words></direction-type><staff>1</staff></direction>
{note("B", 4, 2, "eighth", 1, 1, TRIPLET)}{note("C", 5, 2, "eighth", 1, 1, TRIPLET)}{note("D", 5, 2, "eighth", 1, 1, TRIPLET)}
{note("E", 5, 6, "quarter", 1, 1)}{note("F", 5, 6, "quarter", 1, 1)}<backup><duration>18</duration></backup>
{note("D", 3, 18, "half", 2, 2, "<dot/>")}
</measure></part></score-partwise>"""


def mxl(xml: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("META-INF/container.xml", '<?xml version="1.0"?><container><rootfiles><rootfile full-path="book.xml"/></rootfiles></container>')
        z.writestr("book.xml", xml)
    return buf.getvalue()


class FakeBox:
    def __init__(self, online: bool = True, drop_out: bool = False):
        self.online, self.drop_out, self.runs = online, drop_out, []

    async def reachable(self) -> bool:
        return self.online

    async def transcribe(self, run_id: str, pdf: bytes, pages, dest: Path) -> dict:
        self.runs.append((run_id, pdf, pages))
        if self.drop_out:
            raise EngineOffline(OFFLINE)
        (dest / "book" / "sheet#1").mkdir(parents=True)
        (dest / "book" / "book.xml").write_text(BOOK_XML)
        (dest / "book" / "sheet#1" / "sheet#1.xml").write_text(SHEET_XML)
        (dest / "movements.json").write_text(json.dumps(detected_movements(BOOK_XML.encode(), [1])))
        run = {"pdf_pages": pages or [1], "pdf_page_count": 1, "audiveris_s": 30.0, "render_s": 1.0, "box_s": 33.0, "exports": ["book.mxl"]}
        (dest / "book_run.json").write_text(json.dumps(run))
        (dest / "book.mxl").write_bytes(mxl(MUSICXML))
        (dest / "scan").mkdir()
        Image.new("L", (1000, 1400), 255).save(dest / "scan" / "p1.png")
        return run


class FakeMessages:
    def __init__(self):
        self.calls: list[dict] = []

    async def create(self, **kw):
        self.calls.append(kw)
        prompt = kw["messages"][0]["content"][-1]["text"]
        if kw["system"] == VERIFY_SYSTEM:
            ans = {"verdict": "fingering_digit", "value": "3"} if "TUPLET" in prompt else {"verdict": "dynamic_marking", "value": "mf"}
        else:
            assert kw["system"] == REREAD_SYSTEM and "treble + bass staff" in prompt and "measures 1..2" in prompt
            # crop origin (60, 120), size 860 x 440: the dynamic's ink at (205, 310), the word's at (630, 310)
            ans = {"text": [{"text": "mf", "x": 169, "y": 432, "bar": 1}, {"text": "dolce", "x": 663, "y": 432, "bar": 2}]}
        assert kw["max_tokens"] >= 8000 and kw["output_config"] == {"effort": "low"}
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(ans))], stop_reason="end_turn",
                               model="muse-spark-1.3", usage=SimpleNamespace(input_tokens=1000, output_tokens=500))


def fake_client():
    return SimpleNamespace(messages=FakeMessages())


def pdf_book(parts: list[dict] | None = None, score: dict | None = None) -> StoreDB:
    db = StoreDB({f"{SCORE}/source.pdf": b"%PDF-1.4 fake"})
    db.rows["scores"] = [{"id": SCORE, "owner_user_id": "u1", "ensemble_id": None, "title": "Goldberg Variations", "composer": "J. S. Bach",
                          "key_sig": "G major", "meter": None, "bars": None, "status": "ready", **(score or {})}]
    db.rows["sources"] = [{"id": "pdf1", "score_id": SCORE, "kind": "pdf", "storage_paths": [f"{SCORE}/source.pdf"], "created_by": "u1"}]
    db.rows["parts"] = parts or []
    db.rows["members"] = []
    return db


def job(payload: dict | None = None) -> Job:
    return Job("job-1", "omr_convert", {"score_id": SCORE, **(payload or {})}, None, "u1", 1, 1)


async def run(db: StoreDB, box: FakeBox, client=None, payload: dict | None = None):
    j = job(payload)
    ctx = StoreCtx(j, db, {})
    out = await omr_convert(j, ctx, box=box, client=client or fake_client(), model="muse-spark-1.3")
    return out, ctx


async def test_convert_writes_the_digital_version_with_flags_and_the_facts():
    db, box, client = pdf_book(), FakeBox(), fake_client()
    out, ctx = await run(db, box, client, {"pages": [1]})
    assert box.runs == [("job-1", b"%PDF-1.4 fake", [1])]
    assert out["instruments"] == ["Piano"] and out["bars"] == 2 and out["pages"] == [1]
    assert 1 in out["flagged_bars"]                                                  # Audiveris's own rhythm check
    assert len(client.messages.calls) == 3 and len(ctx.charges) == 3                 # two closed questions, one re-read
    assert all(c.kind == "spark" and c.model == "muse-spark-1.3" for c in ctx.charges)
    assert out["cost_usd"] == pytest.approx(3 * (1000 * 1.25 + 500 * 4.25) / 1e6, abs=1e-4)

    key = digital_path(SCORE)
    assert key == f"{SCORE}/digital/score.musicxml" and db.storage.types[key] == "application/vnd.recordare.musicxml+xml"
    back = converter.parse(db.storage.files[key], format="musicxml")
    upper, lower = back.parts
    assert [m.number for m in upper.getElementsByClass(stream.Measure)] == [1, 2]
    assert b"<work-title>Goldberg Variations</work-title>" in db.storage.files[key] and back.metadata.composer == "J. S. Bach"
    m1, m2 = upper.measure(1), upper.measure(2)
    assert [d.value for d in m1.recurse().getElementsByClass(dynamics.Dynamic)] == ["mf"]           # sf -> mf, written once
    assert [t.content for t in m2.recurse().getElementsByClass(expressions.TextExpression)] == ["dolce"]
    assert not any(n.duration.tuplets for n in m2.recurse().notes)                    # the "3" was fingering
    assert [p.nameWithOctave for n in back.recurse().notes for p in n.pitches][:2] == ["G4", "B4"]   # notes as Audiveris read them

    row = next(r for r in db.rows["sources"] if r["id"] == out["source_id"])
    assert row["kind"] == "musicxml" and row["storage_paths"] == [key]
    meta = row["meta"]
    assert meta["transcribed_from"] == "pdf1" and meta["engine"] == "audiveris-5.11+spark"
    assert meta["flags"] == {"bars_doubtful": len(out["flagged_bars"]), "pages_unreadable": 0}
    b1 = meta["flagged_bars"][0]
    assert b1["number"] == 1 and b1["page"] == 1 and b1["key"] == "1.1.1" and b1["box"]["x0"] == 0.1
    assert any("abnormal" in r for r in b1["reasons"])
    assert "instruments" not in meta and "slug" not in meta and "split_from" not in meta   # not a split (the web's isSplit)

    s = db.rows["scores"][0]
    assert s["key_sig"] == "G major" and s["meter"] == "3/4" and s["bars"] == 2 and s["status"] == "ready"
    assert "current_interpretation_id" not in s
    assert [(p["name"], p["storage_path"]) for p in db.rows["parts"]] == [("Piano", key)]
    assert sorted(m["number"] for m in db.rows["measures"]) == [1, 2]


async def test_rerun_replaces_the_file_and_the_row():
    db = pdf_book()
    first, _ = await run(db, FakeBox())
    db.storage.files[digital_path(SCORE)] = b"stale"
    again, _ = await run(db, FakeBox())
    assert again["source_id"] == first["source_id"]
    assert len([r for r in db.rows["sources"] if r["kind"] == "musicxml"]) == 1
    assert db.storage.files[digital_path(SCORE)] != b"stale"


async def test_existing_parts_keep_their_names_and_difficulty():
    db = pdf_book(parts=[{"score_id": SCORE, "name": "Harpsichord", "position": 0, "difficulty": 5, "storage_path": None}])
    out, _ = await run(db, FakeBox())
    assert out["instruments"] == ["Harpsichord"]
    assert db.rows["parts"] == [{"score_id": SCORE, "name": "Harpsichord", "position": 0, "difficulty": 5, "storage_path": digital_path(SCORE)}]
    back = converter.parse(db.storage.files[digital_path(SCORE)], format="musicxml")
    assert {p.partName for p in back.parts} == {"Harpsichord"}


async def test_spark_allowance_stops_the_questions_and_keeps_audiveris():
    db, client = pdf_book(), fake_client()
    out, ctx = await run(db, FakeBox(), client, {"max_cost_usd": 0.000001})
    assert out["spark_skipped"] >= 1 and len(ctx.charges) < 3 and out["bars"] == 2


@pytest.mark.parametrize("box", [FakeBox(online=False), FakeBox(drop_out=True)])
async def test_offline_box_fails_with_the_reason_and_no_charge(box):
    db, client = pdf_book(), fake_client()
    j = job()
    ctx = StoreCtx(j, db, {})
    with pytest.raises(EngineOffline, match=OFFLINE):
        await omr_convert(j, ctx, box=box, client=client, model="muse-spark-1.3")
    assert ctx.result["reason"] == OFFLINE and ctx.charges == [] and client.messages.calls == []
    assert [r["kind"] for r in db.rows["sources"]] == ["pdf"] and db.rows["scores"][0]["status"] == "ready"


async def test_a_book_without_a_pdf_is_refused():
    db = pdf_book()
    db.rows["sources"] = [{"id": "img", "score_id": SCORE, "kind": "images", "storage_paths": []}]
    with pytest.raises(RuntimeError, match="no PDF"):
        await run(db, FakeBox())


def test_name_parts_prefers_the_books_names_when_the_counts_agree():
    sc = converter.parse(MUSICXML, format="musicxml")
    groups, kept = name_parts(sc, ["Cembalo"])
    assert kept and [n for n, _ in groups] == ["Cembalo"] and all(p.partName == "Cembalo" for p in sc.parts)
    groups, kept = name_parts(converter.parse(MUSICXML, format="musicxml"), ["Violin I", "Cello"])
    assert not kept and [n for n, _ in groups] == ["Piano"]


def test_box_script_pages_and_movements():
    assert parse_pages(None, 3) == [1, 2, 3] and parse_pages("1-2", 3) == [1, 2] and parse_pages("1,3", 3) == [1, 3]
    for bad in ("0-2", "2-4", "1,1"):
        with pytest.raises(ValueError):
            parse_pages(bad, 3)
    mv = detected_movements(BOOK_XML.encode(), [7])
    assert mv == [{"sheet": 1, "pdf_page": 7, "page": 1, "movement_start": True, "movement": 1, "name": "Aria", "measures": 2}]


def fake_ssh(tmp_path: Path, code: int) -> str:
    bin_dir = tmp_path / f"bin{code}"
    bin_dir.mkdir()
    exe = bin_dir / "ssh"
    exe.write_text(f"#!/bin/sh\nexit {code}\n")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return f"{bin_dir}{os.pathsep}{os.environ['PATH']}"


async def test_ssh_box_reads_exit_255_as_offline(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", fake_ssh(tmp_path, 255))
    assert await SshBox(host="omr").reachable() is False
    with pytest.raises(EngineOffline):
        await SshBox(host="omr").transcribe("job-1", b"%PDF", [1], tmp_path)
    monkeypatch.setenv("PATH", fake_ssh(tmp_path, 0))
    assert await SshBox(host="omr").reachable() is True


# ---------------------------------------------------------------------------------------------------- the route

@pytest.fixture
def client(monkeypatch):
    holder: dict = {}

    def use(db: StoreDB, user: User | None = OWNER) -> TestClient:
        holder["db"] = db
        monkeypatch.setattr(scores_routes, "db", lambda: db)
        monkeypatch.setattr(convert_routes, "db", lambda: db)
        if user is None:
            def broke():
                raise HTTPException(402, "Your budget for model calls is spent")
            app.dependency_overrides[require_budget] = broke
        else:
            app.dependency_overrides[require_budget] = lambda: user
        return TestClient(app)
    yield use
    app.dependency_overrides.clear()


def test_route_queues_one_convert_job(client):
    db = pdf_book()
    r = client(db).post(f"/scores/{SCORE}/convert", json={"pages": [3, 1, 2, 1]})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["kind"] == "omr_convert" and j["score_id"] is None and j["created_by"] == "u1" and j["max_attempts"] == 1
    assert j["payload"] == {"score_id": SCORE, "source_id": "pdf1", "pages": [1, 2, 3]}
    r = client(db).post(f"/scores/{SCORE}/convert")
    assert r.status_code == 400 and r.json()["detail"] == "A transcription of this book is already in progress"
    db.rows["jobs"][0]["status"] = "failed"
    r = client(db).post(f"/scores/{SCORE}/convert")                     # a finished one does not block; no body: every page
    assert r.status_code == 200 and r.json()["payload"] == {"score_id": SCORE, "source_id": "pdf1"}


def test_route_refusals(client):
    db = pdf_book()
    assert client(db, user=None).post(f"/scores/{SCORE}/convert").status_code == 402
    assert client(db).post("/scores/22222222-2222-2222-2222-222222222222/convert").status_code == 404
    assert client(db, user=OTHER).post(f"/scores/{SCORE}/convert").status_code == 403
    db.rows["sources"] = [{"id": "x", "score_id": SCORE, "kind": "musicxml"}]
    r = client(db).post(f"/scores/{SCORE}/convert")
    assert r.status_code == 400 and r.json()["detail"] == "This book has no PDF to convert"
    assert db.rows.get("jobs", []) == []


def test_an_unconfirmed_point_yields_to_sparks_bar_label():
    ms = [{"number": 18, "px": [100, 0, 500, 100]}, {"number": 19, "px": [500, 0, 900, 100]}]
    staves, crop = [{"top": 20, "bottom": 80}], {"origin": [0, 0], "size": [1000, 100]}
    words = [{"text": "cresc.", "x": 520, "y": 90, "bar": 18}]
    (alone,), _ = place(words, ms, staves, crop)                                       # no glyph near: the label wins
    assert alone["number"] == 18 and alone["how"] == "label-over-x" and alone["x_bar"] == 19 and alone["label_agrees"]
    glyph = {"tag": "word", "value": "cresc.", "bounds": [540, 85, 60, 10]}
    (seen,), _ = place(words, ms, staves, crop, glyphs=[glyph])                         # Audiveris saw the ink there: x wins
    assert seen["number"] == 19 and seen["how"] == "glyph+x" and seen["label_agrees"] is False


ONE_BAR = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1"><part-list><score-part id="P1"><part-name>Violin</part-name></score-part>
<score-part id="P2"><part-name>Cello</part-name></score-part></part-list>
<part id="P1"><measure number="1"><attributes><divisions>1</divisions><time><beats>3</beats><beat-type>4</beat-type></time>
<clef><sign>G</sign><line>2</line></clef></attributes>{n1}</measure><measure number="2">{n2}</measure></part>
<part id="P2"><measure number="2"><attributes><divisions>1</divisions><time><beats>3</beats><beat-type>4</beat-type></time>
<clef><sign>F</sign><line>4</line></clef></attributes>{n3}</measure></part></score-partwise>"""


def test_a_bar_the_export_left_out_becomes_a_flagged_rest(tmp_path):
    xml = ONE_BAR.format(n1=note("A", 4, 3, "half", 1, 1, "<dot/>"), n2=note("B", 4, 3, "half", 1, 1, "<dot/>"),
                         n3=note("C", 3, 3, "half", 1, 1, "<dot/>"))
    (tmp_path / "book.mxl").write_bytes(mxl(xml))
    doc = {"measures": [{"number": n, "movement": 1, "movement_bar": n} for n in (1, 2)]}
    sc, filled = merge(doc, [tmp_path / "book.mxl"])
    violin, cello = sc.parts
    assert [m.number for m in cello.getElementsByClass(stream.Measure)] == [1, 2]
    assert [r.quarterLength for r in cello.measure(1).recurse().notesAndRests] == [3.0]          # the export's 3/4
    assert [p.nameWithOctave for p in cello.measure(2).recurse().notes[0].pitches] == ["C3"]
    assert filled == {1: ["staff 2: bar missing from the export (a rest stands in)"]}
    groups, kept = name_parts(sc, [])
    assert [n for n, _ in groups] == ["Violin", "Cello"] and not kept


def test_ocr_part_names_are_tidied():
    assert [clean_name(n) for n in ("Piano I.", "Piano 11.", "Violoncello", "Viola:", "Flute 1")] == [
        "Piano I", "Piano II", "Violoncello", "Viola", "Flute I"]
