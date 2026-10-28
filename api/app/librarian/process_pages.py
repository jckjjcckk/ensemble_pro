"""Path B: scanned or photographed pages become a ready score. Build-queue item 6's engine.

Meta models: **Muse Spark 1.3** (one labelling call per page through `ctx.complete`, effort low, about
$0.008 a page: first measure number, part names per system, rehearsal marks, doubtful bars, title, composer,
key, meter, difficulty per part, a two-sentence brief), plus one closed question on page 1's first system for the
book's key and time signature (`signature.py`; that read, not the page labels', fills `scores.key_sig` and
`scores.meter` in the canonical forms "F# minor" and "4/4", null when Spark is unsure). SAM 3.1 is not used: the experiment showed geometry
finds systems in 30 ms without a network call, and SAM never sees a barline.

Per page: download the PNG the browser rasterised, `geometry.measures_on_page` (OpenCV staff and barline
geometry, boxes as fractions, confidence from the geometry), then `labels.label_page` (Spark labels what
geometry found; it never moves a box). Then one pass writes interpretation v(n+1) with engine
`opencv-geometry+spark-labels`, stable `measures` (upsert, never delete), `measure_placements`, `parts` with
difficulty, and the score's facts and `ready` status.

The deliberate realistic failure: when a page's staff-to-part assignment is ambiguous (Spark's parts do not
add up to the staves it sees, systems on one page disagree, or a page introduces parts earlier pages did not
have), the handler parks the run with `ctx.needs_review(question, payload)` and returns. The pages already
read are kept in `interpretations.params.state`, so the follow-up job (same payload plus `answer`: the part
names top to bottom, as a list or a comma-separated string) continues from that page without paying for the
earlier ones again.
"""
from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

from anthropic import AsyncAnthropic

from ..llm import _client as default_client, model_name as default_model
from . import Job, JobContext, ScoreFailure, handler
from .geometry import measures_on_page
from .labels import PageLabels, canon_part, label_page
from .signature import read_signature

ENGINE = "opencv-geometry+spark-labels"
LEVELS = ["high", "medium", "low"]
SIGNATURE_PAGES = 4   # how far into the book the signature read looks for the first system (title and blank pages first)


def downgrade(conf: str) -> str:
    return LEVELS[min(len(LEVELS) - 1, LEVELS.index(conf) + 1)]


def page_paths(score_id: str, src: dict[str, Any]) -> list[str]:
    """Bucket path of every page in reading order. `page_order` holds 1-based indexes into the upload set."""
    paths: list[str] = src.get("storage_paths") or []
    count = src.get("page_count") or len(paths)
    order = src.get("page_order") or list(range(1, count + 1))
    out = []
    for idx in order:
        if 1 <= idx <= len(paths) and paths[idx - 1].lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            out.append(paths[idx - 1])
        else:
            out.append(f"{score_id}/pages/{idx}.png")
    return out


def parse_answer(answer: Any) -> list[str]:
    if answer is None:
        return []
    if isinstance(answer, dict):
        answer = answer.get("parts") or answer.get("answer") or []
    if isinstance(answer, str):
        answer = [a for a in answer.replace(";", ",").split(",")]
    return [canon_part(a) for a in answer if str(a).strip()]


def split_staves(staves: int, parts: list[str]) -> list[int]:
    if not parts:
        return []
    base, extra = divmod(staves, len(parts))
    return [base + (1 if i < extra else 0) for i in range(len(parts))]


