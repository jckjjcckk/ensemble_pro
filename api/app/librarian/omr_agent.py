"""Librarian agent v2: the Muse Spark stage of Convert to Digital (feature 005), on top of Audiveris. Replaces
`omr_spark` (2026-10-28). Spark never places staves or bars and never changes a note: it sorts pages, reads text
and answers closed questions; everything it says is written by deterministic rules in `omr_enrich`.

The four steps, each a prompt here and a writer in `omr_enrich`:

  page_kinds    before Audiveris. The PDF is rendered on the Mac (PyMuPDF, as the import does) and the 003
                geometry says which pages have staves. A page without staves is front matter by geometry alone
                (the first page of the set, when it has no staves, is taken as the cover). For the first pages
                that do have staves, one closed question per page: cover / preface / contents (a table of contents
                or a thematic index, which prints incipits on staves) / music, until the first page of music;
                every later page is music, unasked. Front-matter pages are recorded, never transcribed; Audiveris
                then runs on the music pages only. The cover page image becomes the book's cover.
  front_matter  one call on the head of the first music page (the top of the page down through the first system,
                at least 8 interlines above its first staff), filling a fixed form: title, composer,
                movement_or_number, tempo_heading, metronome {unit, bpm}, opus, dedication, editor; null where the
                page prints nothing. Written as the file's credits and work metadata, a metronome mark with text
                and number at the head of bar 1, and into the score row where it has no value.
  enrich        one call per system: the system crop (padded so fingering under the lowest staff and a tempo line
                above the top staff are in frame), every bar boxed and labelled with its global number. Spark
                returns items of kind words / dynamic / fingering / pedal / ornament, each anchored by bar number,
                staff (1 = top) and note index within the bar (chords once, grace notes counted, rests not), plus
                the text. Anchors are symbolic on purpose: Spark's bar label alone scored text F1 1.00 on Goldberg
                p1-5 while its pixel x drifted 50 to 150 px (the v1 placement by position is gone with it).
  verify        the closed questions that remain: one per low-grade accidental (`alter`) or ornament the gate let in
                (`omr_book.VERIFY_TAGS`). An accidental verdict never edits a pitch: a disagreement flags the bar. An
                ornament that is not one is removed (ornaments are Spark's to change). The v1 questions on tuplets,
                rests, dots, wedges, fermatas and dynamics are gone: the first four could change a note's duration
                (decision 2026-10-28: Spark never changes a note), the last two are covered by the enrichment.

Every call: effort low, an 8k output budget, a JSON-only system prompt, one retry on a truncated or unparseable
reply, charged through `ctx.charge` (`ask.ask_model`), and recorded against the PDF page it concerns (`Budget`),
within `max_cost_usd` (default $1.00 a page). Past the cap the rest keep Audiveris's reading.
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .ask import NoJSON, ask_model

log = logging.getLogger("folio.omr")

MAX_TOKENS = 8000
WORKERS = 6
USD_PER_PAGE = 1.00            # the default allowance per PDF page (v1 measured $0.078 a page; v2 asks more per system)
MAX_KIND_QUESTIONS = 6         # front matter longer than this is assumed to have ended: the rest is music
PAGE_KINDS = ("cover", "preface", "contents", "music")
ITEM_KINDS = ("words", "dynamic", "fingering", "pedal", "ornament")
DYNAMICS = {"p", "pp", "ppp", "pppp", "mp", "mf", "f", "ff", "fff", "ffff", "sf", "sfz", "sffz", "fp", "fz", "rf", "rfz", "sfp"}
ORNAMENTS = ("mordent", "inverted_mordent", "trill", "turn", "schleifer")
UNITS = {"whole": ("whole", 0), "half": ("half", 0), "quarter": ("quarter", 0), "eighth": ("eighth", 0), "sixteenth": ("16th", 0),
         "dotted-half": ("half", 1), "dotted-quarter": ("quarter", 1), "dotted-eighth": ("eighth", 1)}
FRONT_FIELDS = ("title", "composer", "movement_or_number", "tempo_heading", "metronome", "opus", "dedication", "editor")

# ---------------------------------------------------------------------------------------------------- prompts

PAGE_KIND_SYSTEM = "You are a music librarian sorting the pages of a scanned book of printed music. Answer with strict JSON only."
PAGE_KIND_PROMPT = """This is one page of a scanned book of printed music (page {page} of the file). Which kind of page is it? Pick exactly one:
- "cover": the cover or title page (title, composer, publisher, perhaps a decorative snippet; not the music itself)
- "preface": a preface, foreword, notes, commentary, critical or editorial remarks, a copyright page, a blank page
- "contents": a table of contents or a thematic index (a list of pieces, often with a short incipit of a bar or two each)
- "music": a page of the music itself (staves running across the page, bar after bar)
Return only JSON: {{"kind": "<cover|preface|contents|music>", "confidence": "high|medium|low"}}"""

FRONT_SYSTEM = "You are a music librarian reading the head of the first page of a piece of printed music. Answer with strict JSON only."
FRONT_PROMPT = """This is the top of the first page of music of a scanned printed book (300 dpi): the heading area down through the first system of staves. Read the printed text and fill in this form, using exactly what is printed (original language and spelling, no translation). Put null where the page prints nothing for a field.
{{"title": "the title of the work or piece", "composer": "the composer as printed", "movement_or_number": "the movement title or piece number at the head of the music, e.g. Aria, No. 3, Var. 1, Polonaise", "tempo_heading": "the tempo or character heading at the start of the music, e.g. Allegro con brio, Andante espressivo.", "metronome": {{"unit": "quarter|half|eighth|sixteenth|whole|dotted-quarter|dotted-half|dotted-eighth", "bpm": 72}}, "opus": "the opus or catalogue number, e.g. Op. 40 No. 1, BWV 988", "dedication": "the dedication line, e.g. à Monsieur ...", "editor": "the editor or reviser named on the page"}}
The metronome mark is the small note-symbol = number, usually next to the tempo heading; null when there is none. Do not include fingering digits, dynamics, bar numbers, page numbers, publisher plate numbers or footnotes. Return only the JSON object."""

ENRICH_SYSTEM = "You are a music engraver reading one system of a scanned page of printed music. Answer with strict JSON only, no prose."
ENRICH_PROMPT = """This is one system ({staves}) of a scanned page of printed piano or chamber music, 300 dpi. Blue boxes with yellow numbers mark the measures {first}..{last}; a measure's box covers every staff of the system. Staves are numbered from the top: staff 1 is the top staff{staff_note}.

