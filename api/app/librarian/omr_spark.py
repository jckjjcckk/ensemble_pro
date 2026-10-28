"""The two Muse Spark passes of Convert to Digital (feature 005), on top of Audiveris. Spark never places staves or
bars and never judges or re-transcribes notes: it answers closed questions and reads text.

A  verify   one closed question per symbol the grade gate let in (`omr_book` doubtful: tuplets, dynamics,
            fermatas, rests, dots, ornaments, wedges graded under 0.6): a context crop with the symbol boxed in red,
            "what is it really?", one of four options. The answer becomes a deterministic edit (`omr_score`).
B  reread   one call per system: the system crop with every bar boxed and labelled with its global number. Spark
            lists every dynamic and direction word with its centre on its 0-1000 grid and the bar label it reads.
            `place` puts each word on a bar by position, snapped to the Audiveris text glyph and, for a dynamic,
            anchored to the first notehead at or right of its ink; staff by the nearer staff band. When no glyph
            confirms the point and Spark's label names another bar of the system, the label wins (the open
            question of the p1-5 run, decided here: every such case so far was the label's bar).

Ported from `api/experiments/omr/{spark_layers,text_place,crops}.py` (text F1 0.986 on Goldberg p1-5). Two changes:
the reread no longer asks for ornaments (precision 0.60 in the run: Audiveris's own ornaments stay, nothing is
attached to notes by the model), and the prompts say "piano or chamber music" with the system's staff count
instead of "treble + bass staff". Every call: effort low, an 8k output budget, a JSON-only system prompt, one retry
on a truncated or unparseable reply, charged through `ctx.charge` (`ask.ask_model`).
"""

from __future__ import annotations

import asyncio
import io
import re
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .ask import NoJSON, ask_model

MAX_TOKENS = 8000
WORKERS = 6

VERIFY_SYSTEM = "You are a music engraver checking symbols on a scanned page of printed music. Answer with strict JSON only."
VERIFY_OPTIONS = {
    "tuplet": ["tuplet_number", "fingering_digit", "letter_of_word", "nothing_else"],
    "dynamics": ["dynamic_marking", "fingering_digit", "letters_of_word", "nothing_else"],
    "fermata": ["fermata", "slur_or_tie_end", "fingering_or_bracket", "nothing_else"],
    "rest": ["rest", "fingering_digit", "letters_of_word", "nothing_else"],
    "augmentation-dot": ["augmentation_dot", "staccato_dot", "noise_or_nothing", "part_of_text"],
    "ornament": ["ornament", "fingering_digit", "letters_of_word", "nothing_else"],
    "wedge": ["hairpin_wedge", "slur_or_beam", "nothing_else"],
}
VERIFY_PROMPT = """This crop comes from a scanned page of printed piano or chamber music (300 dpi). The red box marks one symbol that an OMR engine read as "{shape}" with low confidence.
Look only inside the red box (use the surroundings as context). What is it really? Pick exactly one of: {options}.
If it is a dynamic marking, give its text (p, pp, mp, mf, f, ff, sf, fp, rf, cresc, dim). If it is a digit or letters, give them.
Return only JSON: {{"verdict": "<one option>", "value": "<text, digit, or dynamic as printed, else empty>", "confidence": "high|medium|low"}}"""

REREAD_SYSTEM = "You are a music engraver reading a scanned page of printed music. Answer with strict JSON only, no prose."
REREAD_PROMPT = """This is one system ({staves}) of a scanned page of printed piano or chamber music, 300 dpi. Blue boxes with yellow numbers mark the measures {first}..{last}; a measure's box covers every staff of the system.

"text": every dynamic marking and direction word printed in or around this system, exactly as printed, one item per word (examples: "p", "mf", "f", "rf", "cresc.", "dim.", "dolce", "poco"). For each give where its ink is, on a 0-1000 grid over this image ((0,0) top-left, (1000,1000) bottom-right): "x" = horizontal centre of the word, "y" = vertical centre. Also give "bar" = the yellow number of the box it sits in or under. Do NOT include fingering digits, the yellow labels, measure numbers, tempo headings (e.g. "Allegretto"), instrument names or movement titles (e.g. "Var. 2").

Return only JSON: {{"text": [{{"text": "p", "x": 120, "y": 640, "bar": {first}}}]}}"""


