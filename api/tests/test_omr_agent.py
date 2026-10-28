"""Librarian agent v2 (feature 005), the parts that need no box and no model: the normalisers of Spark's answers, the
page-kind walk with a fake model, the crop padding, and the writers (`omr_enrich`) on a small score."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from music21 import articulations, chord, converter, dynamics, expressions, stream, tempo

from app.librarian import Job
from app.librarian.omr_agent import (Budget, Cropper, PAGE_KIND_SYSTEM, normalize_front, normalize_items, normalize_kind,
                                     page_kinds)
from app.librarian.omr_enrich import apply_front, apply_items, apply_verify, note_slots
from tests.test_part_cut import Ctx, FakeDB


def test_normalize_kind_accepts_the_four_kinds_and_their_aliases():
    assert normalize_kind({"kind": "music", "confidence": "high"}) == ("music", "high")
    assert normalize_kind({"kind": "Thematic index"}) == ("contents", None)
    assert normalize_kind({"kind": "title page"}) == ("cover", None)
    assert normalize_kind({"kind": "poem"}) == (None, None) and normalize_kind(None) == (None, None)


def test_normalize_front_fills_the_fixed_form():
    form = normalize_front({"title": " Aria con Variazioni. ", "composer": "null", "metronome": {"unit": "Crotchet", "bpm": "72."},
                            "opus": "BWV 988", "editor": None, "extra": "ignored"})
    assert form == {"title": "Aria con Variazioni.", "composer": None, "movement_or_number": None, "tempo_heading": None,
                    "metronome": {"unit": "quarter", "bpm": 72}, "opus": "BWV 988", "dedication": None, "editor": None}
    assert normalize_front({"metronome": {"unit": "quarter", "bpm": 900}})["metronome"] is None
    assert normalize_front({"metronome": {"unit": "dotted-quarter", "bpm": 60}})["metronome"] == {"unit": "dotted-quarter", "bpm": 60}
    assert normalize_front("garbage") == {k: None for k in ("title", "composer", "movement_or_number", "tempo_heading", "metronome", "opus", "dedication", "editor")}


def test_normalize_items_keeps_the_five_kinds_anchored_in_the_system():
    raw = [{"kind": "dynamics", "text": "mf", "bar": 3, "staff": 1, "note": 2},
           {"kind": "dynamic", "text": "cresc.", "bar": 3, "staff": 2, "note": 1},     # a word called a dynamic
           {"kind": "words", "text": "f", "bar": 4, "staff": 1, "note": 1},            # a dynamic called a word
           {"kind": "fingering", "text": "5 2", "bar": 4, "staff": 1, "note": 3},
           {"kind": "fingering", "text": "x", "bar": 4, "staff": 1, "note": 3},
           {"kind": "pedal", "text": "Ped.", "bar": 3, "staff": 2, "note": 1}, {"kind": "pedal", "text": "*", "bar": 4, "staff": 2, "note": 2},
           {"kind": "ornament", "text": "tr", "bar": 4, "staff": 1, "note": 1}, {"kind": "ornament", "text": "wiggle", "bar": 4, "staff": 1, "note": 1},
           {"kind": "words", "text": "dolce", "bar": 9, "staff": 1, "note": 1},         # not in this system
           {"kind": "words", "text": "legato", "bar": 3, "staff": 7, "note": "2"},      # staff clamped, note from a string
           "nonsense"]
    items, dropped = normalize_items(raw, [3, 4], 2)
    assert [(i["kind"], i["text"], i["number"], i["staff"], i["note"]) for i in items] == [
        ("dynamic", "mf", 3, 1, 2), ("words", "cresc.", 3, 2, 1), ("dynamic", "f", 4, 1, 1), ("fingering", "5 2", 4, 1, 3),
        ("pedal", "start", 3, 2, 1), ("pedal", "stop", 4, 2, 2), ("ornament", "trill", 4, 1, 1), ("words", "legato", 3, 2, 2)]
    assert [d["why"][:12] for d in dropped] == ["fingering 'x", "ornament 'wi", "bar 9 is not", "not an objec"]


class KindModel:
    def __init__(self, answers: list[str]):
        self.answers, self.calls = list(answers), []

    async def create(self, **kw):
        self.calls.append(kw["messages"][0]["content"][-1]["text"])
        assert kw["system"] == PAGE_KIND_SYSTEM
        kind = self.answers.pop(0)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps({"kind": kind, "confidence": "high"}))],
                               stop_reason="end_turn", model="muse-spark-1.3", usage=SimpleNamespace(input_tokens=800, output_tokens=100))


class Pdf:
    def __init__(self, staves: list[bool]):
        self.staves = staves

    @property
    def count(self):
        return len(self.staves)

    def png(self, page):
        return b"png"

    def has_staves(self, page):
        return self.staves[page - 1]


def ctx():
    j = Job("j", "omr_convert", {"score_id": "s"}, None, "u1", 1, 1)
    return Ctx(j, FakeDB(), {})


async def test_page_kinds_asks_until_the_first_page_of_music():
    model = KindModel(["contents", "music"])
    budget = Budget(1.0)
    out = await page_kinds(ctx(), SimpleNamespace(messages=model), "muse-spark-1.3", Pdf([False, True, True, True, True]), None, budget)
    assert [(r["pdf_page"], r["kind"], r["asked"]) for r in out] == [(1, "cover", False), (2, "contents", True), (3, "music", True),
                                                                      (4, "music", False), (5, "music", False)]
    assert len(model.calls) == 2 and "page 2 " in model.calls[0] and budget.per_page == {2: pytest.approx(0.001425), 3: pytest.approx(0.001425)}
    assert budget.summary()["per_step"] == {"page_kind": pytest.approx(0.00285, abs=1e-4)}


async def test_page_kinds_gives_up_asking_after_the_cap_and_without_budget():
    model = KindModel(["preface"] * 2)
    out = await page_kinds(ctx(), SimpleNamespace(messages=model), "muse-spark-1.3", Pdf([True] * 4), None, Budget(1.0), max_asked=2)
    assert [r["kind"] for r in out] == ["preface", "preface", "music", "music"] and len(model.calls) == 2
    model = KindModel([])
    out = await page_kinds(ctx(), SimpleNamespace(messages=model), "muse-spark-1.3", Pdf([True, True]), [2], Budget(0.0))
    assert [(r["pdf_page"], r["kind"]) for r in out] == [(2, "music")] and model.calls == []


def test_crop_pads_stop_halfway_to_the_next_system():
    from PIL import Image
    doc = {"pages": [{"page": 1, "interline": 20}], "measures": [],
           "systems": [{"page": 1, "system": 1, "top": 400, "bottom": 600, "left": 100, "right": 900, "numbers": [1]},
                       {"page": 1, "system": 2, "top": 700, "bottom": 900, "left": 100, "right": 900, "numbers": [2]}]}
    c = Cropper(doc, 1, Image.new("L", (1000, 1400), 255))
    assert c.pads(1) == (160, 70) and c.pads(2) == (70, 140)      # 8 il above the first, 7 il below the last; (100/2 + 20) between
    im, crop = c.system_crop(1)
    assert crop == {"origin": [60, 240], "size": [860, 430]} and im.size == (860, 430)
    assert c.head_crop().size == (1000, 660)


XML = """<?xml version="1.0"?><score-partwise version="3.1"><part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
<part id="P1"><measure number="7"><attributes><divisions>2</divisions><time><beats>2</beats><beat-type>4</beat-type></time><staves>2</staves>
<clef number="1"><sign>G</sign><line>2</line></clef><clef number="2"><sign>F</sign><line>4</line></clef></attributes>
<note><grace/><pitch><step>B</step><octave>4</octave></pitch><voice>1</voice><type>eighth</type><staff>1</staff></note>
<note><pitch><step>C</step><octave>5</octave></pitch><duration>2</duration><voice>1</voice><type>quarter</type><staff>1</staff></note>
<note><pitch><step>E</step><octave>4</octave></pitch><duration>2</duration><voice>1</voice><type>quarter</type><staff>1</staff></note>
<note><chord/><pitch><step>G</step><octave>4</octave></pitch><duration>2</duration><voice>1</voice><type>quarter</type><staff>1</staff></note>
<backup><duration>4</duration></backup>
<note><rest/><duration>2</duration><voice>2</voice><type>quarter</type><staff>2</staff></note>
<note><pitch><step>C</step><octave>3</octave></pitch><duration>2</duration><voice>2</voice><type>quarter</type><staff>2</staff></note>
</measure></part></score-partwise>"""


def small_score() -> stream.Score:
    return converter.parse(XML, format="musicxml")


def test_note_slots_count_as_a_reader_does():
    sc = small_score()
    upper, lower = sc.parts
    assert [getattr(s, "nameWithOctave", "chord") if not isinstance(s, chord.Chord) else "chord" for s in note_slots(upper.measure(7))] == ["B4", "C5", "chord"]
    assert [s.nameWithOctave for s in note_slots(lower.measure(7))] == ["C3"]       # the rest is not counted


def doc_for(sc: stream.Score) -> dict:
    return {"systems": [{"page": 1, "system": 1, "staves": [{}, {}], "numbers": [7]}], "measures": [{"number": 7}]}


def test_items_land_on_the_counted_note_and_stacked_fingering_goes_top_down():
    sc = small_score()
    items = [{"kind": "fingering", "text": "5 1", "number": 7, "staff": 1, "note": 3},     # on the chord E4+G4: 5 on G4, 1 on E4
             {"kind": "fingering", "text": "2", "number": 7, "staff": 1, "note": 1},       # on the grace note
             {"kind": "dynamic", "text": "mf", "number": 7, "staff": 1, "note": 2},
             {"kind": "dynamic", "text": "mf", "number": 7, "staff": 2, "note": 1},        # seen again from the lower staff
             {"kind": "words", "text": "dolce", "number": 7, "staff": 1, "note": 2},
             {"kind": "ornament", "text": "mordent", "number": 7, "staff": 1, "note": 2},
             {"kind": "ornament", "text": "trill", "number": 7, "staff": 1, "note": 2},    # the note has one already
             {"kind": "fingering", "text": "4", "number": 7, "staff": 2, "note": 5},       # past the last note: skipped
             {"kind": "pedal", "text": "start", "number": 7, "staff": 2, "note": 1}]       # Ped. without *: to the end of the bar
    log, counts = apply_items(sc, doc_for(sc), [{"page": 1, "system": 1, "numbers": [7], "ok": True, "items": items, "dropped": [{}]}])
    upper, lower = sc.parts
    m = upper.measure(7)
    slots = note_slots(m)
    assert [a.fingerNumber for a in slots[0].articulations] == [2]
    ch = slots[2]
    assert [p.nameWithOctave for p in ch.pitches] == ["E4", "G4"] and [a.fingerNumber for a in ch.articulations] == [1, 5]
    assert [(d.value, d.getOffsetBySite(m), d.placement) for d in m.getElementsByClass(dynamics.Dynamic)] == [("mf", 0.0, "below")]
    assert [(t.content, t.style.fontStyle) for t in m.getElementsByClass(expressions.TextExpression)] == [("dolce", "italic")]
    assert [type(e).__name__ for e in slots[1].expressions] == ["Mordent"]
    assert counts == {"words": 1, "dynamic": 1, "fingering": 2, "pedal": 1, "ornament": 1, "duplicates": 2, "dropped": 1, "out_of_range": 1}
    pedal = lower.getElementsByClass(expressions.PedalMark)
    assert len(pedal) == 1 and pedal[0].getFirst().nameWithOctave == "C3"
    assert any(e["layer"] == "pedal" and "end of its bar" in e.get("what", "") for e in log)


def test_front_matter_writes_the_tempo_line_once_and_the_metadata():
    sc = small_score()
    upper = sc.parts[0]
    old = tempo.MetronomeMark(number=60)
    upper.measure(7).insert(0, old)                                                        # Audiveris's unchecked mark
    form = {"title": "Aria", "composer": "J. S. Bach", "movement_or_number": "Aria", "tempo_heading": "Andante",
            "metronome": {"unit": "dotted-quarter", "bpm": 50}, "opus": "BWV 988", "dedication": "To CK", "editor": "Ed"}
    log = apply_front(sc, form, 7, title="Goldberg Variations", composer="")
    marks = list(upper.measure(7).getElementsByClass(tempo.MetronomeMark))
    assert len(marks) == 1 and marks[0].text == "Andante" and marks[0].number == 50 and marks[0].referent.quarterLength == 1.5
    assert sc.metadata.title == "Goldberg Variations" and sc.metadata.composer == "J. S. Bach" and sc.metadata.movementName == "Aria"
    assert sc.metadata.opusNumber == "BWV 988" and [e["layer"] for e in log] == ["front-clear", "front"]
    sc2 = small_score()
    assert apply_front(sc2, {k: None for k in form}, 7, title="T") == [] and not sc2.parts[0].measure(7).getElementsByClass(tempo.MetronomeMark)


def test_verify_flags_accidentals_and_removes_false_ornaments():
    sc = small_score()
    upper = sc.parts[0]
    c5 = note_slots(upper.measure(7))[1]
    c5.expressions.append(expressions.Trill())
    answers = [{"inter": {"number": 7, "tag": "alter", "shape": "SHARP", "staff": 1}, "answer": {"verdict": "natural"}},
               {"inter": {"number": 7, "tag": "alter", "shape": "FLAT", "staff": 2}, "answer": {"verdict": "flat"}},
               {"inter": {"number": 7, "tag": "ornament", "shape": "TR", "staff": 1}, "answer": {"verdict": "fingering_digit", "value": "4"}},
               {"inter": {"number": 7, "tag": "ornament", "shape": "MORDENT", "staff": 1}, "answer": None}]
    log, flags = apply_verify(sc, answers)
    assert flags == {7: ["accidental: the engine read a sharp; Spark sees natural (not changed: the PDF is the truth)"]}
    assert c5.expressions == [] and c5.nameWithOctave == "C5"                                # the pitch is never touched
    assert [e["layer"] for e in log] == ["flag", "A"]