List every printed marking of these kinds in or around this system, each anchored to the note it is printed at:
- "dynamic": p, pp, ppp, mp, mf, f, ff, fff, sf, sfz, fp, rf, rfz; one item each, exactly as printed.
- "words": expression and direction words or phrases: "dolce", "cresc.", "dim.", "cresc. poco a poco", "legato", "espress.", "rit.", "a tempo". One item per phrase, not per word. A hairpin (the long < or > wedge) is NOT a word: never list hairpins.
- "fingering": the small digits 1 to 5 printed above or below noteheads. One item per note; when a chord carries a stack of digits, give them top to bottom separated by spaces ("5 2").
- "pedal": the "Ped." pedal-down sign (text "Ped.") and the "*" pedal-up sign (text "*").
- "ornament": mordent (short zigzag with a vertical stroke through it), inverted_mordent (short zigzag without a stroke), trill ("tr" or a long zigzag), turn (a sideways S), schleifer; the text is that name.

For every item give "kind", "text" (exactly as printed; for an ornament its name), "bar" (the yellow number of the measure it belongs to), "staff" (1 = top staff) and "note": the note it is printed at, counting the notes and chords of that staff in that measure from left to right starting at 1 (a chord counts once, small grace notes count, rests do not count). A dynamic or word printed between two notes takes the note at or just right of it.
Do NOT include the yellow labels, measure numbers, tempo headings or titles (e.g. "Allegretto", "Var. 2"), instrument names, page numbers or footnotes. Do not invent anything: list only what is printed, and return an empty list when there is nothing.

