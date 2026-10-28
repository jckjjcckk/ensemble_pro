"""Engraving (features 005 and 010): a digital book's MusicXML becomes pages the reader shows, drawn by MuseScore
Studio 4.7.5 headless on the OMR box (`~/omr/musescore/`, `MU_QT_QPA_PLATFORM=offscreen`, about a second a score).
No model call. The engraver is a separate process over ssh, like Audiveris: nothing here imports it.

Every `musicxml` source that is a book's own notation (an import, or Convert to Digital's transcription; never a split)
gets two layouts, each a run of MuseScore over one job file (SVG pages plus the `.mpos` measure positions):

  display   "Optimised for digital display", the default: a copy of the file with its `<print>` system and page
            breaks removed and `<defaults>` set to an iPad page (3:4 portrait, 210 x 280 mm, the file's own staff
            scaling kept), engraved with a style that turns vertical justification off (`enableVerticalSpread` 0,
            `lastSystemFillLimit` 0): systems sit at their natural distance and a short last page keeps its empty
            space at the bottom instead of stretching the music over it.
  original  "Preserve original formatting": the file as it stands. A transcription carries the scan's page size
            and system breaks (`musicxml_fix`), so MuseScore reproduces the scan's systems; an import carries
            whatever its editor wrote, or MuseScore's defaults.

Each layout is written as `{score_id}/digital/{layout}/p{nnn}.svg` and one `sources` row of kind `engraving`:
`storage_paths` the pages in order, `page_count`, `meta = {layout, source_id (the notation engraved), engine,
page_mm: [w, h], bars: [[number, page, x, y, w, h], ...]}` with the bar boxes as fractions of the page (1-based page)
joined to our bar numbers (the measure numbers of the file's first part, in order; `measures.number`). A re-run
replaces the files and updates the row. The book's chosen layout is `scores.digital_layout` (migration
`20261028230000_engraved_layouts.sql`), default `display`.

Runs as a best-effort step at the end of `omr_convert` and `import_musicxml` (`engrave_step`: the book is ready
either way, the reader falls back to on-device OSMD when no pages exist) and as its own job kind `engrave`
(payload `{score_id, source_id?}`) to engrave again. Failures are plain sentences in `result.engraving.reason`.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import re
import shlex
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from . import Job, JobContext, handler

ENGINE = "musescore-4.7.5"
KIND = "engraving"
LAYOUTS = ("display", "original")
DEFAULT_LAYOUT = "display"
OFFLINE = "The engraving engine is offline"
SVG_TYPE = "image/svg+xml"

# The iPad page: 3:4 portrait (the screen's shape, so a page fills it), in millimetres.
IPAD_PAGE_MM = (210.0, 280.0)
IPAD_MARGIN_MM = (12.0, 14.0)            # left/right, top/bottom
FALLBACK_SCALING = (7.0, 40.0)           # music21's default when a file has no <scaling>: 7 mm per 40 tenths

# MuseScore style (.mss) for the display layout: no vertical justification (systems at their natural distance, the
# rest of the page left empty), no stretching of a short last page.
DISPLAY_STYLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<museScore version="4.70">
  <Style>
    <enableVerticalSpread>0</enableVerticalSpread>
    <lastSystemFillLimit>0</lastSystemFillLimit>
    <pageTwosided>0</pageTwosided>
  </Style>
</museScore>
"""

# `.mpos` coordinates are twelve times the SVG's user units (the SVG is written at 1200 dpi: viewBox units per inch;
# measured on the Goldberg Aria: the first bar's x / 12 = the first staff line's x, system y / 12 = the staff's top).
MPOS_PER_SVG_UNIT = 12.0


class EngraverOffline(RuntimeError):
    pass


class EngraverFailed(RuntimeError):
    pass


def page_key(score_id: str, layout: str, page: int) -> str:
    return f"{score_id}/digital/{layout}/p{page:03d}.svg"


