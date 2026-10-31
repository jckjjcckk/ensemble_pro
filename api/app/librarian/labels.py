"""Muse Spark 1.3 labels what the geometry found. One call per page, effort low, about $0.008 a page; plus the score
header once per book.

Spark sees the page with the geometry's measure boxes drawn and provisionally numbered, and is asked only
for what geometry cannot know: the real number of the first measure, the part names of each system's staves,
rehearsal marks, measures that do not look real, title, composer, key and meter, a 1..5 difficulty per part,
a two-sentence brief, and (item 8, 013 v4e) the printed landmarks (tempo words, key and meter changes, double bars,
repeats, segno, coda, Fine, section titles), each pointed at a box as rehearsal marks are. It never moves a box, never
counts bars: the page's geometry count gives each box its bar number (`process_pages`), and a landmark whose box is
missing or not on the page is dropped (`page_landmarks`). The call goes through `ctx.complete`, so it is charged to the
job's user with the job id (model from settings: `muse-spark-1.3` when LLM_PROVIDER=meta).

Prompt lifted from `api/experiments/grounding/label_with_spark.py` (experiment README, "Exact prompts"), plus
items 6 and 7.

`read_header` is the part cut's header read (`header.py`: the instruments in score order on the numbered staff
overlay of the first page with music, one Spark call) for page reading: its staff count per full system drives the
staff recovery on every page (`cut.page_measures(expected_staves=)`), and its instruments tell a cut-away system
(resting parts not printed) from a page that brings parts the book does not have (`match_part`).
"""
from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from anthropic import AsyncAnthropic
from PIL import Image, ImageDraw, ImageFont

from . import JobContext
from . import header as hdr
from .ask import NoJSON, ask_model
from .cut import overlay_png, page_geometry

PROMPT = """This is a scanned page of printed sheet music. Blue boxes with provisional numbers (1..{n}, reading left to right, top to bottom) mark the measures that a geometry detector found. Dashed grey boxes mark staff systems; system {systems_desc}.
{parts_context}
Answer these questions about the page. Do not re-locate anything; only label what is drawn.
1. first_measure_number: the real measure number of provisional measure 1, using printed measure numbers, rehearsal letters or the musical context if visible; if the page starts with an incomplete pickup bar say so (is_pickup true). If nothing on the page tells you, answer 1 with confidence "low".
2. systems: for each system, the part names of its staves top to bottom (e.g. ["Piano I", "Piano II"] for a two-piano score where each part has two staves; ["Piano"] for a piano grand staff; ["Violin I", "Violin II", "Viola", "Cello"] for a quartet). Give staves_per_part so the counts add up to the staves in that system. Use the names as printed, in English, with Roman numerals for numbered parts.
3. rehearsal_marks: any boxed numbers or letters, with the provisional measure they are attached to.
4. doubtful_measures: provisional measure numbers that do not look like real measures (for example a box that spans only a clef or key signature, or two boxes that are really one bar split by a note stem), each with a reason.
5. title and composer if printed; key_signature (e.g. "G major") and time_signature (e.g. "3/4") as printed at the start, else null.
6. parts_difficulty: for every distinct part name on the page, a difficulty from 1 (easy) to 5 (virtuoso) for an amateur player, judged from the notation on this page.
7. brief: two sentences a librarian would write about this music for the ensemble: what it is and what will take the most work. No preamble.
8. landmarks: what is printed on this page that marks a place in the music, each with the provisional measure (the blue box number) it is printed over, exactly as for rehearsal marks: tempo words (Allegro, Adagio, meno mosso, a tempo, rit., ritenuto, Tempo I) and metronome marks; a key signature or time signature that changes (not the ones repeated at the start of every system); double barlines; repeat signs; segno, coda, "To Coda", Fine, D.C., D.S.; section titles (Trio, Var. 2, Cadenza). Give "text" as printed (for a key change the new signature, e.g. "3 flats"; for a time signature, e.g. "3/4"; for repeat signs "start repeat" or "end repeat"; for a double barline "double bar"). For a double barline or an end repeat give the box it closes (the box to its left); for everything else the box it stands over or begins. Do not count bars or give bar numbers; only point at a box. If you cannot tell which box it belongs to, give null. List only what you can see printed: a repeat sign is two dots beside a double barline, so never infer a start repeat from an end repeat or from the form of the music; for a key change count the sharps or flats of the new signature; one barline can carry two landmarks (an end repeat and Fine). Leave out dynamics, hairpins, articulations, fingering, pedal marks, expression words (dolce, cresc., espress., con forza), the clef, key and time signature at the start of each system, and the final barline of the piece.

Return only JSON:
{{"first_measure_number": 1, "is_pickup": false, "confidence": "high|medium|low",
 "systems": [{{"index": 1, "parts": ["Piano"], "staves_per_part": [2]}}],
 "rehearsal_marks": [{{"mark": "1", "provisional_measure": 9}}],
 "doubtful_measures": [{{"provisional_measure": 5, "reason": "..."}}],
 "title": "", "composer": "", "key_signature": null, "time_signature": null,
 "parts_difficulty": [{{"part": "Piano", "difficulty": 3}}],
 "brief": "",
 "landmarks": [{{"kind": "tempo|key_change|meter_change|double_bar|repeat|coda|segno|fine|section", "text": "Adagio", "provisional_measure": 12}}]}}"""

