"""The post-write MusicXML pass (`musicxml_fix`, feature 005): voices numbered per staff, Audiveris's page layout and
title and composer credits carried, never "Music21". No network."""
from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter

from music21 import converter, stream

from app.librarian.musicxml_fix import PageLayout, fix_musicxml, renumber_voices
from app.librarian.omr_convert import write_musicxml


def n(step: str, octave: int, dur: int, voice: int, staff: int) -> str:
    return (f"<note><pitch><step>{step}</step><octave>{octave}</octave></pitch><duration>{dur}</duration>"
            f"<voice>{voice}</voice><type>quarter</type><staff>{staff}</staff></note>")


ATTRS = ("<attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time><staves>2</staves>"
         "<clef number=\"1\"><sign>G</sign><line>2</line></clef><clef number=\"2\"><sign>F</sign><line>4</line></clef></attributes>")
# What music21's merge writes: bar 1 has voice 1 upper and voice 2 lower; bar 2 flips them (voice 1 is the bass, voice 2
# the treble, with one cross-staff note of the treble voice on the lower staff), as on the Chopin and Goldberg pages.
FLIPPED = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">
<score-partwise version="4.0"><work><work-title /></work><movement-title>Music21 Fragment</movement-title>
<identification><creator type="composer">Music21</creator></identification>
<defaults><scaling><millimeters>7</millimeters><tenths>40</tenths></scaling></defaults>
<part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
<part id="P1">
<measure number="1">{ATTRS}{n("C", 5, 4, 1, 1)}<backup><duration>4</duration></backup>{n("C", 3, 4, 2, 2)}</measure>
<measure number="2"><print new-system="yes" />{n("C", 2, 4, 1, 2)}<backup><duration>4</duration></backup>
{n("E", 5, 1, 2, 1)}{n("F", 5, 1, 2, 1)}{n("G", 3, 1, 2, 2)}<forward><duration>1</duration><voice>2</voice><staff>1</staff></forward></measure>
<measure number="3"><print new-page="yes" />{n("D", 5, 4, 1, 1)}<backup><duration>4</duration></backup>{n("D", 3, 4, 2, 2)}</measure>
</part></score-partwise>""".encode()

AUDIVERIS = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0.3"><movement-title>Aria con Variazioni.</movement-title>
<identification><creator type="composer">S. Bach.</creator></identification>
<defaults><scaling><millimeters>6.7733</millimeters><tenths>40</tenths></scaling>
<page-layout><page-height>1783</page-height><page-width>1434</page-width><page-margins type="both"><left-margin>80</left-margin>
<right-margin>80</right-margin><top-margin>80</top-margin><bottom-margin>80</bottom-margin></page-margins></page-layout></defaults>
<credit page="1"><credit-words default-x="934" default-y="1642" font-size="8">4</credit-words></credit>
<credit page="1"><credit-words default-x="458" default-y="1598" font-family="serif" font-size="27">Aria con Variazioni.</credit-words></credit>
<credit page="1"><credit-words default-x="478" default-y="1528" font-size="5">i</credit-words></credit>
<credit page="1"><credit-type>composer</credit-type><credit-words default-x="1182" default-y="1554" font-size="11">S. Bach.</credit-words></credit>
<credit page="1"><credit-words default-x="1125" default-y="1274" font-size="8">'*</credit-words></credit>
<credit page="1"><credit-words default-x="1034" default-y="962" font-size="8">p</credit-words></credit>
<credit page="1"><credit-words default-x="780" default-y="386" font-size="11">4 2</credit-words></credit>
<credit page="1"><credit-words default-x="126" default-y="110" font-size="14">PWM-9386</credit-words></credit>
<part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
<part id="P1"><measure number="1">{m1}</measure></part></score-partwise>""".replace("{m1}", ATTRS + n("C", 5, 4, 1, 1) + n("C", 3, 4, 5, 2)).encode()


def notes(data: bytes) -> list[tuple]:
    """Every note as (bar, pitch, octave, duration, staff): what the fix must not touch."""
    root = ET.fromstring(data)
    return [(m.get("number"), x.findtext("pitch/step"), x.findtext("pitch/octave"), x.findtext("duration"), x.findtext("staff"))
            for m in root.iter("measure") for x in m.findall("note")]


def staves_of_voices(data: bytes) -> tuple[dict[str, set[str]], list[tuple[str, str, str]]]:
    """Per voice, the staves it is the majority voice of a bar on; and every minority (cross-staff) note."""
    home: dict[str, set[str]] = {}
    cross = []
    for m in ET.fromstring(data).iter("measure"):
        per: dict[str, Counter] = {}
        for x in m.findall("note"):
            per.setdefault(x.findtext("voice"), Counter())[x.findtext("staff")] += 1
        for v, c in per.items():
            (main, _), *rest = c.most_common()
            home.setdefault(v, set()).add(main)
            cross += [(m.get("number"), v, s) for s, _ in rest]
    return home, cross


def test_the_flipped_file_has_a_voice_on_both_staves():
    home, _ = staves_of_voices(FLIPPED)
    assert home["1"] == {"1", "2"} and home["2"] == {"1", "2"}


