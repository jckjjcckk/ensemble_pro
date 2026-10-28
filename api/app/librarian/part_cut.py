"""part_cut: cut one instrument's staves out of a scanned full score, as an agent run. Payload
`{score_id, instrument, interpretation_id?, pages?: [int], answer?, resume_from?}`.

Meta model: **Muse Spark 1.3** through the agent loop (`app.agent.run_agent`): one model call per turn, plus one
call inside `read_header` (the instrument list on page 1), one inside `read_page` (Spark labels the numbered
staff overlay: which staves are the instrument's, per system) and one inside `commit_system` (Spark re-reads
the crop alone and names the instrument; it must agree). Geometry and the cut are OpenCV (`cut.py`), no model.

The loop carries the guarantees: `commit_system` is a commit tool whose checks (staves exist in the system,
count matches the header, crop verify, model recheck) the model cannot skip; after `max_refusals` the run
parks with `needs_review` and a typed question `{kind: "choose_staves", page, system, proposal, staff_boxes,
image_key, allowed}`; the admin's answer `{staves: [...] | "absent"}` is applied as if the commit succeeded and
the run resumes. `finish` refuses while a page is uncommitted.

Writes: crops to `{score_id}/parts/{slug}/p{page:03}-s{k}.png`, a derived `sources` row (kind `part_images`,
needs migration 20261028090000), an `interpretations` row (engine `part-cut-agent`) whose summary carries the
counts and the log, and the page-intake interpretation's placements copied under the new interpretation (same
`measures` ids, nothing deleted). Agent state lives in `jobs.result.agent` (persisted every turn).
"""
from __future__ import annotations

import json
import re
import time
from decimal import Decimal
from typing import Any

from anthropic import AsyncAnthropic

from ..agent import AgentState, Refusal, Stop, ToolBox, run_agent
from ..llm import _client as default_client, model_name as default_model, price
from ..settings import settings
from ..spend import Charge
from . import Job, JobContext, handler
from .cut import cut_system, overlay_png, page_geometry, to_png
from .labels import extract_json
from .process_pages import page_paths

ENGINE = "part-cut-agent"
SYSTEM = """You are an orchestral librarian cutting one instrument's part out of a scanned full score. Geometry has already found every staff, system and barline; you only decide which numbered staves belong to the instrument on each system, then commit them. Work page by page: read_header once, then for each page read_page and commit_system for every system (staves, or "absent" when the instrument's staves are not printed in that system), then finish. Trust the margin labels first, then clefs, brace and score order. Call exactly one tool per turn, no prose."""

HEADER_PROMPT = """This is the first page of a scanned full score. List the instruments of the score in order from top to bottom as printed in the left margin, with the number of staves each one uses on this page and their clefs, and the key and time signature. Return only JSON: {"instruments": [{"name": "Flute", "staves": 1, "clefs": ["treble"]}], "key": "C major", "time": "4/4"}"""

LABEL_PROMPT = """Page {page} of a scanned full score. Every staff has a blue box and a yellow tag with its number ({first}..{last}, top to bottom); grey boxes mark the systems: {systems_desc}. Instrument wanted: "{instrument}" ({staves} staves per system according to the header). For each system give the staff numbers that belong to the wanted instrument (empty if its staves are not printed in that system) and whether it is "playing", "resting" or "absent". Return only JSON: {{"systems": [{{"index": 1, "wanted_staves": [11, 12], "status": "playing"}}], "confidence": "high|medium|low", "notes": ""}}"""

RECHECK_PROMPT = """This image is a block of staves cut from a scanned full score. The left margin may carry the instrument label; otherwise judge from the clefs, brace or bracket and the writing. Which instrument or section is this block? Return only JSON: {"instrument": "short name", "confidence": "high|medium|low", "why": "one sentence"}"""


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "part"


