"""The verify step of librarian agent v2 (feature 005, CK's decision 2026-10-28 late): after the digital file is
written, every bar an edit touched is engraved by MuseScore on the box and shown to Spark next to the scan of the
same system, one closed question per system: same text? yes/no, a one-line reason and the measures that differ. On no, the
edits of the named bars (every touched bar of the system when none is named) are reverted (`omr_enrich.Undo`: Audiveris's reading comes back) and the
bars are flagged. The verify calls are charged like every other call and recorded per page (`Budget`, step
`verify_render`).

The render: MuseScore writes one PNG per page at 300 dpi plus the `.mpos` measure positions (`engrave.SshEngraver
.render_png`); a system's box on the page is the union of its bars' boxes (`.mpos` units are 12 per 300 dpi pixel). The
question image is the scan's system (no labels) above the engraved system, both scaled to one width.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from .engrave import measure_numbers, parse_mpos
from .omr_agent import Budget, Cropper, _ask, png_bytes
from .omr_enrich import Undos

log = logging.getLogger("folio.omr")

MPOS_PER_PX_300 = 12.0                               # .mpos units per pixel of a 300 dpi PNG (measured on Chopin p25: 32054 / 2670 px)
PAD_PX = 60                                          # around the engraved system, so text above and below is in frame
MAX_WIDTH = 1600

VERIFY_RENDER_SYSTEM = "You are a music engraver proofreading a transcription against its scanned original. Answer with strict JSON only."
VERIFY_RENDER_PROMPT = """Two images of the same system, measures {first}..{last} of a piece of piano or chamber music. TOP: the scanned original (300 dpi). BOTTOM: our engraving of the transcription (a different engraver: spacing, line breaks, note layout, stems, beams, slurs and hairpin shapes differ; ignore all of that).
Do the words, dynamics and tempo text in the rendering match the scan, ignoring spacing, line breaks and note layout? Compare measure by measure: dynamic letters (p, mf, f, sf, rf ...), expression words (dolce, cresc., dim., poco ...) and tempo text. Fingering digits, plate and page numbers are not text here; hairpins, slurs and ornaments are not text.
Return only JSON: {{"same": true, "reason": "<one line>", "differences": [{{"measure": {first}, "what": "<which text differs and how>"}}]}} ("differences" empty when same is true)."""


def _system_boxes(mpos: str, numbers: list[int], png_sizes: list[tuple[int, int]]) -> dict[int, tuple[int, int, int, int, int]]:
    """Bar number -> (page index, x0, y0, x1, y1) in PNG pixels."""
    out: dict[int, tuple[int, int, int, int, int]] = {}
    for p in parse_mpos(mpos):
        i, pg = p["ordinal"], p["page"]
        if i >= len(numbers) or pg >= len(png_sizes) or numbers[i] in out:
            continue
        x0, y0 = p["x"] / MPOS_PER_PX_300, p["y"] / MPOS_PER_PX_300
        out[numbers[i]] = (pg, int(x0), int(y0), int(x0 + p["w"] / MPOS_PER_PX_300), int(y0 + p["h"] / MPOS_PER_PX_300))
    return out


def engraved_system(pages: list[Image.Image], boxes: dict, bars: list[int]) -> Image.Image | None:
    """The engraved image of the bars (one system of ours; when MuseScore broke it over two lines, both lines)."""
    found = [boxes[n] for n in bars if n in boxes]
    if not found:
        return None
    pg = found[0][0]
    found = [b for b in found if b[0] == pg]
    x0, y0 = min(b[1] for b in found) - PAD_PX, min(b[2] for b in found) - PAD_PX
    x1, y1 = max(b[3] for b in found) + PAD_PX, max(b[4] for b in found) + PAD_PX
    im = pages[pg]
    return im.crop((max(0, x0), max(0, y0), min(im.width, x1), min(im.height, y1)))


def pair_image(scan: Image.Image, render: Image.Image) -> Image.Image:
    w = min(MAX_WIDTH, max(scan.width, render.width))
    a = scan.resize((w, max(1, round(scan.height * w / scan.width))), Image.LANCZOS).convert("RGB")
    b = render.resize((w, max(1, round(render.height * w / render.width))), Image.LANCZOS).convert("RGB")
    gap = 24
    out = Image.new("RGB", (w, a.height + gap + b.height), (255, 255, 255))
    out.paste(a, (0, 0))
    ImageDraw.Draw(out).rectangle((0, a.height + gap // 2 - 2, w, a.height + gap // 2 + 2), fill=(200, 0, 0))
    out.paste(b, (0, a.height + gap))
    return out


def _same(ans: dict | None, numbers: list[int]) -> tuple[bool | None, str, list[int]]:
    """Spark's verdict, its reason, and the measures it names as different (within the system; empty = all)."""
    if not ans:
        return None, "no answer", []
    v = ans.get("same")
    if isinstance(v, str):
        v = v.strip().lower() in ("true", "yes", "same", "y")
    reason = " ".join(str(ans.get("reason") or "").split())[:200]
    named: list[int] = []
    for d in ans.get("differences") if isinstance(ans.get("differences"), list) else []:
        m = d.get("measure") if isinstance(d, dict) else None
        if isinstance(m, (int, float)) and int(m) in numbers:
            named.append(int(m))
        elif isinstance(m, str) and m.strip().isdigit() and int(m) in numbers:
            named.append(int(m))
    return (bool(v) if v is not None else None), reason, sorted(set(named))


