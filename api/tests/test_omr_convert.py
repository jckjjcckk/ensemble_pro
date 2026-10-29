"""Convert to Digital (feature 005, librarian agent v2) against a stubbed OMR box, a stubbed PDF and a stubbed model:
no ssh, no network, no Supabase, no model call.

The fake PDF has three pages: a cover without staves, a contents page with staves (Spark calls it "contents") and a
page of music. The fake box writes what `omr_box.py` leaves on the real one: a one-page Audiveris book (book.xml,
sheet#1.xml with one grand-staff system of two stacks and a few inters), movements.json, book_run.json, the export
`book.mxl`, and a white 300 dpi scan. The fake model answers by system prompt: the page kind, the front-matter form,
the per-system text, the two closed questions and the render check."""
from __future__ import annotations

import io
import json
import os
import re
import stat
import zipfile
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from music21 import articulations, converter, dynamics, expressions, stream, tempo
from PIL import Image

from app.auth import User
from app.librarian import Job
from app.librarian.omr_box import detected_movements, parse_pages
from app.librarian.omr_agent import FRONT_SYSTEM, PAGE_KIND_SYSTEM, REREAD_SYSTEM, VERIFY_SYSTEM
from app.librarian.omr_verify import VERIFY_RENDER_SYSTEM
from app.librarian.omr_convert import OFFLINE, EngineOffline, SshBox, clean_name, cover_path, digital_path, name_parts, omr_convert
from app.librarian.omr_score import merge
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
    <ornament id="13" shape="MORDENT" grade="0.3" staff="1"><bounds x="300" y="150" w="15" h="20"/></ornament>
    <alter id="14" shape="SHARP" grade="0.4" staff="1"><bounds x="620" y="190" w="10" h="25"/></alter>
    <alter id="15" shape="FLAT" grade="0.9" staff="2"><bounds x="220" y="420" w="10" h="25"/></alter>
  </inters></sig>
</system></page></sheet>"""


def note(step: str, octave: int, dur: int, typ: str, staff_no: int, voice: int, extra: str = "") -> str:
    return (f"<note><pitch><step>{step}</step><octave>{octave}</octave></pitch><duration>{dur}</duration><voice>{voice}</voice>"
            f"<type>{typ}</type>{extra}<staff>{staff_no}</staff></note>")


MORDENT = "<notations><ornaments><mordent/></ornaments></notations>"
WEDGE = '<direction placement="below"><direction-type><wedge type="{t}"/></direction-type><staff>1</staff></direction>'
PEDAL = '<direction placement="below"><direction-type><pedal type="{t}"/></direction-type><staff>2</staff></direction>'
MUSICXML = f"""<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1"><work><work-title>book</work-title></work>
<part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
<part id="P1">
<measure number="1"><attributes><divisions>6</divisions><key><fifths>1</fifths></key><time><beats>3</beats><beat-type>4</beat-type></time>
<staves>2</staves><clef number="1"><sign>G</sign><line>2</line></clef><clef number="2"><sign>F</sign><line>4</line></clef></attributes>
<direction placement="below"><direction-type><dynamics><sf/></dynamics></direction-type><staff>1</staff></direction>
{PEDAL.format(t="start")}
{note("G", 4, 6, "quarter", 1, 1)}{note("A", 4, 6, "quarter", 1, 1, MORDENT)}{note("B", 4, 6, "quarter", 1, 1)}{PEDAL.format(t="stop")}<backup><duration>18</duration></backup>{note("G", 2, 18, "half", 2, 2, "<dot/>")}
</measure>
<measure number="2"><direction placement="above"><direction-type><words font-weight="bold">Andante espressivo.</words></direction-type>
<direction-type><metronome parentheses="yes"><beat-unit>quarter</beat-unit><per-minute>72</per-minute></metronome></direction-type><staff>1</staff><sound tempo="72"/></direction>
<direction placement="below"><direction-type><words>dolc</words></direction-type><staff>1</staff></direction>
<direction placement="below"><direction-type><words>07'880.</words></direction-type><staff>2</staff></direction>
{WEDGE.format(t="crescendo")}
{note("B", 4, 3, "eighth", 1, 1)}{note("C", 5, 3, "eighth", 1, 1)}{note("D", 5, 6, "quarter", 1, 1)}{note("E", 5, 6, "quarter", 1, 1)}
{WEDGE.format(t="stop")}<backup><duration>18</duration></backup>
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
        (dest / "movements.json").write_text(json.dumps(detected_movements(BOOK_XML.encode(), pages or [1])))
        run = {"pdf_pages": pages or [1], "pdf_page_count": 1, "audiveris_s": 30.0, "render_s": 1.0, "box_s": 33.0, "exports": ["book.mxl"]}
        (dest / "book_run.json").write_text(json.dumps(run))
        (dest / "book.mxl").write_bytes(mxl(MUSICXML))
        (dest / "scan").mkdir()
        Image.new("L", (1000, 1400), 255).save(dest / "scan" / "p1.png")
        return run


