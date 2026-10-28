# /// script
# requires-python = ">=3.12"
# dependencies = ["anthropic>=2.3.0"]
# ///
"""Piano-cut experiment, step 2: Muse Spark names the staves that geometry found.

One call per page. Spark sees the page with every staff boxed and numbered (overlay-p<NN>.png from
piano_cut_geometry.py) and is asked which staff numbers belong to the requested instrument, what the other
staves are, and whether the instrument is playing, resting or absent on the page. It never moves a box.

Calls Meta the way app/llm.py does with LLM_PROVIDER=meta (Anthropic SDK pointed at Meta's /v1/messages,
output_config.effort, max_tokens >= 1024); the client code is mirrored here because app.spend imports FastAPI.
Keeps a running spend tally in out/piano-cut/spend.json and refuses to call once the cap is reached.

Usage (from api/):  uv run experiments/grounding/piano_cut_label.py [--score <pdf stem>] [--instrument "Piano (solo)"] [page ...]
Writes label-p<NN>.json into the run folder (common.PIANO_CUT_RUN: the score folder for "Piano (solo)", else
out/piano-cut/<stem>/<instrument-slug>/). The instrument is any name; header.json (score_header.py) tells the
prompt how many staves it has, its clefs and its place in the score order.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import PIANO_CUT_INSTRUMENT, PIANO_CUT_OUT, PIANO_CUT_RUN, PIANO_CUT_TITLE, PRICE, load_env  # noqa: E402

MODEL = "muse-spark-1.3"


def _client():
    """Same construction as app/llm.py `_client()` for LLM_PROVIDER=meta: the Anthropic SDK pointed at Meta's
    base URL without its /v1 (the SDK appends /v1/messages). app.llm itself is not imported because app.spend
    pulls in FastAPI."""
    from anthropic import AsyncAnthropic

    load_env()
    base = os.environ.get("META_API_BASE_URL", "https://api.meta.ai/v1").rstrip("/")
    base = base[:-3] if base.endswith("/v1") else base
    return AsyncAnthropic(api_key=os.environ["META_API_KEY"], base_url=base, max_retries=1)


async def complete(user_text: str, *, system: str, effort: str, max_tokens: int, image_png_b64: str) -> tuple[str, dict]:
    """Mirror of app/llm.py `complete()`: output_config.effort, max_tokens >= 1024 for Spark's reasoning."""
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_png_b64}},
        {"type": "text", "text": user_text},
    ]
    res = await _client().messages.create(
        model=MODEL, max_tokens=max(max_tokens, 1024), system=system,
        messages=[{"role": "user", "content": content}], output_config={"effort": effort},
    )
    text = "".join(b.text for b in res.content if b.type == "text")
    u = res.usage
    stop = getattr(res, "stop_reason", None)
    price = PRICE[MODEL]
    cost = u.input_tokens / 1e6 * price["input_per_m"] + u.output_tokens / 1e6 * price["output_per_m"]
    return text, {"model": res.model or MODEL, "input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
                  "cost_usd": round(cost, 5), "stop_reason": stop}


async def complete_json(user_text: str, *, system: str, effort: str, max_tokens: int, image_png_b64: str,
                        retries: int = 1) -> tuple[str, dict, dict | None, str | None, list[dict]]:
    """complete() plus parse, with one retry when the answer was cut off (stop_reason max_tokens) or does not
    parse. Every attempt is charged; the retry log (reason, tokens, cost) comes back and is written out."""
    log: list[dict] = []
    text, charge, parsed, err = "", {}, None, None
    for attempt in range(retries + 1):
        text, charge = await complete(user_text, system=system, effort=effort, max_tokens=max_tokens, image_png_b64=image_png_b64)
        parsed, err, repaired = parse(text)
        truncated = charge.get("stop_reason") == "max_tokens"
        charge["json_repaired"] = repaired
        if parsed is not None and not truncated:
            break
        reason = "truncated (stop_reason max_tokens)" if truncated else f"unparseable: {err}"
        log.append({"attempt": attempt + 1, "reason": reason, "output_tokens": charge.get("output_tokens"),
                    "cost_usd": charge.get("cost_usd"), "tail": text[-120:]})
        print(json.dumps({"retry": attempt + 1, "reason": reason, "output_tokens": charge.get("output_tokens")}), file=sys.stderr)
        if attempt < retries:
            spend_add({"kind": "retry-wasted", "cost_usd": charge["cost_usd"], "model": MODEL, "reason": reason})
    return text, charge, parsed, err, log