# ---------------------------------------------------------------------------------------------------- the file

def _set(parent: ET.Element, tag: str, text: str) -> ET.Element:
    el = parent.find(tag)
    if el is None:
        el = ET.SubElement(parent, tag)
    el.text = text
    return el


def display_copy(data: bytes) -> bytes:
    """The file re-paged for the iPad: every `<print>` break dropped (its attributes and its page and system layout
    children; an empty `<print>` goes), `<defaults>` page layout set to the iPad page in the file's own tenths (its
    `<scaling>` kept, music21's default when absent), system and staff layout defaults dropped so the style decides."""
    prolog = data[: data.find(b"<score-partwise")] if b"<score-partwise" in data else b""
    doctype = re.search(rb"<!DOCTYPE[^>]*>", prolog)
    root = ET.fromstring(data)
    for part in root.findall("part"):
        for m in part.findall("measure"):
            for p in m.findall("print"):
                for a in ("new-system", "new-page", "blank-page", "page-number"):
                    p.attrib.pop(a, None)
                for child in list(p):
                    if child.tag in ("page-layout", "system-layout", "staff-layout"):
                        p.remove(child)
                if not len(p) and not p.attrib:
                    m.remove(p)
    defaults = root.find("defaults")
    if defaults is None:
        defaults = ET.Element("defaults")
        pl = root.find("part-list")
        root.insert(list(root).index(pl), defaults)
    scaling = defaults.find("scaling")
    mm, tenths = FALLBACK_SCALING
    if scaling is not None:
        try:
            mm, tenths = float(scaling.findtext("millimeters") or mm), float(scaling.findtext("tenths") or tenths)
        except ValueError:
            mm, tenths = FALLBACK_SCALING
    else:
        scaling = ET.Element("scaling")
        _set(scaling, "millimeters", f"{mm:g}")
        _set(scaling, "tenths", f"{tenths:g}")
        defaults.insert(0, scaling)
    per_mm = tenths / mm
    for child in list(defaults):
        if child.tag in ("page-layout", "system-layout", "staff-layout"):
            defaults.remove(child)
    page = ET.Element("page-layout")
    w, h = IPAD_PAGE_MM
    mx, my = IPAD_MARGIN_MM
    _set(page, "page-height", f"{h * per_mm:.1f}")
    _set(page, "page-width", f"{w * per_mm:.1f}")
    margins = ET.SubElement(page, "page-margins", type="both")
    for tag, v in (("left-margin", mx), ("right-margin", mx), ("top-margin", my), ("bottom-margin", my)):
        _set(margins, tag, f"{v * per_mm:.1f}")
    defaults.insert(list(defaults).index(scaling) + 1, page)
    ET.indent(root, space="  ")
    out = b'<?xml version="1.0" encoding="UTF-8"?>\n'
    if doctype:
        out += doctype.group(0) + b"\n"
    return out + ET.tostring(root, encoding="utf-8", xml_declaration=False) + b"\n"


def measure_numbers(data: bytes) -> list[int]:
    """The bar numbers of the file's first part in order: what MuseScore's `.mpos` ordinals count (one element per
    measure of the score), and the `measures.number` rows the import and the conversion write. A non-numeric number
    ("X1") counts as the previous number plus one; a pickup written as "0" stays 0."""
    root = ET.fromstring(data)
    part = root.find("part")
    out: list[int] = []
    for m in (part.findall("measure") if part is not None else []):
        raw = (m.get("number") or "").strip()
        try:
            n = int(raw)
        except ValueError:
            digits = re.sub(r"\D", "", raw)
            n = int(digits) if digits else (out[-1] + 1 if out else 1)
        out.append(n)
    return out


# ---------------------------------------------------------------------------------------------------- the positions

_EL = re.compile(r'<element\s+id="(\d+)"\s+x="([^"]+)"\s+y="([^"]+)"\s+sx="([^"]+)"\s+sy="([^"]+)"\s+page="(\d+)"')


