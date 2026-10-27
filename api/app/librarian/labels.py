"""Muse Spark 1.3 labels what the geometry found. One call per page, effort low, about $0.008 a page.

Spark sees the page with the geometry's measure boxes drawn and provisionally numbered, and is asked only
for what geometry cannot know: the real number of the first measure, the part names of each system's staves,
rehearsal marks, measures that do not look real, title, composer, key and meter, a 1..5 difficulty per part
and a two-sentence brief. It never moves a box. The call goes through `ctx.complete`, so it is charged to the
job's user with the job id (model from settings: `muse-spark-1.3` when LLM_PROVIDER=meta).

Prompt lifted from `api/experiments/grounding/label_with_spark.py` (experiment README, "Exact prompts"), plus
items 6 and 7.
"""
from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from . import JobContext
from .geometry import PageGeometry

PROMPT = """This is a scanned page of printed sheet music. Blue boxes with provisional numbers (1..{n}, reading left to right, top to bottom) mark the measures that a geometry detector found. Dashed grey boxes mark staff systems; system {systems_desc}.

Answer these questions about the page. Do not re-locate anything; only label what is drawn.
1. first_measure_number: the real measure number of provisional measure 1, using printed measure numbers, rehearsal letters or the musical context if visible; if the page starts with an incomplete pickup bar say so (is_pickup true). If nothing on the page tells you, answer 1 with confidence "low".
2. systems: for each system, the part names of its staves top to bottom (e.g. ["Piano I", "Piano II"] for a two-piano score where each part has two staves; ["Piano"] for a piano grand staff; ["Violin I", "Violin II", "Viola", "Cello"] for a quartet). Give staves_per_part so the counts add up to the staves in that system. Use the names as printed, in English, with Roman numerals for numbered parts.
3. rehearsal_marks: any boxed numbers or letters, with the provisional measure they are attached to.
4. doubtful_measures: provisional measure numbers that do not look like real measures (for example a box that spans only a clef or key signature, or two boxes that are really one bar split by a note stem), each with a reason.
5. title and composer if printed; key_signature (e.g. "G major") and time_signature (e.g. "3/4") as printed at the start, else null.
6. parts_difficulty: for every distinct part name on the page, a difficulty from 1 (easy) to 5 (virtuoso) for an amateur player, judged from the notation on this page.
7. brief: two sentences a librarian would write about this music for the ensemble: what it is and what will take the most work. No preamble.

Return only JSON:
{{"first_measure_number": 1, "is_pickup": false, "confidence": "high|medium|low",
 "systems": [{{"index": 1, "parts": ["Piano"], "staves_per_part": [2]}}],
 "rehearsal_marks": [{{"mark": "1", "provisional_measure": 9}}],
 "doubtful_measures": [{{"provisional_measure": 5, "reason": "..."}}],
 "title": "", "composer": "", "key_signature": null, "time_signature": null,
 "parts_difficulty": [{{"part": "Piano", "difficulty": 3}}],
 "brief": ""}}"""


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
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "PageLabels":
        return PageLabels(
            int(d.get("first_measure_number") or 1), bool(d.get("is_pickup")), d.get("confidence") or "low", d.get("systems") or [],
            {int(k): v for k, v in (d.get("rehearsal_marks") or {}).items()}, {int(k): v for k, v in (d.get("doubtful") or {}).items()},
            d.get("title") or "", d.get("composer") or "", d.get("key_signature"), d.get("time_signature"),
            {k: int(v) for k, v in (d.get("parts_difficulty") or {}).items()}, d.get("brief") or "",
            Decimal(str(d.get("cost_usd") or 0)), d.get("model") or "",
        )


CANON = {"Violoncello": "Cello", "Contrabass": "Double bass", "Pianoforte": "Piano", "Klavier": "Piano", "Pf.": "Piano", "Pf": "Piano",
         "Piano 1": "Piano I", "Piano 2": "Piano II", "Violin 1": "Violin I", "Violin 2": "Violin II"}


def canon_part(name: str) -> str:
    n = re.sub(r"\s+", " ", str(name)).strip().rstrip(".")
    return CANON.get(n, n)


def annotated_png(page_png: bytes, geo: PageGeometry) -> bytes:
    """The page with system boxes (grey) and numbered measure boxes (blue) drawn on it."""
    im = Image.open(io.BytesIO(page_png)).convert("RGB")
    W, H = im.size
    d = ImageDraw.Draw(im)
    size = max(18, W // 45)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size)
    except Exception:  # noqa: BLE001
        font = ImageFont.load_default()
    for s in geo.systems:
        b = s.box.to_px(W, H)
        d.rectangle([b["x0"], b["y0"], b["x1"], b["y1"]], outline=(90, 90, 90), width=2)
    for m in geo.measures:
        b = m.box.to_px(W, H)
        d.rectangle([b["x0"], b["y0"], b["x1"], b["y1"]], outline=(0, 110, 220), width=3)
        label = str(m.provisional)
        tw = int(d.textlength(label, font=font)) + 8
        d.rectangle([b["x0"] + 3, b["y0"] + 3, b["x0"] + 3 + tw, b["y0"] + size + 8], fill=(255, 255, 255))
        d.text((b["x0"] + 7, b["y0"] + 2), label, fill=(0, 110, 220), font=font)
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


def _int(v: Any, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


async def label_page(ctx: JobContext, page_png: bytes, geo: PageGeometry, *, effort: str = "low") -> PageLabels:
    """One Spark call for the page. Raises on a malformed answer so the worker retries the job."""
    png = annotated_png(page_png, geo)
    systems_desc = ", ".join(f"{s.index} has {s.staves} staves" for s in geo.systems) or "none"
    prompt = PROMPT.format(n=len(geo.measures), systems_desc=systems_desc)
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
    return out
