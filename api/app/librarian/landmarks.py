"""The book's landmarks (013 voice notes, prompt v4e part a): what is printed at a bar that a conductor names a place by.

`scores.landmarks` (migration 20261030160000) is one list per book:

    {"kind": "key_change|meter_change|tempo|double_bar|repeat|coda|segno|fine|section|rehearsal",
     "label": "<printed text>", "bar": 97, "bar_after": 98 | None, "source": "musicxml" | "page", "trust"?: "low"}
`trust: "low"` marks a landmark from a page read at effort minimal (process_pages); `for_facts` drops its double bars.

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
        rec = {"kind": d["kind"], "label": label, "bar": bar, "bar_after": after, "source": src}
        if d.get("trust") == "low":
            rec["trust"] = "low"
        if key in out and out[key].get("trust") == "low" and "trust" not in rec:
            out[key] = rec                          # the same landmark read at low too: the trusted copy wins
        out.setdefault(key, rec)
    return sorted(out.values(), key=lambda d: (d["bar"], KINDS.index(d["kind"])))


def for_facts(landmarks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What the voice prompt lists: MusicXML entries when the book has any (a converted book), else the page ones. A
    double bar from a page read at effort minimal (`trust: "low"`) is left out unless a trusted read has a double bar at
    the same bar: minimal invented 3-4 double bars in 20 page reads where low invented none (004-speed-eval), and a
    conductor's "after the double bar" placed on an invented one is a wrong mark."""
    lm = clean(landmarks)
    xml = [d for d in lm if d["source"] == "musicxml"]
    if xml:
        return xml
    page = [d for d in lm if d["source"] == "page"]
    trusted = {d["bar"] for d in page if d["kind"] == "double_bar" and d.get("trust") != "low"}
    return [d for d in page if not (d["kind"] == "double_bar" and d.get("trust") == "low" and d["bar"] not in trusted)]


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


# ---------------------------------------------------------------- digital books: music21 on the MusicXML

TEMPO_WORDS = re.compile(
    r"\b(grave|largo|larghetto|lento|adagio|adagietto|andante|andantino|moderato|allegretto|allegro|vivace|vivacissimo|"
    r"presto|prestissimo|maestoso|tempo|a\s+tempo|rit|ritard|ritardando|riten|ritenuto|rall|rallentando|accel|"
    r"accelerando|stringendo|allargando|calando|smorzando|morendo|slentando|mosso|moto|l'istesso|primo|doppio\s+movimento|"
    r"langsam|schnell|lebhaft|mässig|massig|ruhig|bewegt|lent|vif|modéré|modere|animé|anime|cédez|cedez)\b", re.I)
SECTION_WORDS = re.compile(
    r"^\s*(trio|menuetto|minuetto|menuet|minuet|scherzo|finale|introduction|introduzione|cadenza|cadenz|var\.?|"
    r"variation|variatio|aria|recit\.?|recitativo|chorale|coral|fuga|fugue|interlude|intermezzo|coda|tutti|solo)\b", re.I)
DYNAMIC_WORDS = re.compile(r"^\s*(cresc|decresc|dim|sf|sfz|fp|pp|p|mp|mf|f|ff|poco|più|piu|molto|sempre|subito)\b", re.I)


def _key_label(ks) -> str:
    """What a key signature prints: "3 flats", "2 sharps", "no sharps or flats" (the mode is not printed)."""
    n = int(getattr(ks, "sharps", 0) or 0)
    if n == 0:
        return "no sharps or flats"
    return f"{abs(n)} {'sharp' if n > 0 else 'flat'}{'s' if abs(n) != 1 else ''}"


def _text_kind(text: str) -> str | None:
    """A printed word or phrase as a landmark kind, or None (dolce, cresc., espress.: not a place a conductor names)."""
    t = text.strip()
    low = t.lower()
    if not t or len(t) > 60:
        return None
    if re.search(r"\b(d\.?\s?c\.?|da capo|d\.?\s?s\.?|dal segno|fine)\b", low):
        return "fine"
    if re.search(r"\bcoda\b", low):
        return "coda"
    if re.search(r"\bsegno\b", low):
        return "segno"
    if SECTION_WORDS.search(t):
        return "section"
    if TEMPO_WORDS.search(t) and not DYNAMIC_WORDS.match(t):
        return "tempo"
    return None


def _words(e) -> str:
    """The printed words of a music21 repeat expression ("To Coda", "D.C. al Fine"), or ""."""
    try:
        return str(e.getText() or "").strip()
    except Exception:  # noqa: BLE001
        return str(getattr(e, "text", "") or "").strip()


def _reference_part(s):
    """A non-transposing part (key signatures read as printed for the concert key), else the first."""
    for p in s.parts:
        try:
            inst = p.getInstrument(returnDefault=False)
        except Exception:  # noqa: BLE001
            inst = None
        if inst is None or getattr(inst, "transposition", None) is None:
            return p
    return s.parts[0]