def assign_parts(geo_systems: list[dict[str, Any]], labels: PageLabels, known: list[str], page_no: int) -> tuple[list[dict[str, Any]], str | None]:
    """Parts per system from Spark; a reason when the assignment is ambiguous and the admin must decide."""
    per_system = []
    for s in geo_systems:
        parts, spp = labels.parts_for_system(s["index"])
        staves = s["staves"]
        if not parts:
            return [], f"Spark named no parts for system {s['index']} ({staves} staves)"
        if spp and (len(spp) != len(parts) or sum(spp) != staves):
            return [], f"Spark reads system {s['index']} as {', '.join(parts)} with staves {spp}, but it has {staves} staves"
        if not spp:
            if staves % len(parts):
                return [], f"Spark reads system {s['index']} as {', '.join(parts)}, which does not divide its {staves} staves"
            spp = split_staves(staves, parts)
        per_system.append({"index": s["index"], "parts": parts, "staves_per_part": spp})
    names = [tuple(p["parts"]) for p in per_system]
    if len(set(names)) > 1:
        return [], "systems on this page disagree on their parts: " + "; ".join(f"system {p['index']}: {', '.join(p['parts'])}" for p in per_system)
    new = [n for n in names[0] if n not in known]
    if known and new:
        staves = geo_systems[0]["staves"]
        return [], f"page {page_no} has {staves} staves per system and Spark reads them as {', '.join(names[0])}; earlier pages had {', '.join(known)}"
    return per_system, None


def apply_answer(geo_systems: list[dict[str, Any]], parts: list[str]) -> list[dict[str, Any]]:
    return [{"index": s["index"], "parts": parts, "staves_per_part": split_staves(s["staves"], parts)} for s in geo_systems]


