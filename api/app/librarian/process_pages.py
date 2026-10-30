"""Path B: scanned or photographed pages become a ready score. Build-queue item 6's engine.

Meta models: **Muse Spark 1.3** (one labelling call per page through `ctx.complete`, effort low, about
$0.008 a page: first measure number, part names per system, rehearsal marks, doubtful bars, title, composer,
key, meter, difficulty per part, a two-sentence brief), plus two closed questions on the first page with music:
the book's key and time signature on its first system (`signature.py`; that read, not the page labels', fills
`scores.key_sig` and `scores.meter` in the canonical forms "F# minor" and "4/4", null when Spark is unsure) and
the score header on the numbered staff overlay (`labels.read_header`, the part cut's header read: instruments in
score order and the staff count of a full system). SAM 3.1 is not used: the experiment showed geometry finds
systems in 30 ms without a network call, and SAM never sees a barline.

Per page: download the PNG the browser rasterised, `cut.page_measures` (the part cut's staff geometry: page-edge
shadows masked, the working scale, staves as row-profile peaks, systems by the systemic line, the header's staff
count driving the staff recovery, system barlines voted with a spacing-scaled tolerance; boxes as fractions,
confidence from the geometry), then `labels.label_page` (Spark labels what geometry found; it never moves a box).
Then one pass writes interpretation v(n+1) with engine `opencv-staff-geometry+spark-labels`, stable `measures`
(upsert, never delete), `measure_placements`, `parts` with difficulty, and the score's facts and `ready` status.

The deliberate realistic failure: when a page's staff-to-part assignment is ambiguous (Spark names no parts for a
system, its parts do not add up to the staves the geometry found, or a page brings a part that neither earlier
pages nor the score header have), the handler parks the run with `ctx.needs_review(question, payload)` and
returns. A cut-away system (resting parts left out) is not a question when its parts are known. The pages already
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
from . import label_memory
from .cut import page_measures
from .labels import PageLabels, canon_part, label_page, match_part, read_header
from .signature import read_signature

ENGINE = "opencv-staff-geometry+spark-labels"
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


def header_names(header: dict[str, Any] | None) -> list[str]:
    return [canon_part(i.get("label") or i.get("name") or "") for i in (header or {}).get("instruments") or [] if (i.get("label") or i.get("name"))]


def assign_parts(geo_systems: list[dict[str, Any]], labels: PageLabels, known: list[str], page_no: int,
                 header: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], str | None]:
    """Parts per system from Spark; a reason when the assignment is ambiguous and the admin must decide.

    Every system needs Spark's parts, adding up to the staves the geometry found. Systems on one page may differ:
    a cut-away system that leaves resting parts out is how scores are engraved (two-piano and orchestral pages), so
    it is not a question when its parts are parts the book already has. On a later page each name is matched to the
    parts read so far (`labels.match_part`: exact, an abbreviation, a shared numeral) and stored under that name; a
    name that matches none is accepted when the score header lists it (a part resting on the first pages), and is a
    question otherwise, as is a system where two names match one part. The first page read sets the parts."""
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
    if not known:
        return per_system, None
    in_header = header_names(header)
    pool = list(known)
    unknown: list[str] = []
    for p in per_system:
        named: list[str] = []
        for name in p["parts"]:
            k = match_part(name, pool)
            if k is None and match_part(name, in_header) is not None:
                k = name
                pool.append(name)
            if k is None or k in named:
                unknown.append(name)
                k = name
            named.append(k)
        p["parts"] = named
    if unknown:
        staves = sorted({s["staves"] for s in geo_systems})
        return [], (f"page {page_no} has {'/'.join(str(n) for n in staves)} staves per system and Spark reads {', '.join(dict.fromkeys(unknown))} there, "
                    f"which earlier pages did not have (they had {', '.join(known)})")
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
            "params": {"engine": ENGINE, "geometry": "cut.page_measures", "header_spaces": 12, "spark_effort": "low", "state": state},
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
        ctx.db.table("scores").update(signature_facts(sig, confirmed(ctx, score_id))).eq("id", score_id).execute()
    signature = state["signature"]

    # ---------------------------------------------------------------- the score header: staves per full system, instruments
    if "header" not in state:
        header: dict[str, Any] | None = None
        hp = signature.get("page") if not str(signature.get("error", "")).startswith("no system found") else None
        if hp:
            await ctx.progress(0.04, "Reading the score header")
            title = (ctx.db.table("scores").select("title").eq("id", score_id).single().execute().data or {}).get("title") or ""
            header = await read_header(ctx, page_png(hp), client or default_client(), model or default_model(), page=hp, title=title)
            ov = header.pop("overlay_png", None)
            if ov:
                header["overlay_key"] = f"{score_id}/header/p{hp:03}-overlay.png"
                ctx.storage_upload(header["overlay_key"], ov, "image/png")
            state["cost_usd"] = float(Decimal(str(state["cost_usd"])) + Decimal(str(header["cost_usd"])))
            if header.get("expected_staves"):
                insts = ", ".join(f"{i['name']} ({i['staves']})" for i in header["instruments"])
                state["log"].append(f"Page {hp}, score header: {header['expected_staves']} staves per full system ({insts})")
            else:
                state["log"].append(f"Page {hp}, score header not read ({header.get('error', 'no instruments')}); staves are not recovered")
        state["header"] = header
        save_state()
    header = state["header"]
    expected = (header or {}).get("expected_staves")

    # ---------------------------------------------------------------- per page: geometry, then Spark labels
    for i, path in enumerate(paths, start=1):
        key = str(i)
        done = state["pages"].get(key)
        if done and not done.get("ambiguous"):
            continue
        await ctx.progress(0.05 + 0.75 * (i - 1) / n_pages, f"Reading page {i} of {n_pages}")
        png = page_png(i)
        geo_d = page_measures(png, expected_staves=expected)
        if not geo_d["measures"]:
            state["pages"][key] = {"unreadable": True, "geometry": geo_d, "labels": None, "parts": [], "ambiguous": None}
            state["log"].append(f"Page {i} could not be read ({geo_d['log'][-1].lower()})")
            save_state()
            continue
        await ctx.progress(0.05 + 0.75 * (i - 0.5) / n_pages, f"Labelling page {i} of {n_pages} with Spark")
        labels = await label_page(ctx, png, geo_d, effort=interp["params"].get("spark_effort", "low"), known=state["known_parts"])
        state["cost_usd"] = float(Decimal(str(state["cost_usd"])) + labels.cost_usd)
        parts, why = assign_parts(geo_d["systems"], labels, state["known_parts"], i, header)
        page = {"unreadable": False, "geometry": geo_d, "labels": labels.as_dict(), "parts": parts, "ambiguous": why}
        state["pages"][key] = page
        if why:
            spark_parts = labels.parts_for_system(geo_d["systems"][0]["index"])[0]
            question = f"Which parts are on page {i}, top to bottom? {why[0].upper() + why[1:]}."
            payload = {
                "page": i, "interpretation_id": interp_id, "system_staves": [s["staves"] for s in geo_d["systems"]],
                "spark_parts": spark_parts, "known_parts": state["known_parts"],
                "options": [o for o in (spark_parts, state["known_parts"]) if o],
                "header_parts": header_names(header), "expected_staves": expected,
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
        on_page = list(dict.fromkeys(name for p in parts for name in p["parts"]))
        for name in on_page:
            if name not in state["known_parts"]:
                state["known_parts"].append(name)
        cut_away = sum(1 for p in parts if len(p["parts"]) < len(state["known_parts"]))
        state["log"].append(f"Page {i}: {len(geo_d['systems'])} systems, {len(geo_d['measures'])} bars, parts {', '.join(on_page) or '?'}"
                            + (f" ({cut_away} cut-away system{'s' if cut_away != 1 else ''})" if cut_away else "")
                            + (f"; {sum(s['recovered'] for s in geo_d['systems'])} staves recovered" if any(s["recovered"] for s in geo_d["systems"]) else ""))
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

    # The book's label memory (008, 006 agentic memory rule): the header's printed names and abbreviations as the parts
    # this reading named ("Klavier" and "Klav." are the "Piano"), so a later part cut starts from what was read here.
    if header and header.get("instruments"):
        mem = label_memory.load(ctx.db, score_id)
        if mem.seed_from_header(header, part_names) and label_memory.save(ctx.db, score_id, mem):
            state["log"].append(f"Label memory: {len(mem.entries)} printed labels remembered from the header")

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
        "signature": {k: signature.get(k) for k in ("key_sig", "meter", "key_sig_guess", "meter_guess", "confidence", "read", "why", "crop", "crop_key", "cost_usd", "error", "page") if signature.get(k) is not None},
        "header": {k: header.get(k) for k in ("page", "expected_staves", "instruments", "validation", "overlay_key", "cost_usd", "error") if header.get(k) is not None} if header else None,
        "flagged": {"pages_unreadable": unreadable, "bars_doubtful": doubtful},
        "unreadable_pages": unreadable_pages(state),
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
        "current_interpretation_id": interp_id, **signature_facts(signature, confirmed(ctx, score_id)),
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
        "unreadable_pages": unreadable_pages(state),
        "question": question, "log": state["log"],
    }


def unreadable_pages(state: dict[str, Any]) -> list[dict[str, Any]]:
    """The pages the geometry found no bars on, with the geometry's last word on why, for the stand's placeholder."""
    out = []
    for key, p in sorted(state["pages"].items(), key=lambda kv: int(kv[0])):
        if p["unreadable"]:
            log = (p.get("geometry") or {}).get("log") or []
            out.append({"page": int(key), "reason": log[-1] if log else "no staves found"})
    return out


def confirmed(ctx: JobContext, score_id: str) -> bool:
    row = ctx.db.table("scores").select("signature_confirmed").eq("id", score_id).single().execute().data or {}
    return bool(row.get("signature_confirmed"))


def signature_facts(sig: dict[str, Any], owner_confirmed: bool = False) -> dict[str, Any]:
    """The score row's signature columns: the confident read (or null) and the best guess with its confidence. Once the
    owner has confirmed the key and meter in Details (`scores.signature_confirmed`), a reading never touches them."""
    facts = {"key_sig_guess": sig.get("key_sig_guess"), "meter_guess": sig.get("meter_guess"), "signature_confidence": sig.get("confidence")}
    if not owner_confirmed:
        facts.update({"key_sig": sig.get("key_sig"), "meter": sig.get("meter")})
    return facts
