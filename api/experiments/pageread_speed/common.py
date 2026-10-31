"""Ledger ($4 cap, every Meta call one line), the books and pages, and the two ways of calling Spark."""
from __future__ import annotations

import base64
import datetime as dt
import json
import time
from decimal import Decimal
from pathlib import Path

import httpx

from app.llm import complete, price
from app.settings import settings

HERE = Path(__file__).resolve().parent
API = HERE.parents[1]
RESULTS = HERE / "results"
LEDGER = HERE / "spend.jsonl"
CAP_USD = 4.0
PER_CALL_CEILING = 0.06
MODEL = "muse-spark-1.3"

FIX = API / "fixtures" / "pdf"
B9_PNG = API / "experiments" / "grounding" / "out" / "piano-cut" / "beethoven-sym9-fullscore-imslp46254" / "pages"
RACH_PDF = Path("/Users/ckjiang/Downloads/stave-extractor/api/fixtures/pdf/rach1-fullscore-gutheil-1919.pdf")

# book -> (kind, title, seeded known parts, [(page id, source, page)]). The 016 corpus (all 10 pages) plus the two Chopin
# pages of today's landmarks eval that are not in it (Chopin p. 14 too: 3 of the 5); Goldberg p2-3 serve both sets.
BOOKS = {
    "goldberg": ("keyboard", "Bach, Goldberg Variations, BGA", [], True,
                 [("goldberg-bga-p01", ("pdf", FIX / "goldberg-bga-p1-5.pdf", 1)),
                  ("goldberg-bga-p02", ("pdf", FIX / "goldberg-bga-p1-5.pdf", 2)),
                  ("goldberg-bga-p03", ("pdf", FIX / "goldberg-bga-p1-5.pdf", 3))]),
    "rach1": ("orchestral", "Rachmaninoff, Piano Concerto No. 1, 1919 Gutheil edition", [], True,
              [("rach1-gutheil-p01", ("pdf", RACH_PDF, 1)), ("rach1-gutheil-p02", ("pdf", RACH_PDF, 2)),
               ("rach1-gutheil-p03", ("pdf", RACH_PDF, 3))]),
    "beethoven9": ("orchestral", "Beethoven, Symphony No. 9, finale (Breitkopf)", [], True,
                   [(f"beethoven9-p{n}", ("png", B9_PNG / f"p{n}.png", n)) for n in (172, 173, 174, 175)]),
    # mid-book pages: no header read (as today's landmarks eval), the book's part seeded as page 1 would have read it
    "chopin": ("keyboard", "Chopin, Polonaises (Ekier)", ["Piano"], False,
               [(f"chopin-p{14 + i}", ("pdf", FIX / "chopin-polonaises-ekier-test-p4-7.pdf", 2 + i)) for i in range(3)]),
}


def spent() -> float:
    if not LEDGER.exists():
        return 0.0
    return sum(json.loads(l)["usd"] for l in LEDGER.read_text().splitlines() if l.strip())


def log(**row) -> None:
    row = {"at": dt.datetime.now().isoformat(timespec="seconds"), **row}
    with LEDGER.open("a") as f:
        f.write(json.dumps(row) + "\n")


def guard() -> None:
    if spent() + PER_CALL_CEILING > CAP_USD:
        raise SystemExit(f"cap: ${spent():.4f} spent of ${CAP_USD}")


async def call_messages(prompt: str, png: bytes, *, effort: str, tag: str, uid: str) -> dict:
    """The app's path: `llm.complete` (Messages, output_config.effort), forced to Meta, 8000 budget, no system prompt."""
    guard()
    t0 = time.monotonic()
    c = await complete(prompt, effort=effort, max_tokens=8000, image_png_b64=base64.b64encode(png).decode(), provider="meta")
    secs = time.monotonic() - t0
    usd = float(c.charge.cost_usd)
    log(tag=tag, uid=uid, api="messages", effort=effort, model=c.charge.model, usd=usd, input_tokens=c.charge.input_tokens,
        output_tokens=c.charge.output_tokens, seconds=round(secs, 2))
    return {"text": c.text, "seconds": secs, "usd": usd, "input_tokens": c.charge.input_tokens, "output_tokens": c.charge.output_tokens,
            "reasoning_tokens": None, "api": "messages"}


async def call_chat(prompt: str, png: bytes, *, effort: str, tag: str, uid: str) -> dict:
    """/v1/chat/completions, not streamed (the app's Messages call is not streamed either): reasoning_effort takes
    "minimal" here, which Messages refuses. Same message (image then text), same 8000 budget, no system prompt.
    Priced at the app's list price (no cache discount), as `llm.price` prices the Messages calls."""
    guard()
    b64 = base64.b64encode(png).decode()
    body = {"model": MODEL, "messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}, {"type": "text", "text": prompt}]}],
        "reasoning_effort": effort, "max_completion_tokens": 8000}
    base = settings.meta_api_base_url.rstrip("/")
    t0 = time.monotonic()
    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post(f"{base}/chat/completions", json=body, headers={"Authorization": f"Bearer {settings.meta_api_key}"})
    secs = time.monotonic() - t0
    if r.status_code != 200:
        log(tag=tag, uid=uid, api="chat", effort=effort, model=MODEL, usd=0.0, error=f"HTTP {r.status_code}", seconds=round(secs, 2))
        raise RuntimeError(f"chat HTTP {r.status_code}: {r.text[:300]!r}")
    d = r.json()
    u = d.get("usage") or {}
    tin, tout = u.get("prompt_tokens", 0), u.get("completion_tokens", 0)
    reasoning = (u.get("completion_tokens_details") or {}).get("reasoning_tokens")
    cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
    usd = float(price(MODEL, tin, tout))
    log(tag=tag, uid=uid, api="chat", effort=effort, model=d.get("model") or MODEL, usd=usd, input_tokens=tin, cached_tokens=cached,
        output_tokens=tout, reasoning_tokens=reasoning, seconds=round(secs, 2))
    text = (d["choices"][0]["message"].get("content") or "") if d.get("choices") else ""
    return {"text": text, "seconds": secs, "usd": usd, "input_tokens": tin, "output_tokens": tout, "reasoning_tokens": reasoning,
            "cached_tokens": cached, "api": "chat", "finish": (d.get("choices") or [{}])[0].get("finish_reason")}