def model_name() -> str:
    return MODEL


PC = PIANO_CUT_OUT  # score folder: pages, geometry, overlays, header, spend
RUN = PIANO_CUT_RUN  # run folder: labels, crops, rechecks, results, html, strip
SPEND = PC / "spend.json"
CAP_USD = 1.50  # per score folder
GLOBAL_SPEND = PC.parent / "spend-global.json" if PC.name != "piano-cut" else PC / "spend-global.json"
GLOBAL_CAP_USD = 4.00  # tonight's cap across every score (started 2026-10-27 at 0)
DEFAULT_PAGES = [1, 2, 7, 15, 16, 43]

SYSTEM = "You are an orchestral librarian reading a scanned page of a full score. Answer with strict JSON only, no prose."

PROMPT = """This is page {page} of a scanned orchestral full score ({title}). A geometry detector has drawn a blue box around every staff and put a yellow tag with the staff number at the left end of each box; staves are numbered {first}..{last} from top to bottom. Grey boxes mark systems; this page has {n_systems} system(s): {systems_desc}.

Instrument wanted: "{instrument}".
{header_context}
Read the margin labels (full names on a first page, abbreviations such as "Pno.", "Fl.", "Cor.", "Vl. I" on later pages; some pages carry no labels at all, then use the clefs, the braces and brackets, the position in the score order and the music itself). {instrument_desc} When the wanted player shares one staff with another player (e.g. "Flauti I. II." written on one staff, or "Violoncello e Basso"), that shared staff is the answer; a player written on its own staff ("Violino I") never shares.

Answer, for each system:
- the staff numbers that belong to "{instrument}" (an empty list if its staves are not printed in that system),
- a short instrument name for every staff number in that system, top to bottom,
- whether the wanted instrument in that system is "playing", "resting" (its staves are printed but hold only rests) or "absent" (its staves are not printed at all).

Return only JSON of this shape:
{{"instrument": "{instrument}",
 "systems": [{{"index": 1, "wanted_staves": [11, 12], "status": "playing|resting|absent",
               "staves": [{{"n": 1, "instrument": "Flauti I.II"}}]}}],
 "page_status": "playing|resting|absent",
 "other_instruments": ["..."],
 "confidence": "high|medium|low",
 "notes": "one sentence if anything is odd"}}"""