def parse_mpos(text: str) -> list[dict[str, Any]]:
    """MuseScore's measure positions: `{ordinal, page (0-based), x, y, w, h}` in `.mpos` units, in file order."""
    return [{"ordinal": int(i), "page": int(p), "x": float(x), "y": float(y), "w": float(sx), "h": float(sy)}
            for i, x, y, sx, sy, p in _EL.findall(text)]


def svg_size(svg: bytes) -> tuple[float, float]:
    """The page's size in the SVG's user units (its viewBox), the frame the `.mpos` coordinates refer to."""
    head = svg[:2000].decode("utf-8", errors="replace")
    m = re.search(r'viewBox="\s*([-\d.]+)\s+([-\d.]+)\s+([\d.]+)\s+([\d.]+)', head)
    if not m:
        raise EngraverFailed("The engraver wrote a page without a size")
    return float(m.group(3)), float(m.group(4))


def svg_size_mm(svg: bytes) -> tuple[float, float] | None:
    head = svg[:2000].decode("utf-8", errors="replace")
    m = re.search(r'width="([\d.]+)mm"\s+height="([\d.]+)mm"', head)
    return (float(m.group(1)), float(m.group(2))) if m else None


def bar_boxes(positions: list[dict[str, Any]], numbers: list[int], page_sizes: list[tuple[float, float]]) -> list[list]:
    """`[number, page (1-based), x, y, w, h]` per bar, the box as fractions of its page, rounded to 4 places. Ordinal
    i is bar `numbers[i]`; an ordinal past the numbers (a measure MuseScore added) is skipped, as is a page the
    engraver wrote no SVG for. A number engraved twice keeps its first box."""
    out: list[list] = []
    seen: set[int] = set()
    for p in positions:
        i, pg = p["ordinal"], p["page"]
        if i >= len(numbers) or pg >= len(page_sizes) or numbers[i] in seen:
            continue
        w, h = page_sizes[pg]
        sx, sy = MPOS_PER_SVG_UNIT * w, MPOS_PER_SVG_UNIT * h
        seen.add(numbers[i])
        out.append([numbers[i], pg + 1, round(p["x"] / sx, 4), round(p["y"] / sy, 4), round(p["w"] / sx, 4), round(p["h"] / sy, 4)])
    return out


# ---------------------------------------------------------------------------------------------------- the box