@handler("process_pages")
async def process_pages(job: Job, ctx: JobContext, *, client: AsyncAnthropic | None = None, model: str | None = None) -> dict:
    t0 = time.time()
    score_id = job.payload["score_id"]
    source_id = job.payload.get("source_id")
    answer = parse_answer(job.payload.get("answer"))

    q = ctx.db.table("sources").select("*").eq("score_id", score_id)
    q = q.eq("id", source_id) if source_id else q.order("created_at", desc=True)
    src = q.limit(1).execute().data
    if not src:
        raise RuntimeError("the score has no source to read")
    src = src[0]
    source_id = src["id"]
    paths = page_paths(score_id, src)
    n_pages = len(paths)
    if not n_pages:
        raise RuntimeError("the source has no pages")

    # Resume a parked run when an answer arrives; otherwise start interpretation v(n+1).
    interp = None
    if answer:
        rows = ctx.db.table("interpretations").select("*").eq("score_id", score_id).eq("status", "needs_review").order("version", desc=True).limit(1).execute().data
        interp = rows[0] if rows else None
    if interp:
        state = interp["params"].get("state") or {}
        question = state.get("question") or {}
        page_q = str(question.get("page", ""))
        if page_q and page_q in state.get("pages", {}):
            page = state["pages"][page_q]
            page["parts"] = apply_answer(page["geometry"]["systems"], answer)
            page["ambiguous"] = None
            page["answered"] = True
            state["known_parts"] = state.get("known_parts", []) + [p for p in answer if p not in state.get("known_parts", [])]
            state["log"].append(f"Page {page_q}: parts set to {', '.join(answer)} by the admin")
        state["question"] = None
        ctx.db.table("interpretations").update({"status": "running", "params": {**interp["params"], "state": state}}).eq("id", interp["id"]).execute()
    else:
        prev = ctx.db.table("interpretations").select("version").eq("score_id", score_id).order("version", desc=True).limit(1).execute().data
        version = (prev[0]["version"] + 1) if prev else 1
        state = {"pages": {}, "known_parts": [], "log": [], "cost_usd": 0.0, "latency_ms": 0, "question": None}
        interp = ctx.db.table("interpretations").insert({
            "score_id": score_id, "source_id": source_id, "version": version, "engine": ENGINE, "status": "running",
            "params": {"engine": ENGINE, "min_cover": 0.92, "header_spaces": 12, "spark_effort": "low", "state": state},
        }).execute().data[0]
    interp_id = interp["id"]
    version = interp["version"]
    ctx.result["interpretation_id"] = interp_id

    def save_state() -> None:
        ctx.db.table("interpretations").update({"params": {**interp["params"], "state": state}}).eq("id", interp_id).execute()

    pngs: dict[int, bytes] = {}

    def page_png(i: int) -> bytes:
        if i not in pngs:
            pngs[i] = ctx.storage_download(paths[i - 1])
        return pngs[i]

    # ---------------------------------------------------------------- the book's key and meter: the first system of the music
    if "signature" not in state:
        await ctx.progress(0.03, "Reading the key and time signature")
        title = (ctx.db.table("scores").select("title").eq("id", score_id).single().execute().data or {}).get("title") or ""
        # A whole PDF often opens with a title page and a blank page (Rach 1 two-piano, Gutheil 1919): the first system is
        # on the first page where the geometry finds one. Pages with no system cost no call; at most SIGNATURE_PAGES looked at.
        for sig_page in range(1, min(n_pages, SIGNATURE_PAGES) + 1):
            sig = await read_signature(ctx, page_png(sig_page), client or default_client(), model or default_model(), title=title)
            if not str(sig.get("error", "")).startswith("no system found"):
                break
        sig["page"] = sig_page
        crop_png = sig.pop("crop_png", None)
        if crop_png:
            sig["crop_key"] = f"{score_id}/signature/p{sig_page:03}-s1.png"
            ctx.storage_upload(sig["crop_key"], crop_png, "image/png")
        state["signature"] = sig
        state["cost_usd"] = float(Decimal(str(state["cost_usd"])) + Decimal(str(sig["cost_usd"])))
        said = ", ".join(x for x in (sig["key_sig"], sig["meter"]) if x)
        state["log"].append(f"Page {sig_page}, first system: {said}" if said else f"Page {sig_page}, first system: key and meter left blank (not sure)")
        save_state()
        # the identity shows on the cover even while the run waits on a question
        ctx.db.table("scores").update({"key_sig": sig["key_sig"], "meter": sig["meter"]}).eq("id", score_id).execute()
    signature = state["signature"]

    # ---------------------------------------------------------------- per page: geometry, then Spark labels
    for i, path in enumerate(paths, start=1):
        key = str(i)
        done = state["pages"].get(key)
        if done and not done.get("ambiguous"):
            continue
        await ctx.progress(0.05 + 0.75 * (i - 1) / n_pages, f"Reading page {i} of {n_pages}")
        png = page_png(i)
        geo = measures_on_page(png)
        if not geo.readable:
            state["pages"][key] = {"unreadable": True, "geometry": geo.as_dict(), "labels": None, "parts": [], "ambiguous": None}
            state["log"].append(f"Page {i} could not be read ({geo.log[-1].lower()})")
            save_state()
            continue
        await ctx.progress(0.05 + 0.75 * (i - 0.5) / n_pages, f"Labelling page {i} of {n_pages} with Spark")
        labels = await label_page(ctx, png, geo, effort=interp["params"].get("spark_effort", "low"))
        state["cost_usd"] = float(Decimal(str(state["cost_usd"])) + labels.cost_usd)
        geo_d = geo.as_dict()
        parts, why = assign_parts(geo_d["systems"], labels, state["known_parts"], i)
        page = {"unreadable": False, "geometry": geo_d, "labels": labels.as_dict(), "parts": parts, "ambiguous": why}
        state["pages"][key] = page
        if why:
            spark_parts = labels.parts_for_system(geo_d["systems"][0]["index"])[0]
            question = f"Which parts are on page {i}, top to bottom? {why[0].upper() + why[1:]}."
            payload = {
                "page": i, "interpretation_id": interp_id, "system_staves": [s["staves"] for s in geo_d["systems"]],
                "spark_parts": spark_parts, "known_parts": state["known_parts"],
                "options": [o for o in (spark_parts, state["known_parts"]) if o],
                "answer_format": "part names top to bottom, a list or comma-separated, e.g. Piano I, Piano II",
            }
            state["question"] = {"page": i, "question": question}
            state["log"].append(f"Asked which parts are on page {i}")
            state["latency_ms"] = state.get("latency_ms", 0) + int((time.time() - t0) * 1000)
            save_state()
            summary = partial_summary(state, n_pages, question)
            ctx.db.table("interpretations").update({"summary": summary, "cost_usd": state["cost_usd"]}).eq("id", interp_id).execute()
            ctx.needs_review(question, payload, interpretation_id=interp_id)
            ctx.result["pages_read"] = i
            return ctx.result
        for name in parts[0]["parts"] if parts else []:
            if name not in state["known_parts"]:
                state["known_parts"].append(name)
        state["log"].append(f"Page {i}: {len(geo.systems)} systems, {len(geo.measures)} bars, parts {', '.join(state['known_parts'][-len(parts[0]['parts']):]) if parts else '?'}")
        save_state()

    # ---------------------------------------------------------------- one pass over the pages: numbers and records
    await ctx.progress(0.85, "Writing measures and parts")
    pages_read = [k for k, p in sorted(state["pages"].items(), key=lambda kv: int(kv[0])) if not p["unreadable"]]
    unreadable = n_pages - len(pages_read)
    if not pages_read:
        state["log"].append(f"None of the {n_pages} pages could be read")
        ctx.db.table("interpretations").update({"status": "failed", "summary": partial_summary(state, n_pages, ""), "cost_usd": state["cost_usd"],
                                                "finished_at": ctx.now(), "params": {**interp["params"], "state": state}}).eq("id", interp_id).execute()
        what = "page" if n_pages == 1 else f"{n_pages} pages"
        raise ScoreFailure(f"Folio found no staves on the {what}. If this is a scan or a photo, try a sharper, straighter copy.")
    first_labels = PageLabels.from_dict(state["pages"][pages_read[0]]["labels"]) if pages_read else PageLabels()
    first = first_labels.first_measure_number if first_labels.confidence in ("high", "medium") else 1
    if first_labels.is_pickup:
        first = 0
    n = first
    placements: list[dict[str, Any]] = []
    systems_total = 0
    for key in pages_read:
        page = state["pages"][key]
        pno = int(key)
        labels = PageLabels.from_dict(page["labels"])
        geo_d = page["geometry"]
        systems_total += len(geo_d["systems"])
        if pno != int(pages_read[0]) and labels.confidence == "high" and labels.first_measure_number != n:
            state["log"].append(f"Page {pno} prints bar {labels.first_measure_number} where the count says {n}; kept the count")
        for m in geo_d["measures"]:
            conf, flag = m["confidence"], m["flag"]
            if m["provisional"] in labels.doubtful:
                conf = downgrade(conf)
                flag = (flag + "; " if flag else "") + f"Spark: {labels.doubtful[m['provisional']]}"
            placements.append({"number": n, "page": pno, "system": m["system"], "box": m["box"], "confidence": conf, "flag": flag,
                               "rehearsal_mark": labels.rehearsal_marks.get(m["provisional"])})
            n += 1

    numbers = [p["number"] for p in placements]
    rows = [{"score_id": score_id, "number": num, "part": None} for num in numbers]
    for i in range(0, len(rows), 500):
        ctx.db.table("measures").upsert(rows[i:i + 500], on_conflict="score_id,number,part").execute()
    existing = ctx.db.table("measures").select("id,number").eq("score_id", score_id).is_("part", "null").execute().data
    id_of = {r["number"]: r["id"] for r in existing}
    pl_rows = [{"interpretation_id": interp_id, "measure_id": id_of[p["number"]], "page": p["page"], "system": p["system"], "box": p["box"],
                "confidence": p["confidence"], "flag": p["flag"], "rehearsal_mark": p["rehearsal_mark"]} for p in placements]
    # A measure an earlier interpretation had and this run did not find keeps its row: low, flagged, no box.
    lost = [num for num in id_of if num not in set(numbers)]
    for num in lost:
        pl_rows.append({"interpretation_id": interp_id, "measure_id": id_of[num], "page": 1, "system": None, "box": {"x0": 0, "y0": 0, "x1": 0, "y1": 0},
                        "confidence": "low", "flag": f"not found in v{version}", "rehearsal_mark": None})
    for i in range(0, len(pl_rows), 500):
        ctx.db.table("measure_placements").upsert(pl_rows[i:i + 500], on_conflict="interpretation_id,measure_id").execute()

    # parts: order of first appearance top to bottom; difficulty = the hardest page's rating
    part_names: list[str] = []
    difficulty: dict[str, int] = {}
    for key in pages_read:
        page = state["pages"][key]
        for sysparts in page["parts"]:
            for name in sysparts["parts"]:
                if name not in part_names:
                    part_names.append(name)
        for name, d in PageLabels.from_dict(page["labels"]).parts_difficulty.items():
            difficulty[name] = max(difficulty.get(name, 0), d)
    if part_names:
        ctx.db.table("parts").upsert([{"score_id": score_id, "name": name, "position": i, "difficulty": difficulty.get(name) or 3}
                                      for i, name in enumerate(part_names)], on_conflict="score_id,name").execute()

    doubtful = sum(1 for p in placements if p["confidence"] != "high")
    title = next((PageLabels.from_dict(state["pages"][k]["labels"]).title for k in pages_read if PageLabels.from_dict(state["pages"][k]["labels"]).title), "")
    composer = next((PageLabels.from_dict(state["pages"][k]["labels"]).composer for k in pages_read if PageLabels.from_dict(state["pages"][k]["labels"]).composer), "")
    brief = next((PageLabels.from_dict(state["pages"][k]["labels"]).brief for k in pages_read if PageLabels.from_dict(state["pages"][k]["labels"]).brief), "")
    state["log"].append(f"Read {len(pages_read)} of {n_pages} pages: {systems_total} systems, {len(placements)} bars, {len(part_names)} parts")
    if lost:
        state["log"].append(f"{len(lost)} bars from the previous reading were not found this time")
    if doubtful:
        state["log"].append(f"{doubtful} bars doubtful")
    summary = {
        "pages": n_pages, "systems": systems_total, "measures": len(placements), "first_measure": first, "last_measure": n - 1,
        "title": title, "composer": composer, "parts": part_names, "difficulty": {p: difficulty.get(p) for p in part_names},
        "key_sig": signature["key_sig"], "meter": signature["meter"],
        "signature": {k: signature.get(k) for k in ("key_sig", "meter", "read", "why", "crop", "crop_key", "cost_usd", "error", "page") if signature.get(k) is not None},
        "flagged": {"pages_unreadable": unreadable, "bars_doubtful": doubtful},
        "models": {"geometry": "opencv", "labels": next((PageLabels.from_dict(state["pages"][k]["labels"]).model for k in pages_read), None)},
        "log": state["log"],
    }
    latency_ms = state.get("latency_ms", 0) + int((time.time() - t0) * 1000)
    ctx.db.table("interpretations").update({
        "status": "done", "summary": summary, "cost_usd": state["cost_usd"], "latency_ms": latency_ms, "finished_at": ctx.now(),
        "params": {**interp["params"], "state": state},
    }).eq("id", interp_id).execute()

    facts: dict[str, Any] = {
        "status": "ready", "progress": 1.0, "failure_reason": None, "pages": n_pages, "bars": len(placements),
        "key_sig": signature["key_sig"], "meter": signature["meter"], "current_interpretation_id": interp_id,
    }
    if brief:
        facts["brief"] = brief
    existing_score = ctx.db.table("scores").select("title,composer,work").eq("id", score_id).single().execute().data
    if not existing_score.get("composer") and composer:
        facts["composer"] = composer
    if not existing_score.get("work") and title:
        facts["work"] = title
    ctx.db.table("scores").update(facts).eq("id", score_id).execute()
    await ctx.progress(1.0, "Ready")
    return {**ctx.result, "interpretation_id": interp_id, "version": version, "pages": n_pages, "measures": len(placements), "parts": part_names,
            "doubtful": doubtful, "cost_usd": state["cost_usd"], "seconds": round(time.time() - t0, 1)}


def partial_summary(state: dict[str, Any], n_pages: int, question: str) -> dict[str, Any]:
    read = [p for p in state["pages"].values() if not p["unreadable"]]
    return {
        "pages": n_pages, "pages_read": len(read), "systems": sum(len(p["geometry"]["systems"]) for p in read),
        "measures": sum(len(p["geometry"]["measures"]) for p in read), "parts": state["known_parts"],
        "flagged": {"pages_unreadable": sum(1 for p in state["pages"].values() if p["unreadable"]),
                    "bars_doubtful": sum(1 for p in read for m in p["geometry"]["measures"] if m["confidence"] != "high")},
        "question": question, "log": state["log"],
    }