def test_voices_are_numbered_per_staff_and_the_notes_are_untouched():
    out = fix_musicxml(FLIPPED)
    home, cross = staves_of_voices(out)
    assert home == {"1": {"1"}, "5": {"2"}}                    # staff 1: voices 1-4, staff 2: voices 5-8
    assert cross == [("2", "1", "2")]                          # the treble voice's one note on the lower staff keeps it
    assert notes(out) == notes(FLIPPED) and len(notes(out)) == 8
    fw = ET.fromstring(out).find(".//measure[@number='2']/forward")
    assert fw.findtext("voice") == "1"                         # a <forward> follows its voice
    assert b'new-system="yes"' in out and b'new-page="yes"' in out


def test_more_than_four_voices_on_a_staff_never_borrow_the_next_staffs_numbers():
    body = "".join(n("C", 5, 4, v, 1) + "<backup><duration>4</duration></backup>" for v in range(1, 6)) + n("C", 3, 4, 6, 2)
    root = ET.fromstring(f"<score-partwise><part id='P1'><measure number='1'>{ATTRS}{body}</measure></part></score-partwise>")
    renumber_voices(root)
    got = [(x.findtext("staff"), x.findtext("voice")) for x in root.iter("note")]
    assert got == [("1", "1"), ("1", "2"), ("1", "3"), ("1", "4"), ("1", "9"), ("2", "5")]


def test_defaults_and_the_title_and_composer_credits_are_carried():
    page = PageLayout.read(AUDIVERIS)
    assert page.text("title") == "Aria con Variazioni." and page.text("composer") == "S. Bach."
    out = fix_musicxml(FLIPPED, page)
    root = ET.fromstring(out)
    d = root.find("defaults")
    assert d.findtext("scaling/millimeters") == "6.7733" and d.findtext("page-layout/page-width") == "1434"
    assert d.findtext("page-layout/page-margins/left-margin") == "80"
    credits = [(c.findtext("credit-type"), c.findtext("credit-words"), c.find("credit-words").get("default-x")) for c in root.findall("credit")]
    assert credits == [("title", "Aria con Variazioni.", "458"), ("composer", "S. Bach.", "1182")]
    assert root.findtext("work/work-title") == "Aria con Variazioni." and root.findtext("movement-title") == "Aria con Variazioni."
    assert root.findtext("identification/creator[@type='composer']") == "S. Bach."
    assert b"Music21" not in out
    tags = [el.tag for el in root]
    assert tags.index("defaults") < tags.index("credit") < tags.index("part-list")   # MusicXML's order
    assert notes(out) == notes(FLIPPED)


def test_the_books_facts_win_over_the_credits_text_in_the_credits_place():
    out = fix_musicxml(FLIPPED, PageLayout.read(AUDIVERIS), title="Goldberg Variations", composer="J. S. Bach")
    root = ET.fromstring(out)
    assert [(c.findtext("credit-type"), c.findtext("credit-words")) for c in root.findall("credit")] == \
        [("title", "Goldberg Variations"), ("composer", "J. S. Bach")]
    assert root.find("credit/credit-words").get("default-y") == "1598"
    assert root.findtext("identification/creator[@type='composer']") == "J. S. Bach"
    assert fix_musicxml(out, PageLayout.read(out), title="Goldberg Variations", composer="J. S. Bach") == out   # idempotent


def test_a_missing_credit_is_placed_on_the_page_and_none_is_invented_without_text():
    chopin = AUDIVERIS.replace(b"Aria con Variazioni.</credit-words>", b"</credit-words>")    # only the composer credit is real
    page = PageLayout.read(chopin)
    assert set(page.credits) == {"composer"}
    root = ET.fromstring(fix_musicxml(FLIPPED, page, title="Polonaise Op. 40 No. 1", composer="F. Chopin"))
    t = root.find("credit/credit-words")
    assert root.findtext("credit/credit-type") == "title" and t.text == "Polonaise Op. 40 No. 1"
    assert (t.get("default-x"), t.get("justify")) == ("717", "center")                      # centred on the 1434 page
    root = ET.fromstring(fix_musicxml(FLIPPED, PageLayout()))
    assert root.find("credit") is None and root.find("identification/creator") is None
    assert root.find("work") is None and root.find("movement-title") is None


def mxl(xml: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("META-INF/container.xml", '<container><rootfiles><rootfile full-path="score.xml"/></rootfiles></container>')
        z.writestr("score.xml", xml)
    return buf.getvalue()


def test_write_musicxml_fixes_a_merged_score_and_never_writes_music21(tmp_path):
    (tmp_path / "a.mxl").write_bytes(mxl(FLIPPED))
    page = PageLayout.read(tmp_path / "a.mxl")                 # an .mxl, as Audiveris writes it
    src = converter.parse(FLIPPED, format="musicxml")
    sc = stream.Score()                                        # a new score, as the merge builds it: no metadata
    for p in src.parts:
        sc.insert(0, p)
    out = write_musicxml(sc, page)
    assert b"Music21" not in out and b"music21 Fragment" not in out.lower()
    home, _ = staves_of_voices(out)
    assert all(len(s) == 1 for s in home.values())
    assert sorted(x[1:3] for x in notes(out)) == sorted(x[1:3] for x in notes(FLIPPED))
    assert b'new-system="yes"' in out and b'new-page="yes"' in out
    assert b"Music21" not in write_musicxml(sc)
