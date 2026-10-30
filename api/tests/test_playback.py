"""Play the parts (014): music21 writes one MIDI track per part and a bar map, at import and on Convert to Digital. No
model, no network: the fixture MusicXML in web/public/fixtures, a made-up score with meter and tempo changes, and the
fake database and bucket of test_part_split."""
from __future__ import annotations

import json

import pytest
from music21 import converter, meter, midi, note, stream, tempo
from music21.musicxml.m21ToXml import GeneralObjectExporter

from app.librarian import Job, playback
from app.librarian.import_musicxml import book_facts, import_musicxml
from tests.test_part_split import BACH, CHOPIN, FIXTURES, QUARTET, SCORE, StoreCtx, digital_book, parse

GOLDBERG = FIXTURES.parents[2] / "api/tests/fixtures/engrave/goldberg-aria-fixed.musicxml"
ALL = [QUARTET, BACH, CHOPIN]


def read_midi(data: bytes):
    mf = midi.MidiFile()
    mf.readstr(data)
    return mf


def track_name(mt) -> str | None:
    names = [e.data for e in mt.events if e.type == midi.MetaEvents.SEQUENCE_TRACK_NAME]
    return names[0].decode() if names else None


def note_ons(mt) -> list[tuple[int, int]]:
    """(absolute tick, pitch) of every sounding note-on in a track."""
    out, t = [], 0
    for e in mt.events:
        if isinstance(e, midi.DeltaTime):
            t += e.time
        elif e.type == midi.ChannelVoiceMessages.NOTE_ON and e.velocity:
            out.append((t, e.pitch))
    return out


@pytest.fixture(scope="module")
def built() -> dict[str, tuple]:
    out = {}
    for name in ALL:
        s = parse(name)
        out[name] = (s, *playback.build(s))
    s = converter.parse(GOLDBERG.read_bytes(), format="musicxml")
    out["goldberg"] = (s, *playback.build(s))
    return out


@pytest.mark.parametrize("name", ALL + ["goldberg"])
def test_one_track_per_part_named_as_the_book(built, name):
    s, data, bm = built[name]
    names = book_facts(s)["names"]
    mf = read_midi(data)
    assert len(mf.tracks) == 1 + len(names)                       # the conductor, then one track per part
    assert [track_name(t) for t in mf.tracks[1:]] == names == bm["parts"]
    assert all(note_ons(t) for t in mf.tracks[1:])                 # every part sounds
    assert bm["ppq"] == mf.ticksPerQuarterNote


@pytest.mark.parametrize("name", ALL + ["goldberg"])
def test_the_bar_map_covers_every_measure_in_order(built, name):
    s, _, bm = built[name]
    assert {b["bar"] for b in bm["bars"]} == set(book_facts(s)["numbers"])
    assert len({b["bar"] for b in bm["bars"]}) == len(bm["bars"])           # one entry per number
    numbers = [m.number for m in s.parts[0].getElementsByClass("Measure")]
    for a, b in zip(bm["bars"], bm["bars"][1:]):
        if len(numbers) == len(set(numbers)):
            assert b["at"] == pytest.approx(a["at"] + a["quarters"])        # each bar starts where the last one ended
        else:                                                                # a repeated number (Chopin's three bar 0s) keeps its first
            assert b["at"] >= a["at"] + a["quarters"] - 1e-6
    last = bm["bars"][-1]
    assert bm["quarters"] == pytest.approx(last["at"] + last["quarters"])
    json.dumps(bm)                                                           # stored as it is


@pytest.mark.parametrize("name", ALL + ["goldberg"])
def test_count_in_is_one_bar_of_the_meter(built, name):
    _, _, bm = built[name]
    for b in bm["bars"]:
        c = playback.count_in(bm, b["bar"])
        assert c["beats"] == int(c["meter"].split("/")[0])
        assert c["beat_quarters"] == pytest.approx(4 / int(c["meter"].split("/")[1]))


def test_the_quartet(built):
    s, data, bm = built[QUARTET]
    assert bm["parts"] == ["Violin I", "Violin II", "Viola", "Cello"] and len(bm["bars"]) == 313
    assert bm["bars"][0] == {"bar": 1, "at": 0.0, "quarters": 3.0} and bm["bars"][-1]["bar"] == 313
    assert bm["meters"] == [{"bar": 1, "at": 0.0, "meter": "3/4", "beats": 3, "beat_quarters": 1.0}]
    # One metronome mark, 132 to the quarter; music21's own "allegro" for a bare mark is not printed text.
    assert bm["tempos"] == [{"bar": 1, "at": 0.0, "qpm": 132.0, "bpm": 132.0, "beat": "quarter", "text": None, "marked": True}]
    assert playback.count_in(bm, 115) == {"meter": "3/4", "beats": 3, "beat_quarters": 1.0, "quarters": 3.0}
    # Repeats are not expanded: the file is as long as the bars printed once.
    mf = read_midi(data)
    last = max(t for tr in mf.tracks[1:] for t, _ in note_ons(tr))
    assert last < bm["quarters"] * bm["ppq"]
    # Bar 1's first note in Violin I sits at tick 0; every onset falls inside the printed bars.
    assert note_ons(mf.tracks[1])[0][0] == 0


