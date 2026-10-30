"""Play the parts (014): a digital book's MIDI and its bar map, written by music21 at import and at the end of Convert to
Digital. No model call; the browser synthesises and mixes (Tone.js), nothing is rendered to audio here.

Two files per book in the `scores` bucket, recorded on the score row (`scores.playback`, migration 20261030180000):

- `{score_id}/playback/score.mid`: a type-1 MIDI file. Track 0 is music21's conductor track (tempo and meter); then one
  track per part in score order, named with the book's own part names (`import_musicxml.part_groups`: "Violin I",
  "Cello", one "Piano" for a grand staff, both staves in one track). Ties are joined, grace notes left out, dynamics
  become velocities (music21 realises them). Repeats are NOT expanded: the file plays the bars as printed, once, so
  bar N always sits at one place in time and playback can start at any bar.
- `{score_id}/playback/bars.json`: where each bar starts, in quarter notes from the start of the file, and the tempo
  and meter changes with their bars:

      {"version": 1, "ppq": 10080, "parts": ["Violin I", ...], "quarters": 939.0,
       "bars": [{"bar": 1, "at": 0.0, "quarters": 3.0}, ...],             # one per measure number, in order
       "tempos": [{"bar": 1, "at": 0.0, "qpm": 132.0, "bpm": 132.0, "beat": "quarter", "text": null, "marked": true}],
       "meters": [{"bar": 1, "at": 0.0, "meter": "3/4", "beats": 3, "beat_quarters": 1.0}]}

  `qpm` is quarter notes per minute (what MIDI and the player's transport count in); `bpm` and `beat` are the printed
  mark ("dotted quarter = 60" is bpm 60, beat "dotted quarter", qpm 90). A book that prints no metronome mark gets one
  unmarked entry at 120 (`marked: false`). The count-in before a bar is one bar of the meter in force there:
  `beats` clicks of `beat_quarters` each (the meter's numerator and denominator, `count_in`).
"""
from __future__ import annotations

import asyncio
import copy
import json
import time
from typing import Any

from music21 import chord, instrument as m21instrument, meter as m21meter, note, stream, tempo as m21tempo
from music21.midi import DeltaTime, MetaEvents, MidiEvent, translate

MIDI_TYPE = "audio/midi"
JSON_TYPE = "application/json"
DEFAULT_QPM = 120.0


def midi_path(score_id: str) -> str:
    return f"{score_id}/playback/score.mid"


def bars_path(score_id: str) -> str:
    return f"{score_id}/playback/bars.json"


def _first_part(s: stream.Score) -> stream.Part:
    return s.parts[0]


def bar_list(s: stream.Score) -> list[dict[str, Any]]:
    """One entry per measure number (the first time it appears), in the order printed: where it starts and how long
    it is, in quarter notes. A second ending that reuses a number keeps the first."""
    p0 = _first_part(s)
    measures = list(p0.getElementsByClass(stream.Measure))
    starts = [float(m.getOffsetBySite(p0)) for m in measures]
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for i, m in enumerate(measures):
        if m.number in seen:
            continue
        seen.add(m.number)
        # A bar lasts until the next one starts (an overfull Audiveris bar can be longer than its meter).
        length = (starts[i + 1] - starts[i]) if i + 1 < len(measures) else float(m.duration.quarterLength)
        out.append({"bar": int(m.number), "at": round(starts[i], 6), "quarters": round(length, 6)})
    return out


def _bar_at(bars: list[dict[str, Any]], at: float) -> int:
    """The bar that holds quarter offset `at` (the last bar starting at or before it)."""
    hit = bars[0]["bar"] if bars else 1
    for b in bars:
        if b["at"] <= at + 1e-6:
            hit = b["bar"]
        else:
            break
    return hit


def _beat_name(mm: m21tempo.MetronomeMark) -> str:
    try:
        return mm.referent.fullName.lower().replace(" note", "")
    except Exception:  # noqa: BLE001
        return "quarter"


