"""Librarian agent v2 (feature 005), the parts that need no box and no model: the normalisers of Spark's answers, the
page-kind walk with a fake model, the crop padding, and the writers (`omr_enrich`) on a small score."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from music21 import converter, dynamics, expressions, stream, tempo

from app.librarian import Job
from app.librarian.omr_agent import Budget, Cropper, PAGE_KIND_SYSTEM, junk, normalize_front, normalize_kind, page_kinds, place
from app.librarian.omr_enrich import apply_front, apply_text, apply_verify
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


def test_junk_filter_keeps_text_and_drops_numbers_hairpins_and_specks():
    assert junk("cresc. poco a poco") is None and junk("p") is None and junk("dolce") is None and junk("rf") is None
    assert junk("07'880.") and junk("34") and junk("1 2 3") and junk("<") and junk(">") and junk("a") and junk(".") and junk("")


def test_place_writes_only_what_an_audiveris_glyph_confirms():
    ms = [{"number": 18, "px": [100, 0, 500, 100]}, {"number": 19, "px": [500, 0, 900, 100]}]
    staves, crop = [{"top": 20, "bottom": 80}], {"origin": [0, 0], "size": [1000, 100]}
    glyph = {"tag": "word", "value": "creso.", "bounds": [540, 85, 60, 10]}
    heads = [{"x": 560, "number": 19}]
    items = [{"text": "cresc.", "x": 520, "y": 900, "bar": 18},           # Spark's point left of the barline; the glyph is in 19
             {"text": "legato", "x": 150, "y": 900, "bar": 18},           # no glyph near: never added
             {"text": "p", "x": 560, "y": 900, "bar": 19},                # a dynamic on the same glyph: anchored to the head
             {"text": "<", "x": 300, "y": 900, "bar": 18}]
    placed, dropped = place(items, ms, staves, crop, [glyph], heads, interline=10)
    assert [(p["text"], p["kind"], p["number"], p["how"], p["label_agrees"]) for p in placed] == [
        ("cresc.", "words", 19, "glyph+x", False), ("p", "dynamic", 19, "glyph+head", True)]
    assert [d["why"][:18] for d in dropped] == ["no Audiveris text ", "a hairpin characte"]
    _, dropped = place([{"text": "Andante", "x": 520, "y": 900, "bar": 18}], ms, staves, crop, [glyph], heads, interline=10, exclude=("Andante.",))
    assert dropped[0]["why"].startswith("the tempo heading")


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


def test_crops_pad_four_interlines_and_the_head_reaches_the_page_top():
    from PIL import Image
    doc = {"pages": [{"page": 1, "interline": 20}], "measures": [],
           "systems": [{"page": 1, "system": 1, "top": 400, "bottom": 600, "left": 100, "right": 900, "numbers": [1]},
                       {"page": 1, "system": 2, "top": 700, "bottom": 900, "left": 100, "right": 900, "numbers": [2]}]}
    c = Cropper(doc, 1, Image.new("L", (1000, 1400), 255))
    im, crop = c.system_crop(1)
    assert crop == {"origin": [60, 320], "size": [860, 360]} and im.size == (860, 360)
    assert c.system_crop(2, labels=False)[0].size == (860, 360)
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


def doc_for(sc: stream.Score) -> dict:
    return {"systems": [{"page": 1, "system": 1, "staves": [{}, {}], "numbers": [7]}], "measures": [{"number": 7}]}


def test_text_lands_at_the_nearest_onset_and_reverts_cleanly():
    sc = small_score()
    upper, lower = sc.parts
    m = upper.measure(7)
    old = expressions.TextExpression("dolc")
    m.insert(1.0, old)                                                                 # Audiveris's reading
    placed = [{"text": "mf", "kind": "dynamic", "number": 7, "staff": 1, "placement": "below", "how": "glyph+head", "frac": 0.0, "glyph": "SF"},
              {"text": "mf", "kind": "dynamic", "number": 7, "staff": 2, "placement": "above", "how": "glyph+x", "frac": 0.0, "glyph": "SF"},
              {"text": "dolce", "kind": "words", "number": 7, "staff": 1, "placement": "below", "how": "glyph+x", "frac": 0.6, "glyph": "dolc"}]
    undos = {}
    log, counts = apply_text(sc, doc_for(sc), [{"page": 1, "system": 1, "numbers": [7], "ok": True, "placed": placed, "dropped": [{}, {}]}], undos)
    assert counts == {"words": 1, "dynamic": 1, "duplicates": 1, "dropped": 2, "systems": 1, "systems_answered": 1}
    assert [(d.value, d.getOffsetBySite(m), d.placement) for d in m.getElementsByClass(dynamics.Dynamic)] == [("mf", 0.0, "below")]
    assert [(t.content, t.style.fontStyle, t.getOffsetBySite(m)) for t in m.getElementsByClass(expressions.TextExpression)] == [("dolce", "italic", 1.0)]
    assert sorted(undos) == [7] and len(undos[7].added) == 2 and len(undos[7].removed) == 1
    undos[7].revert()
    assert not m.getElementsByClass(dynamics.Dynamic)
    assert [(t.content, t.getOffsetBySite(m)) for t in m.getElementsByClass(expressions.TextExpression)] == [("dolc", 1.0)]


def test_front_matter_writes_the_tempo_line_once_and_the_pages_own_title():
    sc = small_score()
    upper = sc.parts[0]
    old = tempo.MetronomeMark(number=60)
    upper.measure(7).insert(0, old)                                                        # Audiveris's unchecked mark
    form = {"title": "Aria", "composer": "J. S. Bach", "movement_or_number": "Aria", "tempo_heading": "Andante",
            "metronome": {"unit": "dotted-quarter", "bpm": 50}, "opus": "BWV 988", "dedication": "To CK", "editor": "Ed"}
    undos = {}
    log = apply_front(sc, form, 7, undos, credit_title="Aria con Variazioni.", credit_composer="S. Bach.")
    marks = list(upper.measure(7).getElementsByClass(tempo.MetronomeMark))
    assert len(marks) == 1 and marks[0].text == "Andante" and marks[0].number == 50 and marks[0].referent.quarterLength == 1.5
    assert sc.metadata.title == "Aria" and sc.metadata.composer == "J. S. Bach" and sc.metadata.movementName == "Aria"
    assert sc.metadata.opusNumber == "BWV 988" and [e["layer"] for e in log] == ["front-clear", "front"]
    undos[7].revert()
    assert list(upper.measure(7).getElementsByClass(tempo.MetronomeMark)) == [old]
    sc2 = small_score()
    assert apply_front(sc2, {k: None for k in form}, 7, {}, credit_title="Aria con Variazioni.") == []
    assert sc2.metadata.title == "Aria con Variazioni." and not sc2.parts[0].measure(7).getElementsByClass(tempo.MetronomeMark)


def test_verify_flags_accidentals_and_removes_false_ornaments():
    sc = small_score()
    upper = sc.parts[0]
    c5 = next(n for n in upper.measure(7).recurse().notes if n.nameWithOctave == "C5")
    c5.expressions.append(expressions.Trill())
    answers = [{"inter": {"number": 7, "tag": "alter", "shape": "SHARP", "staff": 1}, "answer": {"verdict": "natural"}},
               {"inter": {"number": 7, "tag": "alter", "shape": "FLAT", "staff": 2}, "answer": {"verdict": "flat"}},
               {"inter": {"number": 7, "tag": "ornament", "shape": "TR", "staff": 1}, "answer": {"verdict": "fingering_digit", "value": "4"}},
               {"inter": {"number": 7, "tag": "ornament", "shape": "MORDENT", "staff": 1}, "answer": None}]
    log, flags = apply_verify(sc, answers)
    assert flags == {7: ["accidental: the engine read a sharp; Spark sees natural (not changed: the PDF is the truth)"]}
    assert c5.expressions == [] and c5.nameWithOctave == "C5"                                # the pitch is never touched
    assert [e["layer"] for e in log] == ["flag", "A"]
