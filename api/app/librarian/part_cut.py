"""part_cut: cut the staves of one or more chosen instruments out of a scanned full score, as an agent run. Payload
`{score_id, instruments: [str] (or instrument: str), interpretation_id?, pages?: [int], answer?, resume_from?, max_cost_usd?}`.

Meta model: **Muse Spark 1.3** through the agent loop (`app.agent.run_agent`): one model call per turn, plus one
call inside `read_header` (the instrument list from page 1's numbered overlay, `header.py`), one inside `read_page`
(Spark labels the numbered staff overlay: which staves are each wanted instrument's, per system) and one per block
inside `commit_system` (Spark re-reads the block alone and names the instrument; it must name one of the block's).
Geometry and the cut are OpenCV (`cut.py`), no model.

A part export is a selection of instruments (CK, 2026-10-28): per system the chosen staves are kept together in score
order as one block when they are adjacent; when the chosen set skips a staff in the middle (soprano and tenor without
alto) each contiguous run is its own block, cleaned and verified on its own, and the blocks are stacked vertically
into one strip image per system with a small gap between them.

The loop carries the guarantees: `commit_system` is a commit tool whose checks (staves exist in the system, total
count matches the header, crop verify and model recheck per block; "absent" only where the labels say so) the model
cannot skip; after `max_refusals` the run parks with `needs_review` and a typed question `{kind: "choose_staves",
page, system, instruments, proposal, blocks, staff_boxes, image_key, allowed}`; the admin's answer `{staves: [...] |
"absent"}` or `{blocks: [[...], ...] | "absent"}` is applied as if the commit succeeded and the run resumes. `finish`
refuses while a page is uncommitted.

Writes: strips to `{score_id}/parts/{slug}/p{page:03}-s{k}.png` (slug = the instruments' slugs joined with "+"), a
derived `sources` row (kind `part_images`, needs migration 20261028090000) whose meta carries `instruments` and the
per-system blocks, an `interpretations` row (engine `part-cut-agent`) whose summary carries the counts and the log,
and the page-intake interpretation's placements copied under the new interpretation (same `measures` ids, nothing
deleted). Agent state lives in `jobs.result.agent` (persisted every turn).
"""
from __future__ import annotations

import json
import re
import time
from decimal import Decimal
from typing import Any

from anthropic import AsyncAnthropic
from PIL import Image

from ..agent import AgentState, Refusal, Stop, ToolBox, run_agent
from ..llm import _client as default_client, model_name as default_model, price
from ..settings import settings
from ..spend import Charge
from . import Job, JobContext, handler
from . import header as hdr
from .cut import cut_system, overlay_png, page_geometry, to_png, verify
from .header import same_instrument  # noqa: F401  (re-exported: the matcher lives with the header)
from .process_pages import page_paths

ENGINE = "part-cut-agent"
STACK_GAP_SPACES = 1.5   # white gap between stacked blocks, in staff spaces
RECHECK_MAX_TOKENS = 4000   # Spark's reasoning counts against max_tokens; 3 of 9 rechecks on Dvořák ran out at 2048 (GENERAL.md)
SYSTEM = """You are an orchestral librarian cutting the chosen instruments' staves out of a scanned full score. Geometry has already found every staff, system and barline; you only decide which numbered staves belong to the wanted instruments on each system, then commit them. Work page by page: read_header once, then for each page read_page and commit_system for every system (the staff numbers of every wanted instrument, or "absent" when none of their staves are printed in that system), then finish. Trust the margin labels first, then clefs, brace and score order. Call exactly one tool per turn, no prose."""

# The in-tool calls (header, labels, recheck) are not agent turns: with the agent's SYSTEM ("call exactly one tool
# per turn") Spark sometimes answers a label request with a pretend read_header call instead of the JSON asked for.
ASK_SYSTEM = "You are an orchestral librarian reading a scanned page of a full score. Answer with strict JSON only, no prose."

LABEL_PROMPT = """Page {page} of a scanned full score. Every staff has a blue box and a yellow tag with its number ({first}..{last}, top to bottom); grey boxes mark the systems: {systems_desc}. Instrument wanted: "{instrument}" ({staves} staves per system according to the header).
{header_context}For each system give the staff numbers that belong to the wanted instrument (empty if its staves are not printed in that system) and whether it is "playing", "resting" or "absent". Return only JSON: {{"systems": [{{"index": 1, "wanted_staves": [11, 12], "status": "playing"}}], "confidence": "high|medium|low", "notes": ""}}"""

