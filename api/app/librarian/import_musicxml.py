"""Path A: a MusicXML file becomes a ready score. No model call; music21 does the reading.

Writes interpretation v(n+1) with engine 'musicxml', the parts (names disambiguated: two "Violin" parts
become "Violin I" and "Violin II"; "Violoncello" becomes "Cello"), one stable measure row per measure
number, and the score's facts (key and meter in the canonical forms of `signature.py`, "F# minor" and "4/4"; bars,
tempo, duration, pages estimate). Parts are named by `part_groups`, which `part_split` uses too. Difficulty is a rough
density heuristic until the `brief` job (Spark) replaces it. `book_facts`, `write_parts` and `write_measures` are
shared with Convert to Digital (`omr_convert`, feature 005), so a transcribed book is read the way an imported one is.
The pages are then engraved by MuseScore on the box (`engrave_step`, both layouts, best effort) before the book is ready.
The book's landmarks (key and meter changes, tempo words, double bars, repeats, coda, segno, fine, section titles,
rehearsal marks; `landmarks.from_musicxml`, no model) go to `scores.landmarks` for the voice-note prompt (013 v4e).
"""
from __future__ import annotations

import io
import time
from typing import Any

from music21 import converter, key as m21key, meter as m21meter, stream, tempo as m21tempo

from . import Job, JobContext, handler
from . import landmarks
from .engrave import engrave_step
from .signature import canonical_key, canonical_meter

CANON = {"Violoncello": "Cello", "Contrabass": "Double bass", "Pianoforte": "Piano"}
ROMAN = ["I", "II", "III", "IV", "V", "VI"]


def part_names(raw: list[str]) -> list[str]:
    names = [CANON.get(n.strip(), n.strip()) or f"Part {i + 1}" for i, n in enumerate(raw)]
    # A piano exported as two "Piano" parts (one per staff) is one part, not Piano I and II.
    if len(names) == 2 and names[0] == names[1] == "Piano":
        return ["Piano"]
    out: list[str] = []
    for i, n in enumerate(names):
        if names.count(n) > 1:
            k = names[: i + 1].count(n) - 1
            out.append(f"{n} {ROMAN[k] if k < len(ROMAN) else k + 1}")
        else:
            out.append(n)
    return out


def part_groups(s) -> list[tuple[str, list]]:
    """The score's parts as the app names them, each with the music21 parts that print it, in score order. A part
    written on two staves (music21 splits it into PartStaff objects "P1-Staff1", "P1-Staff2") is one part, and so is
    a piano exported as two "Piano" parts (`part_names`). These names are the `parts.name` rows the import writes
    and the names a split (`part_split`) accepts."""
    groups: list[tuple[list, str | None]] = []
    for p in s.parts:
        sid = str(p.id).rsplit("-Staff", 1)[0] if isinstance(p, stream.PartStaff) and "-Staff" in str(p.id) else None
        if sid and groups and groups[-1][1] == sid:
            groups[-1][0].append(p)
        else:
            groups.append(([p], sid))
    names = part_names([g[0].partName or "" for g, _ in groups])
    if len(names) < len(groups):   # part_names merged a two-part piano
        return [(names[0], [p for g, _ in groups for p in g])]
    return [(n, g) for n, (g, _) in zip(names, groups)]


def difficulty_of(parts) -> int:
    """1..5 from note density and range, over a part's staves. A placeholder the brief job overwrites."""
    parts = parts if isinstance(parts, list) else [parts]
    notes = [n for part in parts for n in part.flatten().notes]
    if not notes:
        return 1
    ql = max(float(part.duration.quarterLength) for part in parts) or 1.0
    density = len(notes) / ql
    pitches = [p.midi for n in notes for p in (n.pitches if hasattr(n, "pitches") else [])]
    span = (max(pitches) - min(pitches)) if pitches else 0
    score = density * 2 + span / 12
    return max(1, min(5, round(score)))


def book_facts(s) -> dict[str, Any]:
    """What a parsed MusicXML says about its book: the parts as the app names them (`part_groups`), the measure
    numbers, and the score facts in canonical form (key, meter, tempo, duration, a pages estimate, title, composer,
    movement), and the landmarks it prints (`landmarks.from_musicxml`). Shared by the import (Path A) and Convert to Digital (`omr_convert`, feature 005)."""
    groups = part_groups(s)
    p0 = s.parts[0]
    measures = list(p0.getElementsByClass("Measure"))
    numbers = sorted({m.number for p in s.parts for m in p.getElementsByClass("Measure")})
    ks = p0.flatten().getElementsByClass(m21key.KeySignature)
    # The signature alone cannot tell F major from D minor; let music21's key analysis pick the mode.
    try:
        mode = s.analyze("key").mode
    except Exception:  # noqa: BLE001
        mode = "major"
    ts = p0.flatten().getElementsByClass(m21meter.TimeSignature)
    mm = s.flatten().getElementsByClass(m21tempo.MetronomeMark)
    bpm = int(mm[0].number) if mm and mm[0].number else None
    quarters = float(s.highestTime or 0)
    md = s.metadata
    try:
        marks = landmarks.from_musicxml(s)
    except Exception:  # noqa: BLE001  (a landmark the reader trips on never fails the import)
        marks = []
    return {
        "groups": groups, "names": [n for n, _ in groups], "numbers": numbers,
        "key_sig": canonical_key(ks[0].asKey(mode).name) if ks else None,
        "meter": canonical_meter(ts[0].ratioString) if ts else None,
        "tempo_bpm": bpm, "duration_sec": int(quarters / bpm * 60) if bpm and quarters else None,
        "pages": max(1, round(len(measures) / 24)),
        "title": (md.title or "").strip() if md else "", "composer": (md.composer or "").strip() if md else "",
        "movement": (md.movementName or "").strip() if md else "",
        "landmarks": marks,
    }


