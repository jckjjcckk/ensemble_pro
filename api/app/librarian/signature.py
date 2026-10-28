"""The book's musical identity from a scan: key signature and time signature of the first system of page 1.

Meta model: **Muse Spark 1.3**, one closed question (effort low, 8k output budget, JSON-only system prompt, through
`ask.ask_model`), on a crop of the first system that the geometry found (`cut.page_geometry` at the working
resolution, `cut.cut_system`: cleaned, the next system's ink erased, never widened). Spark counts the sharps or flats
and says which, picks major or minor, and reads the time signature as digits or the C / cut-C symbol; the code turns
that into the canonical strings. Spark never places a staff or a bar here, and never judges notes.

Canonical storage (`scores.key_sig`, `scores.meter`; the web parses these, and `import_musicxml` writes the same):
- key_sig `"<Tonic> <mode>"`, the tonic a capital letter with `#` or `-` (music21 spelling): "E- major", "F# minor",
  "C major". Null when Spark is unsure (low confidence, mode unsure, or a key name that contradicts its own count).
- meter `"<num>/<den>"`: "3/4", "6/8"; common time "4/4", cut time "2/2". Null when no time signature is printed at the
  start of the system or Spark is unsure.
"""
from __future__ import annotations

import re
from typing import Any

from anthropic import AsyncAnthropic
from music21 import key as m21key

from . import JobContext
from .ask import NoJSON, ask_model
from .cut import cut_system, page_geometry, to_png

MAX_TOKENS = 8000
SYSTEM = "You are a music librarian reading the opening of a printed score. Answer with strict JSON only, no prose."

PROMPT = """This image is the first system of the first page of a printed score{title}, cut out on its own. Read the signatures printed at the very start of the system, right after the clefs.

1. Key signature. Count the sharps or the flats of the key signature. In an orchestral score read it on the staves of instruments that are not transposing: strings, voices, piano, flutes, oboes, bassoons, trombones. Clarinets, horns and trumpets are written transposed and timpani often carry no signature; ignore those staves. Naturals that only cancel an earlier signature do not count. Answer "sharps", "flats" or "none" and the count, 0 to 7.
2. Mode. A key signature stands for a major key and its relative minor (3 sharps: A major or F# minor). Judge from the opening music on this system: the first chords and bass notes, a raised leading note. Answer "major", "minor", or "unsure" if this system does not tell.
3. Time signature. As printed at the start of the system: two digits (numerator over denominator), or the symbol C ("common") or C with a vertical stroke ("cut"). Answer "none" if no time signature is printed there.

Give each a confidence. Say "low" rather than guess.

Return only JSON:
{{"key": {{"accidental": "sharps|flats|none", "count": 3, "mode": "major|minor|unsure", "name": "F# minor", "confidence": "high|medium|low"}},
 "time": {{"symbol": "digits|common|cut|none", "numerator": 4, "denominator": 4, "confidence": "high|medium|low"}},
 "notes": "one short sentence if anything is odd"}}"""

LETTERS = "ABCDEFG"
DENOMINATORS = {1, 2, 4, 8, 16, 32, 64}


# ---------------------------------------------------------------- canonical strings (no model)

def canonical_key(text: str | None) -> str | None:
    """'f# minor', 'F sharp minor', 'E♭ major', 'Eb', 'e- major', 'B-flat minor', 'fis-moll' -> 'F# minor', 'F# minor',
    'E- major', 'E- major', 'E- major', 'B- minor', 'F# minor'. A name without a mode is major. None for anything else."""
    if not text:
        return None
    t = re.sub(r"\s+", " ", str(text)).strip().rstrip(".")
    t = t.replace("♯", "#").replace("♭", "-")
    t = re.sub(r"[\s-]*sharp", "#", t, flags=re.I)
    t = re.sub(r"[\s-]*flat", "-", t, flags=re.I)
    m = re.match(r"^([A-Ga-g])(##|#|--|-|bb|b|is|es|s)?[\s-]*(major|minor|maj|min|dur|moll)?$", t, re.I)
    if not m:
        return None
    letter, acc, mode = m.group(1).upper(), (m.group(2) or "").lower(), (m.group(3) or "major").lower()
    acc = {"#": "#", "is": "#", "##": "##", "-": "-", "b": "-", "es": "-", "s": "-", "--": "--", "bb": "--"}.get(acc, "")
    return f"{letter}{acc} {'minor' if mode in ('minor', 'min', 'moll') else 'major'}"


def key_from_signature(accidental: str | None, count: Any, mode: str | None) -> str | None:
    """The canonical key for a signature of `count` sharps or flats in `mode`: ('sharps', 3, 'minor') -> 'F# minor',
    ('flats', 3, 'major') -> 'E- major', ('none', 0, 'minor') -> 'A minor'. None for an unsure mode or a contradiction."""
    acc = str(accidental or "none").strip().lower()
    mode = str(mode or "").strip().lower()
    if mode not in ("major", "minor"):
        return None
    try:
        n = int(count or 0)
    except (TypeError, ValueError):
        return None
    if acc in ("none", "natural", "naturals"):
        if n != 0:
            return None
    elif acc in ("sharps", "sharp", "#"):
        pass
    elif acc in ("flats", "flat", "b"):
        n = -n
    else:
        return None
    if not -7 <= n <= 7:
        return None
    k = m21key.KeySignature(n).asKey(mode)
    return canonical_key(f"{k.tonic.name} {mode}")


