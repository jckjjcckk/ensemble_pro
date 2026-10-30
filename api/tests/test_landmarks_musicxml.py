"""Digital books' landmarks (013 v4e part a): music21 on the MusicXML, no model call."""
from __future__ import annotations

from pathlib import Path

import pytest
from music21 import bar, converter, expressions, key, meter, note, repeat, stream, tempo
from music21.musicxml.m21ToXml import GeneralObjectExporter

from app.librarian.import_musicxml import book_facts
from app.librarian.landmarks import from_musicxml
from app.librarian.voice_prompt import landmark_lines

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "web/public/fixtures"


def marks(path: Path) -> list[tuple]:
    return [(d["kind"], d["label"], d["bar"], d["bar_after"]) for d in from_musicxml(converter.parse(str(path)))]


def test_beethoven_op18_no1_has_its_exposition_repeat_and_nothing_invented():
    """The fixture prints one metronome mark (no tempo word: music21's own "allegro" is not printed), the
    exposition's end repeat after bar 114 and the final barline; only the repeat is a landmark."""
    assert marks(FIXTURES / "beethoven-op18no1-mv1.musicxml") == [("repeat", "end repeat", 114, 115)]


def test_the_other_fixtures():
    assert marks(FIXTURES / "bach-bwv66-6.musicxml") == []                      # a chorale: final barline only
    chopin = marks(FIXTURES / "piano-chopin-mazurka06-2.musicxml")
    assert ("repeat", "end repeat", 16, None) in chopin and ("repeat", "end repeat", 32, None) in chopin
    assert all(k == "repeat" for k, *_ in chopin)
    aria = marks(ROOT / "api/tests/fixtures/engrave/goldberg-aria-fixed.musicxml")
    assert aria == [("repeat", "end repeat", 16, 17), ("repeat", "start repeat", 17, None), ("repeat", "end repeat", 32, None)]


def test_book_facts_carries_the_landmarks():
    f = book_facts(converter.parse(str(FIXTURES / "beethoven-op18no1-mv1.musicxml")))
    assert [d["bar"] for d in f["landmarks"]] == [114] and f["landmarks"][0]["source"] == "musicxml"


@pytest.fixture(scope="module")
def made_up() -> list[dict]:
    """A 16-bar part with every kind printed once, written to MusicXML and read back the way an import reads it."""
    p = stream.Part()
    p.partName = "Violin"
    for n in range(1, 17):
        m = stream.Measure(number=n)
        if n == 1:
            m.append([key.KeySignature(0), meter.TimeSignature("4/4"), tempo.MetronomeMark(text="Allegro", number=120)])
        m.append(note.Note("C4", quarterLength=4 if n < 13 else 3))
        p.append(m)
    ms = {m.number: m for m in p.getElementsByClass("Measure")}
    ms[3].insert(0, repeat.Segno())
    ms[4].insert(0, expressions.RehearsalMark("A"))
    ms[4].insert(0, expressions.TextExpression("dolce"))                     # not a place
    ms[5].insert(0, tempo.MetronomeMark(text="Adagio", number=60))
    ms[6].insert(0, expressions.TextExpression("cresc."))                    # not a place
    ms[7].insert(0, expressions.TextExpression("Tempo primo"))
    ms[8].rightBarline = bar.Barline("double")
    ms[9].insert(0, key.KeySignature(-3))
    ms[10].insert(0, expressions.TextExpression("Trio"))
    ms[10].leftBarline = bar.Repeat(direction="start")
    ms[11].rightBarline = bar.Repeat(direction="end")
    ms[12].insert(0, expressions.TextExpression("To Coda"))
    ms[13].insert(0, meter.TimeSignature("3/4"))
    ms[13].insert(0, tempo.MetronomeMark(number=96))                         # a bare metronome change
    ms[14].insert(0, expressions.TextExpression("D.C. al Fine"))
    ms[15].insert(0, repeat.Coda())
    ms[16].rightBarline = bar.Barline("final")
    s = stream.Score([p])
    xml = GeneralObjectExporter(s).parse()
    return from_musicxml(converter.parse(xml, format="musicxml"))


def test_every_kind_is_read_at_its_bar(made_up):
    got = {(d["kind"], d["label"], d["bar"], d["bar_after"]) for d in made_up}
    assert got == {
        ("tempo", "Allegro", 1, None), ("segno", "segno", 3, None), ("rehearsal", "A", 4, None),
        ("tempo", "Adagio", 5, None), ("tempo", "Tempo primo", 7, None), ("double_bar", "double bar", 8, 9),
        ("key_change", "3 flats", 9, None), ("section", "Trio", 10, None), ("repeat", "start repeat", 10, None),
        ("repeat", "end repeat", 11, 12), ("coda", "To Coda", 12, None), ("meter_change", "3/4", 13, None),
        ("tempo", "quarter = 96", 13, None), ("fine", "D.C. al Fine", 14, None), ("coda", "Coda", 15, None),
    }, got


def test_the_made_up_book_as_the_facts_say_it(made_up):
    lines = landmark_lines(made_up, 16)
    assert "double bar between bars 8 and 9" in lines and "end repeat between bars 11 and 12" in lines
    assert "Adagio bars 5-6" in lines and "Tempo primo bars 7-12" in lines and "coda bars 15-16" in lines
    assert "key change at bar 9 (3 flats)" in lines and "To Coda at bar 12" in lines
    assert not any("dolce" in x or "cresc" in x or x.startswith("letter") for x in lines)
