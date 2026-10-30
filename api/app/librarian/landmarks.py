"""The book's landmarks (013 voice notes, prompt v4e part a): what is printed at a bar that a conductor names a place by.

`scores.landmarks` (migration 20261030160000) is one list per book:

    {"kind": "key_change|meter_change|tempo|double_bar|repeat|coda|segno|fine|section|rehearsal",
     "label": "<printed text>", "bar": 97, "bar_after": 98 | None, "source": "musicxml" | "page"}

`bar_after` is set for a boundary between two bars (a double bar, an end repeat), so the facts say "double bar
between bars 150 and 151": the v4e eval's one miss (lm15) read "double bar after bar 150" as "the bar before the double
bar" = 149. Two sources fill it, neither a model placing a bar:

- digital books: music21 on the MusicXML at import and on Convert to Digital (`from_musicxml`, no model call);
- scanned books: the per-page Spark read names what is printed over a numbered bar box, exactly as it names
  rehearsal letters; the page's geometry count gives the bar number (`process_pages`).

A converted book's page landmarks are replaced by its MusicXML ones (`save`, source "musicxml"). The voice prompt lists
them (`voice_prompt.landmark_lines`).
"""
from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger(__name__)

KINDS = ("key_change", "meter_change", "tempo", "double_bar", "repeat", "coda", "segno", "fine", "section", "rehearsal")
SOURCES = ("musicxml", "page")
MAX_LANDMARKS = 60     # a long book with a tempo word every page: the facts keep the first 60 in bar order


def clean(raw: Any, source: str | None = None) -> list[dict[str, Any]]:
    """Valid landmarks only, deduplicated, in bar order. A landmark without a kind it knows, a whole bar number or a
    label is dropped; `bar_after` is kept only when it is the next bar or later."""
    out: dict[tuple, dict[str, Any]] = {}
    for d in raw if isinstance(raw, list) else []:
        if not isinstance(d, dict) or d.get("kind") not in KINDS:
            continue
        bar = d.get("bar")
        if not isinstance(bar, int) or isinstance(bar, bool):
            continue
        after = d.get("bar_after")
        after = after if isinstance(after, int) and not isinstance(after, bool) and after > bar else None
        label = re.sub(r"\s+", " ", str(d.get("label") or "")).strip()
        src = source or d.get("source")
        if src not in SOURCES:
            continue
        if not label:
            label = {"double_bar": "double bar", "segno": "segno", "coda": "Coda", "fine": "Fine"}.get(d["kind"], "")
        if not label:
            continue
        key = (d["kind"], bar, label.casefold())
        out.setdefault(key, {"kind": d["kind"], "label": label, "bar": bar, "bar_after": after, "source": src})
    return sorted(out.values(), key=lambda d: (d["bar"], KINDS.index(d["kind"])))


def for_facts(landmarks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What the voice prompt lists: MusicXML entries when the book has any (a converted book), else the page ones."""
    lm = clean(landmarks)
    xml = [d for d in lm if d["source"] == "musicxml"]
    return xml or [d for d in lm if d["source"] == "page"]


def load(db: Any, score_id: str) -> list[dict[str, Any]]:
    """The book's landmarks, or none (no row, or the column not migrated yet: the prompt then says "none listed")."""
    try:
        row = db.table("scores").select("landmarks").eq("id", score_id).single().execute().data or {}
    except Exception:  # noqa: BLE001
        return []
    return clean(row.get("landmarks"))


def save(db: Any, score_id: str, new: list[dict[str, Any]], source: str) -> bool:
    """Replace the book's landmarks of `source`. MusicXML replaces the page ones too (a converted book: the digital
    version is the record). Never fails the job: a missing column (hosted before the migration) writes nothing."""
    new = clean(new, source)
    keep = [d for d in load(db, score_id) if d["source"] != source and not (source == "musicxml" and d["source"] == "page")]
    try:
        db.table("scores").update({"landmarks": clean(keep + new)}).eq("id", score_id).execute()
    except Exception as e:  # noqa: BLE001
        log.warning("landmarks not saved for %s: %s", score_id, e)
        return False
    return True