def write_parts(db, score_id: str, groups: list[tuple[str, list]], path: str) -> None:
    """One `parts` row per app part (upsert on score and name) with its difficulty and the file that prints it."""
    rows = [{"score_id": score_id, "name": name, "position": i, "difficulty": difficulty_of(staves), "storage_path": path}
            for i, (name, staves) in enumerate(groups)]
    db.table("parts").upsert(rows, on_conflict="score_id,name").execute()


def write_measures(db, score_id: str, numbers: list[int]) -> None:
    """Stable identities: upsert, never delete. Part null = the whole score."""
    rows = [{"score_id": score_id, "number": n, "part": None} for n in numbers]
    for i in range(0, len(rows), 500):
        db.table("measures").upsert(rows[i:i + 500], on_conflict="score_id,number,part").execute()


@handler("import_musicxml")
async def import_musicxml(job: Job, ctx: JobContext, *, engraver: Any = None) -> dict:
    t0 = time.time()
    score_id = job.payload["score_id"]
    source_id = job.payload["source_id"]
    src = ctx.db.table("sources").select("*").eq("id", source_id).single().execute().data
    path = src["storage_paths"][0]
    await ctx.progress(0.05, "Reading the file")
    data = ctx.storage_download(path)
    s = converter.parse(io.BytesIO(data).read(), format="musicxml")

    await ctx.progress(0.3, "Finding parts and measures")
    f = book_facts(s)
    groups, names, numbers = f["groups"], f["names"], f["numbers"]
    title, composer, movement = f["title"], f["composer"], f["movement"]

    prev = ctx.db.table("interpretations").select("version").eq("score_id", score_id).order("version", desc=True).limit(1).execute().data
    version = (prev[0]["version"] + 1) if prev else 1
    interp = ctx.db.table("interpretations").insert({
        "score_id": score_id, "source_id": source_id, "version": version, "engine": "musicxml", "status": "running",
        "params": {"music21": True},
    }).execute().data[0]

    await ctx.progress(0.5, "Writing parts")
    write_parts(ctx.db, score_id, groups, path)

    await ctx.progress(0.7, f"Writing {len(numbers)} measures")
    write_measures(ctx.db, score_id, numbers)
    landmarks.save(ctx.db, score_id, f["landmarks"], "musicxml")

    summary = {
        "pages": None, "systems": None, "measures": len(numbers), "first_measure": numbers[0] if numbers else None,
        "title": title, "composer": composer, "movement": movement, "parts": names,
        "flagged": {"pages_unreadable": 0, "bars_doubtful": 0},
        "landmarks": len(f["landmarks"]),
        "log": [f"Read {len(names)} parts and {len(numbers)} measures from MusicXML"]
               + ([f"{len(f['landmarks'])} landmarks (key and meter changes, tempo words, double bars, repeats, signs)"] if f["landmarks"] else []),
    }
    ctx.db.table("interpretations").update({
        "status": "done", "summary": summary, "latency_ms": int((time.time() - t0) * 1000), "finished_at": ctx.now(),
    }).eq("id", interp["id"]).execute()

    # The pages the reader shows: MuseScore on the box, both layouts (engrave.py). Best effort, before the book is
    # ready so it opens engraved; without the box the reader engraves on the device.
    engraving = await engrave_step(ctx, score_id, source_id, box=engraver, progress=0.85)

    facts = {
        "status": "ready", "progress": 1.0, "failure_reason": None,
        "bars": len(numbers), "key_sig": f["key_sig"], "meter": f["meter"],
        "tempo_bpm": f["tempo_bpm"], "duration_sec": f["duration_sec"], "pages": f["pages"],
        "current_interpretation_id": interp["id"],
    }
    existing = ctx.db.table("scores").select("title,composer,work").eq("id", score_id).single().execute().data
    if not existing.get("title"):
        filename = (src.get("meta") or {}).get("filename") or path.rsplit("/", 1)[-1]
        facts["title"] = title or filename.rsplit(".", 1)[0].replace("-", " ").replace("_", " ")
    if not existing.get("composer") and composer and composer.lower() != "music21":
        facts["composer"] = composer
    if not existing.get("work") and (title or movement):
        facts["work"] = movement or title
    ctx.db.table("scores").update(facts).eq("id", score_id).execute()
    await ctx.progress(1.0, "Ready")
    return {"interpretation_id": interp["id"], "parts": names, "measures": len(numbers), "seconds": round(time.time() - t0, 1), "engraving": engraving}