def tempo_list(s: stream.Score, bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The metronome marks in force, from the first part's flattened marks (music21's own default for a bare tempo
    word is skipped unless it is the only one). Consecutive equal tempos are one entry."""
    marks = [mm for mm in _first_part(s).flatten().getElementsByClass(m21tempo.MetronomeMark) if mm.number]
    if not marks:
        marks = [mm for mm in s.flatten().getElementsByClass(m21tempo.MetronomeMark) if mm.number]
    out: list[dict[str, Any]] = []
    for mm in marks:
        at = float(mm.getOffsetInHierarchy(_first_part(s))) if mm.activeSite is not None else 0.0
        try:
            qpm = float(mm.getQuarterBPM())
        except Exception:  # noqa: BLE001
            qpm = float(mm.number)
        if out and abs(out[-1]["qpm"] - qpm) < 1e-6:
            continue
        if out and abs(out[-1]["at"] - at) < 1e-6:
            out.pop()
        out.append({"bar": _bar_at(bars, at), "at": round(at, 6), "qpm": round(qpm, 3), "bpm": float(mm.number),
                    "beat": _beat_name(mm), "text": None if mm.textImplicit or not isinstance(mm.text, str) else mm.text, "marked": True})
    if not out or out[0]["at"] > 1e-6:
        first = out[0] if out else None
        out.insert(0, {"bar": bars[0]["bar"] if bars else 1, "at": 0.0, "qpm": first["qpm"] if first else DEFAULT_QPM,
                       "bpm": first["bpm"] if first else DEFAULT_QPM, "beat": first["beat"] if first else "quarter",
                       "text": None, "marked": False})
    return out


def meter_list(s: stream.Score, bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The time signatures in force, from the first part (consecutive equal meters are one entry). A book without one
    is counted in 4/4."""
    p0 = _first_part(s)
    out: list[dict[str, Any]] = []
    for ts in p0.flatten().getElementsByClass(m21meter.TimeSignature):
        at = float(ts.getOffsetInHierarchy(p0))
        entry = {"bar": _bar_at(bars, at), "at": round(at, 6), "meter": ts.ratioString, "beats": int(ts.numerator),
                 "beat_quarters": round(4.0 / int(ts.denominator), 6)}
        if out and out[-1]["meter"] == entry["meter"]:
            continue
        if out and abs(out[-1]["at"] - at) < 1e-6:
            out.pop()
        out.append(entry)
    if not out:
        out.append({"bar": bars[0]["bar"] if bars else 1, "at": 0.0, "meter": "4/4", "beats": 4, "beat_quarters": 1.0})
    return out


def count_in(bar_map: dict[str, Any], bar: int) -> dict[str, Any]:
    """The one-bar count-in before `bar`: the meter in force at that bar, as clicks. The browser mirrors this."""
    meters = bar_map["meters"]
    start = next((b for b in bar_map["bars"] if b["bar"] == bar), bar_map["bars"][0])
    m = meters[0]
    for x in meters:
        if x["at"] <= start["at"] + 1e-6:
            m = x
    return {"meter": m["meter"], "beats": m["beats"], "beat_quarters": m["beat_quarters"], "quarters": m["beats"] * m["beat_quarters"]}


def _instrument_for(staves: list) -> m21instrument.Instrument:
    for p in staves:
        inst = p.getInstrument(returnDefault=False)
        if inst is not None:
            return copy.deepcopy(inst)
    return m21instrument.Piano()