def test_a_piano_is_one_track_with_both_staves(built):
    s, data, bm = built[CHOPIN]
    mf = read_midi(data)
    assert bm["parts"] == ["Piano"] and len(mf.tracks) == 2
    pitches = {p for _, p in note_ons(mf.tracks[1])}
    assert min(pitches) < 48 < 72 < max(pitches)                   # the left hand and the right hand
    staves = sum(len([n for n in p.flatten().notes if not n.duration.isGrace]) for p in s.parts)
    assert len(note_ons(mf.tracks[1])) <= sum(len(n.pitches) for p in s.parts for n in p.flatten().notes)
    assert staves > 0


def test_a_pickup_bar_counts_in_a_whole_bar(built):
    _, _, bm = built[BACH]
    assert bm["bars"][0] == {"bar": 0, "at": 0.0, "quarters": 1.0}
    assert playback.count_in(bm, 0)["quarters"] == 4.0             # one full 4/4 bar before the upbeat
    assert bm["tempos"][0]["marked"] is False and bm["tempos"][0]["qpm"] == 120.0   # the chorale prints no tempo


@pytest.fixture(scope="module")
def changes() -> dict:
    """Eight bars: 3/4 at quarter = 100 for four bars, then 6/8 at dotted quarter = 60 from bar 5."""
    p = stream.Part()
    p.partName = "Flute"
    for n in range(1, 9):
        m = stream.Measure(number=n)
        if n == 1:
            m.append([meter.TimeSignature("3/4"), tempo.MetronomeMark(number=100)])
        if n == 5:
            m.append([meter.TimeSignature("6/8"), tempo.MetronomeMark(number=60, referent=note.Note(type="quarter", dots=1).duration)])
        m.append(note.Note("C5", quarterLength=3))
        p.append(m)
    sc = stream.Score([p])
    back = converter.parse(GeneralObjectExporter(sc).parse(), format="musicxml")
    return playback.build(back)[1]


def test_meter_and_tempo_changes_with_their_bars(changes):
    bm = changes
    assert [(m["bar"], m["meter"], m["beats"], m["beat_quarters"]) for m in bm["meters"]] == [(1, "3/4", 3, 1.0), (5, "6/8", 6, 0.5)]
    assert [(t["bar"], t["at"], t["qpm"], t["bpm"], t["beat"]) for t in bm["tempos"]] == [(1, 0.0, 100.0, 100.0, "quarter"), (5, 12.0, 90.0, 60.0, "dotted quarter")]
    assert playback.count_in(bm, 4)["beats"] == 3 and playback.count_in(bm, 5) == {"meter": "6/8", "beats": 6, "beat_quarters": 0.5, "quarters": 3.0}


async def test_import_stores_the_midi_and_bar_map_and_records_them():
    db = digital_book()
    j = Job("j1", "import_musicxml", {"score_id": SCORE, "source_id": "x1"}, SCORE, "u1", 1, 3)
    out = await import_musicxml(j, StoreCtx(j, db, {}))
    mkey, bkey = f"{SCORE}/playback/score.mid", f"{SCORE}/playback/bars.json"
    assert out["playback"]["ok"] and out["playback"]["tracks"] == 4 and out["playback"]["bars"] == 313
    assert db.storage.types[mkey] == "audio/midi" and db.storage.types[bkey] == "application/json"
    assert db.storage.files[mkey].startswith(b"MThd")
    bm = json.loads(db.storage.files[bkey])
    assert bm["parts"] == ["Violin I", "Violin II", "Viola", "Cello"] and len(bm["bars"]) == 313
    rec = db.rows["scores"][0]["playback"]
    assert {k: rec[k] for k in ("midi", "bar_map", "source_id", "parts", "bars")} == {
        "midi": mkey, "bar_map": bkey, "source_id": "x1", "parts": bm["parts"], "bars": 313}
    assert db.rows["scores"][0]["status"] == "ready"


async def test_a_book_whose_midi_fails_is_still_ready(monkeypatch):
    def boom(_s):
        raise ValueError("no notes")
    monkeypatch.setattr(playback, "build", boom)
    db = digital_book(BACH)
    j = Job("j1", "import_musicxml", {"score_id": SCORE, "source_id": "x1"}, SCORE, "u1", 1, 3)
    out = await import_musicxml(j, StoreCtx(j, db, {}))
    assert out["playback"] == {"ok": False, "reason": "ValueError: no notes"}
    assert db.rows["scores"][0]["status"] == "ready" and "playback" not in db.rows["scores"][0]
    assert not [k for k in db.storage.files if "/playback/" in k]
