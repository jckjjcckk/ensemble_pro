"""The post-write pass on the MusicXML the Convert-to-Digital merge writes (feature 005). Standard library only, no
model: the experiments (`experiments/omr/score.py`, `apply_edits.py`) import it as well as `omr_convert`.

Two defects of a music21 re-export, both found by engraving our file in MuseScore 4.7
(`experiments/engrave/chopin-op40-1/README.md`, `goldberg/README.md`):

  voices   music21 numbers voices per measure across both staves of a part, so one voice number is the bass in one
           bar and an upper voice in the next. MuseScore's importer binds a voice number to one staff for the whole
           part and silently drops or misfiles the minority uses (Chopin Op. 40/1 page: 586 of 628 notes kept,
           Goldberg Aria 391 of 414). `renumber_voices` gives every staff its own numbers, the convention Audiveris
           writes: staff 1 voices 1-4, staff 2 voices 5-8, and so on. Each voice of a measure goes to the staff
           holding most of its notes there (ties: the lower staff); a cross-staff note keeps its own `<staff>`.
           Notes, durations, `<backup>` and `<forward>` are untouched; `<forward>` and `<direction>` voices follow
           their voice. A staff with more than four voices in one bar gets numbers past the last staff's range.
  tempo    a metronome mark with text comes out of music21 as two directions; `merge_tempo_directions` makes them one
           (words, then metronome), so the heading and the mark draw on one line at the head of the bar.
  wedges   a crescendo whose start wedge says `spread="0"` engraves flat in MuseScore (it reads the height from the
           start); `fix_wedge_spread` drops the zero.
  layout   the merge builds a new score, so Audiveris's `<defaults>` (page size, margins, scaling) and its
           `<credit>`s are lost, and music21 writes "Music21" as composer when none is set. `PageLayout.read` takes
           the `<defaults>` and the title and composer credits from the first Audiveris movement file (the first two
           real text credits: OCR'd fingering digits, specks and one-letter credits are dropped; at most one title and
           one composer); `fix_musicxml` puts them back, writes the title and composer (the score's facts first,
           else the credits' text) into the credits, `<work-title>`, `<movement-title>` (the movement title only when the file has none) and the composer `<creator>`,
           and removes an empty or "Music21" creator. `<print new-system/new-page>` are music21's and are left as is.
"""
from __future__ import annotations

import io
import re
import zipfile
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
import xml.etree.ElementTree as ET

VOICES_PER_STAFF = 4
FALLBACK_PAGE = (1400.0, 1800.0)          # tenths, when no <page-layout> is known: only to place a new credit
_PLACEHOLDER = {"music21", "music21 fragment"}


def _root_of(src: bytes | str | Path) -> ET.Element:
    """A MusicXML root from bytes or a path, `.mxl` (zipped) or plain."""
    data = Path(src).read_bytes() if isinstance(src, (str, Path)) else src
    if data[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(data))
        name = None
        if "META-INF/container.xml" in z.namelist():
            rf = ET.fromstring(z.read("META-INF/container.xml")).find(".//{*}rootfile")
            name = rf.get("full-path") if rf is not None else None
        name = name or next(n for n in z.namelist() if not n.startswith("META-INF") and n.endswith((".xml", ".musicxml")))
        data = z.read(name)
    return ET.fromstring(data)


def _text(c: ET.Element) -> str:
    return " ".join(" ".join((w.text or "").split()) for w in c.findall("credit-words")).strip()


def real_credit(c: ET.Element) -> bool:
    """A credit that says something: at least two letters ("S. Bach.", "op. 40 M1"), not a fingering digit, a speck
    or a stray one-letter read ("4 2", "'*", "p")."""
    return len(re.findall(r"[^\W\d_]", _text(c))) >= 2


@dataclass
class PageLayout:
    defaults: ET.Element | None = None
    credits: dict[str, ET.Element] = field(default_factory=dict)    # "title" / "composer" -> the source's credit

    @classmethod
    def read(cls, src: bytes | str | Path) -> "PageLayout":
        root = _root_of(src)
        d = root.find("defaults")
        roles: dict[str, ET.Element] = {}
        for i, c in enumerate([c for c in root.findall("credit") if real_credit(c)][:2]):
            typed = c.findtext("credit-type")      # untyped: the title if it comes first (Audiveris types composers only)
            role = typed if typed in ("title", "composer") else ("title" if i == 0 else "composer")
            if role not in roles:
                roles[role] = deepcopy(c)
        return cls(deepcopy(d) if d is not None else None, roles)

    def text(self, role: str) -> str:
        c = self.credits.get(role)
        return _text(c) if c is not None else ""