def playback_score(s: stream.Score) -> tuple[stream.Score, list[str]]:
    """A flat score for MIDI: one Part per app part (its staves' notes merged), ties joined per staff first, grace notes
    dropped, dynamics kept for the velocities, and the tempo and meter marks in the first part for the conductor
    track. Flat parts carry no measures, so music21 does not expand repeats."""
    from .import_musicxml import part_groups   # import_musicxml imports this module

    groups = part_groups(s)
    p0 = _first_part(s)
    out = stream.Score()
    names: list[str] = []
    for i, (name, staves) in enumerate(groups):
        part = stream.Part()
        part.partName = name
        part.id = f"play-{i + 1}"
        inst = _instrument_for(staves)
        inst.partName = name
        inst.partId = part.id
        part.insert(0, inst)
        for staff in staves:
            tied = staff.stripTies(matchByPitch=True)
            flat = tied.flatten()
            for el in flat.getElementsByClass((note.Note, chord.Chord)):
                if el.duration.isGrace or el.duration.quarterLength <= 0:
                    continue
                c = copy.deepcopy(el)
                c.tie = None
                part.insert(float(flat.elementOffset(el)), c)
            for d in flat.getElementsByClass("Dynamic"):
                part.insert(float(flat.elementOffset(d)), copy.deepcopy(d))
        if i == 0:
            for mm in p0.flatten().getElementsByClass(m21tempo.MetronomeMark):
                if mm.number:
                    part.insert(float(mm.getOffsetInHierarchy(p0)), copy.deepcopy(mm))
            for ts in p0.flatten().getElementsByClass(m21meter.TimeSignature):
                part.insert(float(ts.getOffsetInHierarchy(p0)), copy.deepcopy(ts))
        out.insert(0, part)
        names.append(name)
    return out, names


def _name_tracks(mf, names: list[str]) -> None:
    """Track 0 is the conductor; each later track carries its part's name as its track name (the book's `parts.name`)."""
    for mt, name in zip(mf.tracks[1:], names):
        data = name.encode("utf-8")
        named = [e for e in mt.events if e.type == MetaEvents.SEQUENCE_TRACK_NAME]
        for e in named:
            e.data = data
        if not named:
            ev = MidiEvent(mt, type=MetaEvents.SEQUENCE_TRACK_NAME, channel=None)
            ev.data = data
            mt.events[0:0] = [DeltaTime(mt, time=0), ev]


def build(s: stream.Score) -> tuple[bytes, dict[str, Any]]:
    """The MIDI bytes and the bar map of a parsed MusicXML score."""
    bars = bar_list(s)
    flat, names = playback_score(s)
    mf = translate.streamToMidiFile(flat, addEndDelay=False)
    _name_tracks(mf, names)
    data = mf.writestr()
    quarters = max([b["at"] + b["quarters"] for b in bars] + [float(flat.highestTime or 0)])
    bar_map = {"version": 1, "ppq": int(mf.ticksPerQuarterNote), "parts": names, "quarters": round(quarters, 6),
               "bars": bars, "tempos": tempo_list(s, bars), "meters": meter_list(s, bars)}
    return data, bar_map


async def write_step(ctx, score_id: str, source_id: str, s: stream.Score) -> dict[str, Any]:
    """Build both files, upload them next to the score's files and record them on the score row. Best effort: a book
    whose MIDI cannot be made is still a book (the player then says it cannot play this one). Never raises."""
    t0 = time.time()
    try:
        data, bar_map = await asyncio.to_thread(build, s)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"{type(e).__name__}: {e}"[:300]}
    mkey, bkey = midi_path(score_id), bars_path(score_id)
    ctx.storage_upload(mkey, data, MIDI_TYPE)
    ctx.storage_upload(bkey, json.dumps(bar_map, separators=(",", ":")).encode(), JSON_TYPE)
    record = {"midi": mkey, "bar_map": bkey, "source_id": source_id, "parts": bar_map["parts"],
              "bars": len(bar_map["bars"]), "made_at": ctx.now()}
    ctx.db.table("scores").update({"playback": record}).eq("id", score_id).execute()
    return {"ok": True, "midi_bytes": len(data), "tracks": len(bar_map["parts"]), "bars": len(bar_map["bars"]),
            "seconds": round(time.time() - t0, 2)}