ALIASES = {"pno": "piano", "pf": "piano", "pfte": "piano", "pianoforte": "piano", "klavier": "piano", "cemb": "harpsichord", "cembalo": "harpsichord",
           "vn": "violin", "vln": "violin", "vl": "violin", "violino": "violin", "violini": "violin", "vla": "viola", "vc": "cello", "vcl": "cello",
           "violoncello": "cello", "cb": "bass", "kb": "bass", "contrabass": "bass", "fl": "flute", "ob": "oboe", "cl": "clarinet", "fg": "bassoon",
           "bn": "bassoon", "cor": "horn", "hn": "horn", "tr": "trumpet", "tpt": "trumpet", "tbn": "trombone", "timp": "timpani", "org": "organ"}


def same_instrument(a: str, b: str) -> bool:
    """'Piano (solo)' ~ 'Pno.' ~ 'Pianoforte' ~ 'piano': first word, letters only, aliases, then prefix (3+ letters)."""
    def norm(s: str) -> str:
        w = re.sub(r"[^a-z]", "", s.lower().split()[0]) if s.split() else ""
        return ALIASES.get(w, w)
    x, y = norm(a), norm(b)
    return len(x) >= 3 and len(y) >= 3 and (x.startswith(y) or y.startswith(x))


async def ask_model(ctx: JobContext, client: AsyncAnthropic, model: str, prompt: str, png: bytes, *, max_tokens: int = 2048) -> dict[str, Any]:
    """One image+text call outside the loop (header, labels, recheck), charged like a turn."""
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": ctx.png_b64(png)}}, {"type": "text", "text": prompt}]
    is_meta = settings.llm_provider == "meta" or model.startswith("muse")
    res = await client.messages.create(model=model, max_tokens=max(max_tokens, 1024) if is_meta else max_tokens, system=SYSTEM,
                                       messages=[{"role": "user", "content": content}], output_config={"effort": "low"})
    u = res.usage
    cost = price(res.model or model, u.input_tokens, u.output_tokens)
    ctx.charge(Charge("meta" if is_meta else "anthropic", res.model or model, "spark" if is_meta else "claude", cost, u.input_tokens, u.output_tokens))
    text = "".join(b.text for b in res.content if b.type == "text")
    data = extract_json(text)
    data["_cost_usd"] = float(cost)
    return data