def renumber_voices(root: ET.Element) -> int:
    """Staff s holds voices 4(s-1)+1 .. 4s, in each measure of each part. Returns how many notes changed number."""
    changed = 0
    for part in root.findall("part"):
        measures = part.findall("measure")
        n_staves = max([int(s.text) for m in measures for s in m.iter("staves") if (s.text or "").strip().isdigit()] or [1])
        for m in measures:
            notes = m.findall("note")
            per_voice: dict[str, Counter] = {}
            for n in notes:
                v = n.findtext("voice")
                if v is not None:
                    per_voice.setdefault(v, Counter())[int(n.findtext("staff") or 1)] += 1
            used: Counter = Counter()
            spill = max(n_staves, max((s for c in per_voice.values() for s in c), default=1)) * VOICES_PER_STAFF
            new: dict[str, str] = {}
            for v, staves in per_voice.items():                       # dict order = order of first appearance
                staff = min(staves.items(), key=lambda kv: (-kv[1], kv[0]))[0]
                k = used[staff]
                used[staff] += 1
                if k < VOICES_PER_STAFF:
                    new[v] = str((staff - 1) * VOICES_PER_STAFF + 1 + k)
                else:
                    spill += 1
                    new[v] = str(spill)
            for el in m:
                if el.tag not in ("note", "forward", "direction"):
                    continue
                ve = el.find("voice")
                if ve is not None and ve.text in new and ve.text != new[ve.text]:
                    if el.tag == "note":
                        changed += 1
                    ve.text = new[ve.text]
    return changed


def _credit(role: str, text: str, page: tuple[float, float]) -> ET.Element:
    """A new credit where `restore_defaults.py` put it: the title centred near the top, the composer right."""
    w, h = page
    x, y, just, size = (w / 2, h - 100, "center", "22") if role == "title" else (w - 100, h - 170, "right", "12")
    c = ET.Element("credit", page="1")
    ET.SubElement(c, "credit-type").text = role
    cw = ET.SubElement(c, "credit-words", {"default-x": f"{x:g}", "default-y": f"{y:g}", "justify": just,
                                           "valign": "top", "font-size": size})
    cw.text = text
    return c


def _set_header(root: ET.Element, title: str, composer: str, opus: str | None = None) -> None:
    work = root.find("work")
    if opus:
        if work is None:
            work = ET.Element("work")
            root.insert(0, work)
        wn = work.find("work-number")
        if wn is None:
            wn = ET.Element("work-number")
            work.insert(0, wn)
        wn.text = opus
    if title:
        if work is None:
            work = ET.Element("work")
            root.insert(0, work)
        wt = work.find("work-title")
        if wt is None:
            wt = ET.SubElement(work, "work-title")
        wt.text = title
        mt = root.find("movement-title")
        if mt is None:
            mt = ET.Element("movement-title")
            root.insert(list(root).index(work) + 1, mt)
        if not (mt.text or "").strip() or mt.text.strip().lower() in _PLACEHOLDER:
            mt.text = title                        # a real movement name (music21's movementName, v2 front matter) stays
    else:
        if work is not None:
            wt = work.find("work-title")
            if wt is not None and (not (wt.text or "").strip() or wt.text.strip().lower() in _PLACEHOLDER):
                work.remove(wt)
            if not len(work):
                root.remove(work)
        mt = root.find("movement-title")
        if mt is not None and (not (mt.text or "").strip() or mt.text.strip().lower() in _PLACEHOLDER):
            root.remove(mt)
    ident = root.find("identification")
    if ident is None:
        if not composer:
            return
        ident = ET.Element("identification")
        anchor = root.find("movement-title") if root.find("movement-title") is not None else root.find("work")
        root.insert(list(root).index(anchor) + 1 if anchor is not None else 0, ident)
    creators = [c for c in ident.findall("creator") if c.get("type") == "composer"]
    for c in creators:
        ident.remove(c)
    if composer:
        c = ET.Element("creator", type="composer")
        c.text = composer
        ident.insert(0, c)
    for c in ident.findall("creator"):                                # any other placeholder creator
        if (c.text or "").strip().lower() in _PLACEHOLDER or not (c.text or "").strip():
            ident.remove(c)