PAGE_LANDMARK_KINDS = ("tempo", "key_change", "meter_change", "double_bar", "repeat", "coda", "segno", "fine", "section")


@dataclass
class PageLabels:
    first_measure_number: int = 1
    is_pickup: bool = False
    confidence: str = "low"
    systems: list[dict[str, Any]] = field(default_factory=list)   # [{index, parts, staves_per_part}]
    rehearsal_marks: dict[int, str] = field(default_factory=dict)  # provisional -> mark
    doubtful: dict[int, str] = field(default_factory=dict)         # provisional -> reason
    title: str = ""
    composer: str = ""
    key_signature: str | None = None
    time_signature: str | None = None
    parts_difficulty: dict[str, int] = field(default_factory=dict)
    brief: str = ""
    # 013 v4e: printed landmarks, each tied to a provisional box: [{kind, text, provisional}]; and the ones dropped
    # because the box was missing or not on the page ([{kind, text, provisional, why}]), for the log.
    landmarks: list[dict[str, Any]] = field(default_factory=list)
    landmarks_dropped: list[dict[str, Any]] = field(default_factory=list)
    cost_usd: Decimal = Decimal(0)
    model: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def parts_for_system(self, index: int) -> tuple[list[str], list[int]]:
        for s in self.systems:
            if int(s.get("index", 0)) == index:
                parts = [canon_part(p) for p in (s.get("parts") or []) if str(p).strip()]
                spp = [int(x) for x in (s.get("staves_per_part") or [])]
                return parts, spp
        return [], []

    def as_dict(self) -> dict[str, Any]:
        return {
            "first_measure_number": self.first_measure_number, "is_pickup": self.is_pickup, "confidence": self.confidence,
            "systems": self.systems, "rehearsal_marks": self.rehearsal_marks, "doubtful": self.doubtful,
            "title": self.title, "composer": self.composer, "key_signature": self.key_signature, "time_signature": self.time_signature,
            "parts_difficulty": self.parts_difficulty, "brief": self.brief, "cost_usd": float(self.cost_usd), "model": self.model,
            "landmarks": self.landmarks, "landmarks_dropped": self.landmarks_dropped,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "PageLabels":
        return PageLabels(
            int(d.get("first_measure_number") or 1), bool(d.get("is_pickup")), d.get("confidence") or "low", d.get("systems") or [],
            {int(k): v for k, v in (d.get("rehearsal_marks") or {}).items()}, {int(k): v for k, v in (d.get("doubtful") or {}).items()},
            d.get("title") or "", d.get("composer") or "", d.get("key_signature"), d.get("time_signature"),
            {k: int(v) for k, v in (d.get("parts_difficulty") or {}).items()}, d.get("brief") or "",
            d.get("landmarks") or [], d.get("landmarks_dropped") or [],
            Decimal(str(d.get("cost_usd") or 0)), d.get("model") or "",
        )


CANON = {"Violoncello": "Cello", "Contrabass": "Double bass", "Pianoforte": "Piano", "Klavier": "Piano", "Pf.": "Piano", "Pf": "Piano",
         "Piano 1": "Piano I", "Piano 2": "Piano II", "Violin 1": "Violin I", "Violin 2": "Violin II"}


def canon_part(name: str) -> str:
    n = re.sub(r"\s+", " ", str(name)).strip().rstrip(".")
    return CANON.get(n, n)


def annotated_png(page_png: bytes, geo: dict[str, Any]) -> bytes:
    """The page with system boxes (grey) and numbered measure boxes (blue) drawn on it; `geo` is the page record of
    `cut.page_measures` (boxes as fractions of the page)."""
    im = Image.open(io.BytesIO(page_png)).convert("RGB")
    W, H = im.size
    d = ImageDraw.Draw(im)
    size = max(18, W // 45)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size)
    except Exception:  # noqa: BLE001
        font = ImageFont.load_default()

    def px(b: dict[str, float]) -> list[int]:
        return [int(round(b["x0"] * W)), int(round(b["y0"] * H)), int(round(b["x1"] * W)), int(round(b["y1"] * H))]

    for s in geo["systems"]:
        d.rectangle(px(s["box"]), outline=(90, 90, 90), width=2)
    for m in geo["measures"]:
        b = px(m["box"])
        d.rectangle(b, outline=(0, 110, 220), width=3)
        label = str(m["provisional"])
        tw = int(d.textlength(label, font=font)) + 8
        d.rectangle([b[0] + 3, b[1] + 3, b[0] + 3 + tw, b[1] + size + 8], fill=(255, 255, 255))
        d.text((b[0] + 7, b[1] + 2), label, fill=(0, 110, 220), font=font)
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError(f"Spark returned no JSON: {text[:200]!r}")
    return json.loads(text[start : end + 1])


def page_landmarks(raw: Any, n_boxes: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(kept, dropped) from Spark's `landmarks` answer. A landmark is kept only when it names a kind the book records,
    has printed text and points at a box drawn on this page (1..n_boxes); a missing, null or out-of-range box is
    dropped, never guessed: the box is how geometry gives it a bar number."""
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for d in raw if isinstance(raw, list) else []:
        if not isinstance(d, dict):
            continue
        kind = str(d.get("kind") or "").strip().lower().replace(" ", "_").replace("-", "_")
        text = re.sub(r"\s+", " ", str(d.get("text") or d.get("label") or "")).strip()
        box = d.get("provisional_measure")
        box = _int(box, -1) if not isinstance(box, bool) else -1
        item = {"kind": kind, "text": text, "provisional": box}
        if kind not in PAGE_LANDMARK_KINDS:
            dropped.append({**item, "why": f"kind {kind or 'missing'}"})
        elif not text and kind not in ("double_bar", "segno", "coda", "fine"):
            dropped.append({**item, "why": "no text"})
        elif not 1 <= box <= n_boxes:
            dropped.append({**item, "why": "no box" if d.get("provisional_measure") is None else f"box {d.get('provisional_measure')!r} not on the page"})
        elif not any(k["kind"] == kind and k["provisional"] == box and k["text"].lower() == text.lower() for k in kept):
            kept.append(item)
    return kept, dropped


def _int(v: Any, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def parts_context(known: list[str]) -> str:
    """The parts read on earlier pages, for the label prompt, so a later page with abbreviated or no margin labels is
    named with the names already in use. Not the score header's instruments: on a keyboard page with no margin label
    the header read takes the heading ("Aria.") for the instrument, and the first page then named its part "Aria"."""
    if not known:
        return ""
    return ("Parts already read on earlier pages of this book, in score order: " + "; ".join(known) + ". When a staff belongs to one of these "
            "parts (later pages print abbreviations such as \"Fl.\" or no labels at all), use exactly that name. A part printed with another "
            "name or number (\"Piano II\" where the list has \"Piano\") is a new part: give its printed name.\n")


async def label_page(ctx: JobContext, page_png: bytes, geo: dict[str, Any], *, effort: str = "low", known: list[str] | None = None) -> PageLabels:
    """One Spark call for the page (`geo`: the page record of `cut.page_measures`; `known`: the parts read on earlier
    pages, for naming). Raises on a malformed answer so the worker retries the job."""
    png = annotated_png(page_png, geo)
    systems_desc = ", ".join(f"{s['index']} has {s['staves']} staves" for s in geo["systems"]) or "none"
    prompt = PROMPT.format(n=len(geo["measures"]), systems_desc=systems_desc, parts_context=parts_context(known or []))
    c = await ctx.complete(prompt, effort=effort, max_tokens=8000, image_png_b64=ctx.png_b64(png))
    data = extract_json(c.text)
    out = PageLabels(
        first_measure_number=_int(data.get("first_measure_number"), 1),
        is_pickup=bool(data.get("is_pickup")),
        confidence=str(data.get("confidence") or "low").lower(),
        systems=[{"index": _int(s.get("index"), i + 1), "parts": s.get("parts") or [], "staves_per_part": s.get("staves_per_part") or []}
                 for i, s in enumerate(data.get("systems") or []) if isinstance(s, dict)],
        rehearsal_marks={_int(m.get("provisional_measure"), -1): str(m.get("mark")) for m in (data.get("rehearsal_marks") or []) if isinstance(m, dict)},
        doubtful={_int(m.get("provisional_measure"), -1): str(m.get("reason") or "Spark doubts this bar") for m in (data.get("doubtful_measures") or []) if isinstance(m, dict)},
        title=str(data.get("title") or "").strip().rstrip("."),
        composer=str(data.get("composer") or "").strip().rstrip("."),
        key_signature=(str(data["key_signature"]).strip() or None) if data.get("key_signature") else None,
        time_signature=(str(data["time_signature"]).strip() or None) if data.get("time_signature") else None,
        parts_difficulty={canon_part(p.get("part", "")): max(1, min(5, _int(p.get("difficulty"), 3)))
                          for p in (data.get("parts_difficulty") or []) if isinstance(p, dict) and p.get("part")},
        brief=str(data.get("brief") or "").strip(),
        cost_usd=c.charge.cost_usd,
        model=c.charge.model,
        raw=data,
    )
    out.landmarks, out.landmarks_dropped = page_landmarks(data.get("landmarks"), len(geo["measures"]))
    return out


# ---------------------------------------------------------------- the book's parts: the header and the name matcher

async def read_header(ctx: JobContext, png: bytes, client: AsyncAnthropic, model: str, *, page: int, title: str = "") -> dict[str, Any]:
    """The score header of the first page with music (the part cut's read, `header.py`): one Spark call on the staff
    overlay. Returns the reconciled header (instruments, expected_staves, validation) plus page, cost_usd and the
    overlay PNG; on a page with no system or an answer with no JSON, `expected_staves` None and the reason in `error`
    (the book is then read without the staff recovery, never failed over it)."""
    out: dict[str, Any] = {"page": page, "instruments": [], "expected_staves": None, "cost_usd": 0.0}
    try:
        geom, _, im = page_geometry(png)
    except Exception as e:  # noqa: BLE001
        out["error"] = f"geometry: {type(e).__name__}: {e}"
        return out
    if not geom["systems"]:
        out["error"] = f"no system found on page {page}"
        return out
    ov = overlay_png(im, geom)
    try:
        data = await ask_model(ctx, client, model, hdr.prompt(page, geom, title), ov, max_tokens=hdr.HEADER_MAX_TOKENS, effort="low", require="instruments")
    except NoJSON as e:
        out.update(cost_usd=e.cost_usd, error=str(e))
        return out
    out["cost_usd"] = data.pop("_cost_usd", 0.0)
    out["retries"] = data.pop("_retries", [])
    out["json_repaired"] = data.pop("_repaired", False)
    out.update(hdr.reconcile(data, geom))
    out["expected_staves"] = int(out.get("expected_staves") or 0) or None
    out["overlay_png"] = ov
    return out


def _plain(name: str) -> tuple[str, ...]:
    """Lower-case words without punctuation, each made singular ("Double Basses" -> ("double", "bass"))."""
    out = []
    for t in re.findall(r"[a-zäöüß]+|\d+", str(name).lower()):
        if t.endswith("sses"):
            t = t[:-2]
        elif t.endswith("s") and not t.endswith("ss") and len(t) > 3:
            t = t[:-1]
        out.append(t)
    return tuple(out)


def generic_name(name: str, pool: list[str]) -> bool:
    """A bare family name ("Horn", "Clarinets": the family's word and nothing else, no numeral) that is not itself one of
    the book's parts, where the book has two or more parts of that family, so it names no one part (004 speed eval:
    effort minimal named Rach 1's horns "Horn", "Horn" in 1 of 4 chains). "Bass Trombone" or "Horns in D" say more than
    the family; "Flutes" when the earlier pages read "Flutes" is that part."""
    fam = hdr.family(name)
    if fam is None or hdr.numerals(name):
        return False
    words = [t for t in hdr.tokens(name) if t not in hdr.IGNORE and t not in hdr.ROMAN]
    if not words or any(t not in hdr.SYNONYMS.get(fam, []) for t in words):
        return False
    if any(canon_part(k).lower() == canon_part(name).lower() or _plain(k) == _plain(name) for k in pool):
        return False
    return len({canon_part(k).lower() for k in pool if hdr.family(k) == fam}) >= 2


def doubtful_names(systems: list[tuple[int, list[str]]], pool: list[str]) -> list[str]:
    """Why a page's part names cannot be trusted as read: a name given twice in one system (two staves, one part
    name), or a generic family name (`generic_name`) against `pool` (the parts already read and the header's). The
    guard on a page read at effort minimal: a page with any reason is read again at low."""
    why: list[str] = []
    for index, names in systems:
        seen: set[str] = set()
        for n in names:
            k = canon_part(n).lower()
            if k in seen:
                why.append(f"system {index}: {n!r} is given to two parts")
            seen.add(k)
            if generic_name(n, pool):
                why.append(f"system {index}: {n!r} is a family name and the book has several such parts")
    return why


def match_part(name: str, pool: list[str]) -> str | None:
    """The one entry of `pool` that is the same part as `name`, else None. Exact (canonical) names first; then the
    header's synonym families: a numbered name ("Violin I") matches an entry of its family that shares a numeral
    ("Violini I.", or "Flauti I. II." for "Flute I") and never an unnumbered one ("Piano I" is not "Piano": a second
    piano is a new part); an unnumbered name ("Fl.", "Pno.") matches only when its family has exactly one entry.
    Names outside the synonym table match by `header.same_instrument` when exactly one entry does. The exact step
    ignores case, punctuation and plurals ("Double Bass" is "Double Basses", "Flutes I, II" is "Flutes I. II"):
    the synonym table reads "basses" as the voice."""
    c = canon_part(name)
    for k in pool:
        if canon_part(k).lower() == c.lower() or _plain(k) == _plain(c):
            return k
    fam = hdr.family(c)
    if fam is None:
        hits = [k for k in pool if hdr.family(k) is None and hdr.same_instrument(c, k)]
        return hits[0] if len(hits) == 1 else None
    same = [k for k in pool if hdr.family(k) == fam]
    nums = set(hdr.numerals(c))
    if nums:
        same = [k for k in same if set(hdr.numerals(k)) & nums]
    return same[0] if len(same) == 1 else None
