"""Path A: a MusicXML file becomes a ready score. No model call; music21 does the reading.

Writes interpretation v(n+1) with engine 'musicxml', the parts (names disambiguated: two "Violin" parts
become "Violin I" and "Violin II"; "Violoncello" becomes "Cello"), one stable measure row per measure
number, and the score's facts (key, meter, bars, tempo, duration, pages estimate). Difficulty is a rough
density heuristic until the `brief` job (Spark) replaces it.
"""
from __future__ import annotations

import io
import time

from music21 import converter, key as m21key, meter as m21meter, tempo as m21tempo

from . import Job, JobContext, handler

CANON = {"Violoncello": "Cello", "Contrabass": "Double bass", "Pianoforte": "Piano"}
ROMAN = ["I", "II", "III", "IV", "V", "VI"]


def part_names(raw: list[str]) -> list[str]:
    names = [CANON.get(n.strip(), n.strip()) or f"Part {i + 1}" for i, n in enumerate(raw)]
    out: list[str] = []
    for i, n in enumerate(names):
        if names.count(n) > 1:
            k = names[: i + 1].count(n) - 1
            out.append(f"{n} {ROMAN[k] if k < len(ROMAN) else k + 1}")
        else:
            out.append(n)
    return out


def difficulty_of(part) -> int:
    """1..5 from note density and range. A placeholder the brief job overwrites."""
    notes = list(part.flatten().notes)
    if not notes:
        return 1
    ql = float(part.duration.quarterLength) or 1.0
    density = len(notes) / ql
    pitches = [p.midi for n in notes for p in (n.pitches if hasattr(n, "pitches") else [])]
    span = (max(pitches) - min(pitches)) if pitches else 0
    score = density * 2 + span / 12
    return max(1, min(5, round(score)))


@handler("import_musicxml")
async def import_musicxml(job: Job, ctx: JobContext) -> dict:
    t0 = time.time()
    score_id = job.payload["score_id"]
    source_id = job.payload["source_id"]
    src = ctx.db.table("sources").select("*").eq("id", source_id).single().execute().data
    path = src["storage_paths"][0]
    await ctx.progress(0.05, "Reading the file")
    data = ctx.storage_download(path)
    s = converter.parse(io.BytesIO(data).read(), format="musicxml")

    await ctx.progress(0.3, "Finding parts and measures")
    names = part_names([p.partName or "" for p in s.parts])
    p0 = s.parts[0]
    measures = list(p0.getElementsByClass("Measure"))
    numbers = sorted({m.number for p in s.parts for m in p.getElementsByClass("Measure")})
    ks = p0.flatten().getElementsByClass(m21key.KeySignature)
    ts = p0.flatten().getElementsByClass(m21meter.TimeSignature)
    mm = s.flatten().getElementsByClass(m21tempo.MetronomeMark)
    bpm = int(mm[0].number) if mm and mm[0].number else None
    quarters = float(s.highestTime or 0)
    duration = int(quarters / bpm * 60) if bpm and quarters else None
    md = s.metadata
    title = (md.title or "").strip() if md else ""
    composer = (md.composer or "").strip() if md else ""
    movement = (md.movementName or "").strip() if md else ""

    prev = ctx.db.table("interpretations").select("version").eq("score_id", score_id).order("version", desc=True).limit(1).execute().data
    version = (prev[0]["version"] + 1) if prev else 1
    interp = ctx.db.table("interpretations").insert({
        "score_id": score_id, "source_id": source_id, "version": version, "engine": "musicxml", "status": "running",
        "params": {"music21": True},
    }).execute().data[0]

    await ctx.progress(0.5, "Writing parts")
    part_rows = []
    for i, (p, name) in enumerate(zip(s.parts, names)):
        part_rows.append({"score_id": score_id, "name": name, "position": i, "difficulty": difficulty_of(p), "storage_path": path})
    ctx.db.table("parts").upsert(part_rows, on_conflict="score_id,name").execute()

    await ctx.progress(0.7, f"Writing {len(numbers)} measures")
    # Stable identities: upsert, never delete. Part null = the whole score.
    rows = [{"score_id": score_id, "number": n, "part": None} for n in numbers]
    for i in range(0, len(rows), 500):
        ctx.db.table("measures").upsert(rows[i:i + 500], on_conflict="score_id,number,part").execute()

    summary = {
        "pages": None, "systems": None, "measures": len(numbers), "first_measure": numbers[0] if numbers else None,
        "title": title, "composer": composer, "movement": movement, "parts": names,
        "flagged": {"pages_unreadable": 0, "bars_doubtful": 0},
        "log": [f"Read {len(names)} parts and {len(numbers)} measures from MusicXML"],
    }
    ctx.db.table("interpretations").update({
        "status": "done", "summary": summary, "latency_ms": int((time.time() - t0) * 1000), "finished_at": ctx.now(),
    }).eq("id", interp["id"]).execute()

    facts = {
        "status": "ready", "progress": 1.0, "failure_reason": None,
        "bars": len(numbers), "key_sig": ks[0].asKey().name if ks else None, "meter": ts[0].ratioString if ts else None,
        "tempo_bpm": bpm, "duration_sec": duration, "pages": max(1, round(len(measures) / 24)),
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
    return {"interpretation_id": interp["id"], "parts": names, "measures": len(numbers), "seconds": round(time.time() - t0, 1)}