LABEL_PROMPT_MULTI = """Page {page} of a scanned full score. Every staff has a blue box and a yellow tag with its number ({first}..{last}, top to bottom); grey boxes mark the systems: {systems_desc}. Instruments wanted: {wanted_desc}.
{header_context}For each system give, for each wanted instrument, the staff numbers that belong to it (empty if its staves are not printed in that system) and whether it is "playing", "resting" or "absent". Return only JSON: {{"systems": [{{"index": 1, "wanted": [{example}]}}], "confidence": "high|medium|low", "notes": ""}}"""

RECHECK_PROMPT = """This image is a block of staves cut from a scanned full score. The left margin may carry the instrument label; otherwise judge from the clefs, brace or bracket and the writing. Which instrument or section is this block? Return only JSON: {"instrument": "short name", "confidence": "high|medium|low", "why": "one sentence"}"""


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "part"


def instruments_of(payload: dict[str, Any]) -> list[str]:
    """`instruments: [str]`, or the one-instrument `instrument: str`; trimmed, deduplicated, order kept."""
    raw = payload.get("instruments")
    if raw is None:
        raw = payload.get("instrument")
    if isinstance(raw, str):
        raw = [raw]
    out: list[str] = []
    for x in raw or []:
        s = str(x).strip()
        if s and s not in out:
            out.append(s)
    return out


def runs(staves: list[int]) -> list[list[int]]:
    """Contiguous runs of staff numbers, each in order: [11, 12, 14] -> [[11, 12], [14]]."""
    blocks: list[list[int]] = []
    for s in sorted(set(int(x) for x in staves)):
        if blocks and s == blocks[-1][-1] + 1:
            blocks[-1].append(s)
        else:
            blocks.append([s])
    return blocks


def stack_crops(crops: list[Image.Image], gap: int) -> Image.Image:
    """The blocks of one system stacked vertically, left-aligned, a white gap between them."""
    if len(crops) == 1:
        return crops[0]
    w = max(c.width for c in crops)
    h = sum(c.height for c in crops) + gap * (len(crops) - 1)
    out = Image.new("RGB", (w, h), (255, 255, 255))
    y = 0
    for c in crops:
        out.paste(c.convert("RGB"), (0, y))
        y += c.height + gap
    return out


class NoJSON(ValueError):
    """Every attempt of an in-tool call failed to give the JSON asked for; carries what the attempts cost."""
    def __init__(self, msg: str, cost_usd: float):
        super().__init__(msg)
        self.cost_usd = cost_usd


async def ask_model(ctx: JobContext, client: AsyncAnthropic, model: str, prompt: str, png: bytes, *, max_tokens: int = 2048,
                    effort: str = "low", retries: int = 1, require: str | None = None) -> dict[str, Any]:
    """One image+text call outside the loop (header, labels, recheck), charged like a turn. The answer is parsed with
    the JSON repair; a reply cut off at max_tokens or one that does not parse is asked again (`retries` times,
    every attempt charged); so is JSON without the `require`d list. `_cost_usd` is the sum, `_retries` the reasons;
    raises when no attempt parsed."""
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": ctx.png_b64(png)}}, {"type": "text", "text": prompt}]
    is_meta = settings.llm_provider == "meta" or model.startswith("muse")
    total, why, data, err = 0.0, [], None, None
    for _ in range(retries + 1):
        res = await client.messages.create(model=model, max_tokens=max(max_tokens, 1024) if is_meta else max_tokens, system=ASK_SYSTEM,
                                           messages=[{"role": "user", "content": content}], output_config={"effort": effort})
        u = res.usage
        cost = price(res.model or model, u.input_tokens, u.output_tokens)
        ctx.charge(Charge("meta" if is_meta else "anthropic", res.model or model, "spark" if is_meta else "claude", cost, u.input_tokens, u.output_tokens))
        total += float(cost)
        text = "".join(b.text for b in res.content if b.type == "text")
        truncated = res.stop_reason == "max_tokens"
        try:
            data, repaired = hdr.parse_json(text)
            data["_repaired"] = repaired
            err = None
            if require and not isinstance(data.get(require), list):
                raise ValueError(f"no {require!r} list in {text.strip()[:160]!r}")
        except (ValueError, json.JSONDecodeError) as e:
            data, err = None, e
        if data is not None and not truncated:
            break
        why.append(f"truncated at {u.output_tokens} output tokens" if truncated else f"unparseable: {err}")
    if data is None:
        raise NoJSON(f"no JSON after {len(why)} attempt(s): {'; '.join(why)}", total)
    data["_cost_usd"], data["_retries"] = total, why
    return data


