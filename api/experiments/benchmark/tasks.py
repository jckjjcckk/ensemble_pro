"""The model tasks: what is asked, on which image, and how the answer is scored. Prompts are the product's
(app.librarian.header, app.librarian.part_cut) or the 005 experiment's (reread_systems.py, verify_symbols.py),
so a number here is a number about what ships or was measured before.

  header   Muse Spark role: read the score header (003). Page 1 overlay, header.prompt, reconcile, score.
  labels   Muse Spark role: staff labelling for a part (008). Overlay + part_cut.LABEL_PROMPT with the frozen
           header's score-order context.
  text     Muse Spark role: text layer re-read (005 insertion B). One call per system crop, measures numbered.
  closed   Muse Spark role: closed questions on low-grade symbols (005 insertion A). One call per symbol crop.

No task asks a model about notes (Spark never on notes); notes are the OMR engines' (omr.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.librarian import header as hdr
from app.librarian.part_cut import ASK_SYSTEM, LABEL_PROMPT

from . import corpus as C
from . import metrics as M

MODEL_TASKS = ("header", "labels", "text", "closed")
NOTES_TASKS = ("omr",)  # only engines; a model task here would break "Spark never on notes"

TEXT_SYSTEM = "You are a music engraver reading a scanned page of printed piano music. Answer with strict JSON only, no prose."
TEXT_PROMPT = """This is one system (treble + bass staff) of a scanned page of printed piano music, {dpi} dpi. Blue boxes with yellow numbers mark the measures {first}..{last}; a measure's box covers both staves.

For every measure, report what is printed in or just around it, in two lists:
1. "text": dynamics and direction words exactly as printed (examples: "p", "mf", "f", "cresc.", "dolce", "poco"). Do NOT include fingering digits, measure numbers, or tempo headings. Each word separately.
2. "ornaments": every ornament sign (mordent = short zigzag with a vertical stroke through it; inverted mordent / pralltriller = short zigzag without stroke; trill = "tr" or long zigzag; turn = sideways S; schleifer = slanted small zigzag with a tail). For each give: "staff" ("upper" or "lower"), "note_index" = which notehead it sits on counting noteheads left to right in that staff of that measure (1-based; a chord counts once; skip small grace notes), and "kind" (one of mordent, inverted_mordent, trill, turn, schleifer).
Also report "fingering_count": how many small fingering digits are printed in the measure (both staves).

