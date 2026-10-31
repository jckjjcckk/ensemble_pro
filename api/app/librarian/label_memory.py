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

Layouts (follow-up, 2026-10-31): the same row keeps what a system of a given shape holds, for the systems that print no
labels (a sonata's later pages, an orchestral page's second line). `layouts` maps a key, the system's staff count plus the
margin labels printed on it in order (`layout_key`: "3", or "11|fl;ob;...|vc"), to the parts on it and their staves as
1-based positions within the system:

    {"layouts": {"1": {"staves": 1, "labels": [], "parts": {"Pianoforte": {"positions": [1], "source": "human",
                                                                          "origin": "answer", "page": 12, "system": 4}}}}}

The page read (`process_pages`) learns whole layouts (every part of the system); the part cut learns the wanted
instruments' places. The same provenance rule as the labels: a human answer overwrites anything, a model read never
overwrites a human, and two model reads that disagree mark the part `disputed` (used by no one until a human answers).
`layout_part` and `full_layout` answer for a system of the same staff count: a label-less system takes any layout of its
count, a labelled one only the layout learned under the same labels in the same order.

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


def layout_key(staves: int, labels: list[str] | None = None) -> str:
    """A system's shape: its staff count, and the margin labels printed on it top to bottom when it has any."""
    names = [norm(x) for x in labels or [] if norm(x)]
    return f"{int(staves)}|{';'.join(names)}" if names else str(int(staves))


