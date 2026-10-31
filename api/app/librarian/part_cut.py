"""part_cut: cut the staves of one or more chosen instruments out of a scanned full score, as an agent run. Payload
`{score_id, instruments: [str] (or instrument: str), interpretation_id?, pages?: [int], answer?, resume_from?, max_cost_usd?}`.

Meta model: **Muse Spark 1.3** through the agent loop (`app.agent.run_agent`): one model call per turn, plus one
call inside `read_header` (the instrument list from page 1's numbered overlay, `header.py`), one inside `read_page`
(Spark labels the numbered staff overlay: which staves are each wanted instrument's, per system) and one per block
inside `commit_system` (the closed recheck: Spark sees the block alone and is told what the header's staff order and the page's labels say
it is, the part, its staff count and clef; it answers yes or no with the clefs it sees; a no, or a seen clef that
contradicts the header's, refuses the commit; CK 2026-10-28: the open "which instrument is this?" question asked
about three questions in five choir pages because a lone C-clef staff is ambiguous).
Geometry and the cut are OpenCV (`cut.py`), no model; the header's staff count drives the staff recovery on every
page read after it, and the header's families set the lyric rule's `voice` / `voice_above` flags per block.

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

The book's label memory (`label_memory.py`, `scores.label_memory`; 006 agentic memory rule, CK 2026-10-30): the
header (the book's own, from `process_pages`, when it has one) seeds it, the label call reads every printed margin
label per system, and a wanted instrument whose label the memory knows is settled on that system: from an admin's
answer, no recheck; from a model read, the recheck's doubts give way when it saw the same label. Commits that pass
every check and the admin's answers teach it, so a page printing "Klav." is not asked about again.

Writes: strips to `{score_id}/parts/{slug}/p{page:03}-s{k}.png` (slug = the instruments' slugs joined with "+"), a
derived `sources` row (kind `part_images`, needs migration 20261028090000) whose meta carries `instruments` and the
per-system blocks, an `interpretations` row (engine `part-cut-agent`) whose summary carries the counts and the log,
and the page-intake interpretation's placements copied under the new interpretation (same `measures` ids, nothing
deleted). Agent state lives in `jobs.result.agent` (persisted every turn).
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from decimal import Decimal
from typing import Any

from anthropic import AsyncAnthropic
from PIL import Image

from ..agent import AgentState, Refusal, Stop, ToolBox, run_agent
from ..llm import _client as default_client, model_name as default_model
from . import Job, JobContext, handler
from . import header as hdr
from . import label_memory
from .ask import ASK_SYSTEM, NoJSON, ask_model  # noqa: F401  (re-exported: the benchmark imports ASK_SYSTEM from here)
from .cut import cut_system, overlay_png, page_geometry, to_png, verify
from .header import same_instrument  # noqa: F401  (re-exported: the matcher lives with the header)
from .label_memory import LabelMemory, same_part
from .process_pages import CONCURRENCY as PREREAD_CONCURRENCY, page_paths

ENGINE = "part-cut-agent"
STACK_GAP_SPACES = 1.5   # white gap between stacked blocks, in staff spaces
RECHECK_MAX_TOKENS = 4000   # Spark's reasoning counts against max_tokens; 3 of 9 rechecks on Dvořák ran out at 2048 (GENERAL.md)
# Efforts of the in-tool calls (speed pass 2026-10-30, benchmark 3.12). Labels at minimal: 20 of 21 pages gave the same
# staves as low on the same overlay (Rach 1, PC3, B9 x2, Dvorak), the one difference low's error; a read `label_guard`
# doubts is read again at low on the spot. Rechecks stay at low: 12 of 14 yes/no agreed, the two that did not were the
# soprano C clef, the recheck's known weak spot.
LABEL_EFFORT = "minimal"
RECHECK_EFFORT = "low"
FALLBACK_EFFORT = "low"
PREREAD_PAGES = True   # every page's label call ahead of the agent (`start_prereads`); the scripted tests turn it off
SYSTEM = """You are an orchestral librarian cutting the chosen instruments' staves out of a scanned full score. Geometry has already found every staff, system and barline; you only decide which numbered staves belong to the wanted instruments on each system, then commit them. Work page by page: read_header once, then for each page read_page and commit_system for every system (the staff numbers of every wanted instrument, or "absent" when none of their staves are printed in that system), then finish. Trust the margin labels first, then clefs, brace and score order. Call exactly one tool per turn, no prose."""