class FakePdf:
    """Three pages: a cover (no staves), a contents page (staves) and the music (staves)."""

    def __init__(self, count: int = 3, staves: dict[int, bool] | None = None):
        self.count = count
        self.staves = staves or {1: False, 2: True, 3: True}
        self.rendered: list[int] = []

    def png(self, page: int) -> bytes:
        self.rendered.append(page)
        buf = io.BytesIO()
        Image.new("L", (200, 280), 255 - page).save(buf, format="PNG")
        return buf.getvalue()

    def has_staves(self, page: int) -> bool:
        return self.staves.get(page, True)


FRONT = {"title": "Aria con Variazioni.", "composer": "J. S. Bach", "movement_or_number": "Aria", "tempo_heading": "Andante espressivo.",
         "metronome": {"unit": "quarter", "bpm": 72}, "opus": "BWV 988", "dedication": None, "editor": "Hans Bischoff"}
TEXT = [
    {"text": "p", "x": 169, "y": 432, "bar": 1},                     # on Audiveris's sf glyph: written as p (the sf is cleared)
    {"text": "dolce", "x": 663, "y": 432, "bar": 2},                 # on Audiveris's "dolc" glyph: written in italic
    {"text": "cresc.", "x": 500, "y": 432, "bar": 2},                # snaps to the "dolc" glyph, but a hairpin starts in bar 2: duplicate
    {"text": "07'880.", "x": 900, "y": 980, "bar": 2},               # a plate number
    {"text": "<", "x": 400, "y": 432, "bar": 1},                     # a hairpin character
    {"text": "3", "x": 120, "y": 900, "bar": 1},                     # a fingering digit
    {"text": "Andante espressivo.", "x": 160, "y": 20, "bar": 1},    # the tempo heading: the front-matter read owns it
]


class FakeRenderer:
    """Writes one white 300 dpi page and an .mpos with the two bars side by side; remembers the file it was given."""

    def __init__(self, fail: bool = False):
        self.fail, self.runs = fail, []

    async def reachable(self) -> bool:
        return True

    async def render_png(self, run_id: str, musicxml: bytes, dest: Path) -> dict:
        self.runs.append((run_id, musicxml))
        if self.fail:
            raise RuntimeError("no MuseScore today")
        Image.new("RGB", (2480, 3508), (255, 255, 255)).save(dest / "p-1.png")
        (dest / "p.mpos").write_text('<?xml version="1.0"?><score><elements>'
                                     '<element id="0" x="9600" y="24000" sx="48000" sy="19200" page="0"/>'
                                     '<element id="1" x="57600" y="24000" sx="48000" sy="19200" page="0"/></elements></score>')
        return {"seconds": 0.5}


class FakeMessages:
    def __init__(self, same: bool = True):
        self.calls: list[dict] = []
        self.same = same

    async def create(self, **kw):
        self.calls.append(kw)
        prompt = kw["messages"][0]["content"][-1]["text"]
        if kw["system"] == PAGE_KIND_SYSTEM:
            ans = {"kind": "contents" if "page 2 " in prompt else "music", "confidence": "high"}
        elif kw["system"] == FRONT_SYSTEM:
            ans = FRONT
        elif kw["system"] == REREAD_SYSTEM:
            assert "treble + bass staff" in prompt and "measures 1..2" in prompt
            ans = {"text": TEXT}
        elif kw["system"] == VERIFY_RENDER_SYSTEM:
            assert "measures 1..2" in prompt
            ans = ({"same": True, "reason": "matches", "differences": []} if self.same else
                   {"same": False, "reason": "the bottom shows dolce where the top prints nothing", "differences": [{"measure": 2, "what": "dolce"}]})
        else:
            assert kw["system"] == VERIFY_SYSTEM
            ans = {"verdict": "natural", "value": ""} if "SHARP" in prompt else {"verdict": "nothing_else", "value": ""}
        assert kw["max_tokens"] >= 8000 and kw["output_config"] == {"effort": "low"}
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(ans))], stop_reason="end_turn",
                               model="muse-spark-1.3", usage=SimpleNamespace(input_tokens=1000, output_tokens=500))