class LabelMemory:
    def __init__(self, entries: dict[str, dict[str, Any]] | None = None, layouts: dict[str, dict[str, Any]] | None = None):
        self.entries: dict[str, dict[str, Any]] = dict(entries or {})
        self.layouts: dict[str, dict[str, Any]] = dict(layouts or {})
        self.changed = False

    @staticmethod
    def from_dict(d: Any) -> "LabelMemory":
        entries = (d or {}).get("entries") if isinstance(d, dict) else None
        ok = {k: v for k, v in (entries or {}).items() if isinstance(v, dict) and v.get("label") and v.get("part") and v.get("source") in SOURCES}
        raw = (d or {}).get("layouts") if isinstance(d, dict) else None
        layouts: dict[str, dict[str, Any]] = {}
        for k, v in (raw or {}).items():
            if not isinstance(v, dict) or not isinstance(v.get("parts"), dict) or not str(v.get("staves", "")).isdigit():
                continue
            parts = {p: e for p, e in v["parts"].items() if isinstance(e, dict) and e.get("source") in SOURCES
                     and isinstance(e.get("positions"), list) and e["positions"] and all(isinstance(x, int) and 1 <= x <= int(v["staves"]) for x in e["positions"])}
            if parts:
                layouts[k] = {"staves": int(v["staves"]), "labels": list(v.get("labels") or []), "parts": parts}
        return LabelMemory(ok, layouts)

    def to_dict(self) -> dict[str, Any]:
        return {"entries": self.entries, "layouts": self.layouts, "updated_at": datetime.now(timezone.utc).isoformat()}

    def merge(self, other: "LabelMemory") -> None:
        """Take another copy's entries (the row as it is now, written by another job meanwhile) under the same rule."""
        for e in other.entries.values():
            self.learn(e["label"], e["part"], e["source"], e.get("origin", ""), page=e.get("page"), staves=e.get("staves"),
                       job_id=e.get("job_id"), at=e.get("at"), mark=False)
        for lay in other.layouts.values():
            for part, e in lay["parts"].items():
                self.learn_layout(lay["staves"], lay.get("labels"), part, e["positions"], e["source"], e.get("origin", ""), page=e.get("page"),
                                  system=e.get("system"), job_id=e.get("job_id"), at=e.get("at"), mark=False, disputed=bool(e.get("disputed")))

    # ------------------------------------------------------------ layouts: what a system of this shape holds

    def learn_layout(self, staves: int, labels: list[str] | None, part: str, positions: list[int], source: str, origin: str, *,
                     page: int | None = None, system: int | None = None, job_id: str | None = None, at: str | None = None,
                     mark: bool = True, disputed: bool = False) -> bool:
        """Remember that in a system of `staves` staves (with these margin labels) `part` sits on `positions` (1-based).
        A human overwrites anything (and takes those staves from any other part); a model read never moves a human
        entry, and a model read that disagrees with a model entry marks it disputed."""
        pos = sorted(set(int(x) for x in positions or []))
        if not str(part).strip() or source not in SOURCES or not pos or pos[0] < 1 or pos[-1] > int(staves):
            return False
        key = layout_key(staves, labels)
        lay = self.layouts.setdefault(key, {"staves": int(staves), "labels": [norm(x) for x in labels or [] if norm(x)], "parts": {}})
        name = next((p for p in lay["parts"] if same_part(p, part)), None)
        old = lay["parts"].get(name) if name else None
        if old is not None:
            if old["source"] == "human" and source == "model":
                return False
            if old["positions"] == pos and (old["source"] == source or source == "model"):
                return False                                  # already known; the first provenance stands
            if old["source"] == source == "model":
                if old.get("disputed"):
                    return False
                old["disputed"] = True                        # two reads of one shape disagree: a human decides
                if mark:
                    self.changed = True
                return True
            del lay["parts"][name]
        overlap = [p for p, e in lay["parts"].items() if set(e["positions"]) & set(pos)]
        if overlap and source == "model":
            if any(lay["parts"][p]["source"] == "human" for p in overlap):
                return False
            disputed = True
        for p in overlap:
            if source == "human":
                del lay["parts"][p]
            else:
                lay["parts"][p]["disputed"] = True
        lay["parts"][str(part).strip()] = {"positions": pos, "source": source, "origin": origin, "page": page, "system": system, "job_id": job_id,
                                           "at": at or datetime.now(timezone.utc).isoformat(), **({"disputed": True} if disputed else {})}
        if mark:
            self.changed = True
        return True

    def _shapes(self, staves: int, labels: list[str] | None) -> list[dict[str, Any]]:
        """The layouts a system may take: a label-less system any of its staff count, a labelled one its own key only."""
        if [x for x in labels or [] if norm(x)]:
            lay = self.layouts.get(layout_key(staves, labels))
            return [lay] if lay else []
        return [lay for lay in self.layouts.values() if lay["staves"] == int(staves)]

    def layout_part(self, staves: int, labels: list[str] | None, part: str) -> dict[str, Any] | None:
        """Where `part` sits in a system of this shape: {positions, source, origin, page, system}, a human's word first;
        None when nothing is known, every read of it is disputed, or the reads disagree."""
        hits = [e for lay in self._shapes(staves, labels) for p, e in lay["parts"].items() if same_part(p, part) and not e.get("disputed")]
        human = [e for e in hits if e["source"] == "human"]
        pick = human or hits
        if not pick or len({tuple(e["positions"]) for e in pick}) != 1:
            return None
        return max(pick, key=lambda e: e.get("at") or "")

    def full_layout(self, staves: int, labels: list[str] | None = None) -> dict[str, Any] | None:
        """A whole system of this shape: {parts, staves_per_part, source, page} when one remembered layout covers every
        staff top to bottom with no gap and nothing disputed (a human's first); else None."""
        found = []
        for lay in self._shapes(staves, labels):
            rows = sorted(lay["parts"].items(), key=lambda kv: kv[1]["positions"][0])
            flat = [x for _, e in rows for x in e["positions"]]
            if not rows or flat != list(range(1, int(staves) + 1)) or any(e.get("disputed") for _, e in rows):
                continue
            if any(e["positions"] != list(range(e["positions"][0], e["positions"][-1] + 1)) for _, e in rows):
                continue
            src = "human" if all(e["source"] == "human" for _, e in rows) else "model"
            page = max((e.get("page") or 0 for _, e in rows), default=0) or None
            found.append({"parts": [p for p, _ in rows], "staves_per_part": [len(e["positions"]) for _, e in rows], "source": src, "page": page})
        human = [f for f in found if f["source"] == "human"]
        pick = human or found
        if not pick or len({(tuple(f["parts"]), tuple(f["staves_per_part"])) for f in pick}) != 1:
            return None
        return pick[0]

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