class SshEngraver:
    """MuseScore on the OMR box over ssh (BatchMode: a key, never a password). One job file per layout: SVG pages and
    the `.mpos` in one run. Everything runs under ~/<root>/<run id>/<layout>."""

    def __init__(self, host: str | None = None, root: str | None = None, musescore: str | None = None, connect_timeout: int = 8):
        self.host = host or os.environ.get("OMR_HOST", "omr")
        self.root = (root or os.environ.get("OMR_ROOT", "omr/folio")).strip("/")
        self.musescore = musescore or os.environ.get("MUSESCORE_BIN", "omr/musescore/squashfs-root/AppRun")
        self.opts = ["-o", "BatchMode=yes", "-o", f"ConnectTimeout={connect_timeout}"]

    async def ssh(self, command: str, stdin: bytes | None = None, timeout: float = 60) -> tuple[int, bytes, bytes]:
        proc = await asyncio.create_subprocess_exec(
            "ssh", *self.opts, self.host, command, stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, err = await asyncio.wait_for(proc.communicate(stdin), timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise EngraverFailed(f"The engraving engine took longer than {int(timeout)} s")
        if proc.returncode == 255:      # ssh's own failure: no route, refused, host key, auth
            raise EngraverOffline(OFFLINE)
        return proc.returncode, out, err

    async def reachable(self) -> bool:
        try:
            rc, _, _ = await self.ssh("true", timeout=20)
        except (EngraverOffline, EngraverFailed, OSError):
            return False
        return rc == 0

    async def engrave(self, run_id: str, layout: str, musicxml: bytes, style: bytes | None, dest: Path) -> dict:
        """Runs MuseScore over the file; leaves `p-1.svg, p-2.svg, ...` and `p.mpos` in `dest`. Returns the timing."""
        if not re.fullmatch(r"[A-Za-z0-9-]+", run_id) or layout not in LAYOUTS:
            raise ValueError("run id must be alphanumeric and the layout known")
        d = f"{self.root}/{run_id}/{layout}"
        q = shlex.quote
        t0 = time.perf_counter()
        await self.ssh(f"mkdir -p {q(d)} && cat > {q(d + '/in.musicxml')}", stdin=musicxml, timeout=120)
        style_arg = ""
        if style:
            await self.ssh(f"cat > {q(d + '/style.mss')}", stdin=style)
            style_arg = f"-S {q(d + '/style.mss')}"
        job = json.dumps([{"in": f"{d}/in.musicxml", "out": [f"{d}/p.svg", f"{d}/p.mpos"]}])
        await self.ssh(f"cat > {q(d + '/job.json')}", stdin=job.encode())
        try:
            rc, out, err = await self.ssh(
                f"cd && MU_QT_QPA_PLATFORM=offscreen QT_QPA_PLATFORM=offscreen {q(self.musescore)} {style_arg} -j {q(d + '/job.json')} > {q(d + '/run.log')} 2>&1; "
                f"rc=$?; test -s {q(d + '/p.mpos')} || rc=$((rc == 0 ? 9 : rc)); echo $rc; tail -c 400 {q(d + '/run.log')}", timeout=180)
            lines = out.decode(errors="replace").strip().splitlines() or ["1"]
            try:
                code = int(lines[0].strip())
            except ValueError:
                code = 1
            if code != 0:
                raise EngraverFailed(_box_error(code, "\n".join(lines[1:]) or err.decode(errors="replace")))
            rc, tar, err = await self.ssh(f"cd {q(d)} && tar -czf - p-*.svg p.mpos", timeout=120)
            if rc != 0:
                raise EngraverFailed(f"Could not fetch the engraved pages: {err.decode(errors='replace')[-200:]}")
            with tarfile.open(fileobj=io.BytesIO(tar), mode="r:gz") as tf:
                tf.extractall(dest, filter="data")
        finally:
            if not os.environ.get("OMR_KEEP"):
                try:
                    await self.ssh(f"rm -rf {q(self.root + '/' + run_id)}", timeout=60)
                except (EngraverOffline, EngraverFailed):
                    pass
        return {"seconds": round(time.perf_counter() - t0, 1)}


    async def render_png(self, run_id: str, musicxml: bytes, dest: Path, dpi: int = 300) -> dict:
        """The file as 300 dpi PNG pages (`p-1.png`, ...) plus `p.mpos` in `dest`: what the verify step of Convert
        (`omr_verify`) shows Spark next to the scan. Same job-file run as `engrave`, under <run id>/verify."""
        if not re.fullmatch(r"[A-Za-z0-9-]+", run_id):
            raise ValueError("run id must be alphanumeric")
        d = f"{self.root}/{run_id}/verify"
        q = shlex.quote
        t0 = time.perf_counter()
        await self.ssh(f"mkdir -p {q(d)} && cat > {q(d + '/in.musicxml')}", stdin=musicxml, timeout=120)
        job = json.dumps([{"in": f"{d}/in.musicxml", "out": [f"{d}/p.png", f"{d}/p.mpos"]}])
        await self.ssh(f"cat > {q(d + '/job.json')}", stdin=job.encode())
        try:
            rc, out, err = await self.ssh(
                f"cd && MU_QT_QPA_PLATFORM=offscreen QT_QPA_PLATFORM=offscreen {q(self.musescore)} -r {int(dpi)} -j {q(d + '/job.json')} > {q(d + '/run.log')} 2>&1; "
                f"rc=$?; test -s {q(d + '/p.mpos')} || rc=$((rc == 0 ? 9 : rc)); echo $rc; tail -c 400 {q(d + '/run.log')}", timeout=300)
            lines = out.decode(errors="replace").strip().splitlines() or ["1"]
            try:
                code = int(lines[0].strip())
            except ValueError:
                code = 1
            if code != 0:
                raise EngraverFailed(_box_error(code, "\n".join(lines[1:]) or err.decode(errors="replace")))
            rc, tar, err = await self.ssh(f"cd {q(d)} && tar -czf - p-*.png p.mpos", timeout=180)
            if rc != 0:
                raise EngraverFailed(f"Could not fetch the rendered pages: {err.decode(errors='replace')[-200:]}")
            with tarfile.open(fileobj=io.BytesIO(tar), mode="r:gz") as tf:
                tf.extractall(dest, filter="data")
        finally:
            if not os.environ.get("OMR_KEEP"):
                try:
                    await self.ssh(f"rm -rf {q(d)}", timeout=60)
                except (EngraverOffline, EngraverFailed):
                    pass
        return {"seconds": round(time.perf_counter() - t0, 1)}


def _box_error(code: int, tail: str) -> str:
    if code == 9:
        return "The engraving engine wrote no pages for this file"
    if code == 134:
        return "The engraving engine crashed on this file"
    tail = " ".join(tail.split())[-160:]
    return f"The engraving engine failed ({tail or code})"


def read_pages(dest: Path) -> tuple[list[bytes], str]:
    """The pages MuseScore wrote (`p-1.svg`, `p-2.svg`, ... in page order) and the `.mpos` text."""
    files = sorted(dest.glob("p-*.svg"), key=lambda f: int(re.sub(r"\D", "", f.stem) or 0))
    if not files:
        raise EngraverFailed("The engraving engine wrote no pages for this file")
    return [f.read_bytes() for f in files], (dest / "p.mpos").read_text()


# ---------------------------------------------------------------------------------------------------- the step

def book_notation(db, score_id: str, source_id: str | None = None) -> dict | None:
    """The `musicxml` source that is the book's own notation: the one asked for, else the transcription when there is
    one (Convert to Digital), else the first import. Never a split (`meta.instruments` / `meta.slug`)."""
    rows = db.table("sources").select("*").eq("score_id", score_id).eq("kind", "musicxml").order("created_at").execute().data or []
    if source_id:
        return next((r for r in rows if r["id"] == source_id), None)
    own = [r for r in rows if not ((r.get("meta") or {}).get("instruments") or (r.get("meta") or {}).get("slug"))]
    transcribed = [r for r in own if (r.get("meta") or {}).get("transcribed_from")]
    return (transcribed or own or [None])[-1]


def _engraving_rows(db, score_id: str) -> list[dict]:
    return db.table("sources").select("id,meta,storage_paths").eq("score_id", score_id).eq("kind", KIND).execute().data or []


async def engrave_layout(ctx: JobContext, box: Any, run_id: str, score_id: str, src: dict, data: bytes, layout: str, numbers: list[int]) -> dict:
    """One layout: MuseScore on the box, the pages to storage, the row written. Returns the row's meta plus timing."""
    file = display_copy(data) if layout == "display" else data
    style = DISPLAY_STYLE if layout == "display" else None
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp)
        timing = await box.engrave(run_id, layout, file, style, dest)
        pages, mpos = read_pages(dest)
    sizes = [svg_size(p) for p in pages]
    bars = bar_boxes(parse_mpos(mpos), numbers, sizes)
    if not bars:
        raise EngraverFailed("The engraver placed no bars on the pages")
    keys = []
    for i, svg in enumerate(pages, start=1):
        key = page_key(score_id, layout, i)
        ctx.storage_upload(key, svg, SVG_TYPE)
        keys.append(key)
    mm = svg_size_mm(pages[0])
    meta = {"layout": layout, "source_id": src["id"], "engine": ENGINE, "page_mm": [round(mm[0], 1), round(mm[1], 1)] if mm else None,
            "bars": bars, "engraved_at": ctx.now()}
    same = [r for r in _engraving_rows(ctx.db, score_id) if (r.get("meta") or {}).get("layout") == layout]
    row = {"storage_paths": keys, "page_count": len(keys), "page_order": list(range(1, len(keys) + 1)), "meta": meta}
    if same:
        ctx.db.table("sources").update(row).eq("id", same[0]["id"]).execute()
        row_id = same[0]["id"]
    else:
        row_id = ctx.db.table("sources").insert({"score_id": score_id, "kind": KIND, "created_by": ctx.job.created_by or src["created_by"], **row}).execute().data[0]["id"]
    return {"source_id": row_id, "pages": len(keys), "bars": len(bars), **timing}


async def engrave_step(ctx: JobContext, score_id: str, source_id: str | None = None, *, box: Any = None, run_id: str | None = None,
                       progress: float = 0.9) -> dict:
    """Both layouts for the book's notation. Never raises: the outcome, with a plain reason when it did not happen,
    goes to `ctx.result["engraving"]` and is returned, so the job that called it stays what it was. `ENGRAVE=off` in
    the environment skips the real box (the test suite, a Mac without the box); a `box` handed in always runs."""
    t0 = time.time()
    out: dict[str, Any] = {}
    try:
        if box is None and os.environ.get("ENGRAVE", "").lower() in ("off", "0", "no"):
            raise EngraverFailed("Engraving is switched off (ENGRAVE=off)")
        src = book_notation(ctx.db, score_id, source_id)
        if src is None:
            raise EngraverFailed("This book has no notation file to engrave")
        key = next((k for k in (src.get("storage_paths") or []) if k.lower().endswith((".musicxml", ".xml", ".mxl"))), None)
        if key is None:
            raise EngraverFailed("This book's notation source holds no MusicXML file")
        data = ctx.storage_download(key)
        if data[:2] == b"PK":
            raise EngraverFailed("A compressed .mxl cannot be engraved yet; import the .musicxml")
        numbers = measure_numbers(data)
        if not numbers:
            raise EngraverFailed("The notation file has no measures")
        box = box or SshEngraver()
        if not await box.reachable():
            raise EngraverOffline(OFFLINE)
        run = run_id or f"{ctx.job.id}-engrave"
        layouts: dict[str, dict] = {}
        for layout in LAYOUTS:
            await ctx.progress(progress, f"Engraving the pages ({'for the iPad' if layout == 'display' else 'as printed'})")
            layouts[layout] = await engrave_layout(ctx, box, run, score_id, src, data, layout, numbers)
        out = {"ok": True, "layouts": layouts, "seconds": round(time.time() - t0, 1)}
    except (EngraverOffline, EngraverFailed) as e:
        out = {"ok": False, "reason": str(e), "seconds": round(time.time() - t0, 1)}
    except Exception as e:  # noqa: BLE001  (the book is ready without pages; the reason is kept, in words)
        out = {"ok": False, "reason": f"The engraving stopped ({type(e).__name__}: {str(e)[:160]})", "seconds": round(time.time() - t0, 1)}
    ctx.result["engraving"] = out
    return out


@handler("engrave")
async def engrave(job: Job, ctx: JobContext, *, box: Any = None) -> dict:
    """Engrave a book again (both layouts). Payload `{score_id, source_id?}`. Fails the job with the plain reason."""
    out = await engrave_step(ctx, job.payload["score_id"], job.payload.get("source_id"), box=box)
    if not out.get("ok"):
        ctx.result["reason"] = out.get("reason")
        raise EngraverFailed(out.get("reason") or "The engraving stopped")
    ctx.result["note"] = f"Engraved {out['layouts']['display']['pages']} pages"
    return out