def fake_client(same: bool = True):
    return SimpleNamespace(messages=FakeMessages(same))


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


async def run(db: StoreDB, box: FakeBox, client=None, payload: dict | None = None, pdf: FakePdf | None = None, renderer=None):
    j = job(payload)
    ctx = StoreCtx(j, db, {})
    out = await omr_convert(j, ctx, box=box, client=client or fake_client(), model="muse-spark-1.3", pdf_pages=pdf or FakePdf(),
                            engraver=renderer or FakeRenderer())
    return out, ctx


CALL_USD = (1000 * 1.25 + 500 * 4.25) / 1e6


async def test_convert_writes_the_digital_version_with_flags_and_the_facts():
    db, box, client, pdf, renderer = pdf_book(), FakeBox(), fake_client(), FakePdf(), FakeRenderer()
    out, ctx = await run(db, box, client, pdf=pdf, renderer=renderer)
    # page kinds: the cover by geometry, the contents page asked, the music page asked; Audiveris gets the music page only
    assert out["page_kinds"] == [(1, "cover"), (2, "contents"), (3, "music")]
    assert box.runs == [("job-1", b"%PDF-1.4 fake", [3])]
    assert out["cover"] == cover_path(SCORE) and db.storage.types[out["cover"]] == "image/png" and 1 in pdf.rendered
    assert out["instruments"] == ["Piano"] and out["bars"] == 2 and out["pages"] == [3]
    assert 1 in out["flagged_bars"]                                                  # Audiveris's own rhythm check
    # two page-kind questions, the front matter, one system, two closed questions (the flat at 0.9 is over the gate), one render check
    assert len(client.messages.calls) == 7 and len(ctx.charges) == 7
    assert all(c.kind == "spark" and c.model == "muse-spark-1.3" for c in ctx.charges)
    assert out["cost_usd"] == pytest.approx(7 * CALL_USD, abs=1e-4)
    assert out["cost_per_page"] == {"2": pytest.approx(CALL_USD, abs=1e-4), "3": pytest.approx(6 * CALL_USD, abs=1e-4)}
    assert out["verify"] == {"asked": 1, "reverted": {}, "missing": {}, "systems": 1, "skipped": None, "render_s": 0.5}
    assert len(renderer.runs) == 1 and renderer.runs[0][0] == "job-1-verify"

    key = digital_path(SCORE)
    assert key == f"{SCORE}/digital/score.musicxml" and db.storage.types[key] == "application/vnd.recordare.musicxml+xml"
    xml = db.storage.files[key]
    assert xml == renderer.runs[0][1]                                                # what Spark checked is what was written
    back = converter.parse(xml, format="musicxml")
    upper, lower = back.parts
    assert [m.number for m in upper.getElementsByClass(stream.Measure)] == [1, 2]
    # front matter: the page's heading is the file's title (the shelf title "Goldberg Variations" is never written in)
    assert b"<work-title>Aria con Variazioni.</work-title>" in xml and b"Goldberg Variations" not in xml
    assert back.metadata.composer == "J. S. Bach"
    assert b"<work-number>BWV 988</work-number>" in xml and b"<movement-title>Aria</movement-title>" in xml
    assert b'<creator type="editor">Hans Bischoff</creator>' in xml
    m1, m2 = upper.measure(1), upper.measure(2)
    marks = [(mm.number, mm.getOffsetBySite(m1)) for mm in m1.getElementsByClass(tempo.MetronomeMark)]
    assert marks == [(72, 0.0)] and not m2.getElementsByClass(tempo.MetronomeMark)
    assert xml.count(b"<metronome") == 1 and b'<sound tempo="72"' in xml
    m1_xml = re.search(rb'<measure[^>]*number="1".*?</measure>', xml, re.S).group(0)
    tempo_dir = next(d for d in re.findall(rb"<direction\b.*?</direction>", m1_xml, re.S) if b"<metronome" in d)
    assert tempo_dir.index(b"Andante espressivo.") < tempo_dir.index(b"<metronome")      # one direction: words, then the mark
    assert xml.count(b"Andante espressivo.") == 1
    # text: p where Audiveris's sf glyph was, dolce in italic where its "dolc" was; the free cresc., the plate number,
    # the hairpin character and the digit never reach the file
    assert [d.value for d in back.recurse().getElementsByClass(dynamics.Dynamic)] == ["p"]
    words = [(t.content, t.style.fontStyle) for t in back.recurse().getElementsByClass(expressions.TextExpression)
             if t.style.fontWeight != "bold"]                                         # the heading comes back as bold words
    assert words == [("dolce", "italic")]
    assert b"07'880" not in xml and b">cresc.<" not in xml and b"&lt;" not in xml
    assert [type(e).__name__ for e in next(n for n in back.recurse().notes if n.nameWithOctave == "A4").expressions] == []   # the low-grade mordent Spark called nothing
    assert xml.count(b"<pedal") == 2 and xml.count(b"<wedge") == 2                 # Audiveris's pedal and hairpin untouched
    assert [p.nameWithOctave for n in back.recurse().notes for p in n.pitches][:2] == ["G4", "A4"]   # notes as Audiveris read them
    assert out["items"]["written"] == {"words": 1, "dynamic": 1} and out["items"]["duplicates"] == 1 and out["items"]["dropped"] == 4
    assert out["items"]["verified"] == {"systems": 1, "reverted_bars": [], "missing_bars": [], "skipped": None}

    row = next(r for r in db.rows["sources"] if r["id"] == out["source_id"])
    assert row["kind"] == "musicxml" and row["storage_paths"] == [key]
    meta = row["meta"]
    assert meta["transcribed_from"] == "pdf1" and meta["engine"] == "audiveris-5.11+spark-v2"
    assert meta["flags"] == {"bars_doubtful": len(out["flagged_bars"]), "pages_unreadable": 0}
    b1 = meta["flagged_bars"][0]
    assert b1["number"] == 1 and b1["page"] == 3 and b1["key"] == "1.1.1" and b1["box"]["x0"] == 0.1
    assert any("abnormal" in r for r in b1["reasons"])
    b2 = next(b for b in meta["flagged_bars"] if b["number"] == 2)
    assert any(r.startswith("accidental: the engine read a sharp; Spark sees natural") for r in b2["reasons"])
    assert [k["kind"] for k in meta["page_kinds"]] == ["cover", "contents", "music"] and meta["cover"] == out["cover"]
    assert meta["front_matter"]["tempo_heading"] == "Andante espressivo." and meta["front_matter"]["read"] is True
    assert meta["cost"]["total_usd"] == out["cost_usd"] and set(meta["cost"]["per_step"]) == {"page_kind", "front_matter", "reread", "verify", "verify_render"}
    assert "instruments" not in meta and "slug" not in meta and "split_from" not in meta   # not a split (the web's isSplit)

    s = db.rows["scores"][0]
    assert s["key_sig"] == "G major" and s["meter"] == "3/4" and s["bars"] == 2 and s["pages"] == 3 and s["status"] == "ready"
    assert s["title"] == "Goldberg Variations" and s["composer"] == "J. S. Bach" and s["work"] == "BWV 988" and s["tempo_bpm"] == 72
    assert "current_interpretation_id" not in s
    assert [(p["name"], p["storage_path"]) for p in db.rows["parts"]] == [("Piano", key)]
    assert sorted(m["number"] for m in db.rows["measures"]) == [1, 2]