def fix_wedge_spread(root: ET.Element) -> int:
    """Audiveris writes the ink's opening on each end of a hairpin: `spread="0"` on a crescendo's start (and on a
    diminuendo's stop). MuseScore takes a hairpin's height from the START wedge's spread, so a crescendo that starts at
    0 is drawn as a flat line (the pre-v2 files had the same). A zero spread on a start is dropped (MuseScore then uses
    its default height); a non-zero one stays. Returns how many were dropped."""
    n = 0
    for w in root.iter("wedge"):
        if w.get("type") in ("crescendo", "diminuendo") and w.get("spread") is not None:
            try:
                zero = float(w.get("spread")) == 0
            except ValueError:
                zero = False
            if zero:
                del w.attrib["spread"]
                n += 1
    return n


def merge_tempo_directions(root: ET.Element) -> int:
    """music21 writes a MetronomeMark with text as two directions at the same spot (the metronome, then the bold words).
    Engravers draw those as two stacked tempo texts; one direction with the words first and the metronome second draws
    "Andante espressivo. (quarter = 72)" as the scan prints it. Returns how many pairs were joined."""
    joined = 0
    for measure in root.iter("measure"):
        children = list(measure)
        for i, el in enumerate(children):
            if el.tag != "direction" or i + 1 >= len(children) or children[i + 1].tag != "direction":
                continue
            nxt = children[i + 1]
            types_a, types_b = el.findall("direction-type"), nxt.findall("direction-type")
            if len(types_a) != 1 or len(types_b) != 1:
                continue
            metro, words = types_a[0].find("metronome"), types_b[0].find("words")
            if metro is None or words is None or el.find("offset") is not None or nxt.find("offset") is not None:
                continue
            if (el.findtext("staff") or "1") != (nxt.findtext("staff") or "1"):
                continue
            el.remove(types_a[0])
            el.insert(0, types_a[0])
            el.insert(0, types_b[0])
            if el.get("placement") is None:
                el.set("placement", nxt.get("placement") or "above")
            measure.remove(nxt)
            joined += 1
    return joined


def fix_musicxml(data: bytes, layout: PageLayout | None = None, *, title: str | None = None,
                 composer: str | None = None, opus: str | None = None) -> bytes:
    """The written file with per-staff voice numbers and, when `layout` is given, Audiveris's page layout and title
    and composer credits. `title` / `composer` are the score's facts; empty ones fall back to the credits' text; `opus` goes to `<work-number>`."""
    prolog = data[: data.find(b"<score-partwise")] if b"<score-partwise" in data else b""
    doctype = re.search(rb"<!DOCTYPE[^>]*>", prolog)
    root = ET.fromstring(data)
    renumber_voices(root)
    merge_tempo_directions(root)
    fix_wedge_spread(root)

    layout = layout or PageLayout()
    title = (title or "").strip() or layout.text("title")
    composer = (composer or "").strip() or layout.text("composer")
    if title.lower() in _PLACEHOLDER:
        title = ""
    if composer.lower() in _PLACEHOLDER:
        composer = ""

    pl = root.find("part-list")
    if layout.defaults is not None:
        for d in root.findall("defaults"):
            root.remove(d)
        root.insert(list(root).index(pl), deepcopy(layout.defaults))
    defaults = root.find("defaults")
    page_el = defaults.find("page-layout") if defaults is not None else None
    page = (float(page_el.findtext("page-width") or FALLBACK_PAGE[0]), float(page_el.findtext("page-height") or FALLBACK_PAGE[1])) \
        if page_el is not None else FALLBACK_PAGE

    if layout.defaults is not None or layout.credits:
        for c in root.findall("credit"):
            root.remove(c)
        new = []
        for role, text in (("title", title), ("composer", composer)):
            src = layout.credits.get(role)
            if src is not None:
                c = deepcopy(src)
                if c.find("credit-type") is None:
                    ct = ET.Element("credit-type")
                    ct.text = role
                    c.insert(0, ct)
                words = c.findall("credit-words")
                if text and words:
                    words[0].text = text
                    for w in words[1:]:
                        c.remove(w)
                if _text(c):
                    new.append(c)
            elif text:
                new.append(_credit(role, text, page))
        at = list(root).index(pl)
        for i, c in enumerate(new):
            root.insert(at + i, c)

    _set_header(root, title, composer, opus)
    ET.indent(root, space="  ")
    out = b'<?xml version="1.0" encoding="UTF-8"?>\n'
    if doctype:
        out += doctype.group(0) + b"\n"
    return out + ET.tostring(root, encoding="utf-8", xml_declaration=False) + b"\n"