def parse_answer(answer: Any) -> list[int] | str:
    """The admin's answer as staff numbers or "absent": `{staves: [...] | "absent"}`, `{blocks: [[...], ...] | "absent"}`,
    a bare list, or a string holding the numbers."""
    ans = answer
    if isinstance(ans, str):
        s = ans.strip()
        ans = json.loads(s) if s.startswith("{") else {"staves": s}
    if isinstance(ans, list):
        ans = {"staves": ans}
    if not isinstance(ans, dict):
        return "absent"
    chosen = ans.get("blocks") if ans.get("blocks") is not None else ans.get("staves", "absent")
    if isinstance(chosen, str):
        if chosen.strip().lower() == "absent":
            return "absent"
        chosen = [int(x) for x in re.findall(r"\d+", chosen)]
    flat: list[int] = []
    for x in chosen or []:
        flat.extend(int(y) for y in x) if isinstance(x, list) else flat.append(int(x))
    return sorted(set(flat)) or "absent"


@handler("part_cut")
async def part_cut(job: Job, ctx: JobContext, *, client: AsyncAnthropic | None = None, model: str | None = None) -> dict:
    t0 = time.time()
    p = job.payload
    score_id = p["score_id"]
    instruments = instruments_of(p)
    if not instruments:
        raise RuntimeError("the payload names no instrument (instruments: [...])")
    label = " + ".join(instruments)                       # the export's name in logs, questions and the parts row
    part_slug = "+".join(slug(i) for i in instruments)
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
    sc.setdefault("commits", {})    # "page:system" -> {"staves" | "absent", "blocks", "key", "verify"}
    sc.setdefault("questions", 0)
    sc.setdefault("log", [])
    cache: dict[int, tuple[Any, Any, Any]] = {}   # page -> (geom, bw, page image), not persisted

    def load_page(n: int):
        if n not in cache:
            png = ctx.storage_download(paths[n - 1])
            cache[n] = page_geometry(png)
        return cache[n]

    def header_staves(instrument: str) -> int:
        inst = hdr.match_instrument((sc["header"] or {}).get("instruments") or [], instrument)
        if inst is not None:
            return max(1, int(inst.get("staves") or 1))
        return 2 if hdr.family(instrument) in ("piano", "harp", "organ") else 1

    def want_total() -> int:
        return sum(header_staves(i) for i in instruments)

    def wanted_of(name: str, fallback: int) -> str | None:
        """Which wanted instrument a name in the label reply stands for: the same spelling, else the synonym table, else the position."""
        low = name.strip().lower()
        for i in instruments:
            if i.lower() == low:
                return i
        for i in instruments:
            if name.strip() and same_instrument(name, i):
                return i
        return instruments[fallback] if 0 <= fallback < len(instruments) else None

    def proposal_entry(s: dict, i: int) -> dict:
        """One system of the label reply -> {system, staves (union), blocks, per_instrument, status}."""
        per: dict[str, list[int]] = {}
        statuses: list[str] = []
        wanted = s.get("wanted")
        if isinstance(wanted, list):
            for k, w in enumerate(wanted):
                if not isinstance(w, dict):
                    continue
                inst = wanted_of(str(w.get("instrument") or ""), k)
                if inst is not None:
                    per[inst] = sorted(set(per.get(inst, []) + [int(x) for x in (w.get("staves") or []) if str(x).lstrip("-").isdigit()]))
                    statuses.append(str(w.get("status") or ""))
        elif isinstance(wanted, dict):
            for k, (name, staves) in enumerate(wanted.items()):
                inst = wanted_of(str(name), k)
                if inst is not None and isinstance(staves, list):
                    per[inst] = sorted(set(per.get(inst, []) + [int(x) for x in staves if str(x).lstrip("-").isdigit()]))
        elif isinstance(s.get("wanted_staves"), list) and len(instruments) == 1:
            per[instruments[0]] = sorted(set(int(x) for x in s["wanted_staves"] if str(x).lstrip("-").isdigit()))
        union = sorted(set(x for v in per.values() for x in v))
        status = str(s.get("status") or "")
        if not union:
            status = "absent"
        elif not status:
            status = "playing" if any(x == "playing" for x in statuses) else (statuses[0] if statuses else "playing")
        return {"system": int(s.get("index", i + 1)), "staves": union, "blocks": runs(union), "per_instrument": per, "status": status}

    def block_instruments(page: int, system: int, block: list[int]) -> list[str]:
        """The wanted instruments a block holds, from the page's proposal; every wanted instrument when the proposal cannot say."""
        prop = next((q for q in (sc["pages"].get(str(page)) or {}).get("proposal", []) if q["system"] == system), None)
        per = (prop or {}).get("per_instrument") or {}
        found = [i for i in instruments if set(per.get(i) or []) & set(block)]
        return found or list(instruments)

    def names_block(said: str, expected: list[str]) -> bool:
        """The recheck's name fits the block: one of the block's instruments, or "chorus"/"choir" for a block of voices.
        Accepting any instrument of the export was tried live (Beethoven 9 S+T run 2) and let a block shifted by one
        staff through; the strict rule asks the admin instead."""
        if any(same_instrument(said, i) for i in expected):
            return True
        return hdr.family(said) == "chorus" and all(hdr.family(i) in hdr.VOICES for i in expected)

    def check_against_labels(page: int, system: int, block: list[int]) -> None:
        """A block must hold exactly the staves the labels put in it: the block's instruments (those whose proposed
        staves it touches) account for all of its staves. Catches a box shifted by one staff before any model call."""
        prop = next((q for q in (sc["pages"].get(str(page)) or {}).get("proposal", []) if q["system"] == system), None)
        per = (prop or {}).get("per_instrument") or {}
        touched = [i for i in instruments if set(per.get(i) or []) & set(block)]
        if not touched:
            return                                   # the labels say nothing about these staves; verify and the recheck decide
        labelled = sorted(set(s for i in touched for s in per[i]) & set(block))
        stray = [s for s in block if s not in labelled]
        if stray or len(block) != sum(header_staves(i) for i in touched):
            raise Refusal(f"the labels put {', '.join(f'{i} on {per[i]}' for i in touched)} in system {system}; the block {block} "
                          + (f"adds staff {stray} that the labels give to no wanted instrument" if stray else f"does not hold the {sum(header_staves(i) for i in touched)} staves they expect")
                          + ". Commit the labelled staves, or a block that shares none of them if the labels are wrong")

    async def do_commit(page: int, system: int, staves: list[int] | str, *, recheck: bool = True) -> dict:
        key = f"{page}:{system}"
        geom, bw, im = load_page(page)
        sysd = next((s for s in geom["systems"] if s["index"] == system), None)
        if sysd is None:
            raise Refusal(f"page {page} has no system {system}; it has systems {[s['index'] for s in geom['systems']]}")
        if staves == "absent":
            prop = next((q for q in (sc["pages"].get(str(page)) or {}).get("proposal", []) if q["system"] == system), None)
            if recheck and (prop is None or prop["staves"]):   # an absent commit has no crop to check; the labels must agree
                said = "did not cover this system" if prop is None else f"proposed staves {prop['staves']} ({prop['status']})"
                raise Refusal(f"the labels for page {page} {said}; commit \"absent\" only for a system where no staff of {label} is printed, "
                              f"otherwise commit the staves (system {system} has staves {sysd['staff_indices']})")
            sc["commits"][key] = {"staves": "absent", "blocks": [], "key": None, "verify": None}
            sc["log"].append(f"Page {page} system {system}: {label} absent")
            return {"committed": key, "status": "absent"}
        staves = sorted(set(int(s) for s in staves))
        missing = [s for s in staves if s not in sysd["staff_indices"]]
        if missing:
            raise Refusal(f"staves {missing} are not in system {system} of page {page}, which has staves {sysd['staff_indices']}")
        want = want_total()
        if len(staves) != want and recheck:   # the admin's answer is final (011): no count, verify or recheck refusal
            per = ", ".join(f"{i} {header_staves(i)}" for i in instruments)
            raise Refusal(f"{label} has {want} staves per system according to the header ({per}); you named {len(staves)}")
        blocks = runs(staves)
        if recheck:
            for block in blocks:
                check_against_labels(page, system, block)
        crops, boxes, verifies = [], [], []
        for block in blocks:
            crop, box, checks = cut_system(bw, im, geom, sysd, block)
            if not checks["pass"] and len(block) > 1 and checks["staves_in_crop"]["pass"] and not checks["barlines_present"]["pass"]:
                # vocal staves: barlines stop at each staff and do not cross the lyric gap, so no barline runs through
                # the whole block; the block is sound when every staff of it has its barlines on its own
                per_staff = [verify(crop, geom, sysd, [s], box)["barlines_present"] for s in block]
                if all(v["pass"] for v in per_staff):
                    checks["barlines_present"] = {**checks["barlines_present"], "pass": True, "per_staff": True, "missing": []}
                    checks["pass"] = all(v["pass"] for v in checks.values() if isinstance(v, dict) and "pass" in v and not v.get("informational"))
            if not checks["pass"] and recheck:
                failed = [k for k, v in checks.items() if isinstance(v, dict) and "pass" in v and not v.get("informational") and not v["pass"]]
                raise Refusal(f"the crop of staves {block} failed the geometric check {failed}: {json.dumps({k: checks[k] for k in failed})}")
            crops.append(crop)
            boxes.append(box)
            verifies.append({k: v for k, v in checks.items() if k != "clean"})
        if recheck:
            for block, crop in zip(blocks, crops):
                expected = block_instruments(page, system, block)
                said = await ask_model(ctx, c, m, RECHECK_PROMPT, to_png(crop), max_tokens=RECHECK_MAX_TOKENS)
                sc["cost_usd"] = sc.get("cost_usd", 0.0) + said.pop("_cost_usd", 0.0)
                if not names_block(str(said.get("instrument", "")), expected):
                    raise Refusal(f"re-reading the block of staves {block} alone, the model calls it {said.get('instrument')!r}, "
                                  f"not {' / '.join(expected)!r} ({said.get('why', '')})")
        sp = float(sum(s["spacing"] for s in geom["staves"] if s["index"] in staves) / len(staves))
        png = to_png(stack_crops(crops, int(round(STACK_GAP_SPACES * sp))))
        storage_key = f"{score_id}/parts/{part_slug}/p{page:03}-s{system}.png"
        ctx.storage_upload(storage_key, png, "image/png")
        sc["commits"][key] = {"staves": staves, "blocks": blocks, "key": storage_key, "boxes": boxes, "verify": verifies, "bars": sysd["n_measures"],
                              "modes": [v["mode"] for v in verifies]}
        how = f"{len(blocks)} blocks stacked" if len(blocks) > 1 else "one block"
        sc["log"].append(f"Page {page} system {system}: staves {staves} cut ({how}), {sysd['n_measures']} bars")
        return {"committed": key, "staves": staves, "blocks": blocks, "storage_key": storage_key, "bars": sysd["n_measures"]}

    box = ToolBox()

    @box.tool("read_header", "Read the score header on page 1: instruments in order, staves each, clefs, key, time. Call once, first.", {"properties": {}})
    async def read_header(args, st):
        if sc["header"] is None:
            geom, bw, im = load_page(1)
            if not geom["staves"]:
                raise RuntimeError("page 1 has no staves the geometry could find; the header cannot be read")
            ov = overlay_png(im, geom)
            ctx.storage_upload(f"{score_id}/parts/{part_slug}/overlay-p001.png", ov, "image/png")
            score = ctx.db.table("scores").select("title,composer").eq("id", score_id).single().execute().data or {}
            title = ", ".join(x for x in (score.get("composer"), score.get("title")) if x)
            try:
                data = await ask_model(ctx, c, m, hdr.prompt(1, geom, title), ov, max_tokens=hdr.HEADER_MAX_TOKENS, effort="low",
                                       require="instruments")
            except NoJSON as e:
                sc["cost_usd"] = sc.get("cost_usd", 0.0) + e.cost_usd
                raise
            sc["cost_usd"] = sc.get("cost_usd", 0.0) + data.pop("_cost_usd", 0.0)
            retries = data.pop("_retries", [])
            sc["header"] = {**hdr.reconcile(data, geom), "retries": retries, "json_repaired": data.pop("_repaired", False)}
            h = sc["header"]
            sc["log"].append(f"Header: {', '.join(f'{i['name']} ({i['staves']})' for i in h['instruments'])}; {h['expected_staves']} staves"
                             + ("" if h["validation"]["match"] else f", geometry found {h['validation']['geometry_staves_system1']} in system 1")
                             + (f"; {len(retries)} retry: {retries}" if retries else ""))
        h = sc["header"]
        matched = {}
        for i in instruments:
            match = hdr.match_instrument(h.get("instruments") or [], i)
            matched[i] = match and {"label": match["label"], "position": match["position"], "staves": match["staves"]}
        return {"header": {k: v for k, v in h.items() if k not in ("retries", "json_repaired")}, "instruments": instruments,
                "matched": matched, "staves_per_system": {i: header_staves(i) for i in instruments}, "staves_total": want_total()}

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

    def header_context(geom: dict) -> str:
        """hdr.context for every wanted instrument: the score order once, then each instrument's lines."""
        out: list[str] = []
        for k, i in enumerate(instruments):
            lines = hdr.context(sc["header"], i, geom).rstrip("\n").split("\n")
            if not lines or not lines[0]:
                continue
            out.extend(lines if k == 0 else lines[1:])
        return ("\n".join(out) + "\n") if out else ""

    @box.tool("read_page", "Geometry of one page (staves, systems, barlines) and the model's proposal of which staves are the wanted instruments', from the numbered overlay.", {"properties": {"page": {"type": "integer"}}, "required": ["page"]})
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
        if len(instruments) == 1:
            prompt = LABEL_PROMPT.format(page=n, first=1, last=len(geom["staves"]), systems_desc=desc, instrument=instruments[0],
                                         staves=header_staves(instruments[0]), header_context=header_context(geom))
        else:
            wanted_desc = ", ".join(f'"{i}" ({header_staves(i)} staves per system according to the header)' for i in instruments)
            example = ", ".join(json.dumps({"instrument": i, "staves": [], "status": "playing"}) for i in instruments)
            prompt = LABEL_PROMPT_MULTI.format(page=n, first=1, last=len(geom["staves"]), systems_desc=desc, wanted_desc=wanted_desc,
                                               example=example, header_context=header_context(geom))
        try:
            lab = await ask_model(ctx, c, m, prompt, ov, max_tokens=8000, require="systems")
        except NoJSON as e:   # no labels: the header's score order still proposes the full systems
            lab = {"systems": [], "confidence": "low", "notes": f"label call failed ({e}); proposal by score order only", "_cost_usd": e.cost_usd}
        sc["cost_usd"] = sc.get("cost_usd", 0.0) + lab.pop("_cost_usd", 0.0)
        label_retries = lab.pop("_retries", [])
        proposal = [proposal_entry(s, i) for i, s in enumerate(lab.get("systems") or []) if isinstance(s, dict)]
        for s in geom["systems"]:   # a system the labels left out: the header's order, when the system is the full set
            if any(q["system"] == s["index"] for q in proposal):
                continue
            per = {i: g for i in instruments if (g := hdr.by_order(sc["header"], i, s))}
            union = sorted(set(x for v in per.values() for x in v))
            if union:
                proposal.append({"system": s["index"], "staves": union, "blocks": runs(union), "per_instrument": per, "status": "by-order"})
        proposal.sort(key=lambda q: q["system"])
        summary = {"page": n, "staves": len(geom["staves"]),
                   "systems": [{"index": s["index"], "staves": s["staff_indices"], "bars": s["n_measures"]} for s in geom["systems"]],
                   "proposal": proposal, "confidence": lab.get("confidence"), "notes": lab.get("notes", "")}
        sc["pages"][str(n)] = {"geometry": geom, "proposal": proposal, "overlay_key": ov_key, "summary": summary}
        sc["log"].append(f"Page {n}: {len(geom['staves'])} staves, {len(geom['systems'])} systems; proposal {[(q['system'], q['staves'] or q['status']) for q in proposal]}"
                         + (f"; label retries: {label_retries}" if label_retries else ""))
        return summary

    @box.tool("commit_system", "Commit which staves of a system are the wanted instruments' (or \"absent\"). Give `staves` (all of them in one list; adjacent staves become one block, a skipped staff splits the cut into stacked blocks) or `blocks` (one list per block). Checked: staves exist, total count matches the header, crop verify and model recheck per block; \"absent\" must agree with the page labels.",
              {"properties": {"page": {"type": "integer"}, "system": {"type": "integer"},
                              "staves": {"description": "staff numbers, or the string \"absent\"", "anyOf": [{"type": "array", "items": {"type": "integer"}}, {"type": "string", "enum": ["absent"]}]},
                              "blocks": {"description": "lists of staff numbers, one per block, or the string \"absent\"", "anyOf": [{"type": "array", "items": {"type": "array", "items": {"type": "integer"}}}, {"type": "string", "enum": ["absent"]}]}},
               "required": ["page", "system"]}, commit=True)
    async def commit_system(args, st):
        n = int(args["page"])
        if str(n) not in sc["pages"]:
            raise Refusal(f"read_page({n}) first")
        given = args.get("blocks") if args.get("blocks") is not None else args.get("staves")
        if given is None:
            raise Refusal('give staves (a list of staff numbers) or blocks (a list of lists), or the string "absent"')
        if isinstance(given, str):
            if given.strip().lower() != "absent":
                raise Refusal('staves must be a non-empty list of staff numbers or "absent"')
            chosen: list[int] | str = "absent"
        else:
            flat: list[int] = []
            for x in given if isinstance(given, list) else []:
                if isinstance(x, list):
                    flat.extend(int(y) for y in x if isinstance(y, (int, float)) and not isinstance(y, bool))
                elif isinstance(x, (int, float)) and not isinstance(x, bool):
                    flat.append(int(x))
            if not flat:
                raise Refusal('staves must be a non-empty list of staff numbers or "absent"')
            chosen = flat
        return await do_commit(n, int(args["system"]), chosen)

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
        chosen = parse_answer(p["answer"])
        state.refusals = {}
        out = await do_commit(int(q["page"]), int(q["system"]), chosen, recheck=False)
        sc["log"].append(f"Page {q['page']} system {q['system']}: {chosen} chosen by the admin")
        answer_text = f"The admin decided page {q['page']} system {q['system']}: {json.dumps(chosen)}. It is committed ({json.dumps(out)}). Continue with the next uncommitted system or finish."

    def persist(d: dict[str, Any]) -> None:
        ctx.result["agent"] = d
        ctx.db.table("jobs").update({"result": ctx.result}).eq("id", job.id).execute()

    st = await run_agent(system=SYSTEM, tools=box, state=state, answer=answer_text, client=c, model=m, persist=persist, charge=ctx.charge,
                         user_text=None if resumed else f'Cut the part "{label}" (instruments: {json.dumps(instruments)}) from pages {pages}. Start with read_header.',
                         max_turns=8 + 6 * len(pages), max_cost_usd=float(p.get("max_cost_usd", 2.0)), max_refusals=3)
    cost = float(Decimal(str(st.cost_usd)) + Decimal(str(sc.get("cost_usd", 0.0))))
    interp = write_interpretation(ctx, score_id, src, p.get("interpretation_id"), instruments, part_slug, sc, st, pages, cost, t0)

    if st.status == "needs_review":
        q = st.question_payload
        args = q.get("args") or {}
        n, k = int(args.get("page") or 0), int(args.get("system") or 0)
        read = sc["pages"].get(str(n)) or {}
        geom = read.get("geometry") or {"staves": [], "systems": []}
        sysd = next((s for s in geom["systems"] if s["index"] == k), None)
        prop = next((pr for pr in read.get("proposal", []) if pr["system"] == k), None)
        proposal = (prop["staves"] or "absent") if prop else (args.get("blocks") if args.get("blocks") is not None else args.get("staves"))
        per = (prop or {}).get("per_instrument") or {}
        blocks = [{"staves": b, "instruments": [i for i in instruments if set(per.get(i) or []) & set(b)] or list(instruments)}
                  for b in ((prop or {}).get("blocks") or [])]
        sc["questions"] += 1
        payload = {"kind": "choose_staves", "page": n, "system": k, "instrument": label, "instruments": instruments, "interpretation_id": interp["id"],
                   "proposal": proposal, "blocks": blocks, "staves_per_instrument": {i: header_staves(i) for i in instruments},
                   "last_attempt": args.get("blocks") if args.get("blocks") is not None else args.get("staves"), "feedback": q.get("feedback"),
                   "staff_boxes": [{"index": s["index"], "y_top": s["y_top"], "y_bottom": s["y_bottom"], "x0": s["x0"], "x1": s["x1"]}
                                   for s in geom["staves"] if sysd is None or s["index"] in sysd["staff_indices"]],
                   "image_key": read.get("overlay_key"),
                   "allowed": {"staves": "list of staff numbers from staff_boxes (a skipped staff splits the cut into stacked blocks)",
                               "blocks": "lists of staff numbers, one per block", "absent": True},
                   "answer_format": '{"staves": [11, 12]} or {"blocks": [[11], [13]]} or {"staves": "absent"}'}
        question = f"Which staves on page {n}, system {k} are {label}'s? {q.get('feedback', '')}"
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
        "meta": {"instrument": label, "instruments": instruments, "slug": part_slug, "derived_from_source_id": src["id"], "interpretation_id": interp["id"],
                 "systems": [{"page": int(k.split(":")[0]), "system": int(k.split(":")[1]), "staves": v["staves"], "blocks": v.get("blocks") or [],
                              "key": v["key"], "bars": v.get("bars")} for k, v in commits]},
    }).execute().data[0]
    ctx.db.table("interpretations").update({"status": "done", "finished_at": ctx.now(), "params": {"instrument": label, "instruments": instruments, "source_id": derived["id"], "state": sc}}).eq("id", interp["id"]).execute()
    ctx.db.table("parts").upsert({"score_id": score_id, "name": label, "position": 0, "storage_path": keys[0] if keys else None}, on_conflict="score_id,name").execute()
    await ctx.progress(1.0, f"{label}: {len(keys)} systems cut")
    return {**ctx.result, "interpretation_id": interp["id"], "source_id": derived["id"], "systems_cut": len(keys), "absent": len(commits) - len(keys),
            "questions": sc["questions"], "cost_usd": cost, "seconds": round(time.time() - t0, 1)}