LABEL_PROMPT = """Page {page} of a scanned full score. Every staff has a blue box and a yellow tag with its number ({first}..{last}, top to bottom); grey boxes mark the systems: {systems_desc}. Instrument wanted: "{instrument}" ({staves} staves per system according to the header).
{header_context}For each system give the staff numbers that belong to the wanted instrument (empty if its staves are not printed in that system) and whether it is "playing", "resting" or "absent". Also list every instrument name printed in that system's left margin, exactly as printed (abbreviations as they are), with the staff numbers each one labels (empty when the margin is bare). Return only JSON: {{"systems": [{{"index": 1, "wanted_staves": [11, 12], "status": "playing", "margin_labels": [{{"text": "Klav.", "staves": [11, 12]}}]}}], "confidence": "high|medium|low", "notes": ""}}"""

LABEL_PROMPT_MULTI = """Page {page} of a scanned full score. Every staff has a blue box and a yellow tag with its number ({first}..{last}, top to bottom); grey boxes mark the systems: {systems_desc}. Instruments wanted: {wanted_desc}.
{header_context}For each system give, for each wanted instrument, the staff numbers that belong to it (empty if its staves are not printed in that system) and whether it is "playing", "resting" or "absent". Also list every instrument name printed in that system's left margin, exactly as printed (abbreviations as they are), with the staff numbers each one labels (empty when the margin is bare). Return only JSON: {{"systems": [{{"index": 1, "wanted": [{example}], "margin_labels": [{{"text": "Fl.", "staves": [1]}}]}}], "confidence": "high|medium|low", "notes": ""}}"""

RECHECK_PROMPT = """This image is a block of staves cut from a scanned full score. {claim} Does this crop look like that: {n} staff{plural}{clef_phrase}, and no staff of another instrument? Judge from the margin label when one is printed, else from the clef{plural}, the brace or bracket and the writing.{voice_hint} Return only JSON: {{"matches": true|false, "staves_seen": {n}, "clefs_seen": ["treble"], "label_seen": "text of any margin label or empty", "why": "one line"}}"""

# Clef names as the header and Spark spell them -> one name. "c" is a C clef of unknown line.
CLEF_NAMES = {"treble": ("treble", "g", "g clef", "violin", "treble clef"), "bass": ("bass", "f", "f clef", "bass clef"),
              "soprano": ("soprano", "c1", "soprano clef", "soprano c clef", "discant"), "mezzo-soprano": ("mezzo", "mezzo-soprano", "c2", "mezzo-soprano clef"),
              "alto": ("alto", "c3", "alto clef", "alto c clef", "viola", "viola clef"), "tenor": ("tenor", "c4", "tenor clef", "tenor c clef"), "baritone": ("baritone", "c5", "baritone clef"),
              "c": ("c", "c clef", "ut")}
C_CLEFS = {"soprano", "mezzo-soprano", "alto", "tenor", "baritone", "c"}


def clef_name(text: Any) -> str | None:
    """"Treble clef" -> treble, "C3" -> alto, "C clef" -> c; None for a spelling the table does not know."""
    t = re.sub(r"[^a-z0-9 -]", "", str(text or "").lower()).strip()
    t = re.sub(r"\s+", " ", t.replace("8vb", "").replace("octave", "")).strip()
    for name, syns in CLEF_NAMES.items():
        if t in syns:
            return name
    return None


def clefs_fit(seen: list[Any], expected: list[str], voice: bool) -> bool:
    """Whether the clefs Spark saw can be the header's: nothing seen, an unknown spelling or a generic C clef passes;
    for a voice any C clef or the treble passes against any C clef or treble (the C clefs are what Spark confuses,
    and the labels and the header already say which voice it is), so only a bass clef on a soprano, alto or tenor
    staff, or a C or treble clef on a bass voice, contradicts; for an instrument a known clef must be one of the
    header's. Contradiction = no seen clef fits."""
    names = [clef_name(x) for x in seen if str(x or "").strip()]
    if not names or any(n is None or n == "c" and (not expected or set(expected) & C_CLEFS or voice) for n in names):
        return True
    if not expected:
        return True
    exp = set(expected)
    if voice:
        upper = (exp & C_CLEFS) or ("treble" in exp)
        return any((n in C_CLEFS or n == "treble") if upper else n == "bass" for n in names)
    return any(n in exp for n in names)


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