Return only JSON: {{"items": [{{"kind": "dynamic", "text": "p", "bar": {first}, "staff": 1, "note": 1}}]}}"""

VERIFY_SYSTEM = "You are a music engraver checking symbols on a scanned page of printed music. Answer with strict JSON only."
VERIFY_OPTIONS = {
    "alter": ["sharp", "flat", "natural", "double_sharp", "double_flat", "nothing_else"],
    "ornament": ["ornament", "fingering_digit", "letters_of_word", "nothing_else"],
}
VERIFY_PROMPT = """This crop comes from a scanned page of printed piano or chamber music (300 dpi). The red box marks one symbol that an OMR engine read as "{shape}" with low confidence.
Look only inside the red box (use the surroundings as context). What is it really? Pick exactly one of: {options}.
Return only JSON: {{"verdict": "<one option>", "value": "<the digit or letters if it is one, else empty>", "confidence": "high|medium|low"}}"""


# ---------------------------------------------------------------------------------------------------- budget

class Budget:
    """Stops asking once the job has spent its Spark allowance; what is not asked keeps Audiveris's reading. Every
    call's cost is logged and recorded against the PDF page it concerns (`per_page`), so the book's spend per page
    goes into the source's meta and the job result."""

    def __init__(self, cap_usd: float, workers: int = WORKERS):
        self.cap, self.spent, self.calls, self.skipped = cap_usd, 0.0, 0, 0
        self.per_page: dict[int, float] = {}
        self.per_step: dict[str, float] = {}
        self.sem = asyncio.Semaphore(workers)   # every step shares it: at most `workers` calls in flight

    def ok(self) -> bool:
        if self.spent >= self.cap:
            self.skipped += 1
            return False
        return True

    def add(self, step: str, page: int | None, data: dict | None, cost: float = 0.0) -> None:
        usd = float((data or {}).get("_cost_usd", cost))
        retries = len((data or {}).get("_retries", []))
        self.spent += usd
        self.calls += 1 + retries
        self.per_step[step] = self.per_step.get(step, 0.0) + usd
        if page is not None:
            self.per_page[page] = self.per_page.get(page, 0.0) + usd
        log.info("spark %s page %s: $%.4f%s (book $%.4f of $%.2f)", step, page, usd, f", {retries} retried" if retries else "",
                 self.spent, self.cap)

    def summary(self) -> dict[str, Any]:
        return {"total_usd": round(self.spent, 4), "cap_usd": round(self.cap, 2), "calls": self.calls, "skipped": self.skipped,
                "per_page": {str(p): round(v, 4) for p, v in sorted(self.per_page.items())},
                "per_step": {k: round(v, 4) for k, v in self.per_step.items()}}