def extract_json(text: str) -> tuple[dict, bool]:
    """Parse Spark's JSON. Returns (obj, repaired). Spark 1.3 occasionally drops a stray token right after a
    closing bracket (`}-math]` on page 1, `]} apron,` on pages 16 and 43); the repair strips one stray word
    after a bracket and retries.
    The repair is logged, never hidden."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    body = text[start : end + 1]
    try:
        return json.loads(body), False
    except json.JSONDecodeError:
        pass
    stray = r"(?<=[\]\}])\s*-?[A-Za-z_]+(?:=\d+)?(?=\s*[,\]\}])"  # `}-math]`, `]} apron,`, `]} responsibility=0,`
    # the stray word sometimes stands where a closing bracket should have been (`]} apron,` for `]],`)
    for repl in ("", "]", "}"):
        try:
            return json.loads(re.sub(stray, repl, body, count=1)), True
        except json.JSONDecodeError:
            continue
    return json.loads(body), False  # raise the original error


def spend_total() -> float:
    if SPEND.exists():
        return float(json.loads(SPEND.read_text()).get("total_usd", 0.0))
    return 0.0


def spend_add(entry: dict) -> float:
    for path in (SPEND, GLOBAL_SPEND):
        data = json.loads(path.read_text()) if path.exists() else {"total_usd": 0.0, "calls": []}
        data["calls"].append({**entry, "score": PC.name} if path is GLOBAL_SPEND else entry)
        data["total_usd"] = round(sum(c["cost_usd"] for c in data["calls"]), 5)
        path.write_text(json.dumps(data, indent=2))
    return json.loads(SPEND.read_text())["total_usd"]


def global_total() -> float:
    return float(json.loads(GLOBAL_SPEND.read_text()).get("total_usd", 0.0)) if GLOBAL_SPEND.exists() else 0.0


def spend_check(what: str) -> None:
    if spend_total() >= CAP_USD:
        raise SystemExit(f"folder spend cap reached ({spend_total():.3f} >= {CAP_USD}); not calling for {what}")
    if global_total() >= GLOBAL_CAP_USD:
        raise SystemExit(f"global spend cap reached ({global_total():.3f} >= {GLOBAL_CAP_USD}); not calling for {what}")


def parse(text: str) -> tuple[dict | None, str | None, bool]:
    try:
        parsed, repaired = extract_json(text)
        return parsed, None, repaired
    except Exception as e:  # keep the raw text; the build step treats this as a failed label
        return None, repr(e), False


def reparse(n: int) -> None:
    """Re-run only the parser on a saved answer (no model call)."""
    path = RUN / f"label-p{n:02d}.json"
    out = json.loads(path.read_text())
    out["parsed"], out["parse_error"], out["json_repaired"] = parse(out["raw_text"])
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(json.dumps({"page": n, "reparsed": True, "parse_error": out["parse_error"], "json_repaired": out["json_repaired"]}))


# instrument names as editions print them (Italian, German, French, English, abbreviations), lower case, no dots
SYNONYMS = {
    "piano": ["piano", "pianoforte", "klavier", "pfte", "pno", "p-no", "cembalo", "clavier"],
    "violin": ["violin", "violino", "violini", "violine", "violinen", "violon", "violons", "vl", "vn", "viol"],
    "viola": ["viola", "viole", "bratsche", "bratschen", "alto", "altos", "va", "vla"],
    "cello": ["cello", "celli", "violoncello", "violoncelli", "violoncelle", "vc", "vcl", "vcll"],
    "bass": ["contrabass", "contrabasso", "contrabassi", "kontrabass", "kontrabaß", "contrebasse", "basso", "bassi", "cb", "kb", "k-b"],
    "flute": ["flute", "flutes", "flauto", "flauti", "flöte", "flöten", "floete", "fl"],
    "piccolo": ["piccolo", "flauto piccolo", "kleine flöte", "picc"],
    "oboe": ["oboe", "oboi", "oboen", "hautbois", "ob"],
    "english horn": ["english horn", "corno inglese", "englisch horn", "englisches horn", "cor anglais", "c ingl"],
    "clarinet": ["clarinet", "clarinets", "clarinetto", "clarinetti", "klarinette", "klarinetten", "clarinette", "cl", "klar"],
    "bassoon": ["bassoon", "bassoons", "fagotto", "fagotti", "fagott", "fagotte", "basson", "fag", "fg", "bsn"],
    "horn": ["horn", "horns", "corno", "corni", "hörner", "horner", "cor", "cors", "hr"],
    "trumpet": ["trumpet", "trumpets", "tromba", "trombe", "trompete", "trompeten", "trompette", "tr", "trb", "tromp", "trbe"],
    "trombone": ["trombone", "trombones", "tromboni", "posaune", "posaunen", "trbni", "trbne", "pos"],
    "tuba": ["tuba", "basstuba", "tb"],
    "timpani": ["timpani", "pauken", "timbales", "timp", "pk", "pauk"],
    "harp": ["harp", "arpa", "harfe", "harpe"],
    "soprano": ["soprano", "soprani", "sopran", "sopr", "canto", "discant"],
    "alto": ["alto", "alti", "alt", "contralto"],
    "tenor": ["tenor", "tenore", "tenori", "ten"],
    "bass": ["bass", "basso", "bassi", "bässe"],
    "chorus": ["chorus", "coro", "chor", "choir"],
}
VOICES = {"soprano", "alto", "tenor", "bass", "chorus", "mezzo", "baritone", "voice"}
ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "1": 1, "2": 2, "3": 3, "4": 4, "1st": 1, "2nd": 2}


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9äöüß-]+", (text or "").lower()) if t]


def match_instrument(instruments: list[dict], wanted: str) -> dict | None:
    """The header entry for the wanted instrument ("Violin I", "Flute I", "Piano (solo)"): the family word is
    matched through the synonym table against the label and abbreviations (as a whole word, so "Fl." matches
    "flute" but not "Flautino"), and a numeral in the wanted name must appear in the label ("Violino I." has
    it, "Violini II." does not, "Flauti I. II." has both: a shared staff). Without a numeral the first entry
    of that family wins."""
    wtok = _tokens(wanted.split(" (")[0])
    numerals = [ROMAN[t] for t in wtok if t in ROMAN]
    words = [t for t in wtok if t not in ROMAN and t not in ("solo",)]
    if not words:
        return None
    family = " ".join(words)
    names = set(SYNONYMS.get(family, [])) | {family}
    for key, syns in SYNONYMS.items():
        if family in syns:
            names |= set(syns) | {key}
    voice = family in VOICES
    best: tuple[int, int, dict] | None = None
    for k, inst in enumerate(instruments):
        label_toks = _tokens(inst.get("label") or "")
        abbr_toks = [t for a in (inst.get("abbreviations") or []) for t in _tokens(a)]
        label_text = " ".join(label_toks)
        hit = any(n in label_toks or n in abbr_toks or (" " in n and n in label_text) for n in names)
        if not hit and family == "piano" and inst.get("family") == "keyboard":
            hit = True
        if not hit:
            continue
        label_nums = [ROMAN[t] for t in label_toks + abbr_toks if t in ROMAN]
        if numerals and label_nums and not all(n in label_nums for n in numerals):
            continue
        # "Alto" must find the choir's alto ("CORO Alto", family voice), not "Tromboni Alto e Tenore" or the
        # Viola: a voice name prefers a voice-family entry, then the entry whose label starts with the name
        inst_family = (inst.get("family") or "").lower()
        score = (2 if voice and inst_family in ("voice", "vocal", "choir", "chorus") else 0) + \
                (1 if label_toks and label_toks[0] in names else 0) + (-2 if voice and inst_family in ("brass", "strings", "woodwind") and not any(x in label_toks for x in ("coro", "chor", "chorus", "choir")) else 0)
        if best is None or score > best[0]:
            best = (score, k, inst)
    return best[2] if best else None


def header_instruments() -> list[dict]:
    path = PC / "header.json"
    if not path.exists():
        return []
    return json.loads(path.read_text()).get("instruments") or []


def instrument_desc(instrument: str) -> str:
    """One sentence for the prompts about the wanted instrument, from the header when it knows it."""
    inst = match_instrument(header_instruments(), instrument)
    if inst is None:
        return (f'The header of this edition does not list "{instrument}"; if it is not on the page, answer "absent" for every system. '
                f"If it is there, it is a single staff unless it is a keyboard or harp part (two staves joined by a curly brace).")
    ns = int(inst.get("staves") or 1)
    clefs = ", ".join(inst.get("clefs") or [])
    return (f'In this edition "{instrument}" is printed as "{inst.get("label")}" (abbreviated {", ".join(inst.get("abbreviations") or []) or "variously"}), '
            f"{ns} staff{'s' if ns != 1 else ''}" + (f" ({clefs} clef{'s' if ns != 1 else ''})" if clefs else "")
            + (", joined by a curly brace" if ns == 2 and inst.get("family") == "keyboard" else "")
            + f", family {inst.get('family')}.")


def instrument_staves(instrument: str) -> int | None:
    inst = match_instrument(header_instruments(), instrument)
    return int(inst.get("staves") or 1) if inst else None


def header_context(geom: dict, instrument: str) -> str:
    """Score order from header.json (score_header.py) as prompt context, plus the by-order guess per system:
    when a system has exactly the header's staff count, staff k is the k-th staff of the list; when it has fewer,
    some instruments are not printed (cut-away) or a staff was missed, and Spark decides from labels and clefs."""
    inst = header_instruments()
    if not inst:
        return ""
    order, k = [], 1
    for i in inst:
        ns = int(i.get("staves") or 1)
        order.append(f"{k}" + (f"..{k + ns - 1}" if ns > 1 else "") + f" {i.get('label')} ({', '.join(i.get('abbreviations') or [])})")
        k += ns
    total = k - 1
    lines = [f"Score header (read from the first page): {total} staves per full system, in this order (position: instrument): "
             + "; ".join(order) + "."]
    cand = match_instrument(inst, instrument)
    pos = None
    if cand:
        k = 1
        for i in inst:
            ns = int(i.get("staves") or 1)
            if i is cand:
                pos = list(range(k, k + ns))
                break
            k += ns
    for sysd in geom["systems"]:
        idxs = sysd["staff_indices"]
        if pos and len(idxs) == total:
            guess = [idxs[p - 1] for p in pos]
            lines.append(f"System {sysd['index']} has {len(idxs)} staves, the full set, so by order the wanted instrument is staff "
                         f"{guess}: confirm from the labels/clefs/brace, or correct it.")
        elif pos:
            lines.append(f"System {sysd['index']} has {len(idxs)} staves, not the full {total}: either resting instruments are "
                         f"not printed (then say which are absent) or the detector missed a staff (then say so in notes); "
                         f"identify the wanted instrument from the labels, clefs, brace and position, and answer \"absent\" if its staves are not printed.")
    return "\n".join(lines) + "\n"


async def run_page(n: int, instrument: str, effort: str) -> dict:
    spend_check(f"page {n}")
    geom = json.loads((PC / f"geom-p{n:02d}.json").read_text())
    png = (PC / f"overlay-p{n:02d}.png").read_bytes()
    systems_desc = "; ".join(
        f"system {s['index']} = staves {s['staff_indices'][0]}..{s['staff_indices'][-1]}" for s in geom["systems"])
    prompt = PROMPT.format(title=PIANO_CUT_TITLE, page=n, first=geom["staves"][0]["index"], last=geom["staves"][-1]["index"],
                           n_systems=len(geom["systems"]), systems_desc=systems_desc, instrument=instrument,
                           header_context=header_context(geom, instrument), instrument_desc=instrument_desc(instrument))
    t0 = time.perf_counter()
    text, charge, parsed, parse_error, retries = await complete_json(
        prompt, system=SYSTEM, effort=effort, max_tokens=8000, image_png_b64=base64.b64encode(png).decode())
    dt = time.perf_counter() - t0
    cost = charge["cost_usd"]
    repaired = charge.get("json_repaired", False)
    out = {"page": n, "instrument": instrument, "model": model_name(), "effort": effort,
           "latency_s": round(dt, 1), "cost_usd": round(cost, 5), "charge": charge, "retries": retries,
           "prompt": prompt, "raw_text": text, "parsed": parsed, "parse_error": parse_error, "json_repaired": repaired}
    RUN.mkdir(parents=True, exist_ok=True)
    (RUN / f"label-p{n:02d}.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    total = spend_add({"page": n, "cost_usd": round(cost, 5), "latency_s": round(dt, 1), "model": model_name(),
                       "retries": len(retries)})
    summary = {"page": n, "latency_s": round(dt, 1), "cost_usd": round(cost, 4), "running_total_usd": total,
               "global_total_usd": global_total(), "retries": len(retries), "parse_error": parse_error, "json_repaired": repaired}
    if parsed:
        summary["page_status"] = parsed.get("page_status")
        summary["wanted"] = [(s.get("index"), s.get("wanted_staves"), s.get("status")) for s in parsed.get("systems", [])]
    print(json.dumps(summary))
    return out


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instrument", default=PIANO_CUT_INSTRUMENT, help="also read by common.py from the command line")
    ap.add_argument("--effort", default="low")
    ap.add_argument("--reparse", action="store_true", help="only re-parse saved answers, no model call")
    ap.add_argument("pages", nargs="*", type=int, default=DEFAULT_PAGES)
    a = ap.parse_args()
    for n in a.pages:
        if a.reparse:
            reparse(n)
        else:
            await run_page(n, a.instrument, a.effort)


if __name__ == "__main__":
    asyncio.run(main())