def canonical_meter(text: str | None = None, *, numerator: Any = None, denominator: Any = None, symbol: str | None = None) -> str | None:
    """'3/4', 'C', 'common', '¢', 'cut', 'alla breve', or numerator/denominator -> '3/4', '4/4', '2/2'. None otherwise."""
    sym = str(symbol or "").strip().lower()
    t = str(text or "").strip().lower()
    if sym in ("common", "c") or t in ("c", "common", "common time"):
        return "4/4"
    if sym in ("cut", "alla breve", "¢") or t in ("¢", "cut", "cut time", "alla breve", "c|"):
        return "2/2"
    if sym == "none":
        return None
    if t:
        m = re.match(r"^(\d{1,2})\s*/\s*(\d{1,2})$", t)
        if not m:
            return None
        numerator, denominator = m.group(1), m.group(2)
    try:
        num, den = int(numerator), int(denominator)
    except (TypeError, ValueError):
        return None
    if not 1 <= num <= 32 or den not in DENOMINATORS:
        return None
    return f"{num}/{den}"


def interpret(data: dict[str, Any]) -> dict[str, Any]:
    """Spark's answer -> {key_sig, meter, why}. Null where Spark is unsure; never a guess."""
    why: list[str] = []
    k = data.get("key") if isinstance(data.get("key"), dict) else {}
    t = data.get("time") if isinstance(data.get("time"), dict) else {}
    key_sig = None
    if str(k.get("confidence") or "low").lower() == "low":
        why.append("key: low confidence")
    else:
        key_sig = key_from_signature(k.get("accidental"), k.get("count"), k.get("mode"))
        if key_sig is None:
            why.append(f"key: no key for {k.get('count')} {k.get('accidental')}, mode {k.get('mode')}")
        else:
            named = canonical_key(k.get("name"))
            if k.get("name") and named and named != key_sig:
                why.append(f"key: Spark named {k.get('name')!r} but counted {k.get('count')} {k.get('accidental')} ({key_sig})")
                key_sig = None
    meter = None
    if str(t.get("confidence") or "low").lower() == "low":
        why.append("time: low confidence")
    else:
        meter = canonical_meter(numerator=t.get("numerator"), denominator=t.get("denominator"), symbol=t.get("symbol") or "digits")
        if meter is None:
            why.append(f"time: {t.get('symbol')} {t.get('numerator')}/{t.get('denominator')} not read as a meter")
    return {"key_sig": key_sig, "meter": meter, "why": why}


# ---------------------------------------------------------------- the crop and the call

def first_system_crop(png: bytes) -> tuple[bytes, dict[str, Any]] | None:
    """The first system of the page, cleaned (the next system's ink erased), at the working resolution; None when the
    geometry finds no system."""
    geom, bw, page = page_geometry(png)
    if not geom["systems"]:
        return None
    system = geom["systems"][0]
    crop, box, checks = cut_system(bw, page, geom, system, list(system["staff_indices"]))
    return to_png(crop), {"system": 1, "staves": len(system["staff_indices"]), "box_px": box, "image_px": geom["image_px"], "crop_px": [crop.width, crop.height],
                          "mode": checks.get("mode")}


async def read_signature(ctx: JobContext, png: bytes, client: AsyncAnthropic, model: str, *, title: str = "") -> dict[str, Any]:
    """One Spark call on page 1's first system. Returns {key_sig, meter, read, crop, cost_usd, why[, error]}; a page
    with no system or a call that never gives JSON returns nulls with the reason, never raises."""
    out: dict[str, Any] = {"key_sig": None, "meter": None, "read": None, "crop": None, "cost_usd": 0.0, "why": []}
    try:
        cut = first_system_crop(png)
    except Exception as e:  # noqa: BLE001  (the geometry failing on page 1 must not fail the book)
        out["error"] = f"geometry: {type(e).__name__}: {e}"
        return out
    if cut is None:
        out["error"] = "no system found on page 1"
        return out
    crop_png, info = cut
    out["crop"] = info
    out["crop_png"] = crop_png
    try:
        data = await ask_model(ctx, client, model, PROMPT.format(title=f" ({title})" if title else ""), crop_png, max_tokens=MAX_TOKENS, effort="low", system=SYSTEM)
    except NoJSON as e:
        out["cost_usd"] = e.cost_usd
        out["error"] = str(e)
        return out
    out["cost_usd"] = data.pop("_cost_usd", 0.0)
    data.pop("_retries", None)
    data.pop("_repaired", None)
    out["read"] = data
    out.update(interpret(data))
    return out