async def _ask(ctx, client, model: str, prompt: str, png: bytes, system: str, budget: Budget, step: str, page: int | None) -> dict | None:
    try:
        data = await ask_model(ctx, client, model, prompt, png, max_tokens=MAX_TOKENS, effort="low", retries=1, system=system)
    except NoJSON as e:
        budget.add(step, page, None, e.cost_usd)
        log.warning("spark %s page %s: %s", step, page, e)
        return None
    budget.add(step, page, data)
    return {k: v for k, v in data.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------------------------------- images

def _font(size: int):
    for cand in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/System/Library/Fonts/Helvetica.ttc"):
        try:
            return ImageFont.truetype(cand, size)
        except OSError:
            continue
    return ImageFont.load_default()


def png_bytes(im: Image.Image, max_width: int | None = None) -> bytes:
    if max_width and im.width > max_width:
        im = im.resize((max_width, round(im.height * max_width / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


class Cropper:
    """Crops from the 300 dpi scan of one page, in Audiveris's pixel frame (every box is Audiveris's)."""

    HEAD_IL = 8.0      # the front-matter crop and a system's top pad: at least this many interlines above the first staff
    FOOT_IL = 7.0      # a system's bottom pad: fingering under the lowest staff sits 1 to 4 interlines below it

    def __init__(self, model: dict, page: int, scan: Image.Image):
        self.page = scan.convert("RGB")
        self.il = next(p["interline"] for p in model["pages"] if p["page"] == page)
        self.measures = [m for m in model["measures"] if m["page"] == page]
        self.systems = {s["system"]: s for s in model["systems"] if s["page"] == page}

    def pads(self, system: int) -> tuple[int, int]:
        """Top and bottom padding in pixels: generous, but never past the middle of the gap to the next system (its
        fingering would be read as this system's)."""
        s = self.systems[system]
        above = self.systems.get(system - 1)
        below = self.systems.get(system + 1)
        top = self.HEAD_IL * self.il if above is None else min(self.HEAD_IL * self.il, (s["top"] - above["bottom"]) / 2 + self.il)
        bottom = self.FOOT_IL * self.il if below is None else min(self.FOOT_IL * self.il, (below["top"] - s["bottom"]) / 2 + self.il)
        return int(max(top, self.il)), int(max(bottom, self.il))

    def system_crop(self, system: int) -> tuple[Image.Image, dict]:
        s = self.systems[system]
        pt, pb = self.pads(system)
        x0, x1 = max(0, s["left"] - 2 * self.il), min(self.page.width, s["right"] + self.il)
        y0, y1 = max(0, int(s["top"]) - pt), min(self.page.height, int(s["bottom"]) + pb)
        im = self.page.crop((x0, y0, x1, y1))
        d = ImageDraw.Draw(im)
        font = _font(int(1.6 * self.il))
        for m in self.measures:
            if m["system"] != system:
                continue
            l, t, r, b = m["px"]
            bx = (l - x0, int(t) - y0 - 3, r - x0, int(b) - y0 + 3)
            d.rectangle(bx, outline=(0, 90, 220), width=2)
            label = str(m["number"])
            tw = d.textlength(label, font=font)
            lx, ly = bx[0] + 4, bx[1] - int(1.8 * self.il)
            d.rectangle((lx - 3, ly - 2, lx + tw + 3, ly + int(1.7 * self.il)), fill=(255, 230, 0))
            d.text((lx, ly), label, fill=(0, 0, 0), font=font)
        return im, {"origin": [x0, y0], "size": [x1 - x0, y1 - y0]}

    def head_crop(self) -> Image.Image:
        """The top of the page down through the first system (plus a little), the whole width: the heading area."""
        first = self.systems[min(self.systems)]
        y1 = min(self.page.height, int(first["bottom"]) + int(3 * self.il))
        y1 = max(y1, int(first["top"]) - int(self.HEAD_IL * self.il))
        return self.page.crop((0, 0, self.page.width, y1))

    def symbol_crop(self, inter: dict, ctx: float = 6.0) -> Image.Image:
        x, y, w, h = inter["bounds"]
        c = int(ctx * self.il)
        x0, y0 = max(0, x - c), max(0, y - c)
        x1, y1 = min(self.page.width, x + w + c), min(self.page.height, y + h + c)
        im = self.page.crop((x0, y0, x1, y1))
        ImageDraw.Draw(im).rectangle((x - x0 - 3, y - y0 - 3, x + w - x0 + 3, y + h - y0 + 3), outline=(220, 0, 0), width=3)
        return im


# ---------------------------------------------------------------------------------------------------- page kinds

class PdfPages:
    """The PDF's pages on the Mac: rendered as the import renders them (PyMuPDF, 150 dpi), staves by the 003
    geometry (`cut.page_geometry`). Only what `page_kinds` looks at is rendered."""

    def __init__(self, pdf: bytes):
        import pymupdf
        if b"%PDF-" not in pdf[:1024]:
            raise ValueError("not a PDF")
        self.doc = pymupdf.open(stream=pdf, filetype="pdf")     # no page cap here: a page subset of a long book is fine
        if self.doc.needs_pass:
            raise ValueError("the PDF is locked with a password")
        if self.doc.page_count == 0:
            raise ValueError("the PDF has no pages")
        self._png: dict[int, bytes] = {}

    @property
    def count(self) -> int:
        return self.doc.page_count

    def png(self, page: int) -> bytes:
        if page not in self._png:
            from .import_pdf import render_page
            self._png[page] = render_page(self.doc[page - 1])[0]
        return self._png[page]

    def has_staves(self, page: int) -> bool:
        from .cut import page_geometry
        try:
            geom, _, _ = page_geometry(self.png(page))
        except ValueError:
            return False
        return bool(geom["staves"])


def normalize_kind(data: dict | None) -> tuple[str | None, str | None]:
    if not data:
        return None, None
    kind = str(data.get("kind", "")).strip().lower().replace(" ", "_")
    aliases = {"title_page": "cover", "title": "cover", "front_cover": "cover", "foreword": "preface", "notes": "preface",
               "blank": "preface", "commentary": "preface", "index": "contents", "thematic_index": "contents",
               "table_of_contents": "contents", "contents_or_thematic_index": "contents", "score": "music", "music_page": "music"}
    kind = aliases.get(kind, kind)
    return (kind if kind in PAGE_KINDS else None), (str(data.get("confidence") or "") or None)


async def page_kinds(ctx, client, model: str, pages: PdfPages, wanted: list[int] | None, budget: Budget,
                     max_asked: int = MAX_KIND_QUESTIONS) -> list[dict]:
    """One record per page of the set, in order: {pdf_page, staves, kind, asked, confidence}. Pages after the first
    page of music are music, unasked."""
    order = wanted or list(range(1, pages.count + 1))
    out: list[dict] = []
    asked, music = 0, False
    for i, pg in enumerate(order):
        rec: dict[str, Any] = {"pdf_page": pg, "staves": None, "kind": "music", "asked": False, "confidence": None}
        if not music:
            rec["staves"] = await asyncio.to_thread(pages.has_staves, pg)
            if not rec["staves"]:
                rec["kind"] = "cover" if i == 0 else "preface"      # no staves: front matter by geometry; first page = cover
            elif asked < max_asked and budget.ok():
                async with budget.sem:
                    ans = await _ask(ctx, client, model, PAGE_KIND_PROMPT.format(page=pg), pages.png(pg), PAGE_KIND_SYSTEM,
                                     budget, "page_kind", pg)
                asked += 1
                kind, conf = normalize_kind(ans)
                rec.update({"asked": True, "kind": kind or "music", "confidence": conf})   # no usable answer: assume music
            if rec["kind"] == "music":
                music = True
        out.append(rec)
        log.info("page %s: %s%s", pg, rec["kind"], " (asked)" if rec["asked"] else "")
    return out


# ---------------------------------------------------------------------------------------------------- front matter

def _str(v: Any) -> str | None:
    if v is None or isinstance(v, (dict, list)):
        return None
    s = " ".join(str(v).split()).strip().strip('"')
    return None if not s or s.lower() in ("null", "none", "n/a", "-", "unknown", "not printed") else s


def normalize_front(data: dict | None) -> dict[str, Any]:
    """The fixed form: every field present, null when unknown; the metronome as {unit, dots, bpm} or null."""
    form: dict[str, Any] = {k: None for k in FRONT_FIELDS}
    if not isinstance(data, dict):
        return form
    for k in FRONT_FIELDS:
        if k != "metronome":
            form[k] = _str(data.get(k))
    mm = data.get("metronome")
    if isinstance(mm, dict):
        unit = str(mm.get("unit") or "quarter").strip().lower().replace("_", "-").replace(" ", "-")
        unit = {"crotchet": "quarter", "minim": "half", "quaver": "eighth", "semiquaver": "sixteenth", "semibreve": "whole",
                "dotted-crotchet": "dotted-quarter", "dotted-minim": "dotted-half", "16th": "sixteenth", "8th": "eighth"}.get(unit, unit)
        try:
            bpm = int(round(float(str(mm.get("bpm")).rstrip("."))))
        except (TypeError, ValueError):
            bpm = None
        if bpm and 20 <= bpm <= 300 and unit in UNITS:
            form["metronome"] = {"unit": unit, "bpm": bpm}
    return form


async def front_matter(ctx, client, model: str, doc: dict, scans: dict[int, Image.Image], budget: Budget) -> dict[str, Any]:
    """The form read from the head of the first page of music (`doc` page 1), with `_ok` saying whether Spark answered."""
    page = doc["pages"][0]["page"] if doc["pages"] else None
    if page is None or page not in scans or not any(s["page"] == page for s in doc["systems"]) or not budget.ok():
        return normalize_front(None) | {"_ok": False}
    pdf_page = doc["pages"][0]["pdf_page"]
    im = Cropper(doc, page, scans[page]).head_crop()
    async with budget.sem:
        ans = await _ask(ctx, client, model, FRONT_PROMPT, png_bytes(im, max_width=1800), FRONT_SYSTEM, budget, "front_matter", pdf_page)
    return normalize_front(ans) | {"_ok": ans is not None}


# ---------------------------------------------------------------------------------------------------- enrichment

def _int(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str) and re.fullmatch(r"\s*\d+\s*", v):
        return int(v)
    return None


def normalize_items(raw: Any, numbers: list[int], n_staves: int) -> tuple[list[dict], list[dict]]:
    """Spark's items for one system -> (items, dropped). Each item: kind, text, number (global bar), staff, note; a
    fingering item's text is its digits ("5 2"), a pedal's "start"/"stop", an ornament's one of ORNAMENTS."""
    items, dropped = [], []
    allowed = set(numbers)
    for it in raw if isinstance(raw, list) else []:
        if not isinstance(it, dict):
            dropped.append({"item": it, "why": "not an object"})
            continue
        kind = str(it.get("kind", "")).strip().lower()
        kind = {"dynamics": "dynamic", "word": "words", "text": "words", "expression": "words", "finger": "fingering",
                "fingerings": "fingering", "ornaments": "ornament", "pedals": "pedal"}.get(kind, kind)
        text = " ".join(str(it.get("text", "")).split()).strip()
        bar, staff, note = _int(it.get("bar")), _int(it.get("staff")), _int(it.get("note"))
        if kind not in ITEM_KINDS or not text:
            dropped.append({"item": it, "why": "no kind or no text"})
            continue
        if bar not in allowed:
            dropped.append({"item": it, "why": f"bar {bar} is not in this system ({numbers[0]}..{numbers[-1]})"})
            continue
        plain = text.rstrip(".").lower()
        if kind == "words" and plain in DYNAMICS:
            kind = "dynamic"
        if kind == "dynamic":
            if plain not in DYNAMICS:
                kind = "words"                                   # "cresc." called a dynamic: it is a word
            else:
                text = plain
        if kind == "fingering":
            digits = re.findall(r"[1-5]", text)
            if not digits or len(digits) > 5:
                dropped.append({"item": it, "why": f"fingering {text!r} is not digits 1 to 5"})
                continue
            if bar == numbers[0] and (note or 1) == 1 and text.strip() == str(numbers[0]):
                # the measure number engraved at the left of a system (Chopin p25: "4" at bar 4 read as a fingering)
                dropped.append({"item": it, "why": f"fingering {text!r} on the first note of bar {bar} is the printed bar number"})
                continue
            text = " ".join(digits)
        if kind == "pedal":
            low = text.lower().replace(" ", "")
            if "*" in low or low in ("up", "stop", "release", "pedalup"):
                text = "stop"
            elif "ped" in low or low in ("down", "start"):
                text = "start"
            else:
                dropped.append({"item": it, "why": f"pedal {text!r} is neither Ped. nor *"})
                continue
        if kind == "ornament":
            name = text.lower().replace(" ", "_").replace("-", "_")
            name = {"tr": "trill", "pralltriller": "inverted_mordent", "short_trill": "inverted_mordent", "inverted-mordent": "inverted_mordent",
                    "mordant": "mordent", "gruppetto": "turn", "slide": "schleifer"}.get(name, name)
            if name not in ORNAMENTS:
                dropped.append({"item": it, "why": f"ornament {text!r} is not one of {', '.join(ORNAMENTS)}"})
                continue
            text = name
        items.append({"kind": kind, "text": text, "number": bar, "staff": min(max(staff or 1, 1), max(n_staves, 1)),
                      "note": max(note or 1, 1), "spark": {"staff": staff, "note": note}})
    return items, dropped


async def enrich(ctx, client, model: str, doc: dict, scans: dict[int, Image.Image], budget: Budget) -> list[dict]:
    """One record per system: {page, system, numbers, ok, items, dropped}."""
    croppers = {p: Cropper(doc, p, im) for p, im in scans.items()}
    pdf_page = {p["page"]: p["pdf_page"] for p in doc["pages"]}

    async def one(s):
        rec = {"page": s["page"], "system": s["system"], "numbers": s["numbers"], "ok": False, "items": [], "dropped": []}
        if s["page"] not in croppers:
            return rec
        async with budget.sem:
            if not budget.ok():
                return rec | {"skipped": "budget"}
            im, crop = croppers[s["page"]].system_crop(s["system"])
            n = len(s["staves"])
            staves = "treble + bass staff" if n == 2 else f"{n} staves" if n != 1 else "one staff"
            staff_note = ", staff 2 the bottom staff" if n == 2 else f", staff {n} the bottom staff" if n > 2 else ""
            prompt = ENRICH_PROMPT.format(staves=staves, first=s["numbers"][0], last=s["numbers"][-1], staff_note=staff_note)
            ans = await _ask(ctx, client, model, prompt, png_bytes(im), ENRICH_SYSTEM, budget, "enrich", pdf_page[s["page"]])
        if ans is None:
            return rec
        items, dropped = normalize_items(ans.get("items"), s["numbers"], len(s["staves"]))
        return rec | {"ok": True, "items": items, "dropped": dropped, "crop": crop}

    return list(await asyncio.gather(*(one(s) for s in doc["systems"])))


# ---------------------------------------------------------------------------------------------------- closed questions

async def verify(ctx, client, model: str, doc: dict, scans: dict[int, Image.Image], budget: Budget) -> list[dict]:
    croppers = {p: Cropper(doc, p, im) for p, im in scans.items()}
    pdf_page = {p["page"]: p["pdf_page"] for p in doc["pages"]}
    todo = [d for d in doc["doubtful"] if d["tag"] in VERIFY_OPTIONS and d["page"] in croppers]

    async def one(d):
        async with budget.sem:
            if not budget.ok():
                return {"inter": d, "answer": None, "skipped": "budget"}
            png = png_bytes(croppers[d["page"]].symbol_crop(d))
            shape = d["shape"] or d["tag"]
            ans = await _ask(ctx, client, model, VERIFY_PROMPT.format(shape=shape, options=", ".join(VERIFY_OPTIONS[d["tag"]])),
                             png, VERIFY_SYSTEM, budget, "verify", pdf_page[d["page"]])
            return {"inter": d, "answer": ans}

    return list(await asyncio.gather(*(one(d) for d in todo)))
