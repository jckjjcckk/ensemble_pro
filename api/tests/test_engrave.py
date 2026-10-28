"""Engraving (005, 010) against a fake MuseScore box: no ssh, no network. The fake engraver writes what MuseScore
leaves on the real one (`p-1.svg`, `p-2.svg`, `p.mpos`); the `.mpos` sample is the real one MuseScore wrote for the
Goldberg Aria (`experiments/engrave/goldberg/same-file/F-musescore-fixed.mpos`, 32 bars on two pages)."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from app.librarian import Job
from app.librarian.engrave import (DEFAULT_LAYOUT, DISPLAY_STYLE, KIND, LAYOUTS, OFFLINE, EngraverFailed, EngraverOffline, SshEngraver,
                                   bar_boxes, book_notation, display_copy, engrave, engrave_step, measure_numbers, page_key, parse_mpos,
                                   svg_size, svg_size_mm)
from app.librarian.import_musicxml import import_musicxml
from tests.test_part_split import FIXTURES, QUARTET, StoreCtx, StoreDB, digital_book, SCORE

HERE = Path(__file__).resolve().parent
GOLDBERG = HERE.parent / "experiments" / "engrave" / "goldberg" / "same-file"
MPOS = (GOLDBERG / "F-musescore-fixed.mpos").read_text()
GOLD_XML = (GOLDBERG / "F-input.musicxml").read_bytes()
# The page MuseScore wrote for that file: Audiveris's 1434 x 1783 tenths at 6.7733 mm / 40 tenths, in 1200 dpi units.
GOLD_SVG = (11471.9, 14263.9)


def svg(w: float, h: float, n: int = 1) -> bytes:
    return (f'<?xml version="1.0"?>\n<svg width="{w / 47.244:.3f}mm" height="{h / 47.244:.3f}mm" viewBox="0 0 {w} {h}" '
            f'xmlns="http://www.w3.org/2000/svg"><title>page {n}</title><polyline class="StaffLines" points="100,200 900,200"/></svg>').encode()


# ------------------------------------------------------------------------------------------------- the file

def test_display_copy_repages_for_the_ipad_and_drops_the_breaks():
    out = display_copy(GOLD_XML)
    root = ET.fromstring(out)
    pl = root.find("defaults/page-layout")
    # 210 x 280 mm in the file's own tenths (6.7733 mm per 40 tenths): the scaling is kept, so the staff size is the scan's.
    assert root.findtext("defaults/scaling/millimeters") == "6.7733"
    assert (pl.findtext("page-width"), pl.findtext("page-height")) == ("1240.2", "1653.6")
    assert float(pl.findtext("page-width")) / float(pl.findtext("page-height")) == pytest.approx(0.75, abs=1e-3)
    assert pl.find("page-margins").findtext("left-margin") == "70.9" and pl.find("page-margins").findtext("top-margin") == "82.7"
    assert b"new-system" not in out and b"new-page" not in out and b"<system-layout>" not in out
    assert root.find("defaults/lyric-font") is not None                     # the rest of the defaults stays
    assert b"new-system" in GOLD_XML and b"<system-layout>" in GOLD_XML     # and the original is untouched
    assert len(root.findall("part/measure")) == 32
    assert out.startswith(b'<?xml version="1.0" encoding="UTF-8"?>\n<score-partwise')


def test_display_copy_of_a_file_without_defaults_uses_music21s_scaling():
    xml = b'<score-partwise><part-list><score-part id="P1"><part-name>V</part-name></score-part></part-list><part id="P1"><measure number="1"><print new-page="yes"/><note><rest/><duration>4</duration></note></measure></part></score-partwise>'
    root = ET.fromstring(display_copy(xml))
    assert root.findtext("defaults/scaling/millimeters") == "7" and root.findtext("defaults/page-layout/page-width") == "1200.0"
    assert list(root).index(root.find("defaults")) < list(root).index(root.find("part-list"))
    assert root.find("part/measure/print") is None                          # an emptied <print> goes


def test_measure_numbers_follow_the_first_part():
    assert measure_numbers(GOLD_XML) == list(range(1, 33))
    assert measure_numbers((FIXTURES / QUARTET).read_bytes()) == list(range(1, 314))
    xml = b'<score-partwise><part id="P1"><measure number="0"/><measure number="1"/><measure number="X2"/><measure number="3"/></part></score-partwise>'
    assert measure_numbers(xml) == [0, 1, 2, 3]
    assert measure_numbers(b"<score-partwise/>") == []


# ------------------------------------------------------------------------------------------------- the positions

def test_mpos_parses_to_bar_boxes_as_page_fractions():
    pos = parse_mpos(MPOS)
    assert len(pos) == 32 and pos[0] == {"ordinal": 0, "page": 0, "x": 14896.9, "y": 24546.1, "w": 25870.8, "h": 16489.9}
    assert [p["page"] for p in pos].count(1) == 4                               # bars 29 to 32 on page 2
    boxes = bar_boxes(pos, list(range(1, 33)), [GOLD_SVG, GOLD_SVG])
    assert len(boxes) == 32
    n, page, x, y, w, h = boxes[0]
    # The first bar starts where the first staff line starts (x = 1241.4 of 11471.9) and under the title.
    assert (n, page) == (1, 1) and x == pytest.approx(1241.4 / 11471.9, abs=1e-4) and y == pytest.approx(0.1434, abs=1e-4)
    assert w == pytest.approx(25870.8 / 12 / 11471.9, abs=1e-4) and 0.09 < h < 0.11
    assert boxes[6][1:3] == [1, pytest.approx(7679.96 / 12 / 11471.9, abs=1e-4)]  # system 2 is not indented
    assert boxes[28][:2] == [29, 2]
    assert all(0 <= b[2] and b[2] + b[4] <= 1 and 0 <= b[3] and b[3] + b[5] <= 1 for b in boxes)
    # Systems: six on page 1 (1-6, 7-12, 13-16, 17-20, 21-24, 25-28), one on page 2, as the scan has them.
    rows = {}
    for b in boxes:
        rows.setdefault((b[1], b[3]), []).append(b[0])
    assert [v for v in rows.values()] == [[1, 2, 3, 4, 5, 6], [7, 8, 9, 10, 11, 12], [13, 14, 15, 16], [17, 18, 19, 20], [21, 22, 23, 24], [25, 26, 27, 28], [29, 30, 31, 32]]


def test_bar_boxes_skip_what_cannot_be_joined():
    pos = parse_mpos(MPOS)
    assert len(bar_boxes(pos, list(range(1, 31)), [GOLD_SVG, GOLD_SVG])) == 30     # two ordinals past the numbers
    assert len(bar_boxes(pos, list(range(1, 33)), [GOLD_SVG])) == 28               # no SVG for page 2
    assert [b[0] for b in bar_boxes(pos, [1, 1, 2] + list(range(3, 32)), [GOLD_SVG, GOLD_SVG])][:3] == [1, 2, 3]   # a repeated number keeps its first box


def test_svg_size_reads_the_viewbox():
    assert svg_size(svg(11471.9, 14263.9)) == (11471.9, 14263.9)
    assert svg_size_mm(svg(11471.9, 14263.9)) == pytest.approx((242.823, 301.92), abs=0.01)
    with pytest.raises(EngraverFailed):
        svg_size(b"<svg/>")


# ------------------------------------------------------------------------------------------------- the step

class FakeEngraver:
    """Leaves two pages and the Goldberg `.mpos` in `dest`; remembers what it was given."""

    def __init__(self, online: bool = True, fail: str | None = None):
        self.online, self.fail, self.runs = online, fail, []

    async def reachable(self) -> bool:
        return self.online

    async def engrave(self, run_id: str, layout: str, musicxml: bytes, style: bytes | None, dest: Path) -> dict:
        self.runs.append({"run_id": run_id, "layout": layout, "musicxml": musicxml, "style": style})
        if self.fail:
            raise EngraverFailed(self.fail)
        (dest / "p-1.svg").write_bytes(svg(*GOLD_SVG, 1))
        (dest / "p-2.svg").write_bytes(svg(*GOLD_SVG, 2))
        (dest / "p.mpos").write_text(MPOS)
        return {"seconds": 0.9}


def gold_book() -> StoreDB:
    path = f"{SCORE}/digital/score.musicxml"
    db = StoreDB({path: GOLD_XML})
    db.rows["scores"] = [{"id": SCORE, "owner_user_id": "u1", "ensemble_id": None, "title": "Aria", "status": "ready"}]
    db.rows["sources"] = [{"id": "pdf1", "score_id": SCORE, "kind": "pdf", "storage_paths": [f"{SCORE}/source.pdf"], "created_by": "u1", "meta": {}},
                          {"id": "split", "score_id": SCORE, "kind": "musicxml", "storage_paths": [f"{SCORE}/parts/x.musicxml"], "created_by": "u1", "meta": {"instruments": ["Piano"], "slug": "piano"}},
                          {"id": "mx1", "score_id": SCORE, "kind": "musicxml", "storage_paths": [path], "created_by": "u1", "meta": {"transcribed_from": "pdf1"}}]
    db.rows["parts"] = []
    return db


def ctx_for(db: StoreDB, kind: str = "engrave", payload: dict | None = None) -> StoreCtx:
    j = Job("job-7", kind, {"score_id": SCORE, **(payload or {})}, None, "u1", 1, 1)
    return StoreCtx(j, db, {})


def test_book_notation_prefers_the_transcription_and_never_a_split():
    db = gold_book()
    assert book_notation(db, SCORE)["id"] == "mx1"
    assert book_notation(db, SCORE, "split")["id"] == "split"          # asked for by id: given
    db.rows["sources"] = [r for r in db.rows["sources"] if r["id"] != "mx1"]
    assert book_notation(db, SCORE) is None
    assert book_notation(digital_book(), SCORE)["id"] == "x1"


async def test_step_engraves_both_layouts_and_records_a_row_each():
    db, box = gold_book(), FakeEngraver()
    ctx = ctx_for(db)
    out = await engrave_step(ctx, SCORE, box=box)
    assert out["ok"] and set(out["layouts"]) == set(LAYOUTS) == {"display", "original"} and DEFAULT_LAYOUT == "display"
    assert [r["layout"] for r in box.runs] == ["display", "original"] and all(r["run_id"] == "job-7-engrave" for r in box.runs)
    assert box.runs[0]["style"] == DISPLAY_STYLE and box.runs[1]["style"] is None
    assert b"new-system" not in box.runs[0]["musicxml"] and box.runs[1]["musicxml"] == GOLD_XML
    for layout in LAYOUTS:
        keys = [page_key(SCORE, layout, i) for i in (1, 2)]
        assert keys == [f"{SCORE}/digital/{layout}/p001.svg", f"{SCORE}/digital/{layout}/p002.svg"]
        assert all(db.storage.types[k] == "image/svg+xml" and db.storage.files[k].startswith(b"<?xml") for k in keys)
        row = next(r for r in db.rows["sources"] if r["kind"] == KIND and r["meta"]["layout"] == layout)
        assert row["storage_paths"] == keys and row["page_count"] == 2 and row["page_order"] == [1, 2] and row["created_by"] == "u1"
        m = row["meta"]
        assert m["source_id"] == "mx1" and m["engine"] == "musescore-4.7.5" and m["page_mm"] == [242.8, 301.9]
        assert len(m["bars"]) == 32 and m["bars"][0][:2] == [1, 1] and m["bars"][-1][:2] == [32, 2]
        assert out["layouts"][layout] == {"source_id": row["id"], "pages": 2, "bars": 32, "seconds": 0.9}
    assert ctx.result["engraving"] is out and "Engraving the pages" in ctx.result["note"]


async def test_rerun_replaces_the_pages_and_keeps_the_rows():
    db = gold_book()
    first = await engrave_step(ctx_for(db), SCORE, box=FakeEngraver())
    db.storage.files[page_key(SCORE, "display", 1)] = b"stale"
    again = await engrave_step(ctx_for(db), SCORE, box=FakeEngraver())
    assert again["layouts"]["display"]["source_id"] == first["layouts"]["display"]["source_id"]
    assert len([r for r in db.rows["sources"] if r["kind"] == KIND]) == 2
    assert db.storage.files[page_key(SCORE, "display", 1)] != b"stale"


@pytest.mark.parametrize("box, reason", [
    (FakeEngraver(online=False), OFFLINE),
    (FakeEngraver(fail="The engraving engine crashed on this file"), "The engraving engine crashed on this file"),
])
async def test_step_reports_a_plain_reason_and_never_raises(box, reason):
    db = gold_book()
    ctx = ctx_for(db)
    out = await engrave_step(ctx, SCORE, box=box)
    assert out == {"ok": False, "reason": reason, "seconds": out["seconds"]} and ctx.result["engraving"] == out
    assert not [r for r in db.rows["sources"] if r["kind"] == KIND] and not [k for k in db.storage.files if k.endswith(".svg")]


async def test_step_without_notation_or_switched_off(monkeypatch):
    db = gold_book()
    db.rows["sources"] = [db.rows["sources"][0]]
    out = await engrave_step(ctx_for(db), SCORE, box=FakeEngraver())
    assert out["reason"] == "This book has no notation file to engrave"
    monkeypatch.setenv("ENGRAVE", "off")
    out = await engrave_step(ctx_for(gold_book()), SCORE)                      # no engraver handed in: the real box, skipped
    assert "switched off" in out["reason"]


async def test_engrave_job_fails_with_the_reason():
    db = gold_book()
    ctx = ctx_for(db)
    out = await engrave(ctx.job, ctx, box=FakeEngraver())
    assert out["ok"] and ctx.result["note"] == "Engraved 2 pages"
    ctx = ctx_for(db)
    with pytest.raises(EngraverFailed, match=OFFLINE):
        await engrave(ctx.job, ctx, box=FakeEngraver(online=False))
    assert ctx.result["reason"] == OFFLINE


async def test_import_engraves_before_the_book_is_ready():
    db, box = digital_book(), FakeEngraver()
    j = Job("j1", "import_musicxml", {"score_id": SCORE, "source_id": "x1"}, SCORE, "u1", 1, 3)
    out = await import_musicxml(j, StoreCtx(j, db, {}), engraver=box)
    assert out["engraving"]["ok"] and [r["layout"] for r in box.runs] == ["display", "original"]
    assert db.rows["scores"][0]["status"] == "ready"
    rows = [r for r in db.rows["sources"] if r["kind"] == KIND]
    assert len(rows) == 2 and all(r["meta"]["source_id"] == "x1" for r in rows)
    # The fake positions name 32 bars; the quartet's numbers run to 313, so every ordinal joins a number.
    assert len(rows[0]["meta"]["bars"]) == 32
    # Switched off (the suite's default): the import still finishes, the reason on the result.
    db = digital_book()
    out = await import_musicxml(j, StoreCtx(j, db, {}))
    assert db.rows["scores"][0]["status"] == "ready" and out["engraving"]["ok"] is False and "switched off" in out["engraving"]["reason"]


# ------------------------------------------------------------------------------------------------- the box

async def test_ssh_engraver_reads_exit_255_as_offline(tmp_path, monkeypatch):
    from tests.test_omr_convert import fake_ssh
    monkeypatch.setenv("PATH", fake_ssh(tmp_path, 255))
    assert await SshEngraver(host="omr").reachable() is False
    with pytest.raises(EngraverOffline):
        await SshEngraver(host="omr").engrave("job-1", "display", b"<x/>", DISPLAY_STYLE, tmp_path)
    with pytest.raises(ValueError):
        await SshEngraver(host="omr").engrave("job 1", "display", b"<x/>", None, tmp_path)
    with pytest.raises(ValueError):
        await SshEngraver(host="omr").engrave("job-1", "pretty", b"<x/>", None, tmp_path)


def test_display_style_turns_vertical_justification_off():
    assert re.search(rb"<enableVerticalSpread>0</enableVerticalSpread>", DISPLAY_STYLE)
    assert re.search(rb"<lastSystemFillLimit>0</lastSystemFillLimit>", DISPLAY_STYLE)
    ET.fromstring(DISPLAY_STYLE)