async def test_a_render_check_that_fails_reverts_the_named_bars_and_flags_them():
    db, renderer = pdf_book(), FakeRenderer()
    out, _ = await run(db, FakeBox(), fake_client(same=False), renderer=renderer)
    assert out["verify"]["asked"] == 1 and sorted(out["verify"]["reverted"]) == [2]       # Spark named measure 2 only
    xml = db.storage.files[digital_path(SCORE)]
    assert xml != renderer.runs[0][1]                                                 # rewritten after the revert
    back = converter.parse(xml, format="musicxml")
    assert [d.value for d in back.recurse().getElementsByClass(dynamics.Dynamic)] == ["p"]           # bar 1 kept Spark's p
    assert [t.content for t in back.recurse().getElementsByClass(expressions.TextExpression) if t.style.fontWeight != "bold"] == ["dolc"]
    assert b"07'880" not in xml                                                       # Audiveris's plate number never comes back
    assert xml.count(b"<metronome") == 1 and b"Andante espressivo." in xml           # the tempo line on bar 1 stays
    m1 = re.search(rb'<measure[^>]*number="1".*?</measure>', xml, re.S).group(0)
    assert b"<metronome" in m1
    meta = next(r for r in db.rows["sources"] if r["id"] == out["source_id"])["meta"]
    reasons = {b["number"]: b["reasons"] for b in meta["flagged_bars"]}
    assert any(r.startswith("verify: the engraved text did not match the scan (the bottom shows dolce") for r in reasons[2])
    assert not any(r.startswith("verify:") for r in reasons.get(1, []))
    assert out["items"]["verified"]["reverted_bars"] == [2]


