"""part_split: "Split by instrument" for a Digital book (an imported MusicXML). No model call, no cost, one pass.

Payload `{score_id, instruments: [str], source_id?}`, queued by the same route as the scan's part cut
(`POST /scores/{id}/parts`, feature 008); the route picks this kind when the score's source is MusicXML. The chosen
names are `parts.name` rows (`import_musicxml.part_groups` made them: "Violin I", "Cello", one "Piano" for a grand
staff). music21 loads the stored MusicXML, keeps the chosen parts in score order (every staff of a part; a brace
over a multi-staff part, the original brackets kept where two or more of their parts survive), and writes a new
MusicXML to `{score_id}/parts/{slug}.musicxml` (slug: the lowercase names joined with "+", as the part cut's). A
`sources` row of kind `musicxml` records it: `meta = {instruments, split_from, slug}`, `storage_paths = [key]`. The
same selection again replaces the file and reuses the row. Measure numbers are the source's, so `measures` ids hold.
"""
from __future__ import annotations

import copy
import re
import time
from typing import Any

from music21 import converter, layout, stream
from music21.musicxml.m21ToXml import GeneralObjectExporter

from . import Job, JobContext, handler
from .import_musicxml import part_groups

CONTENT_TYPE = "application/vnd.recordare.musicxml+xml"


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "part"


class UnknownInstrument(ValueError):
    def __init__(self, unknown: list[str], available: list[str]):
        super().__init__(f"not in this score: {', '.join(unknown)}; the parts are {', '.join(available)}")
        self.unknown, self.available = unknown, available


def original_source(db, score_id: str, source_id: str | None = None) -> dict | None:
    """The book's imported MusicXML: the given source, else the earliest musicxml source that is not itself a split."""
    if source_id:
        rows = db.table("sources").select("*").eq("id", source_id).limit(1).execute().data
        return rows[0] if rows and rows[0].get("kind") == "musicxml" else None
    rows = db.table("sources").select("*").eq("score_id", score_id).eq("kind", "musicxml").order("created_at").execute().data
    return next((r for r in rows if not (r.get("meta") or {}).get("split_from")), None)


def split_score(s: stream.Score, instruments: list[str]) -> tuple[bytes, list[str]]:
    """The chosen parts of `s` as a new MusicXML document, and the chosen names in score order. Raises UnknownInstrument."""
    groups = part_groups(s)
    available = [n for n, _ in groups]
    unknown = [i for i in instruments if i not in available]
    if unknown:
        raise UnknownInstrument(unknown, available)
    out = stream.Score()
    if s.metadata is not None:
        out.metadata = copy.deepcopy(s.metadata)
    copies: dict[int, Any] = {}
    chosen: list[str] = []
    for name, staves in groups:
        if name not in instruments:
            continue
        chosen.append(name)
        mine = []
        for p in staves:
            c = copy.deepcopy(p)
            if len(staves) == 1:
                c.partName = name          # "Violoncello" prints as the app's "Cello", "Violin" as "Violin I"
            out.insert(0, c)
            copies[id(p)] = c
            mine.append(c)
        if len(mine) > 1:
            out.insert(0, layout.StaffGroup(mine, name=name, symbol="brace", barTogether=True))
    for g in s.getElementsByClass(layout.StaffGroup):
        kept = [copies[id(p)] for p in g.getSpannedElements() if id(p) in copies]
        if len(kept) >= 2 and not all(isinstance(p, stream.PartStaff) for p in kept):
            out.insert(0, layout.StaffGroup(kept, name=g.name, symbol=g.symbol or "bracket", barTogether=g.barTogether))
    return GeneralObjectExporter(out).parse(), chosen


@handler("part_split")
async def part_split(job: Job, ctx: JobContext) -> dict:
    t0 = time.time()
    p = job.payload
    score_id = p["score_id"]
    instruments = [str(i).strip() for i in (p.get("instruments") or []) if str(i).strip()]
    if not instruments:
        raise RuntimeError("the payload names no instrument (instruments: [...])")
    src = original_source(ctx.db, score_id, p.get("source_id"))
    if src is None:
        raise RuntimeError("the score has no MusicXML source to split")
    # no ctx.progress: it would move the ready book's own progress bar for a split that takes a second
    s = converter.parse(ctx.storage_download(src["storage_paths"][0]), format="musicxml")
    data, chosen = split_score(s, instruments)
    part_slug = "+".join(slug(n) for n in chosen)
    key = f"{score_id}/parts/{part_slug}.musicxml"
    ctx.storage_upload(key, data, CONTENT_TYPE)
    meta = {"instruments": chosen, "split_from": src["id"], "slug": part_slug}
    row = {"score_id": score_id, "kind": "musicxml", "storage_paths": [key], "meta": meta, "created_by": job.created_by or src["created_by"]}
    same = [r for r in ctx.db.table("sources").select("id,meta").eq("score_id", score_id).eq("kind", "musicxml").execute().data
            if (r.get("meta") or {}).get("split_from") == src["id"] and (r.get("meta") or {}).get("slug") == part_slug]
    if same:
        derived = ctx.db.table("sources").update({"storage_paths": [key], "meta": meta}).eq("id", same[0]["id"]).execute().data[0]
    else:
        derived = ctx.db.table("sources").insert(row).execute().data[0]
    ctx.result["note"] = f"{' + '.join(chosen)}: split"
    return {"source_id": derived["id"], "instruments": chosen, "storage_path": key, "bytes": len(data), "seconds": round(time.time() - t0, 2)}
