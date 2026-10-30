"""The book's label memory: which printed staff label is which part, remembered across pages and jobs (008, 006).

The agentic memory rule (CK, 2026-10-30): work and human answers within a book are remembered and reused. A part
cut of a Beethoven concerto asked "which staves are the piano?" on every page although the first reading had read
"Klavier" as the piano and the admin had already answered for "Klav.". The memory is one JSON per book on
`scores.label_memory` (migration 20261030140000):

    {"entries": {"klav": {"label": "Klav.", "part": "Piano", "source": "human", "origin": "answer",
                          "page": 2, "staves": [8, 9], "job_id": "...", "at": "2026-10-30T..."}},
     "updated_at": "..."}

Keys are the normalised label (`norm`: lower case, no dots, commas or brackets, one space). `source` is "human"
(an admin's answer) or "model" (Spark: the header read of the first page, or a page whose cut passed every check);
`origin` says which ("answer", "header", "header-abbreviation", "page"). A human entry is never overwritten by a model
read; a human answer overwrites anything. `resolve(label)` finds the entry for a printed label: the same key first,
then the same instrument by the header's synonym table ("Pfte." is "Pianoforte") or as an abbreviation ("Klav." is
"Klavier": the first word is a prefix of at least three letters), numerals agreeing ("Vl. I" is not "Violine II");
two entries for different parts make the label unresolved, so a genuinely new or ambiguous label still asks.

No model call here. Spark only reads the labels (`part_cut.read_page`); geometry places every staff.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

from . import header as hdr
from .labels import canon_part, match_part

SOURCES = ("human", "model")


def norm(label: Any) -> str:
    """"Klav." -> "klav", "Vl. I" -> "vl i", "Violoncello u. Kontrabaß" -> "violoncello u kontrabaß"."""
    t = unicodedata.normalize("NFKC", str(label or "")).lower()
    t = re.sub(r"[.,;:()\[\]{}'\"*]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _first_word(label: str) -> str:
    w = [t for t in hdr.tokens(label) if t not in hdr.ROMAN]
    return w[0].strip("-") if w else ""


def same_label(a: str, b: str) -> bool:
    """Two printed labels for one instrument: the same normalised text, the same family by the synonym table, or one
    an abbreviation of the other (first word a prefix, at least three letters), with no numeral disagreeing."""
    if norm(a) == norm(b):
        return True
    na, nb = set(hdr.numerals(a)), set(hdr.numerals(b))
    if na != nb:
        return False
    fa, fb = hdr.family(a), hdr.family(b)
    if fa and fb:
        return fa == fb
    x, y = _first_word(a), _first_word(b)
    return len(x) >= 3 and len(y) >= 3 and (x.startswith(y) or y.startswith(x))


def same_part(a: str, b: str) -> bool:
    """A remembered part and a wanted instrument are the same part: the same name, or the same family with the same
    numerals ("Pianoforte" is "Piano"; "Piano I" is not "Piano", a second piano is another part)."""
    if canon_part(a).lower() == canon_part(b).lower():
        return True
    fa = hdr.family(a.split(" (")[0]) or hdr.family(a)
    fb = hdr.family(b.split(" (")[0]) or hdr.family(b)
    return bool(fa) and fa == fb and set(hdr.numerals(a)) == set(hdr.numerals(b))


class LabelMemory:
    def __init__(self, entries: dict[str, dict[str, Any]] | None = None):
        self.entries: dict[str, dict[str, Any]] = dict(entries or {})
        self.changed = False

    @staticmethod
    def from_dict(d: Any) -> "LabelMemory":
        entries = (d or {}).get("entries") if isinstance(d, dict) else None
        ok = {k: v for k, v in (entries or {}).items() if isinstance(v, dict) and v.get("label") and v.get("part") and v.get("source") in SOURCES}
        return LabelMemory(ok)

    def to_dict(self) -> dict[str, Any]:
        return {"entries": self.entries, "updated_at": datetime.now(timezone.utc).isoformat()}

    def merge(self, other: "LabelMemory") -> None:
        """Take another copy's entries (the row as it is now, written by another job meanwhile) under the same rule."""
        for e in other.entries.values():
            self.learn(e["label"], e["part"], e["source"], e.get("origin", ""), page=e.get("page"), staves=e.get("staves"),
                       job_id=e.get("job_id"), at=e.get("at"), mark=False)

    def learn(self, label: str, part: str, source: str, origin: str, *, page: int | None = None, staves: list[int] | None = None,
              job_id: str | None = None, at: str | None = None, mark: bool = True) -> bool:
        """Remember that `label` is `part`. A human answer overwrites anything; a model read never overwrites a human
        entry, nor a model entry that names another part (the first read stands; a conflict is for a human)."""
        key = norm(label)
        if not key or not str(part).strip() or source not in SOURCES:
            return False
        old = self.entries.get(key)
        if old is not None:
            if old["source"] == "human" and source == "model":
                return False
            if old["source"] == source == "model" and not same_part(old["part"], part):
                return False
            if old["source"] == source and same_part(old["part"], part):
                return False                                  # already known; the first provenance stands
        self.entries[key] = {"label": str(label).strip(), "part": str(part).strip(), "source": source, "origin": origin, "page": page,
                             "staves": staves, "job_id": job_id, "at": at or datetime.now(timezone.utc).isoformat()}
        if mark:
            self.changed = True
        return True

    def resolve(self, label: str) -> dict[str, Any] | None:
        """The entry for a printed label, else None (unknown, or the matches name different parts)."""
        if not norm(label):
            return None
        exact = self.entries.get(norm(label))
        if exact is not None:
            return exact
        hits = [e for e in self.entries.values() if same_label(label, e["label"])]
        if not hits:
            return None
        parts: list[str] = []
        for e in hits:
            if not any(same_part(e["part"], p) for p in parts):
                parts.append(e["part"])
        if len(parts) != 1:
            return None
        return next((e for e in hits if e["source"] == "human"), hits[0])

    def seed_from_header(self, header: dict[str, Any] | None, parts: list[str] | None = None) -> int:
        """The first page's read: each instrument's printed name and the abbreviations it expects, as the book's part
        (`parts`: the book's part names, so "Klavier" is stored as the "Piano" the reading named), source model."""
        n = 0
        page = (header or {}).get("page") or 1
        for i in (header or {}).get("instruments") or []:
            label = str(i.get("label") or i.get("name") or "").strip()
            if not label:
                continue
            part = (match_part(label, parts) if parts else None) or canon_part(label)
            n += self.learn(label, part, "model", "header", page=page)
            for a in i.get("abbreviations") or []:
                if str(a).strip():
                    n += self.learn(str(a), part, "model", "header-abbreviation", page=page)
        return n

    def context(self, instruments: list[str]) -> str:
        """Prompt lines for the label call: what this book's labels are known to be, human answers first."""
        rows = sorted(self.entries.values(), key=lambda e: (e["source"] != "human", e.get("page") or 0))
        rows = [e for e in rows if any(same_part(e["part"], w) for w in instruments)] or []
        if not rows:
            return ""
        said = []
        for e in rows[:12]:
            how = (f"confirmed by the user on page {e['page']}" if e["source"] == "human" else
                   "read from the first page" if str(e.get("origin", "")).startswith("header") else f"read on page {e['page']}")
            said.append(f'"{e["label"]}" is {e["part"]} ({how})')
        return ("Known labels in this book: " + "; ".join(said) + ". A staff printed with one of these labels (or its abbreviation) is that part; "
                "a label confirmed by the user is right.\n")


# ---------------------------------------------------------------- the score row

def load(db: Any, score_id: str) -> LabelMemory:
    """The book's memory, or an empty one (no row, or the column not migrated yet: the cut then runs as before)."""
    try:
        row = db.table("scores").select("label_memory").eq("id", score_id).single().execute().data or {}
    except Exception:  # noqa: BLE001
        return LabelMemory()
    return LabelMemory.from_dict(row.get("label_memory"))


def save(db: Any, score_id: str, mem: LabelMemory) -> bool:
    """Write the memory back, merged with the row as it is now (another job may have learned meanwhile). Never
    fails the job: a missing column (hosted before the migration) leaves the memory in the job's state only."""
    if not mem.changed:
        return False
    try:
        mem.merge(load(db, score_id))
        db.table("scores").update({"label_memory": mem.to_dict()}).eq("id", score_id).execute()
    except Exception:  # noqa: BLE001
        return False
    mem.changed = False
    return True