@handler("part_cut")
async def part_cut(job: Job, ctx: JobContext, *, client: AsyncAnthropic | None = None, model: str | None = None) -> dict:
    t0 = time.time()
    p = job.payload
    score_id, instrument = p["score_id"], p["instrument"]
    part_slug = slug(instrument)
    c, m = client or default_client(), model or default_model()
    src = ctx.db.table("sources").select("*").eq("score_id", score_id).in_("kind", ["pdf", "images"]).order("created_at", desc=True).limit(1).execute().data
    if not src:
        raise RuntimeError("the score has no page source to cut from")
    src = src[0]
    paths = page_paths(score_id, src)
    pages = [n for n in (p.get("pages") or range(1, len(paths) + 1)) if 1 <= n <= len(paths)]
    if not pages:
        raise RuntimeError("no pages to cut")

    # Resume: the parked run's state from the job that asked, the answer applied as a successful commit.
    resumed = bool(p.get("resume_from"))
    answer_text: str | None = None
    if resumed:
        prev = ctx.db.table("jobs").select("result").eq("id", p["resume_from"]).single().execute().data
        state = AgentState.from_dict((prev or {}).get("result", {}).get("agent"))
    else:
        state = AgentState()
    sc = state.scratch
    sc.setdefault("header", None)
    sc.setdefault("pages", {})      # str(page) -> {"geometry", "proposal", "overlay_key"}
    sc.setdefault("commits", {})    # "page:system" -> {"staves" | "absent", "key", "verify"}
    sc.setdefault("questions", 0)
    sc.setdefault("log", [])
    cache: dict[int, tuple[Any, Any, Any]] = {}   # page -> (geom, bw, page image), not persisted

    def load_page(n: int):
        if n not in cache:
            png = ctx.storage_download(paths[n - 1])
            cache[n] = page_geometry(png)
        return cache[n]

    def header_staves() -> int:
        h = sc["header"] or {}
        for inst in h.get("instruments") or []:
            if same_instrument(str(inst.get("name", "")), instrument):
                return max(1, int(inst.get("staves") or 1))
        return 2 if "piano" in instrument.lower() else 1

    async def do_commit(page: int, system: int, staves: list[int] | str, *, recheck: bool = True) -> dict:
        key = f"{page}:{system}"
        geom, bw, im = load_page(page)
        sysd = next((s for s in geom["systems"] if s["index"] == system), None)
        if sysd is None:
            raise Refusal(f"page {page} has no system {system}; it has systems {[s['index'] for s in geom['systems']]}")
        if staves == "absent":
            sc["commits"][key] = {"staves": "absent", "key": None, "verify": None}
            sc["log"].append(f"Page {page} system {system}: {instrument} absent")
            return {"committed": key, "status": "absent"}
        staves = sorted(int(s) for s in staves)
        missing = [s for s in staves if s not in sysd["staff_indices"]]
        if missing:
            raise Refusal(f"staves {missing} are not in system {system} of page {page}, which has staves {sysd['staff_indices']}")
        want = header_staves()
        if len(staves) != want:
            raise Refusal(f"{instrument} has {want} staves per system according to the header; you named {len(staves)}")
        if staves != list(range(staves[0], staves[0] + len(staves))):
            raise Refusal(f"an instrument's staves are adjacent; {staves} are not")
        crop, box, checks = cut_system(bw, im, geom, sysd, staves)
        if not checks["pass"]:
            failed = [k for k, v in checks.items() if isinstance(v, dict) and not v.get("informational") and not v["pass"]]
            raise Refusal(f"the crop of staves {staves} failed the geometric check {failed}: {json.dumps({k: checks[k] for k in failed})}")
        png = to_png(crop)
        if recheck:
            said = await ask_model(ctx, c, m, RECHECK_PROMPT, png)
            sc["cost_usd"] = sc.get("cost_usd", 0.0) + said.pop("_cost_usd", 0.0)
            if not same_instrument(str(said.get("instrument", "")), instrument):
                raise Refusal(f"re-reading the crop of staves {staves} alone, the model calls it {said.get('instrument')!r}, not {instrument!r} ({said.get('why', '')})")
        storage_key = f"{score_id}/parts/{part_slug}/p{page:03}-s{system}.png"
        ctx.storage_upload(storage_key, png, "image/png")
        sc["commits"][key] = {"staves": staves, "key": storage_key, "box": box, "verify": {k: v for k, v in checks.items() if k != "clean"}, "bars": sysd["n_measures"]}
        sc["log"].append(f"Page {page} system {system}: staves {staves} cut ({checks['mode']}), {sysd['n_measures']} bars")
        return {"committed": key, "staves": staves, "storage_key": storage_key, "bars": sysd["n_measures"]}

    box = ToolBox()

    @box.tool("read_header", "Read the score header on page 1: instruments in order, staves each, clefs, key, time. Call once, first.", {"properties": {}})
    async def read_header(args, st):
        if sc["header"] is None:
            geom, bw, im = load_page(pages[0])
            data = await ask_model(ctx, c, m, HEADER_PROMPT, to_png(im))
            sc["cost_usd"] = sc.get("cost_usd", 0.0) + data.pop("_cost_usd", 0.0)
            sc["header"] = data
            sc["log"].append(f"Header: {', '.join(str(i.get('name')) for i in data.get('instruments') or [])}")
        return {"header": sc["header"], "instrument": instrument, "staves_per_system": header_staves()}

    @box.tool("list_pages", "The pages to cut and what is committed on each.", {"properties": {}})
    def list_pages(args, st):
        out = []
        for n in pages:
            read = sc["pages"].get(str(n))
            systems = [s["index"] for s in read["geometry"]["systems"]] if read else None
            committed = [int(k.split(":")[1]) for k in sc["commits"] if int(k.split(":")[0]) == n]
            out.append({"page": n, "read": bool(read), "systems": systems, "committed_systems": committed,
                        "uncommitted_systems": [s for s in (systems or []) if s not in committed]})
        return {"pages": out}

    @box.tool("read_page", "Geometry of one page (staves, systems, barlines) and the model's proposal of which staves are the instrument's, from the numbered overlay.", {"properties": {"page": {"type": "integer"}}, "required": ["page"]})
    async def read_page(args, st):
        n = int(args["page"])
        if n not in pages:
            return {"error": f"page {n} is not in this job; pages: {pages}"}
        if str(n) in sc["pages"]:
            return sc["pages"][str(n)]["summary"]
        geom, bw, im = load_page(n)
        if not geom["staves"]:
            sc["pages"][str(n)] = {"geometry": geom, "proposal": [], "summary": {"page": n, "staves": 0, "systems": [], "note": "no staves found; commit every system as absent or skip"}}
            return sc["pages"][str(n)]["summary"]
        ov = overlay_png(im, geom)
        ov_key = f"{score_id}/parts/{part_slug}/overlay-p{n:03}.png"
        ctx.storage_upload(ov_key, ov, "image/png")
        desc = "; ".join(f"system {s['index']} = staves {s['staff_indices'][0]}..{s['staff_indices'][-1]} ({s['n_measures']} bars)" for s in geom["systems"])
        prompt = LABEL_PROMPT.format(page=n, first=1, last=len(geom["staves"]), systems_desc=desc, instrument=instrument, staves=header_staves())
        lab = await ask_model(ctx, c, m, prompt, ov)
        sc["cost_usd"] = sc.get("cost_usd", 0.0) + lab.pop("_cost_usd", 0.0)
        proposal = [{"system": int(s.get("index", i + 1)), "staves": [int(x) for x in (s.get("wanted_staves") or [])], "status": s.get("status", "absent")}
                    for i, s in enumerate(lab.get("systems") or []) if isinstance(s, dict)]
        summary = {"page": n, "staves": len(geom["staves"]),
                   "systems": [{"index": s["index"], "staves": s["staff_indices"], "bars": s["n_measures"]} for s in geom["systems"]],
                   "proposal": proposal, "confidence": lab.get("confidence"), "notes": lab.get("notes", "")}
        sc["pages"][str(n)] = {"geometry": geom, "proposal": proposal, "overlay_key": ov_key, "summary": summary}
        sc["log"].append(f"Page {n}: {len(geom['staves'])} staves, {len(geom['systems'])} systems; proposal {[(q['system'], q['staves'] or q['status']) for q in proposal]}")
        return summary

    @box.tool("commit_system", "Commit which staves of a system are the instrument's (or \"absent\"). Checked: staves exist, count matches the header, crop verify, model recheck.",
              {"properties": {"page": {"type": "integer"}, "system": {"type": "integer"}, "staves": {"description": "staff numbers, or the string \"absent\"", "anyOf": [{"type": "array", "items": {"type": "integer"}}, {"type": "string", "enum": ["absent"]}]}},
               "required": ["page", "system", "staves"]}, commit=True)
    async def commit_system(args, st):
        n = int(args["page"])
        if str(n) not in sc["pages"]:
            raise Refusal(f"read_page({n}) first")
        staves = args["staves"]
        if not (staves == "absent" or (isinstance(staves, list) and staves)):
            raise Refusal('staves must be a non-empty list of staff numbers or "absent"')
        out = await do_commit(n, int(args["system"]), staves)
        st.refusals.pop("commit_system", None)   # a good commit resets the count (docs/agent-loop.md); the loop itself does not yet
        return out

    @box.tool("finish", "Finish the cut. Refuses while any page or system is uncommitted.", {"properties": {}}, commit=True)
    def finish(args, st):
        missing = []
        for n in pages:
            read = sc["pages"].get(str(n))
            if not read:
                missing.append(f"page {n} not read")
                continue
            for s in read["geometry"]["systems"]:
                if f"{n}:{s['index']}" not in sc["commits"]:
                    missing.append(f"page {n} system {s['index']}")
        if missing:
            raise Refusal("uncommitted: " + ", ".join(missing))
        raise Stop("done", commits=len(sc["commits"]))

    # ---------------------------------------------------------------- the run
    if resumed and p.get("answer") is not None:
        q = state.question_payload or {}
        ans = p["answer"] if isinstance(p["answer"], dict) else json.loads(p["answer"]) if str(p["answer"]).strip().startswith("{") else {"staves": p["answer"]}
        chosen = ans.get("staves", "absent")
        if isinstance(chosen, str) and chosen != "absent":
            chosen = [int(x) for x in re.findall(r"\d+", chosen)] or "absent"
        state.refusals = {}
        out = await do_commit(int(q["page"]), int(q["system"]), chosen, recheck=False)
        sc["log"].append(f"Page {q['page']} system {q['system']}: {chosen} chosen by the admin")
        answer_text = f"The admin decided page {q['page']} system {q['system']}: {json.dumps(chosen)}. It is committed ({json.dumps(out)}). Continue with the next uncommitted system or finish."

    def persist(d: dict[str, Any]) -> None:
        ctx.result["agent"] = d
        ctx.db.table("jobs").update({"result": ctx.result}).eq("id", job.id).execute()

    st = await run_agent(system=SYSTEM, tools=box, state=state, answer=answer_text, client=c, model=m, persist=persist, charge=ctx.charge,
                         user_text=None if resumed else f'Cut the part "{instrument}" from pages {pages}. Start with read_header.',
                         max_turns=8 + 4 * len(pages), max_cost_usd=float(p.get("max_cost_usd", 2.0)), max_refusals=3)
    cost = float(Decimal(str(st.cost_usd)) + Decimal(str(sc.get("cost_usd", 0.0))))
    interp = write_interpretation(ctx, score_id, src, p.get("interpretation_id"), instrument, part_slug, sc, st, pages, cost, t0)

    if st.status == "needs_review":
        q = st.question_payload
        args = q.get("args") or {}
        n, k = int(args.get("page") or 0), int(args.get("system") or 0)
        read = sc["pages"].get(str(n)) or {}
        geom = read.get("geometry") or {"staves": [], "systems": []}
        sysd = next((s for s in geom["systems"] if s["index"] == k), None)
        proposal = next((pr["staves"] or "absent" for pr in read.get("proposal", []) if pr["system"] == k), args.get("staves"))
        sc["questions"] += 1
        payload = {"kind": "choose_staves", "page": n, "system": k, "instrument": instrument, "interpretation_id": interp["id"],
                   "proposal": proposal, "last_attempt": args.get("staves"), "feedback": q.get("feedback"),
                   "staff_boxes": [{"index": s["index"], "y_top": s["y_top"], "y_bottom": s["y_bottom"], "x0": s["x0"], "x1": s["x1"]}
                                   for s in geom["staves"] if sysd is None or s["index"] in sysd["staff_indices"]],
                   "image_key": read.get("overlay_key"), "allowed": {"staves": "list of adjacent staff numbers from staff_boxes", "absent": True},
                   "answer_format": '{"staves": [11, 12]} or {"staves": "absent"}'}
        question = f"Which staves on page {n}, system {k} are {instrument}'s? {q.get('feedback', '')}"
        st.question, st.question_payload = question, payload     # the typed question is what the resume reads
        ctx.result["agent"] = st.to_dict()
        ctx.needs_review(question, payload, interpretation_id=interp["id"])
        return ctx.result
    if st.status == "paused":
        ctx.result["agent"] = st.to_dict()
        ctx.result["paused"] = st.log[-1] if st.log else "paused"
        return ctx.result
    if st.status == "failed":
        raise RuntimeError(st.result.get("error") or "agent failed")

    # done: the derived source and the stable placements
    commits = sorted(sc["commits"].items(), key=lambda kv: tuple(int(x) for x in kv[0].split(":")))
    keys = [v["key"] for _, v in commits if v["key"]]
    derived = ctx.db.table("sources").insert({
        "score_id": score_id, "kind": "part_images", "storage_paths": keys, "page_order": list(range(1, len(keys) + 1)), "page_count": len(keys),
        "created_by": job.created_by or src["created_by"],
        "meta": {"instrument": instrument, "slug": part_slug, "derived_from_source_id": src["id"], "interpretation_id": interp["id"],
                 "systems": [{"page": int(k.split(":")[0]), "system": int(k.split(":")[1]), "staves": v["staves"], "key": v["key"], "bars": v.get("bars")} for k, v in commits]},
    }).execute().data[0]
    ctx.db.table("interpretations").update({"status": "done", "finished_at": ctx.now(), "params": {"instrument": instrument, "source_id": derived["id"], "state": sc}}).eq("id", interp["id"]).execute()
    ctx.db.table("parts").upsert({"score_id": score_id, "name": instrument, "position": 0, "storage_path": keys[0] if keys else None}, on_conflict="score_id,name").execute()
    await ctx.progress(1.0, f"{instrument}: {len(keys)} systems cut")
    return {**ctx.result, "interpretation_id": interp["id"], "source_id": derived["id"], "systems_cut": len(keys), "absent": len(commits) - len(keys),
            "questions": sc["questions"], "cost_usd": cost, "seconds": round(time.time() - t0, 1)}