# ---------------------------------------------------------------------------------------------------- crops

def _font(size: int):
    for cand in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/System/Library/Fonts/Helvetica.ttc"):
        try:
            return ImageFont.truetype(cand, size)
        except OSError:
            continue
    return ImageFont.load_default()


def png_bytes(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


class Cropper:
    """Crops from the 300 dpi scan of one page, in Audiveris's pixel frame (crops.py)."""

    def __init__(self, model: dict, page: int, scan: Image.Image):
        self.page = scan.convert("RGB")
        self.il = next(p["interline"] for p in model["pages"] if p["page"] == page)
        self.measures = [m for m in model["measures"] if m["page"] == page]
        self.systems = {s["system"]: s for s in model["systems"] if s["page"] == page}

    def system_crop(self, system: int, pad_y: float = 4.0) -> tuple[Image.Image, dict]:
        s = self.systems[system]
        py = int(pad_y * self.il)
        x0, x1 = max(0, s["left"] - 2 * self.il), min(self.page.width, s["right"] + self.il)
        y0, y1 = max(0, int(s["top"]) - py), min(self.page.height, int(s["bottom"]) + py)
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

    def symbol_crop(self, inter: dict, ctx: float = 6.0) -> Image.Image:
        x, y, w, h = inter["bounds"]
        c = int(ctx * self.il)
        x0, y0 = max(0, x - c), max(0, y - c)
        x1, y1 = min(self.page.width, x + w + c), min(self.page.height, y + h + c)
        im = self.page.crop((x0, y0, x1, y1))
        ImageDraw.Draw(im).rectangle((x - x0 - 3, y - y0 - 3, x + w - x0 + 3, y + h - y0 + 3), outline=(220, 0, 0), width=3)
        return im


# ---------------------------------------------------------------------------------------------------- placement

GRID = 1000.0
DYNAMICS = {"p", "pp", "ppp", "mp", "mf", "f", "ff", "fff", "sf", "sfz", "fp", "fz", "rf", "rfz", "sfp"}
SNAP_IL = 8.0    # how far (interlines) a Spark point may be from the Audiveris glyph it snaps to
ANCHOR_IL = 3.0  # how far (interlines, horizontally) a dynamic may be from the notehead it anchors to


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


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if -50 <= f <= GRID + 50 else None


def place(items: list[dict[str, Any]], measures: list[dict[str, Any]], staves: list[dict[str, Any]], crop: dict[str, Any],
          glyphs: list[dict[str, Any]] | None = None, heads: list[dict[str, Any]] | None = None,
          interline: float = 20.0) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Spark's words for one system -> (placed, dropped), as text_place.place."""
    placed, dropped = [], []
    by_number = {m["number"]: m for m in measures}
    for it in items:
        text = str(it.get("text", "")).strip() if isinstance(it, dict) else ""
        if not text:
            dropped.append({"item": it, "why": "no text"})
            continue
        kind = "dynamic" if text.rstrip(".").lower() in DYNAMICS else "words"
        x, y = _num(it.get("x")), _num(it.get("y"))
        label = it.get("bar")
        label = int(label) if isinstance(label, (int, float)) or (isinstance(label, str) and label.isdigit()) else None
        if x is not None:
            X, Y = grid_to_page(min(max(x, 0), GRID), min(max(y if y is not None else GRID / 2, 0), GRID), crop)
            g = _snap(X, Y, glyphs or [], interline)
            prefix, left = "", X - interline / 2
            if g is not None:
                X, Y = _centre(g["bounds"])
                prefix, left = "glyph+", g["bounds"][0]
            h = _anchor(left, X, heads or [], interline) if kind == "dynamic" else None
            if h is not None and h["number"] in by_number:
                m, how = by_number[h["number"]], prefix + "head"
            else:
                m, how = bar_at(X, measures)
                how = prefix + how
            if g is None and label in by_number and label != m["number"]:
                # No Audiveris glyph confirms Spark's point and its own bar label disagrees: the label wins (feature
                # 005: Spark's x drifts 50 to 150 px across a barline; its label alone scored text F1 1.00 on p1-5,
                # and every such disagreement in the p1-5 and p1-3 runs was the label's bar).
                m, how = by_number[label], "label-over-x"
        elif label in by_number:
            m, how = by_number[label], "label"
            X = (m["px"][0] + m["px"][2]) / 2
            Y = grid_to_page(0, min(max(y, 0), GRID), crop)[1] if y is not None else None
        else:
            dropped.append({"item": it, "why": "no position and no bar label in this system"})
            continue
        staff, placement = staff_at(Y, staves) if Y is not None else (1, "below")
        left_px, right_px = m["px"][0], m["px"][2]
        placed.append({
            "text": text, "kind": kind, "number": m["number"], "staff": staff, "placement": placement, "how": how,
            "spark_bar": label, "label_agrees": (label == m["number"]) if label is not None else None,
            "x_bar": bar_at(X, measures)[0]["number"] if x is not None else None,
            "frac": round(min(max((X - left_px) / (right_px - left_px), 0.0), 1.0), 3) if right_px > left_px else 0.0,
        })
    return placed, dropped


# ---------------------------------------------------------------------------------------------------- the passes

class Budget:
    """Stops asking once the job has spent its Spark allowance; what is not asked keeps Audiveris's reading."""

    def __init__(self, cap_usd: float, workers: int = WORKERS):
        self.cap, self.spent, self.calls, self.skipped = cap_usd, 0.0, 0, 0
        self.sem = asyncio.Semaphore(workers)   # both passes share it: at most `workers` calls in flight

    def ok(self) -> bool:
        if self.spent >= self.cap:
            self.skipped += 1
            return False
        return True

    def add(self, data: dict | None, cost: float = 0.0) -> None:
        self.spent += float((data or {}).get("_cost_usd", cost))
        self.calls += 1 + len((data or {}).get("_retries", []))


async def _ask(ctx, client, model: str, prompt: str, png: bytes, system: str, budget: Budget) -> dict | None:
    try:
        data = await ask_model(ctx, client, model, prompt, png, max_tokens=MAX_TOKENS, effort="low", retries=1, system=system)
    except NoJSON as e:
        budget.add(None, e.cost_usd)
        return None
    budget.add(data)
    return {k: v for k, v in data.items() if not k.startswith("_")}


async def verify(ctx, client, model: str, doc: dict, scans: dict[int, Image.Image], budget: Budget) -> list[dict]:
    croppers = {p: Cropper(doc, p, im) for p, im in scans.items()}
    todo = [d for d in doc["doubtful"] if d["tag"] in VERIFY_OPTIONS and d["page"] in croppers]

    async def one(d):
        async with budget.sem:
            if not budget.ok():
                return {"inter": d, "answer": None, "skipped": "budget"}
            png = png_bytes(croppers[d["page"]].symbol_crop(d))
            shape = d["shape"] or d["tag"]
            ans = await _ask(ctx, client, model, VERIFY_PROMPT.format(shape=shape, options=", ".join(VERIFY_OPTIONS[d["tag"]])),
                             png, VERIFY_SYSTEM, budget)
            return {"inter": d, "answer": ans}

    return list(await asyncio.gather(*(one(d) for d in todo)))


def place_system(doc: dict, system: dict, answer: dict, crop: dict) -> tuple[list[dict], list[dict]]:
    nums = set(system["numbers"])
    ms = [m for m in doc["measures"] if m["number"] in nums]
    mine = [i for i in doc["inters"] if i["page"] == system["page"] and i["number"] in nums]
    glyphs = [i for i in mine if i["tag"] in ("word", "dynamics")]
    heads = [{"x": i["bounds"][0] + i["bounds"][2] / 2, "number": i["number"]} for i in mine if i["tag"] == "head"]
    il = next(p["interline"] for p in doc["pages"] if p["page"] == system["page"])
    items = answer.get("text") if isinstance(answer.get("text"), list) else []
    return place(items, ms, system["staves"], crop, glyphs=glyphs, heads=heads, interline=il)


async def reread(ctx, client, model: str, doc: dict, scans: dict[int, Image.Image], budget: Budget) -> list[dict]:
    croppers = {p: Cropper(doc, p, im) for p, im in scans.items()}

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
                             png_bytes(im), REREAD_SYSTEM, budget)
        if ans is None:
            return rec
        placed, dropped = place_system(doc, s, ans, crop)
        return rec | {"ok": True, "placed": placed, "dropped": dropped}

    return list(await asyncio.gather(*(one(s) for s in doc["systems"])))