Return only JSON: {{"measures": [{{"number": {first}, "text": [], "ornaments": [{{"staff": "upper", "note_index": 3, "kind": "mordent"}}], "fingering_count": 0}}]}}"""

CLOSED_SYSTEM = "You are a music engraver checking symbols on a scanned page of piano music. Answer with strict JSON only."
CLOSED_OPTIONS = {
    "tuplet": ["tuplet_number", "fingering_digit", "letter_of_word", "nothing_else"],
    "dynamics": ["dynamic_marking", "fingering_digit", "letters_of_word", "nothing_else"],
    "fermata": ["fermata", "slur_or_tie_end", "fingering_or_bracket", "nothing_else"],
    "rest": ["rest", "fingering_digit", "letters_of_word", "nothing_else"],
    "augmentation-dot": ["augmentation_dot", "staccato_dot", "noise_or_nothing", "part_of_text"],
    "ornament": ["ornament", "fingering_digit", "letters_of_word", "nothing_else"],
    "wedge": ["hairpin_wedge", "slur_or_beam", "nothing_else"],
}
CLOSED_PROMPT = """This crop comes from a scanned page of printed piano music ({dpi} dpi). The red box marks one symbol that an OMR engine read as "{shape}" with low confidence.
Look only inside the red box (use the surroundings as context). What is it really? Pick exactly one of: {options}.
If it is a dynamic marking, give its text (p, pp, mp, mf, f, ff, sf, fp, cresc, dim). If it is a digit or letters, give them.
Return only JSON: {{"verdict": "<one option>", "value": "<text, digit, or dynamic as printed, else empty>", "confidence": "high|medium|low"}}"""


@dataclass(frozen=True)
class Item:
    task: str
    id: str            # stable, part of the call id
    page: C.Page
    ref: Any = None    # system id (text), symbol GT entry (closed)


@dataclass
class Request:
    system: str
    prompt: str
    image: bytes
    media_type: str
    image_px: tuple[int, int]
    require: str | None = None


def items(corpus: C.Corpus, task: str) -> list[Item]:
    out: list[Item] = []
    for p in corpus.pages_with(task):
        if task in ("header", "labels"):
            out.append(Item(task, p.id, p))
        elif task == "text":
            layout = corpus.load(p.layout_path)
            lo, hi = min(int(b) for b in p.gt["text"]["bars"]), max(int(b) for b in p.gt["text"]["bars"])
            for s in layout["systems"]:
                ids = [m["id"] for m in layout["measures"] if m["system"] == s["id"]]
                if any(lo - 1 <= i <= hi + 1 for i in ids):
                    out.append(Item(task, f"{p.id}-s{s['id']}", p, s["id"]))
        elif task == "closed":
            for g in p.gt["closed"]:
                out.append(Item(task, f"{p.id}-sym{g['id']}", p, g))
    return out


def _dpi(im, layout: dict) -> int:
    return round(layout["frame_dpi"] * im.width / layout["frame_px"][0])


def image_cache_path(item: Item, res: str) -> Path:
    return C.CACHE / "images" / f"{item.task}-{item.id}@{res}"


def build(corpus: C.Corpus, item: Item, res: str) -> Request:
    """The prompt and image for one item at one resolution (CPU only; the image is cached on disk)."""
    p = item.page
    if item.task == "header":
        geom = corpus.geom(p)
        im = C.overlay(p, res, geom)
        prompt, system, require = hdr.prompt(p.page, geom, corpus.title(p)), ASK_SYSTEM, "instruments"
    elif item.task == "labels":
        geom = corpus.geom(p)
        header = corpus.header(p)
        instrument = p.gt["labels"]["instrument"]
        cand = hdr.match_instrument((header or {}).get("instruments") or [], instrument)
        staves = int(cand.get("staves") or 1) if cand else "unknown"
        desc = "; ".join(f"system {s['index']} = staves {s['staff_indices'][0]}..{s['staff_indices'][-1]}"
                         + (f" ({s['n_measures']} bars)" if s.get("n_measures") is not None else "") for s in geom["systems"])
        prompt = LABEL_PROMPT.format(page=p.page, first=1, last=len(geom["staves"]), systems_desc=desc, instrument=instrument,
                                     staves=staves, header_context=hdr.context(header, instrument, geom))
        im, system, require = C.overlay(p, res, geom), ASK_SYSTEM, "systems"
    elif item.task == "text":
        layout = corpus.load(p.layout_path)
        im, ids = C.system_crop(p, res, layout, item.ref)
        prompt = TEXT_PROMPT.format(dpi=_dpi(C.load_page(p, res), layout), first=min(ids), last=max(ids))
        system, require = TEXT_SYSTEM, "measures"
    elif item.task == "closed":
        layout = corpus.load(p.layout_path)
        sym = next(d for d in layout["doubtful"] if d["id"] == item.ref["id"])
        im = C.symbol_crop(p, res, layout, sym)
        prompt = CLOSED_PROMPT.format(dpi=_dpi(C.load_page(p, res), layout), shape=sym["shape"] or sym["tag"],
                                      options=", ".join(CLOSED_OPTIONS[sym["tag"]]))
        system, require = CLOSED_SYSTEM, None
    else:
        raise ValueError(f"not a model task: {item.task}")
    path = image_cache_path(item, res)
    data, media = C.encode(im)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.with_suffix(".png" if media == "image/png" else ".jpg").write_bytes(data)
    return Request(system, prompt, data, media, (im.width, im.height), require)


def score(corpus: C.Corpus, item: Item, parsed: dict) -> dict[str, Any]:
    p = item.page
    if item.task == "header":
        return M.score_header(hdr.reconcile(parsed, corpus.geom(p)), p.gt["header"])
    if item.task == "labels":
        return M.score_labels(parsed, p.gt["labels"])
    if item.task == "text":
        layout = corpus.load(p.layout_path)
        ids = [m["id"] for m in layout["measures"] if m["system"] == item.ref]
        return M.score_text(M.text_answer_bars(parsed), p.gt["text"]["bars"], ids)
    if item.task == "closed":
        return M.score_closed(parsed, item.ref)
    raise ValueError(item.task)


def zero_score(corpus: C.Corpus, item: Item) -> dict[str, Any]:
    """The score of an item whose answer never parsed: everything wrong, nothing predicted."""
    p = item.page
    if item.task == "header":
        return {"staves_ok": 0, "instruments_ok": 0, "box_ok": 0, "box_n": len(p.gt["header"].get("boxes") or {}), "header_n": 1}
    if item.task == "labels":
        n = len(p.gt["labels"]["systems"])
        return {"systems_ok": 0, "systems_n": n, "page_ok": 0}
    if item.task == "text":
        return score(corpus, item, {"measures": []})
    if item.task == "closed":
        return {"right": 0, "n": 1}
    return {}
