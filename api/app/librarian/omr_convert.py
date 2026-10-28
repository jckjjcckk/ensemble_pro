"""omr_convert: "Convert to Digital" (feature 005). A PDF book gets a second version of itself: a transcription with
flagged bars. The PDF stays the truth and the book's primary source; the web decides which to open.

Meta model: **Muse Spark 1.3** as librarian agent v2 (`omr_agent`, 2026-10-28): it sorts the leading pages (cover,
preface, contents or thematic index, music), reads the front matter of the first page of music into a fixed form,
lists the text, dynamics, fingering, pedal and ornament marks of every system anchored by bar, staff and note, and
answers the closed questions left (low-grade accidentals: flag only; ornaments). Effort low, 8k output budget,
JSON-only system prompts, every call charged through `ctx.charge` and recorded per PDF page. Spark never places
staves or bars and never changes a note; `omr_enrich` writes what it read by fixed rules with a dedupe against what
the bar already holds. The engine is Audiveris 5.11 on the OMR box (a separate process over ssh, AGPL: nothing here
imports it).

Payload `{score_id, source_id?, pages?, max_cost_usd?}`, queued by `POST /scores/{id}/convert` (routes/convert.py).
The job row carries the score in `payload.score_id` and leaves `jobs.score_id` empty on purpose: the worker marks a
job's score `failed` when the job fails and `ctx.progress` moves the score's meter, and neither may touch a ready
PDF book because its conversion failed or is running. `max_attempts` is 1: a retry would pay for Spark again.

Steps:
  1. `omr_agent.page_kinds`: the PDF is rendered on the Mac (PyMuPDF) and the 003 geometry says which pages have
     staves; for the first pages with staves one closed question each, until the first page of music. Front-matter
     pages are recorded in the source's meta, never transcribed; the cover page (the first page when it has no
     staves, or the page Spark calls the cover) is uploaded as `{score_id}/cover.png` and its key written to
     `meta.cover` (the score row has no cover column). No music page: the job fails before the box.
  2. The stored PDF goes to the box over ssh (`OMR_HOST`, default the `omr` alias; runs under `~/OMR_ROOT/<job>`,
     default `~/omr/folio/<job>`); `omr_box.py` runs Audiveris on the music pages only (a page subset is cut into its
     own PDF there), one book per run, no `-sheets`, renders the 300 dpi scans, and the results come back as one
     tar. An unreachable box fails the job with `result.reason` "The transcription engine is offline".
  3. `omr_book` reads the book into the bar map (global bar numbers, Audiveris's boxes, the grade gate at 0.6);
     `omr_score.merge` puts the movements on those numbers (a mismatch fails here).
  4. `omr_agent.front_matter`, `enrich` and `verify` run in parallel (6 calls in flight) within the job's allowance
     (`max_cost_usd`, default $1.00 a page, page-kind questions included); `omr_enrich` writes the answers: the tempo
     line at the head of bar 1, words in italic, dynamics, fingering on the notes, pedal directions, ornaments, each
     deduped against the bar (hairpins, pedals and ornaments Audiveris read are never doubled); accidentals Spark
     disagrees with flag their bar. `flagged_bars` lists every doubtful bar with its page, box and reasons.
  5. The file is written through music21, then `musicxml_fix`: voices numbered per staff (MuseScore drops notes
     otherwise) and the first movement's `<defaults>` and credits put back, the title and composer written into them.
     It goes to `{score_id}/digital/score.musicxml`; a `sources` row of kind `musicxml` records it with
     `meta = {transcribed_from, engine, flags, flagged_bars, pages, parts, page_kinds, cover, front_matter, items,
     cost: {total_usd, per_page, per_step}}` (a re-run replaces the file and updates the same row). The file is read
     back through the import's own `book_facts`: `measures` rows (upsert, never delete); `parts` rows as the import
     writes them when the book has none, else the book's own part names are kept (positionally, when the counts
     agree) and only their `storage_path` moves to the digital file; score facts only where the score has none:
     key, meter, bars, pages, and from the front-matter form composer, work (the opus) and tempo (the metronome Spark
     read from the heading; Audiveris's unchecked marks are still never taken). `status`, `progress` and
     `current_interpretation_id` are not touched.

Result: `{source_id, instruments, bars, flagged_bars (bar numbers), seconds, cost_usd, cost_per_page, pages,
page_kinds, cover, front_matter, items, spark_calls, spark_skipped, timings}`.
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

from anthropic import AsyncAnthropic
from music21 import converter, stream
from PIL import Image

from ..llm import _client as default_client, model_name as default_model
from . import Job, JobContext, handler
from .import_musicxml import book_facts, part_groups, write_measures, write_parts
from .musicxml_fix import PageLayout, fix_musicxml
from .omr_agent import USD_PER_PAGE, Budget, PdfPages, enrich, front_matter, page_kinds, verify
from .omr_book import load_run
from .omr_enrich import apply_front, apply_items, apply_verify
from .omr_score import BarsDoNotLineUp, flagged_bars, merge, movement_files

ENGINE = "audiveris-5.11+spark-v2"
OFFLINE = "The transcription engine is offline"
CONTENT_TYPE = "application/vnd.recordare.musicxml+xml"
MAX_PAGES = 40                 # a book over this is refused before Audiveris runs (about 35 s a page on the box)
BOX_SCRIPT = Path(__file__).with_name("omr_box.py")


class EngineOffline(RuntimeError):
    pass


class EngineFailed(RuntimeError):
    pass


def digital_path(score_id: str) -> str:
    return f"{score_id}/digital/score.musicxml"


def cover_path(score_id: str) -> str:
    return f"{score_id}/cover.png"


# ---------------------------------------------------------------------------------------------------- the box

class SshBox:
    """The OMR box over ssh (BatchMode: a key, never a password). Everything runs under ~/<root>/<run id>."""

    def __init__(self, host: str | None = None, root: str | None = None, connect_timeout: int = 8):
        self.host = host or os.environ.get("OMR_HOST", "omr")
        self.root = (root or os.environ.get("OMR_ROOT", "omr/folio")).strip("/")
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
            raise EngineFailed(f"The transcription engine took longer than {int(timeout)} s")
        if proc.returncode == 255:      # ssh's own failure: no route, refused, host key, auth
            raise EngineOffline(OFFLINE)
        return proc.returncode, out, err

    async def reachable(self) -> bool:
        try:
            rc, _, _ = await self.ssh("true", timeout=20)
        except (EngineOffline, EngineFailed, OSError):
            return False
        return rc == 0

    async def transcribe(self, run_id: str, pdf: bytes, pages: list[int] | None, dest: Path, max_pages: int = MAX_PAGES) -> dict:
        if not re.fullmatch(r"[A-Za-z0-9-]+", run_id):
            raise ValueError("run id must be alphanumeric")
        d = f"{self.root}/{run_id}"
        q = shlex.quote
        t0 = time.perf_counter()
        await self.ssh(f"mkdir -p {q(d)} && cat > {q(d + '/book.pdf')}", stdin=pdf, timeout=120)
        await self.ssh(f"cat > {q(d + '/omr_box.py')}", stdin=BOX_SCRIPT.read_bytes())
        upload_s = time.perf_counter() - t0
        args = f"--pages {q(','.join(map(str, pages)))}" if pages else ""
        n = len(pages) if pages else max_pages
        try:
            rc, out, err = await self.ssh(f"python3 -I {q(d + '/omr_box.py')} {q(d + '/book.pdf')} {q(d + '/out')} --max-pages {max_pages} {args}",
                                          timeout=180 + 90 * n)
            last = (out.decode(errors="replace").strip().splitlines() or ["{}"])[-1]
            try:
                info = json.loads(last)
            except json.JSONDecodeError:
                info = {"error": last[:300] or err.decode(errors="replace")[-300:]}
            if rc != 0:
                raise EngineFailed(_box_error(rc, info))
            t1 = time.perf_counter()
            rc, tar, err = await self.ssh(f"cd {q(d + '/out')} && tar -czf - --exclude=input --exclude='*.omr' .", timeout=300)
            if rc != 0:
                raise EngineFailed(f"Could not fetch the transcription: {err.decode(errors='replace')[-200:]}")
            with tarfile.open(fileobj=io.BytesIO(tar), mode="r:gz") as tf:
                tf.extractall(dest, filter="data")
            pull_s = time.perf_counter() - t1
        finally:
            if not os.environ.get("OMR_KEEP"):
                try:
                    await self.ssh(f"rm -rf {q(d)}", timeout=60)
                except (EngineOffline, EngineFailed):
                    pass
        run = json.loads((dest / "book_run.json").read_text())
        run["upload_s"], run["pull_s"] = round(upload_s, 1), round(pull_s, 1)
        run["box_s"] = round(time.perf_counter() - t0, 1)
        return run


def _box_error(rc: int, info: dict) -> str:
    if rc == 5:
        return f"This PDF has {info.get('pages')} pages; Convert to Digital takes at most {info.get('max_pages')} for now"
    if rc == 2:
        return "The transcription engine could not open this PDF"
    if rc in (3, 4):
        return "The transcription engine could not read this PDF"
    return f"The transcription engine failed ({info.get('error') or rc})"


# ---------------------------------------------------------------------------------------------------- the handler

def pdf_source(db, score_id: str, source_id: str | None = None) -> dict | None:
    q = db.table("sources").select("*").eq("score_id", score_id).eq("kind", "pdf")
    rows = (q.eq("id", source_id) if source_id else q.order("created_at")).execute().data or []
    return rows[0] if rows else None


def _pages(v: Any) -> list[int] | None:
    if not v:
        return None
    pages = sorted({int(n) for n in v if int(n) >= 1})
    return pages or None


async def _fail(ctx: JobContext, exc: Exception) -> None:
    """Record the plain reason on the row (result.reason, result.note) and raise; the worker marks the job failed."""
    ctx.result["reason"] = str(exc)
    await ctx.progress(0.0, str(exc))
    raise exc


def clean_name(name: str) -> str:
    """An instrument name as Audiveris's OCR leaves it, tidied: "Piano I." -> "Piano I", "Piano 11." -> "Piano II"."""
    name = (name or "").strip().rstrip(".:,;").strip()
    head, _, last = name.rpartition(" ")
    if head and re.fullmatch(r"[1Il|]{1,3}", last):
        name = f"{head} {'I' * len(last)}"
    return name