async def verify_edits(ctx, client, model: str, engraver: Any, run_id: str, data: bytes, doc: dict, scans: dict[int, Image.Image],
                       undos: Undos, budget: Budget) -> dict[str, Any]:
    """Render `data`, ask per touched system, revert on no. Returns {asked, reverted: {bar: reason}, missing: {bar: reason}
    (text Spark sees on the scan that the file lacks, in bars no edit touched: a flag, not a revert), log, render_s,
    skipped: reason|None}; the caller rewrites the file when `reverted` is not empty."""
    touched = sorted(n for n, u in undos.items() if u.added or u.removed)
    out: dict[str, Any] = {"asked": 0, "reverted": {}, "missing": {}, "log": [], "systems": 0, "skipped": None}
    if not touched:
        return out
    systems = [s for s in doc["systems"] if any(n in touched for n in s["numbers"]) and s["page"] in scans]
    out["systems"] = len(systems)
    if not systems or not budget.ok():
        out["skipped"] = "no budget" if systems else None
        return out
    numbers = measure_numbers(data)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            timing = await engraver.render_png(run_id, data, dest)
            files = sorted(dest.glob("p-*.png"), key=lambda f: int(re.sub(r"\D", "", f.stem) or 0))
            pages = [Image.open(f).convert("RGB") for f in files]
            for im in pages:
                im.load()
            mpos = (dest / "p.mpos").read_text()
    except Exception as e:  # noqa: BLE001  (the file is written already; verifying is best effort)
        out["skipped"] = f"render failed ({type(e).__name__}: {str(e)[:160]})"
        log.warning("verify render: %s", out["skipped"])
        return out
    out["render_s"] = timing.get("seconds") if isinstance(timing, dict) else None
    boxes = _system_boxes(mpos, numbers, [(p.width, p.height) for p in pages])
    pdf_page = {p["page"]: p["pdf_page"] for p in doc["pages"]}
    croppers = {p: Cropper(doc, p, im) for p, im in scans.items()}
    dump = os.environ.get("OMR_VERIFY_DUMP")

    async def one(s: dict) -> dict | None:
        bars = [n for n in s["numbers"] if n in touched]
        render = engraved_system(pages, boxes, s["numbers"])
        if render is None:
            return {"system": s["system"], "page": s["page"], "bars": bars, "same": None, "reason": "no engraved box for these bars"}
        scan, _ = croppers[s["page"]].system_crop(s["system"], labels=False)
        pair = png_bytes(pair_image(scan, render))
        if dump:
            Path(dump).mkdir(parents=True, exist_ok=True)
            (Path(dump) / f"p{s['page']}-sys{s['system']}.png").write_bytes(pair)
        async with budget.sem:
            if not budget.ok():
                return None
            prompt = VERIFY_RENDER_PROMPT.format(first=s["numbers"][0], last=s["numbers"][-1])
            ans = await _ask(ctx, client, model, prompt, pair, VERIFY_RENDER_SYSTEM, budget, "verify_render", pdf_page[s["page"]])
        same, reason, named = _same(ans, s["numbers"])
        return {"system": s["system"], "page": s["page"], "bars": bars, "same": same, "reason": reason, "named": named, "asked": True}

    results = await asyncio.gather(*(one(s) for s in systems))
    for rec in results:
        if rec is None:
            out["skipped"] = "budget spent before every system was checked"
            continue
        out["log"].append(rec)
        if not rec.get("asked"):
            continue
        out["asked"] += 1
        if rec["same"] is False:
            # The bars Spark names: an edited one is reverted; one we never touched gets a flag only (Spark is pointing at
            # text the scan prints and the file lacks, which no revert can supply). Nothing named: every edited bar reverts.
            reason = rec["reason"] or "Spark says the engraved text differs from the scan"
            if rec["named"]:
                for n in rec["named"]:
                    if n in rec["bars"]:
                        undos[n].revert()
                        out["reverted"][n] = reason
                    else:
                        out["missing"][n] = reason
            else:
                for n in rec["bars"]:
                    undos[n].revert()
                    out["reverted"][n] = reason
    return out