def write_interpretation(ctx: JobContext, score_id: str, src: dict, intake_id: str | None, instrument: str, part_slug: str, sc: dict, st: AgentState,
                         pages: list[int], cost: float, t0: float) -> dict:
    """The run's interpretation row with counts and log; placements copied from the page-intake interpretation (stable measure ids)."""
    commits = sc["commits"].values()
    summary = {"instrument": instrument, "pages": len(pages), "pages_read": len(sc["pages"]), "systems_cut": sum(1 for v in commits if v["key"]),
               "absent": sum(1 for v in commits if not v["key"]), "questions_asked": sc["questions"] + (1 if st.status == "needs_review" else 0),
               "turns": st.turn, "status": st.status, "models": {"geometry": "opencv", "labels": "spark"}, "log": (sc["log"] + st.log)[-40:]}
    existing = sc.get("interpretation_id")
    row = {"status": "running" if st.status != "done" else "done", "summary": summary, "cost_usd": cost, "latency_ms": int((time.time() - t0) * 1000)}
    if existing:
        return ctx.db.table("interpretations").update(row).eq("id", existing).execute().data[0]
    prev = ctx.db.table("interpretations").select("version").eq("score_id", score_id).order("version", desc=True).limit(1).execute().data
    interp = ctx.db.table("interpretations").insert({**row, "score_id": score_id, "source_id": src["id"], "version": (prev[0]["version"] + 1) if prev else 1,
                                                     "engine": ENGINE, "params": {"instrument": instrument, "slug": part_slug, "intake_interpretation_id": intake_id}}).execute().data[0]
    sc["interpretation_id"] = ctx.result["interpretation_id"] = interp["id"]
    if not intake_id:
        cur = ctx.db.table("scores").select("current_interpretation_id").eq("id", score_id).single().execute().data
        intake_id = (cur or {}).get("current_interpretation_id")
    if intake_id:
        pl = ctx.db.table("measure_placements").select("measure_id,page,system,box,confidence,flag,rehearsal_mark").eq("interpretation_id", intake_id).execute().data
        rows = [{**r, "interpretation_id": interp["id"]} for r in pl]
        for i in range(0, len(rows), 500):
            ctx.db.table("measure_placements").upsert(rows[i:i + 500], on_conflict="interpretation_id,measure_id").execute()
    return interp