def name_parts(sc: stream.Score, existing: list[str]) -> tuple[list[tuple[str, list]], bool]:
    """The file's parts as the app names them. When the book already has parts rows and the counts agree, the book's
    names win (they were read from the PDF) and are written into the file, so the rows and the file agree for a split.
    Otherwise Audiveris's OCR names, tidied (`clean_name`)."""
    for p in sc.parts:
        p.partName = clean_name(p.partName or "")
    groups = part_groups(sc)
    keep = bool(existing) and len(existing) == len(groups)
    if keep:
        groups = [(name, staves) for name, (_, staves) in zip(existing, groups)]
    for name, staves in groups:
        for p in staves:
            p.partName = name
    return groups, keep


def write_musicxml(sc: stream.Score, page: PageLayout | None = None, opus: str | None = None) -> bytes:
    """The file as written, then `musicxml_fix`: voices numbered per staff (MuseScore drops notes otherwise) and
    Audiveris's page layout and title and composer credits put back (`page`, from the first movement file)."""
    with tempfile.TemporaryDirectory() as tmp:
        fp = Path(tmp) / "score.musicxml"
        sc.write("musicxml", fp=str(fp), makeNotation=False)   # Audiveris bars can overflow; makeNotation would re-bar them
        md = sc.metadata
        return fix_musicxml(fp.read_bytes(), page, title=md.title if md else None, composer=md.composer if md else None, opus=opus)