def write_interpretation(ctx: JobContext, score_id: str, src: dict, intake_id: str | None, instruments: list[str], part_slug: str, sc: dict, st: AgentState,
                         pages: list[int], cost: float, t0: float) -> dict:
    """The run's interpretation row with counts and log; placements copied from the page-intake interpretation (stable measure ids)."""
    label = " + ".join(instruments)
    commits = sc["commits"].values()
    summary = {"instrument": label, "instruments": instruments, "pages": len(pages), "pages_read": len(sc["pages"]), "systems_cut": sum(1 for v in commits if v["key"]),
               "absent": sum(1 for v in commits if not v["key"]), "questions_asked": sc["questions"] + (1 if st.status == "needs_review" else 0),
               "turns": st.turn, "status": st.status, "models": {"geometry": "opencv", "labels": "spark"}, "log": (sc["log"] + st.log)[-40:]}
    existing = sc.get("interpretation_id")
    row = {"status": "running" if st.status != "done" else "done", "summary": summary, "cost_usd": cost, "latency_ms": int((time.time() - t0) * 1000)}
    if existing:
        return ctx.db.table("interpretations").update(row).eq("id", existing).execute().data[0]
    prev = ctx.db.table("interpretations").select("version").eq("score_id", score_id).order("version", desc=True).limit(1).execute().data
    interp = ctx.db.table("interpretations").insert({**row, "score_id": score_id, "source_id": src["id"], "version": (prev[0]["version"] + 1) if prev else 1,
                                                     "engine": ENGINE, "params": {"instrument": label, "instruments": instruments, "slug": part_slug, "intake_interpretation_id": intake_id}}).execute().data[0]
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