def from_musicxml(s) -> list[dict[str, Any]]:
    """The landmarks a parsed MusicXML prints (music21, no model): key and meter changes, tempo words and metronome
    changes, double bars, repeat barlines and first/second-time bars, segno, coda, To Coda, Fine, D.C./D.S., section
    titles and rehearsal marks. Barlines, key and meter are read on one part (they are the same in every part); words
    and signs on every part, deduplicated by kind, bar and text."""
    from music21 import bar, expressions, key as m21key, meter as m21meter, repeat, spanner, tempo as m21tempo

    out: list[dict[str, Any]] = []

    def add(kind: str, label: str, n: Any, after: Any = None) -> None:
        if isinstance(n, int):
            out.append({"kind": kind, "label": label, "bar": n, "bar_after": after, "source": "musicxml"})

    if not s.parts:
        return []
    ref = _reference_part(s)
    measures = list(ref.getElementsByClass("Measure"))
    numbers = [m.number for m in measures]
    nxt = {a: b for a, b in zip(numbers, numbers[1:]) if isinstance(a, int) and isinstance(b, int) and b > a}
    last = numbers[-1] if numbers else None

    # key and meter changes (the first of each is the book's key and meter, already on the score row)
    prev_key, prev_meter = None, None
    for m in measures:
        for ks in m.getElementsByClass(m21key.KeySignature):
            if prev_key is not None and ks.sharps != prev_key:
                add("key_change", _key_label(ks), m.number)
            prev_key = ks.sharps
        for ts in m.getElementsByClass(m21meter.TimeSignature):
            if prev_meter is not None and ts.ratioString != prev_meter:
                add("meter_change", ts.ratioString, m.number)
            prev_meter = ts.ratioString

    # barlines: double bars and repeats
    for m in measures:
        n = m.number
        lb, rb = m.leftBarline, m.rightBarline
        if isinstance(lb, bar.Repeat) and lb.direction == "start":
            add("repeat", "start repeat", n)
        elif lb is not None and lb.type in ("double", "heavy-light", "light-light", "heavy-heavy", "final"):
            prev = next((a for a, b in nxt.items() if b == n), None)
            if prev is not None:
                add("double_bar", "double bar", prev, n)
        if isinstance(rb, bar.Repeat) and rb.direction == "end":
            add("repeat", "end repeat", n, nxt.get(n))
        elif rb is not None and rb.type in ("double", "light-light", "heavy-heavy", "heavy-light", "final") and n != last:
            if n in nxt:
                add("double_bar", "double bar", n, nxt[n])
    for rbk in ref.spannerBundle.getByClass(spanner.RepeatBracket):
        spanned = [x for x in rbk.getSpannedElements() if getattr(x, "number", None) is not None]
        if spanned:
            num = str(rbk.number or "").strip()
            label = {"1": "1st-time bar", "2": "2nd-time bar"}.get(num, f"{num} ending".strip())
            add("repeat", label, spanned[0].number)

    # words and signs, every part
    metronomes: dict[int, str] = {}           # bar -> "quarter = 96", a metronome mark printed without words
    worded: set[int] = set()
    for p in s.parts:
        for m in p.getElementsByClass("Measure"):
            n = m.number
            for e in m.recurse().getElementsByClass((m21tempo.MetronomeMark, m21tempo.TempoText)):
                # music21 names a bare metronome mark itself ("allegro" for 132): only printed words count
                text = "" if getattr(e, "textImplicit", False) else (getattr(e, "text", None) or "")
                text = str(text).strip()
                if text:
                    add("tempo", text, n)
                    worded.add(n)
                elif isinstance(e, m21tempo.MetronomeMark) and e.number and not e.numberImplicit and isinstance(n, int):
                    unit = e.referent.fullName.lower() if getattr(e, "referent", None) is not None else "quarter"
                    metronomes.setdefault(n, f"{unit} = {int(e.number)}")
            for e in m.recurse().getElementsByClass(expressions.RehearsalMark):
                if str(e.content or "").strip():
                    add("rehearsal", str(e.content).strip(), n)
            for e in m.recurse().getElementsByClass(repeat.RepeatExpression):
                if isinstance(e, repeat.Segno):
                    add("segno", "segno", n)
                elif isinstance(e, repeat.Coda):
                    words = _words(e)
                    add("coda", words if words and words.lower() != "coda" else "Coda", n)
                elif isinstance(e, repeat.Fine):
                    add("fine", "Fine", n)
                else:                                # D.C., D.S., al Fine, al Coda
                    add("fine", _words(e) or re.sub(r"(?<!^)(?=[A-Z])", " ", type(e).__name__), n)
            for e in m.recurse().getElementsByClass(expressions.TextExpression):
                text = str(e.content or "").strip()
                kind = _text_kind(text)
                if kind:
                    add(kind, text, n)
                    if kind == "tempo":
                        worded.add(n)
    # A bare metronome mark is a landmark only where the tempo changes: the first is the book's tempo (tempo_bpm).
    prev = None
    for n in sorted(metronomes):
        if prev is not None and metronomes[n] != prev and n not in worded:
            add("tempo", metronomes[n], n)
        prev = metronomes[n]
    return clean(out)