def label_guard(lab: dict[str, Any], instruments: list[str], header: dict | None) -> list[str]:
    """Why a label reply (`read_page`'s call) cannot be trusted as read: one printed label on two different staff sets
    of one system, two wanted instruments on one staff, or a bare family name ("Horn") on a wanted instrument's staves
    where the header has several parts of that family. A reply read at effort minimal with any reason is read again at
    low (the 004 speed eval's guard)."""
    from .labels import generic_name
    pool = [str(i.get("label") or i.get("name") or "") for i in (header or {}).get("instruments") or []]
    why: list[str] = []
    for k, s in enumerate(lab.get("systems") or []):
        if not isinstance(s, dict):
            continue
        idx = s.get("index", k + 1)
        seen: dict[str, list[int]] = {}
        wanted_staves: set[int] = set()
        claimed: dict[int, str] = {}
        rows = s.get("wanted") if isinstance(s.get("wanted"), list) else []
        for w in rows:
            if not isinstance(w, dict):
                continue
            for x in w.get("staves") or []:
                if str(x).lstrip("-").isdigit():
                    x = int(x)
                    if x in claimed and claimed[x] != str(w.get("instrument")):
                        why.append(f"system {idx}: staff {x} given to both {claimed[x]!r} and {w.get('instrument')!r}")
                    claimed[x] = str(w.get("instrument"))
                    wanted_staves.add(x)
        for x in s.get("wanted_staves") or []:
            if str(x).lstrip("-").isdigit():
                wanted_staves.add(int(x))
        for ml in s.get("margin_labels") or []:
            if not isinstance(ml, dict):
                continue
            text = str(ml.get("text") or "").strip()
            st = sorted(int(x) for x in (ml.get("staves") or []) if str(x).lstrip("-").isdigit())
            if not text or not st:
                continue
            key = label_memory.norm(text)
            if key in seen and seen[key] != st:
                why.append(f"system {idx}: the label {text!r} is read on staves {seen[key]} and {st}")
            seen.setdefault(key, st)
            if set(st) & wanted_staves and generic_name(text, pool):
                why.append(f"system {idx}: the label {text!r} on the wanted staves is a family name and the header has several")
    return why


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
    sc.setdefault("seen_labels", {})   # "page:system" -> [{block, label}]: the label the recheck saw on a refused block
    sc.setdefault("prereads", {})      # str(page) -> the label call's answer, read ahead of the agent (kept for a resume)
    sc.setdefault("label_fallbacks", [])   # [{page, why}]: a minimal label read the guard sent back to low
    cache: dict[int, tuple[Any, Any, Any]] = {}   # page -> (geom, bw, page image), not persisted

    # The book's label memory (006 agentic memory rule): what earlier reads and the admin's answers say each printed label
    # is. The row is the store; the job's state keeps a copy so a resumed run keeps what it learned without the column.
    mem = label_memory.load(ctx.db, score_id)
    stored = {k: e["source"] for k, e in mem.entries.items()}
    mem.merge(LabelMemory.from_dict(sc.get("label_memory")))
    mem.changed = any(stored.get(k) != e["source"] for k, e in mem.entries.items())   # the row lacks what the run learned

    def remember() -> None:
        label_memory.save(ctx.db, score_id, mem)
        sc["label_memory"] = mem.to_dict()

    def proposal_of(page: int, system: int) -> dict | None:
        return next((q for q in (sc["pages"].get(str(page)) or {}).get("proposal", []) if q["system"] == system), None)

    def margin_labels(raw: Any, sysd: dict | None) -> list[dict]:
        """The printed margin labels Spark read on a system: [{text, staves}], staves inside the system only."""
        out = []
        for ml in raw if isinstance(raw, list) else []:
            if not isinstance(ml, dict):
                continue
            text = str(ml.get("text") or ml.get("label") or "").strip()
            st = sorted(set(int(x) for x in (ml.get("staves") or []) if str(x).strip().lstrip("-").isdigit()))
            if sysd is not None:
                st = [x for x in st if x in sysd["staff_indices"]]
            if text and st:
                out.append({"text": text, "staves": st})
        return out

    def label_fits(label: str, inst: str) -> bool:
        """A printed label may be learned as `inst` unless the synonym table names another instrument for it (a human
        who chose the staves "Hr." and "Klav." print on did not say the horn is the piano)."""
        fl, fi = hdr.family(label), hdr.family(inst.split(" (")[0]) or hdr.family(inst)
        return not (fl and fi and fl != fi)

    def apply_memory(n: int, q: dict, sysd: dict) -> None:
        """Resolve the system's printed margin labels through the memory. A wanted instrument whose label resolves is
        `remembered` on that system with the label's staves, with the memory entry's source, when the page's proposal
        agrees (both reads come from the same Spark call; they must agree for a human entry to settle the block). A
        system the proposal left empty is filled from the label (source "model": the recheck still runs). When the
        two disagree nothing is remembered and the usual checks decide."""
        per = q["per_instrument"]
        rem: dict[str, dict] = {}
        for inst in instruments:
            hits = [(ml, e) for ml in q.get("margin_labels") or [] if (e := mem.resolve(ml["text"])) is not None and same_part(e["part"], inst)]
            if not hits:
                continue
            staves = sorted(set(x for ml, _ in hits for x in ml["staves"]))
            own = sorted(per.get(inst) or [])
            want = header_staves(inst)
            if len(staves) != want:     # a brace label read against one staff of the pair: the proposal's pair, when it holds it
                if len(own) == want and set(staves) <= set(own):
                    staves = own
                else:
                    continue
            human = [e for _, e in hits if e["source"] == "human"]
            e = (human or [e for _, e in hits])[0]
            label = hits[0][0]["text"]
            if own and own != staves:
                q.setdefault("label_conflicts", []).append({"instrument": inst, "label": label, "label_staves": staves, "proposed": own})
                sc["log"].append(f"Page {n} system {q['system']}: the label {label!r} ({inst}) sits on {staves} but the labels proposed {own}; not settled")
                continue
            source = e["source"]
            agreed = bool(own)          # the proposal of the same call put the instrument on exactly the label's staves
            if not own:
                per[inst] = staves
                source = "model"
                sc["log"].append(f"Page {n} system {q['system']}: {inst} on {staves} by the label {label!r}, where the labels proposed none")
            rem[inst] = {"staves": staves, "label": label, "source": source, "origin": e.get("origin"), "page": e.get("page"), "agreed": agreed}
        if rem:
            q["remembered"] = rem
            union = sorted(set(x for v in per.values() for x in v))
            if union != q["staves"]:
                q.update(staves=union, blocks=runs(union), status="remembered")

    def settled(page: int, system: int, block: list[int]) -> dict | None:
        """The block is exactly what the memory resolved for every instrument it holds: who settled it."""
        rem = (proposal_of(page, system) or {}).get("remembered") or {}
        insts = block_instruments(page, system, block)
        if not insts or any(i not in rem for i in insts):
            return None
        if sorted(set(block)) != sorted(set(x for i in insts for x in rem[i]["staves"])):
            return None
        return {"source": "human" if all(rem[i]["source"] == "human" for i in insts) else "model", "instruments": insts,
                "labels": [rem[i]["label"] for i in insts], "pages": [rem[i]["page"] for i in insts],
                "agreed": all(rem[i].get("agreed", False) for i in insts)}

    def learn_from(page: int, system: int, chosen: list[int], source: str) -> list[str]:
        """After a commit: the printed labels on the committed staves are the wanted instruments'. `source` "human" for
        the admin's answer (the page's margin labels, else the label the refused recheck saw on that very block),
        "model" for a commit that passed every check."""
        key = f"{page}:{system}"
        labels = list((proposal_of(page, system) or {}).get("margin_labels") or [])
        if source == "human":
            labels += [{"text": x["label"], "staves": x["block"]} for x in sc["seen_labels"].get(key, []) if x.get("label") and sorted(x["block"]) == sorted(chosen)]
        learned: list[str] = []
        for ml in labels:
            if not set(ml["staves"]) <= set(chosen):
                continue
            if len(instruments) == 1:
                cands = list(instruments)
            else:
                cands = [i for i in instruments if (e := mem.resolve(ml["text"])) is not None and same_part(e["part"], i)] \
                    or [i for i in instruments if label_memory.same_label(ml["text"], i)]
            if len(cands) != 1 or not label_fits(ml["text"], cands[0]):
                continue
            if mem.learn(ml["text"], cands[0], source, "answer" if source == "human" else "page", page=page, staves=ml["staves"], job_id=job.id):
                learned.append(f"{ml['text']!r} is {cands[0]}")
        if learned:
            sc["log"].append(f"Page {page} system {system}: remembered " + "; ".join(learned) + (" (the admin's answer)" if source == "human" else ""))
            remember()
        return learned

    def load_page(n: int):
        """Geometry of a page, with the header's staff count driving the staff recovery once the header is read
        (page 1 is read once before the header exists, for the overlay the header call sees, and again after)."""
        if n not in cache:
            png = ctx.storage_download(paths[n - 1])
            cache[n] = page_geometry(png, expected_staves=(sc["header"] or {}).get("expected_staves"))
        return cache[n]

    def header_entry(instrument: str) -> dict | None:
        return hdr.match_instrument((sc["header"] or {}).get("instruments") or [], instrument)

    def header_staves(instrument: str) -> int:
        inst = header_entry(instrument)
        if inst is not None:
            return max(1, int(inst.get("staves") or 1))
        return 2 if hdr.family(instrument) in ("piano", "harp", "organ") else 1

    def voice_flags(page: int, sysd: dict, block: list[int]) -> tuple[bool, bool]:
        """(the block is vocal, the staff above it is vocal), for the lyric rule of the clean pass: the block's
        instruments through the header's family (else the name); the staff above by score order when the system is
        full, else the header entry printed above the block's first instrument (the local order of a choir block),
        or the last entry of the header when the block opens a system under a full one."""
        insts = block_instruments(page, sysd["index"], block)
        voice = any(hdr.is_voice(header_entry(i), i) for i in insts)
        idxs = sysd["staff_indices"]
        pos = idxs.index(min(block))
        above: dict | None = None
        if pos > 0:
            above = hdr.at_position(sc["header"], sysd, idxs[pos - 1])
            if above is None:
                first = min((i for i in insts if header_entry(i) is not None), key=lambda i: header_entry(i).get("position", 0), default=None)
                above = hdr.previous_entry(sc["header"], first) if first else None
        else:
            geom = load_page(page)[0]
            prev_sys = next((s for s in geom["systems"] if s["index"] == sysd["index"] - 1), None)
            if prev_sys:
                above = hdr.at_position(sc["header"], prev_sys, prev_sys["staff_indices"][-1])
        return voice, hdr.is_voice(above) if above else False

    def recheck_claim(page: int, system: int, block: list[int]) -> tuple[dict[str, Any], list[str], bool]:
        """What the header and the page labels say the block is, for the closed recheck: the prompt fields, the
        expected clefs (the header's, per staff, when it read them) and whether the block is vocal."""
        insts = block_instruments(page, system, block)
        entries = [header_entry(i) for i in insts]
        clefs = [clef_name(c) for e in entries if e for c in (e.get("clefs") or []) if clef_name(c) not in (None, "c")]
        voice = any(hdr.is_voice(e, i) for e, i in zip(entries, insts))
        if voice and not clefs:
            clefs = [c for i in insts for c in [chorus_clef(i)] if c]
        n = sum(header_staves(i) for i in insts)
        names = " and ".join(f"the {(e.get('label') or e.get('name')) if e else i}" + (f" ({i})" if e and not same_instrument(e.get("label") or e.get("name") or "", i) else "")
                             for e, i in zip(entries, insts))
        clef_phrase = ""
        if clefs:
            clef_phrase = f" in the {' and '.join(dict.fromkeys(clefs))} clef{'s' if len(set(clefs)) != 1 else ''}"
        claim = (f"According to the score header and the page's staff labels this block is {names}: {n} staff{'s' if n != 1 else ''}{clef_phrase}"
                 + (" (the header did not read the clef)" if not clefs else "") + ".")
        voice_hint = ""
        if voice:
            voice_hint = (" These are voice staves of the chorus: the words under the notes are their lyrics. Older editions print the"
                          " choir in C clefs (a soprano staff in the soprano clef, C on the bottom line; alto in the alto clef, middle line;"
                          " tenor in the tenor clef, fourth line from the bottom): the part's own C clef, or the treble clef, counts as matching.")
        fields = {"claim": claim, "n": n, "plural": "s" if n != 1 else "", "clef_phrase": clef_phrase, "voice_hint": voice_hint}
        return fields, clefs, voice

    def chorus_clef(instrument: str) -> str | None:
        """The voice's clef when the header lists the choir as one entry ("CORO.", 4 staves, clefs soprano, alto,
        tenor, bass: Beethoven 9 live header): the clef named after the voice when the entry has it, else by the
        S A T B order of a four-staff entry."""
        fam = hdr.family(instrument)
        if fam not in hdr.VOICES or header_entry(instrument) is not None:
            return None
        for e in (sc["header"] or {}).get("instruments") or []:
            if not hdr.is_voice(e) or int(e.get("staves") or 1) < 2:
                continue
            names = [clef_name(c) for c in (e.get("clefs") or [])]
            if fam in names:
                return fam
            order = {"soprano": 0, "alto": 1, "tenor": 2, "bass": 3}
            if len(names) == 4 and fam in order and names[order[fam]] not in (None, "c"):
                return names[order[fam]]
        return None

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
        crops, boxes, verifies, voices = [], [], [], []
        for block in blocks:
            voice, voice_above = voice_flags(page, sysd, block)
            voices.append({"voice": voice, "voice_above": voice_above})
            crop, box, checks = cut_system(bw, im, geom, sysd, block, voice=voice, voice_above=voice_above)
            if voice or voice_above:
                voices[-1]["lyric_lines"] = [(l["class"], l["words"]) for l in (checks.get("clean") or {}).get("lyric_lines", [])]
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
        rechecks: list[dict] = []
        if recheck:
            for block, crop in zip(blocks, crops):
                known = settled(page, system, block)
                if known and (known["source"] == "human" or known["agreed"]):
                    # The admin already said what this label is, or the book's memory knows the printed label and the
                    # page's proposal put the instrument on exactly these staves: the recheck would only second-guess
                    # the same label (speed pass 2026-10-30: its true catches were all on unlabelled systems, which the
                    # memory never settles; benchmark 3.12).
                    rechecks.append({"block": block, "verdict": "remembered", "source": known["source"], "labels": known["labels"], "pages": known["pages"]})
                    continue
                fields, expected_clefs, voice = recheck_claim(page, system, block)
                prompt = RECHECK_PROMPT.format(**fields)
                said = await ask_model(ctx, c, m, prompt, to_png(crop), max_tokens=RECHECK_MAX_TOKENS, effort=RECHECK_EFFORT)
                sc["cost_usd"] = sc.get("cost_usd", 0.0) + said.pop("_cost_usd", 0.0)
                matches = said.get("matches")
                if isinstance(matches, str):
                    matches = matches.strip().lower() in ("true", "yes", "y")
                seen = said.get("clefs_seen") if isinstance(said.get("clefs_seen"), list) else ([said["clefs_seen"]] if said.get("clefs_seen") else [])
                fit = clefs_fit(seen, expected_clefs, voice)
                verdict = "yes" if matches and fit else ("clef" if matches else "no")
                label_seen = str(said.get("label_seen") or "").strip()
                if verdict != "yes" and known:
                    # Two reads agree on the printed label (the page's margin labels put it on exactly this block, and the
                    # crop alone shows it) and the book's memory says what it is: the label wins over the crop's doubts
                    # (neighbour ink at the edge, a staff count misread; PC3 p. 2 and 3, 2026-10-30).
                    e = mem.resolve(label_seen) if label_seen else None
                    if e is not None and any(same_part(e["part"], i) for i in known["instruments"]):
                        verdict = "label"
                rechecks.append({"block": block, "verdict": verdict, "matches": bool(matches), "staves_seen": said.get("staves_seen"),
                                 "clefs_seen": seen, "label_seen": said.get("label_seen"), "why": said.get("why")})
                if verdict in ("no", "clef") and label_seen:
                    sc["seen_labels"].setdefault(key, []).append({"block": block, "label": label_seen})
                if verdict == "no":
                    raise Refusal(f"re-reading the block of staves {block} alone against the header ({fields['claim']}), the model says it does not "
                                  f"match ({said.get('why', '')}; label seen {said.get('label_seen') or 'none'!r}, clefs seen {seen})")
                if verdict == "clef":
                    raise Refusal(f"re-reading the block of staves {block} alone, the model sees the {', '.join(str(x) for x in seen)} clef where the header "
                                  f"expects {' and '.join(expected_clefs)} ({said.get('why', '')})")
        sp = float(sum(s["spacing"] for s in geom["staves"] if s["index"] in staves) / len(staves))
        png = to_png(stack_crops(crops, int(round(STACK_GAP_SPACES * sp))))
        storage_key = f"{score_id}/parts/{part_slug}/p{page:03}-s{system}.png"
        ctx.storage_upload(storage_key, png, "image/png")
        sc["commits"][key] = {"staves": staves, "blocks": blocks, "key": storage_key, "boxes": boxes, "verify": verifies, "bars": sysd["n_measures"],
                              "modes": [v["mode"] for v in verifies], "voices": voices, "rechecks": rechecks}
        how = f"{len(blocks)} blocks stacked" if len(blocks) > 1 else "one block"
        by_memory = [r for r in rechecks if r["verdict"] in ("remembered", "label")]
        sc["log"].append(f"Page {page} system {system}: staves {staves} cut ({how}), {sysd['n_measures']} bars"
                         + (f"; settled by the book's labels ({', '.join(r['verdict'] for r in by_memory)})" if by_memory else ""))
        learned = learn_from(page, system, staves, "human" if not recheck else "model") if (not recheck or all(r["verdict"] == "yes" for r in rechecks)) else []
        out = {"committed": key, "staves": staves, "blocks": blocks, "storage_key": storage_key, "bars": sysd["n_measures"]}
        if by_memory:
            out["settled_by"] = [{"block": r["block"], "verdict": r["verdict"]} for r in by_memory]
        if learned:
            out["remembered"] = learned
        return out

    box = ToolBox()

    def book_header() -> dict | None:
        """The header the book's first reading took (`process_pages`, 004: read once per book) when it has the staff
        count; None when the book was never read that way (the cut then reads page 1 itself)."""
        try:
            cur = (ctx.db.table("scores").select("current_interpretation_id").eq("id", score_id).single().execute().data or {}).get("current_interpretation_id")
            row = (ctx.db.table("interpretations").select("params").eq("id", cur).single().execute().data or {}) if cur else {}
        except Exception:  # noqa: BLE001
            return None
        h = (((row or {}).get("params") or {}).get("state") or {}).get("header") or {}
        if not h.get("instruments") or not h.get("expected_staves"):
            return None
        return {k: v for k, v in h.items() if k not in ("overlay_png", "cost_usd")}

    def book_parts() -> list[str]:
        try:
            rows = ctx.db.table("parts").select("name").eq("score_id", score_id).execute().data or []
        except Exception:  # noqa: BLE001
            return []
        return [r["name"] for r in rows if r.get("name") and " + " not in r["name"]]

    @box.tool("read_header", "Read the score header on page 1: instruments in order, staves each, clefs, key, time. Call once, first.", {"properties": {}})
    async def read_header(args, st):
        if sc["header"] is None and (book := book_header()) is not None:
            sc["header"] = {**book, "from_book": True}
            sc["log"].append(f"Header from the book's first reading (page {book.get('page') or 1}): "
                             f"{', '.join(f'{i['name']} ({i['staves']})' for i in book['instruments'])}; {book['expected_staves']} staves")
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
            cache.pop(1, None)   # page 1 is read again with the header's count driving the staff recovery
            h = sc["header"]
            sc["log"].append(f"Header: {', '.join(f'{i['name']} ({i['staves']})' for i in h['instruments'])}; {h['expected_staves']} staves"
                             + ("" if h["validation"]["match"] else f", geometry found {h['validation']['geometry_staves_system1']} in system 1")
                             + (f"; {len(retries)} retry: {retries}" if retries else ""))
        h = sc["header"]
        if mem.seed_from_header(h, book_parts()):
            remember()
        start_prereads()
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

    async def fetch_labels(n: int) -> dict | None:
        """The page's label call (geometry, overlay, prompt, Spark; the fallback to low when the guard doubts a minimal
        read). None for a page with no staves. Pre-read in two waves once the header is known (`start_prereads`)."""
        if str(n) in sc["prereads"]:
            return sc["prereads"][str(n)]
        geom, bw, im = load_page(n)
        if not geom["staves"]:
            return None
        ov = overlay_png(im, geom)
        ov_key = f"{score_id}/parts/{part_slug}/overlay-p{n:03}.png"
        ctx.storage_upload(ov_key, ov, "image/png")
        desc = "; ".join(f"system {s['index']} = staves {s['staff_indices'][0]}..{s['staff_indices'][-1]} ({s['n_measures']} bars)" for s in geom["systems"])
        if len(instruments) == 1:
            prompt = LABEL_PROMPT.format(page=n, first=1, last=len(geom["staves"]), systems_desc=desc, instrument=instruments[0],
                                         staves=header_staves(instruments[0]), header_context=header_context(geom) + mem.context(instruments))
        else:
            wanted_desc = ", ".join(f'"{i}" ({header_staves(i)} staves per system according to the header)' for i in instruments)
            example = ", ".join(json.dumps({"instrument": i, "staves": [], "status": "playing"}) for i in instruments)
            prompt = LABEL_PROMPT_MULTI.format(page=n, first=1, last=len(geom["staves"]), systems_desc=desc, wanted_desc=wanted_desc,
                                               example=example, header_context=header_context(geom) + mem.context(instruments))
        async def ask(effort: str) -> dict:
            try:
                got = await ask_model(ctx, c, m, prompt, ov, max_tokens=8000, require="systems", effort=effort)
            except NoJSON as e:   # no labels: the header's score order still proposes the full systems
                got = {"systems": [], "confidence": "low", "notes": f"label call failed ({e}); proposal by score order only", "_cost_usd": e.cost_usd}
            sc["cost_usd"] = sc.get("cost_usd", 0.0) + got.pop("_cost_usd", 0.0)
            return got

        lab = await ask(LABEL_EFFORT)
        lab["_effort"] = LABEL_EFFORT
        if LABEL_EFFORT != FALLBACK_EFFORT and (why := label_guard(lab, instruments, sc["header"])):
            sc["label_fallbacks"].append({"page": n, "why": why})
            sc["log"].append(f"Page {n}: the labels read at {LABEL_EFFORT} are doubted ({'; '.join(why)}); read again at {FALLBACK_EFFORT}")
            lab = await ask(FALLBACK_EFFORT)
            lab["_effort"], lab["_fallback"] = FALLBACK_EFFORT, why
        lab["_overlay_key"] = ov_key
        sc["prereads"][str(n)] = lab
        return lab

    prereads: dict[int, asyncio.Task] = {}

    def start_prereads() -> None:
        """Every page's label call ahead of the agent, in two waves as page reading does (004): the first page alone,
        then the rest, PREREAD_CONCURRENCY at once. The agent's read_page takes the answer when it is back; the memory
        is applied then, with what the earlier commits taught it."""
        todo = [n for n in pages if str(n) not in sc["pages"] and str(n) not in sc["prereads"] and n not in prereads]
        if not todo or not PREREAD_PAGES:
            return
        first = asyncio.ensure_future(fetch_labels(todo[0]))
        prereads[todo[0]] = first
        gate = asyncio.Semaphore(PREREAD_CONCURRENCY)

        async def later(n: int) -> dict | None:
            try:
                await asyncio.shield(first)
            except Exception:  # noqa: BLE001  (the first page's failure is read_page's to report)
                pass
            async with gate:
                return await fetch_labels(n)
        for n in todo[1:]:
            prereads[n] = asyncio.ensure_future(later(n))

    @box.tool("read_page", "Geometry of one page (staves, systems, barlines) and the model's proposal of which staves are the wanted instruments', from the numbered overlay.", {"properties": {"page": {"type": "integer"}}, "required": ["page"]})
    async def read_page(args, st):
        n = int(args["page"])
        if n not in pages:
            return {"error": f"page {n} is not in this job; pages: {pages}"}
        if str(n) in sc["pages"]:
            return sc["pages"][str(n)]["summary"]
        lab = await (prereads.pop(n) if n in prereads else fetch_labels(n))
        geom, bw, im = load_page(n)
        if lab is None:
            sc["pages"][str(n)] = {"geometry": geom, "proposal": [], "summary": {"page": n, "staves": 0, "systems": [], "note": "no staves found; commit every system as absent or skip"}}
            return sc["pages"][str(n)]["summary"]
        lab = dict(lab)
        ov_key = lab.pop("_overlay_key", None)
        lab.pop("_effort", None)
        lab.pop("_fallback", None)
        lab.pop("_api", None)
        label_retries = lab.pop("_retries", [])
        lab.pop("_repaired", None)
        proposal = [proposal_entry(s, i) for i, s in enumerate(lab.get("systems") or []) if isinstance(s, dict)]
        for q, s in zip(proposal, [s for s in lab.get("systems") or [] if isinstance(s, dict)]):
            sysd = next((g for g in geom["systems"] if g["index"] == q["system"]), None)
            if (ml := margin_labels(s.get("margin_labels"), sysd)):
                q["margin_labels"] = ml
            if sysd is not None and ml:
                apply_memory(n, q, sysd)
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
        if isinstance(given, str) and given.strip().startswith("["):
            # Claude sometimes serialises an array argument as its JSON text ("[8, 9]") when the schema allows a string.
            try:
                given = json.loads(given)
            except ValueError:
                raise Refusal('staves must be a non-empty list of staff numbers or "absent"')
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
        answer_text = (f"The admin decided page {q['page']} system {q['system']}: {json.dumps(chosen)}. It is committed ({json.dumps(out)}). "
                       + (f"Remembered for the later pages: {'; '.join(out['remembered'])}. " if out.get("remembered") else "")
                       + "Continue with the next uncommitted system or finish.")

    def persist(d: dict[str, Any]) -> None:
        ctx.result["agent"] = d
        ctx.db.table("jobs").update({"result": ctx.result}).eq("id", job.id).execute()

    if sc["header"] is not None:        # a resumed run: the pages not read yet are read ahead again
        start_prereads()
    st = await run_agent(system=SYSTEM, tools=box, state=state, answer=answer_text, client=c, model=m, persist=persist, charge=ctx.charge,
                         user_text=None if resumed else f'Cut the part "{label}" (instruments: {json.dumps(instruments)}) from pages {pages}. Start with read_header.',
                         max_turns=8 + 6 * len(pages), max_cost_usd=float(p.get("max_cost_usd", 2.0)), max_refusals=3)
    for t in prereads.values():         # pages the agent never read (a park, a pause): their calls stop here
        t.cancel()
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
                   "answer_format": '{"staves": [11, 12]} or {"blocks": [[11], [13]]} or {"staves": "absent"}',
                   "known_labels": [{k: e.get(k) for k in ("label", "part", "source", "origin", "page")} for e in mem.entries.values()
                                    if any(same_part(e["part"], i) for i in instruments)],
                   "margin_labels": (prop or {}).get("margin_labels") or []}
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
               "turns": st.turn, "status": st.status, "models": {"geometry": "opencv", "labels": "spark"},
               "settled_by_memory": sum(1 for v in commits if any(r.get("verdict") in ("remembered", "label") for r in v.get("rechecks") or [])),
               "log": (sc["log"] + st.log)[-40:]}
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
