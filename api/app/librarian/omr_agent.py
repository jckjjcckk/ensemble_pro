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
  reread        one call per system (the crop with every bar boxed and labelled with its global number): Spark lists
                every dynamic and expression phrase with its centre on a 0-1000 grid and the bar label it reads.
                `place` snaps each item to the Audiveris text glyph nearest its point (within 8 interlines): Spark
                says what the ink says, Audiveris says where the ink is. An item no glyph confirms is discarded
                (CK, 2026-10-28 late: Spark may confirm or correct text Audiveris saw, never add free text), and so
                is anything that is only punctuation, digits, a plate or page number, or a hairpin character. A
                dynamic takes the bar of the first notehead at or right of its ink, a word the bar under its ink;
                staff by the nearer staff band. Without a glyph, a word of the fixed expression vocabulary (`VOCABULARY`:
                cresc., dim., dolce, poco a poco, rit., a tempo, ...) is still written, in the bar Spark named, at the note
                nearest its point (CK, 2026-10-28 late). Spark's bar label is otherwise a cross-check. (The per-note items of the
                first v2 build, fingering, pedal and ornaments, are gone: CK judged them worse than main.)
  verify        the closed questions that remain: one per low-grade accidental (`alter`) or ornament the gate let in
                (`omr_book.VERIFY_TAGS`). An accidental verdict never edits a pitch: a disagreement flags the bar. An
                ornament that is not one is removed (ornaments are Spark's to change). The v1 questions on tuplets,
                rests, dots, wedges, fermatas and dynamics are gone: the first four could change a note's duration
                (decision 2026-10-28: Spark never changes a note), the last two are covered by the enrichment.

Every call: effort low (the reread: minimal, on chat completions, `REREAD_EFFORT`), an 8k output budget, a JSON-only
system prompt, one retry on a truncated or unparseable reply, charged through `ctx.charge` (`ask.ask_model`), and recorded against the PDF page it concerns (`Budget`),
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
# 12 calls in flight (was 6) and the reread at effort minimal: speed pass 2026-10-30, Goldberg p1-5, 30 systems,
# 29 s -> 9 s for the reread with text precision/recall 0.898/0.779 against 0.889/0.706 at low (benchmark 2.10).
WORKERS = 12
REREAD_EFFORT = "minimal"
USD_PER_PAGE = 1.00            # the default allowance per PDF page (v1 measured $0.078 a page; v2 asks more per system)
MAX_KIND_QUESTIONS = 6         # front matter longer than this is assumed to have ended: the rest is music
PAGE_KINDS = ("cover", "preface", "contents", "music")
DYNAMICS = {"p", "pp", "ppp", "pppp", "mp", "mf", "f", "ff", "fff", "ffff", "sf", "sfz", "sffz", "fp", "fz", "rf", "rfz", "sfp"}
GRID = 1000.0
SNAP_IL = 8.0    # how far (interlines) a Spark point may be from the Audiveris glyph it snaps to
ANCHOR_IL = 3.0  # how far (interlines, horizontally) a dynamic may be from the notehead it anchors to
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

REREAD_SYSTEM = "You are a music engraver reading a scanned page of printed music. Answer with strict JSON only, no prose."
REREAD_PROMPT = """This is one system ({staves}) of a scanned page of printed piano or chamber music, 300 dpi. Blue boxes with yellow numbers mark the measures {first}..{last}; a measure's box covers every staff of the system.

"text": every dynamic marking and expression phrase printed in or around this system, exactly as printed. Dynamics one item each ("p", "mf", "f", "rf", "sf"). Expression words one item per phrase, not per word ("dolce", "cresc.", "dim.", "cresc. poco a poco", "legato", "a tempo"). For each give where its ink is, on a 0-1000 grid over this image ((0,0) top-left, (1000,1000) bottom-right): "x" = horizontal centre of the item, "y" = vertical centre. Also give "bar" = the yellow number of the box it sits in or under.
Do NOT include hairpins (the long < or > wedge signs are not text), fingering digits, the yellow labels, measure numbers, plate or page numbers, tempo headings (e.g. "Allegretto"), instrument names or movement titles (e.g. "Var. 2"). List only what is printed; an empty list is a fine answer.

Return only JSON: {{"text": [{{"text": "p", "x": 120, "y": 640, "bar": {first}}}]}}"""

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


async def _ask(ctx, client, model: str, prompt: str, png: bytes, system: str, budget: Budget, step: str, page: int | None,
               effort: str = "low") -> dict | None:
    try:
        data = await ask_model(ctx, client, model, prompt, png, max_tokens=MAX_TOKENS, effort=effort, retries=1, system=system)
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

    HEAD_IL = 8.0      # the front-matter crop reaches at least this many interlines above the first staff
    PAD_IL = 4.0       # a system crop's padding above and below (v1's; the text sits within a few interlines)

    def __init__(self, model: dict, page: int, scan: Image.Image):
        self.page = scan.convert("RGB")
        self.il = next(p["interline"] for p in model["pages"] if p["page"] == page)
        self.measures = [m for m in model["measures"] if m["page"] == page]
        self.systems = {s["system"]: s for s in model["systems"] if s["page"] == page}

    def system_box(self, system: int, pad_il: float | None = None) -> tuple[int, int, int, int]:
        s = self.systems[system]
        py = int((self.PAD_IL if pad_il is None else pad_il) * self.il)
        x0, x1 = max(0, s["left"] - 2 * self.il), min(self.page.width, s["right"] + self.il)
        y0, y1 = max(0, int(s["top"]) - py), min(self.page.height, int(s["bottom"]) + py)
        return x0, y0, x1, y1

    def system_crop(self, system: int, labels: bool = True) -> tuple[Image.Image, dict]:
        x0, y0, x1, y1 = self.system_box(system)
        im = self.page.crop((x0, y0, x1, y1))
        if labels:
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
    page of music are music, unasked, except the pages at the very end where the geometry finds no staff: a publisher's
    catalogue or a blank page at the back ("back"), which Audiveris refuses and which failed the whole conversion (E2E
    night 2026-10-31: the Moscheles edition's last three pages, an advertisement, ended a clean 14-page sonata in
    EngineFailed). Only that trailing run is looked at, from the last page back: a page inside the music whose staves the
    geometry misses (a poor scan) still goes to Audiveris, and no other page is rendered for it."""
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
    for rec in reversed(out):        # the back of the book: trailing pages with no staff are not music
        if rec["kind"] != "music" or rec["staves"] is not None:
            break
        rec["staves"] = await asyncio.to_thread(pages.has_staves, rec["pdf_page"])
        if rec["staves"]:
            break
        rec["kind"] = "back"
    for rec in out:
        log.info("page %s: %s%s", rec["pdf_page"], rec["kind"], " (asked)" if rec["asked"] else "")
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


# ---------------------------------------------------------------------------------------------------- text placement

# Expression words Spark may write without an Audiveris glyph (CK, 2026-10-28 late): lower-cased, punctuation stripped;
# a multi-word item passes when every word is in the list.
VOCABULARY = {"cresc", "crescendo", "dim", "dimin", "diminuendo", "decresc", "decrescendo", "dolce", "poco", "a", "rit", "ritard",
              "ritardando", "rall", "rallentando", "accel", "accelerando", "tempo", "espressivo", "espress", "legato", "staccato",
              "cantabile", "sempre", "molto", "piu", "più", "meno", "sostenuto", "tenuto", "marcato", "leggiero", "con", "senza",
              "pedale", "ped", "tr", "fine", "dc", "ds", "d.c", "d.s", "coda"}


def in_vocabulary(text: str) -> bool:
    words = [re.sub(r"[^\w'’]+", "", w).lower().strip("'’") for w in text.split()]
    words = [w.replace("'", "").replace("’", "") for w in words if w]
    return bool(words) and all(w in VOCABULARY for w in words) and words != ["a"]


JUNK_PLATE = re.compile(r"^[\d\s.'’,:/-]+$")           # "07'880.", "34", "1 2 3": digits and punctuation only


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if -50 <= f <= GRID + 50 else None


def junk(text: str) -> str | None:
    """Why a text item is not text: punctuation or digits only (fingering, plate and page numbers), a hairpin
    character, a single letter that is not a dynamic. None when the item may be written."""
    t = text.strip()
    plain = t.rstrip(".").lower()
    if plain in DYNAMICS:
        return None
    if not t:
        return "empty"
    if "<" in t or ">" in t or "\u2329" in t or "\u232a" in t:
        return "a hairpin character"
    if JUNK_PLATE.fullmatch(t):
        return "digits or punctuation only (fingering, a plate or page number)"
    letters = re.findall(r"[^\W\d_]", t)
    if not letters:
        return "no letters"
    if len(letters) == 1 and len(t) <= 2:
        return "a single letter"
    return None


def grid_to_page(x: float, y: float, crop: dict[str, Any]) -> tuple[float, float]:
    (ox, oy), (w, h) = crop["origin"], crop["size"]
    return ox + x / GRID * w, oy + y / GRID * h


def bar_at(px_x: float, measures: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    ms = sorted(measures, key=lambda m: m["px"][0])
    for m in ms:
        if m["px"][0] <= px_x < m["px"][2]:
            return m, "x"
    if px_x < ms[0]["px"][0]:
        return ms[0], "x-before-first"
    if px_x >= ms[-1]["px"][2]:
        return ms[-1], "x-after-last"
    return min(ms, key=lambda m: min(abs(px_x - m["px"][0]), abs(px_x - m["px"][2]))), "x-gap"


def staff_at(px_y: float, staves: list[dict[str, Any]]) -> tuple[int, str]:
    def dist(s):
        return 0.0 if s["top"] <= px_y <= s["bottom"] else min(abs(px_y - s["top"]), abs(px_y - s["bottom"]))
    best = min(range(len(staves)), key=lambda i: (dist(staves[i]), i))
    s = staves[best]
    return best + 1, "above" if px_y < (s["top"] + s["bottom"]) / 2 else "below"


def is_text_glyph(g: dict[str, Any]) -> bool:
    if g.get("tag") == "dynamics":
        return True
    if g.get("tag") != "word":
        return False
    return bool(re.search(r"[A-Za-z]", (g.get("value") or "").strip()))


def _centre(b: list[float]) -> tuple[float, float]:
    return b[0] + b[2] / 2, b[1] + b[3] / 2


def _snap(X: float, Y: float, glyphs: list[dict[str, Any]], interline: float) -> dict[str, Any] | None:
    best, best_d = None, SNAP_IL * interline
    for g in glyphs:
        if not is_text_glyph(g):
            continue
        cx, cy = _centre(g["bounds"])
        d = ((cx - X) ** 2 + (cy - Y) ** 2) ** 0.5
        if d <= best_d:
            best, best_d = g, d
    return best


def _anchor(left: float, X: float, heads: list[dict[str, Any]], interline: float) -> dict[str, Any] | None:
    near = [h for h in heads if h["x"] >= left - interline / 2 and abs(h["x"] - X) <= ANCHOR_IL * interline]
    return min(near, key=lambda h: h["x"]) if near else None


def place(items: list[dict[str, Any]], measures: list[dict[str, Any]], staves: list[dict[str, Any]], crop: dict[str, Any],
          glyphs: list[dict[str, Any]], heads: list[dict[str, Any]], interline: float = 20.0,
          exclude: tuple[str, ...] = ()) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Spark's text items for one system -> (placed, dropped). Only an item an Audiveris text glyph confirms is
    placed (the glyph's centre is the point); `exclude` lists texts never written (the tempo heading)."""
    placed, dropped = [], []
    by_number = {m["number"]: m for m in measures}
    ex = {e.strip().rstrip(".").lower() for e in exclude if e}
    for it in items:
        text = " ".join(str(it.get("text", "")).split()).strip() if isinstance(it, dict) else ""
        why = junk(text)
        if why:
            dropped.append({"item": it, "why": why})
            continue
        if text.rstrip(".").lower() in ex:
            dropped.append({"item": it, "why": "the tempo heading (written by the front-matter read)"})
            continue
        kind = "dynamic" if text.rstrip(".").lower() in DYNAMICS else "words"
        if kind == "dynamic":
            text = text.rstrip(".").lower()
        x, y = _num(it.get("x")), _num(it.get("y"))
        label = it.get("bar")
        label = int(label) if isinstance(label, (int, float)) or (isinstance(label, str) and label.isdigit()) else None
        if x is None:
            dropped.append({"item": it, "why": "no position"})
            continue
        X, Y = grid_to_page(min(max(x, 0), GRID), min(max(y if y is not None else GRID / 2, 0), GRID), crop)
        g = _snap(X, Y, glyphs, interline)
        if g is None:
            # No glyph: only a word of the expression vocabulary may be written, in the bar Spark named (its label alone
            # scored 1.00 on p1-5), at the note nearest its point; anything else is never added.
            if kind == "words" and in_vocabulary(text) and label in by_number:
                m, how = by_number[label], "vocab+label"
                X = min(max(X, m["px"][0]), m["px"][2] - 1)
            else:
                why = "no Audiveris text glyph within 8 interlines" + ("" if kind == "words" and in_vocabulary(text) else " and not an expression word")
                dropped.append({"item": it, "why": why + " (free text is never added)"})
                continue
        else:
            X, Y = _centre(g["bounds"])
            h = _anchor(g["bounds"][0], X, heads, interline) if kind == "dynamic" else None
            if h is not None and h["number"] in by_number:
                m, how = by_number[h["number"]], "glyph+head"
            else:
                m, how = bar_at(X, measures)
                how = "glyph+" + how
        staff, placement = staff_at(Y, staves)
        left_px, right_px = m["px"][0], m["px"][2]
        placed.append({"text": text, "kind": kind, "number": m["number"], "staff": staff, "placement": placement, "how": how,
                       "glyph": g.get("value") if g else None, "spark_bar": label, "label_agrees": (label == m["number"]) if label is not None else None,
                       "frac": round(min(max((X - left_px) / (right_px - left_px), 0.0), 1.0), 3) if right_px > left_px else 0.0})
    return placed, dropped


def place_system(doc: dict, system: dict, answer: dict, crop: dict, exclude: tuple[str, ...] = ()) -> tuple[list[dict], list[dict]]:
    nums = set(system["numbers"])
    ms = [m for m in doc["measures"] if m["number"] in nums]
    mine = [i for i in doc["inters"] if i["page"] == system["page"] and i["number"] in nums]
    glyphs = [i for i in mine if i["tag"] in ("word", "dynamics")]
    heads = [{"x": i["bounds"][0] + i["bounds"][2] / 2, "number": i["number"]} for i in mine if i["tag"] == "head"]
    il = next(p["interline"] for p in doc["pages"] if p["page"] == system["page"])
    items = answer.get("text") if isinstance(answer.get("text"), list) else []
    return place(items, ms, system["staves"], crop, glyphs, heads, interline=il, exclude=exclude)


async def reread(ctx, client, model: str, doc: dict, scans: dict[int, Image.Image], budget: Budget,
                 exclude: tuple[str, ...] = ()) -> list[dict]:
    """One record per system: {page, system, numbers, ok, placed, dropped}."""
    croppers = {p: Cropper(doc, p, im) for p, im in scans.items()}
    pdf_page = {p["page"]: p["pdf_page"] for p in doc["pages"]}

    async def one(s):
        rec = {"page": s["page"], "system": s["system"], "numbers": s["numbers"], "ok": False, "placed": [], "dropped": []}
        if s["page"] not in croppers:
            return rec
        async with budget.sem:
            if not budget.ok():
                return rec | {"skipped": "budget"}
            im, crop = croppers[s["page"]].system_crop(s["system"])
            n = len(s["staves"])
            staves = "treble + bass staff" if n == 2 else f"{n} staves" if n != 1 else "one staff"
            ans = await _ask(ctx, client, model, REREAD_PROMPT.format(staves=staves, first=s["numbers"][0], last=s["numbers"][-1]),
                             png_bytes(im), REREAD_SYSTEM, budget, "reread", pdf_page[s["page"]], effort=REREAD_EFFORT)
        if ans is None:
            return rec
        placed, dropped = place_system(doc, s, ans, crop, exclude)
        return rec | {"ok": True, "placed": placed, "dropped": dropped, "crop": crop}

    return list(await asyncio.gather(*(one(s) for s in doc["systems"])))


def drop_heading(texts: list[dict], exclude: tuple[str, ...]) -> list[dict]:
    """`reread`'s records with the tempo heading taken out afterwards, as `place(exclude=)` would have done: the reread
    runs beside the front-matter read (which finds the heading), so the exclusion is applied once both are back."""
    ex = {e.strip().rstrip(".").lower() for e in exclude if e}
    if not ex:
        return texts
    for rec in texts:
        keep = []
        for it in rec.get("placed") or []:
            if it["text"].rstrip(".").lower() in ex:
                rec["dropped"].append({"item": {"text": it["text"], "bar": it.get("spark_bar")},
                                       "why": "the tempo heading (written by the front-matter read)"})
            else:
                keep.append(it)
        rec["placed"] = keep
    return texts


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