HEARTBEAT_S = 60


async def _heartbeat(ctx: JobContext) -> None:
    """Keep `jobs.locked_at` fresh: the worker re-queues a `running` job whose lock is older than 15 minutes, and a
    long book on the box can take longer than that (a re-queued copy would pay for Spark twice)."""
    while True:
        await asyncio.sleep(HEARTBEAT_S)
        try:
            ctx.db.table("jobs").update({"locked_at": ctx.now()}).eq("id", ctx.job.id).execute()
        except Exception:  # noqa: BLE001  (a missed beat is not worth failing the run)
            pass


@handler("omr_convert")
async def omr_convert(job: Job, ctx: JobContext, *, box: Any = None, client: AsyncAnthropic | None = None, model: str | None = None,
                      pdf_pages: Any = None) -> dict:
    beat = asyncio.create_task(_heartbeat(ctx))
    try:
        return await _convert(job, ctx, box, client, model, pdf_pages)
    finally:
        beat.cancel()


async def _convert(job: Job, ctx: JobContext, box: Any, client: AsyncAnthropic | None, model: str | None, pdf_pages: Any) -> dict:
    t0 = time.time()
    p = job.payload
    score_id = p["score_id"]
    src = pdf_source(ctx.db, score_id, p.get("source_id"))
    if src is None:
        await _fail(ctx, RuntimeError("This book has no PDF to convert"))
    key = next((k for k in (src.get("storage_paths") or []) if k.lower().endswith(".pdf")), None)
    if key is None:
        await _fail(ctx, RuntimeError("This book's PDF source holds no .pdf file"))
    pages = _pages(p.get("pages"))
    client = client or default_client()
    model = model or default_model()

    box = box or SshBox()
    if not await box.reachable():                      # before any model call: an offline engine costs nothing
        await _fail(ctx, EngineOffline(OFFLINE))
    await ctx.progress(0.02, "Looking at the pages")
    pdf = ctx.storage_download(key)
    try:
        book_pages = pdf_pages or await asyncio.to_thread(PdfPages, pdf)
    except Exception as e:  # noqa: BLE001  (PyMuPDF's own error types)
        await _fail(ctx, EngineFailed(f"This PDF could not be opened ({e})"))
    page_count = book_pages.count
    if pages and pages[-1] > page_count:
        await _fail(ctx, RuntimeError(f"This PDF has {page_count} pages; page {pages[-1]} was asked for"))
    n_pages = len(pages) if pages else page_count
    budget = Budget(float(p.get("max_cost_usd") or USD_PER_PAGE * n_pages))
    t_kinds = time.time()
    kinds = await page_kinds(ctx, client, model, book_pages, pages, budget)
    kinds_s = time.time() - t_kinds
    music = [k["pdf_page"] for k in kinds if k["kind"] == "music"]
    front = [k for k in kinds if k["kind"] != "music"]
    if not music:
        await _fail(ctx, EngineFailed("No page of music was found in this PDF (only " + ", ".join(k["kind"] for k in front) + ")"))
    cover_key = None
    cover = next((k for k in kinds if k["kind"] == "cover"), None)
    if cover is not None:
        cover_key = cover_path(score_id)
        ctx.storage_upload(cover_key, book_pages.png(cover["pdf_page"]), "image/png")

    await ctx.progress(0.05, "Sending the PDF to the transcription engine")
    with tempfile.TemporaryDirectory() as tmp:
        run = Path(tmp)
        await ctx.progress(0.08, f"Reading {len(music)} page{'s' if len(music) != 1 else ''} of music")
        try:
            book_run = await box.transcribe(job.id, pdf, music, run)
        except (EngineOffline, EngineFailed) as e:
            await _fail(ctx, e)
        doc = await asyncio.to_thread(load_run, run)
        if not doc["measures"]:
            await _fail(ctx, EngineFailed("The transcription engine found no bars in this PDF"))
        try:
            sc, filled = await asyncio.to_thread(merge, doc, movement_files(run))
        except BarsDoNotLineUp as e:
            await _fail(ctx, EngineFailed(f"The transcription's bars do not line up with its pages ({e})"))
        page = PageLayout.read(movement_files(run)[0])

        await ctx.progress(0.6, f"Reading the heading, the text of {len(doc['systems'])} systems and {len(doc['doubtful'])} doubtful symbols")
        index = {pg: i for i, pg in enumerate(book_run["pdf_pages"], start=1)}
        scans = {pg["page"]: Image.open(run / "scan" / f"p{index[pg['pdf_page']]}.png") for pg in doc["pages"]}
        t_spark = time.time()
        form, enriched, answers = await asyncio.gather(front_matter(ctx, client, model, doc, scans, budget),
                                                       enrich(ctx, client, model, doc, scans, budget),
                                                       verify(ctx, client, model, doc, scans, budget))
        spark_s = time.time() - t_spark
        for im in scans.values():
            im.close()

    await ctx.progress(0.85, "Writing the digital version")
    t_write = time.time()
    score_row = (ctx.db.table("scores").select("*").eq("id", score_id).limit(1).execute().data or [{}])[0]
    form_ok = form.pop("_ok", False)
    first_number = doc["measures"][0]["number"]
    # The book's facts first, then the page's heading, then the scan's credits; never "Music21".
    log = await asyncio.to_thread(apply_front, sc, form, first_number,
                                  title=score_row.get("title") or page.text("title"), composer=score_row.get("composer") or page.text("composer"))
    items_log, counts = await asyncio.to_thread(apply_items, sc, doc, enriched)
    verify_log, extra = await asyncio.to_thread(apply_verify, sc, answers)
    log += items_log + verify_log
    for n, whys in filled.items():
        extra.setdefault(n, []).extend(whys)
    flags = await asyncio.to_thread(flagged_bars, sc, doc, extra)
    existing = [r["name"] for r in (ctx.db.table("parts").select("name,position").eq("score_id", score_id).order("position").execute().data or [])]
    groups, kept_names = name_parts(sc, existing)
    data = await asyncio.to_thread(write_musicxml, sc, page, form.get("opus"))
    path = digital_path(score_id)
    ctx.storage_upload(path, data, CONTENT_TYPE)

    # Read the file back the way the import reads a MusicXML: what the app will open is what the rows describe.
    f = await asyncio.to_thread(lambda: book_facts(converter.parse(data, format="musicxml")))
    names = f["names"]
    flagged = [b["number"] for b in flags]
    cost = budget.summary()
    items = {"written": {k: counts[k] for k in ("words", "dynamic", "fingering", "pedal", "ornament")},
             "duplicates": counts["duplicates"], "dropped": counts["dropped"], "out_of_range": counts["out_of_range"],
             "systems_answered": sum(1 for r in enriched if r.get("ok")), "systems": len(enriched)}
    meta = {"transcribed_from": src["id"], "engine": ENGINE,
            "flags": {"bars_doubtful": len(flagged), "pages_unreadable": len(doc["unreadable"])},
            "flagged_bars": flags, "pages": book_run["pdf_pages"], "parts": names,
            "page_kinds": [{k: v for k, v in r.items() if k != "staves"} | {"staves": r["staves"]} for r in kinds],
            "cover": cover_key, "front_matter": form | {"read": form_ok}, "items": items, "cost": cost}
    same = [r for r in (ctx.db.table("sources").select("id,meta").eq("score_id", score_id).eq("kind", "musicxml").execute().data or [])
            if (r.get("meta") or {}).get("transcribed_from") == src["id"]]
    if same:
        row = ctx.db.table("sources").update({"storage_paths": [path], "meta": meta}).eq("id", same[0]["id"]).execute().data[0]
    else:
        row = ctx.db.table("sources").insert({"score_id": score_id, "kind": "musicxml", "storage_paths": [path], "meta": meta,
                                              "created_by": job.created_by or src["created_by"]}).execute().data[0]

    if kept_names:
        for name in names:
            ctx.db.table("parts").update({"storage_path": path}).eq("score_id", score_id).eq("name", name).execute()
    elif not existing:
        write_parts(ctx.db, score_id, f["groups"], path)
    write_measures(ctx.db, score_id, f["numbers"])
    # Facts only where the score has none. Tempo comes from the metronome Spark read in the heading, never from an
    # unchecked Audiveris mark (the Goldberg Aria prints none and Audiveris once gave 72).
    mm = form.get("metronome") or {}
    facts = {"key_sig": f["key_sig"], "meter": f["meter"], "bars": len(f["numbers"]),
             "pages": page_count if not pages else None, "composer": form.get("composer"), "work": form.get("opus"),
             "tempo_bpm": mm.get("bpm")}
    fill = {k: v for k, v in facts.items() if v is not None and score_row.get(k) in (None, "")}
    if fill:
        ctx.db.table("scores").update(fill).eq("id", score_id).execute()
    write_s = time.time() - t_write

    ctx.result["note"] = f"Digital: {len(f['numbers'])} bars, {len(flagged)} to check"
    return {
        "source_id": row["id"], "instruments": names, "bars": len(f["numbers"]), "flagged_bars": flagged,
        "seconds": round(time.time() - t0, 1), "cost_usd": cost["total_usd"], "cost_per_page": cost["per_page"],
        "pages": book_run["pdf_pages"], "page_kinds": [(k["pdf_page"], k["kind"]) for k in kinds], "cover": cover_key,
        "pages_unreadable": doc["unreadable"], "spark_calls": budget.calls, "spark_skipped": budget.skipped,
        "front_matter": form | {"read": form_ok}, "items": items,
        "edits": {k: sum(1 for e in log if e["layer"] == k) for k in ("front", "words", "dynamic", "fingering", "pedal", "ornament", "dup", "A", "flag")},
        "timings": {"kinds_s": round(kinds_s, 1), "box_s": book_run.get("box_s"), "audiveris_s": book_run.get("audiveris_s"),
                    "render_s": book_run.get("render_s"), "upload_s": book_run.get("upload_s"), "pull_s": book_run.get("pull_s"),
                    "spark_s": round(spark_s, 1), "write_s": round(write_s, 1)},
    }