async def test_a_failed_render_leaves_the_edits_and_says_why():
    db = pdf_book()
    out, _ = await run(db, FakeBox(), renderer=FakeRenderer(fail=True))
    assert out["verify"]["asked"] == 0 and out["verify"]["skipped"].startswith("render failed (RuntimeError")
    assert b"dolce" in db.storage.files[digital_path(SCORE)]


async def test_a_book_of_front_matter_only_fails_before_the_box():
    db, box = pdf_book(), FakeBox()
    with pytest.raises(RuntimeError, match="No page of music"):
        await run(db, box, pdf=FakePdf(count=2, staves={1: False, 2: False}))
    assert box.runs == []


async def test_a_long_book_is_refused_before_the_box_unless_a_page_set_is_chosen():
    db, box = pdf_book(), FakeBox()
    with pytest.raises(RuntimeError, match="at most 40"):
        await run(db, box, pdf=FakePdf(count=41))
    assert box.runs == []
    out, _ = await run(db, box, payload={"pages": [3]}, pdf=FakePdf(count=49))
    assert out["pages"] == [3]


async def test_a_chosen_page_set_is_sorted_too():
    db, box = pdf_book(), FakeBox()
    out, _ = await run(db, box, payload={"pages": [2, 3]}, pdf=FakePdf())
    assert out["page_kinds"] == [(2, "contents"), (3, "music")] and box.runs[0][2] == [3] and out["cover"] is None
    assert db.rows["scores"][0].get("pages") is None                                 # a subset says nothing about the book's length


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
    assert out["spark_skipped"] >= 1 and len(ctx.charges) == 1 and out["bars"] == 2    # the first call is always allowed
    assert out["page_kinds"] == [(1, "cover"), (2, "contents"), (3, "music")]        # page 3 unasked: a page with staves is music
    assert out["front_matter"]["read"] is False and out["items"]["systems_answered"] == 0 and out["verify"]["asked"] == 0
    xml = db.storage.files[digital_path(SCORE)]
    assert b"dolc" in xml and b"<sf" in xml                                           # Audiveris's reading kept


@pytest.mark.parametrize("box,calls", [(FakeBox(online=False), 0), (FakeBox(drop_out=True), 2)])
async def test_offline_box_fails_with_the_reason_and_no_charge(box, calls):
    """An unreachable box is found before any model call; a box that drops out mid-run has cost only the page questions."""
    db, client = pdf_book(), fake_client()
    j = job()
    ctx = StoreCtx(j, db, {})
    with pytest.raises(EngineOffline, match=OFFLINE):
        await omr_convert(j, ctx, box=box, client=client, model="muse-spark-1.3", pdf_pages=FakePdf())
    assert ctx.result["reason"] == OFFLINE and len(ctx.charges) == calls and len(client.messages.calls) == calls
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
