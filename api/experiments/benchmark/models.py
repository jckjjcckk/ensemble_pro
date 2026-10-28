"""One image + text call to Muse Spark (Meta) or Claude (Anthropic) through the Anthropic SDK, the way
app/llm.py and app/librarian/part_cut.py call them: the same request shape for both providers (system,
one user turn with the image first, output_config.effort), Spark pointed at Meta's base URL without its /v1.
Prices come from app.llm.PRICES. The answer is parsed with app.librarian.header.parse_json (the stray-token
repair); a reply cut off at max_tokens or one that does not parse is asked once more (every attempt charged),
like the product's ask_model. Claude refusals (stop_reason "refusal") are recorded, never retried.
"""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

from app.librarian.header import parse_json
from app.llm import price

SPARK = "muse-spark-1.3"
CLAUDE_MODELS = ("claude-haiku-5-5", "claude-sonnet-5-5")


def provider_of(model: str) -> str:
    return "meta" if model.startswith("muse") else "anthropic"


def load_env() -> None:
    from pathlib import Path

    env = Path(__file__).resolve().parent.parent.parent / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_clients: dict[str, Any] = {}


def client(provider: str):
    from anthropic import AsyncAnthropic

    if provider not in _clients:
        load_env()
        if provider == "meta":
            base = os.environ.get("META_API_BASE_URL", "https://api.meta.ai/v1").rstrip("/")
            base = base[:-3] if base.endswith("/v1") else base
            _clients[provider] = AsyncAnthropic(api_key=os.environ["META_API_KEY"], base_url=base, max_retries=1, timeout=600)
        else:
            _clients[provider] = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=1, timeout=600)
    return _clients[provider]


@dataclass
class Answer:
    parsed: dict | None
    text: str
    cost_usd: float
    latency_s: float
    attempts: list[dict] = field(default_factory=list)
    json_fail_first: bool = False
    refusal: bool = False


async def ask(model: str, system: str, prompt: str, image: bytes, media_type: str, *, effort: str, max_tokens: int,
              retries: int = 1, require: str | None = None, call=None) -> Answer:
    """`call` replaces the SDK call in tests: an async function (kwargs) -> response-like object."""
    provider = provider_of(model)
    if call is None:
        call = client(provider).messages.create
    content = [{"type": "image", "source": {"type": "base64", "media_type": media_type, "data": base64.b64encode(image).decode()}},
               {"type": "text", "text": prompt}]
    total, attempts, parsed, text, first_fail, refusal = 0.0, [], None, "", False, False
    t0 = time.perf_counter()
    for attempt in range(retries + 1):
        res = await call(model=model, max_tokens=max_tokens, system=system, messages=[{"role": "user", "content": content}],
                         output_config={"effort": effort})
        u = res.usage
        cost = float(price(model, u.input_tokens, u.output_tokens))
        total += cost
        text = "".join(getattr(b, "text", "") for b in res.content if getattr(b, "type", "") == "text")
        stop = getattr(res, "stop_reason", None)
        rec = {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens, "cost_usd": round(cost, 6), "stop_reason": stop}
        if stop == "refusal":
            refusal = True
            rec["parse"] = "refusal"
            attempts.append(rec)
            first_fail = first_fail or attempt == 0
            parsed = None
            break
        try:
            parsed, repaired = parse_json(text)
            rec["repaired"] = repaired
            if require and not isinstance(parsed.get(require), list):
                raise ValueError(f"no {require!r} list")
        except (ValueError, json.JSONDecodeError) as e:
            parsed = None
            rec["parse"] = f"unparseable: {str(e)[:120]}"
        if stop == "max_tokens":
            rec["parse"] = "truncated"
            parsed = None
        attempts.append(rec)
        if parsed is not None:
            break
        if attempt == 0:
            first_fail = True
    return Answer(parsed=parsed, text=text, cost_usd=round(total, 6), latency_s=round(time.perf_counter() - t0, 2),
                  attempts=attempts, json_fail_first=first_fail, refusal=refusal)


# ---------------------------------------------------------------- estimates (dry run and the budget guard)

# Output tokens per call at effort low, from the reference runs (005, 008: Spark reasons 2-7k tokens at low)
# and a guess for Claude; medium doubles them. Input: Claude ~ w*h/750 image tokens (capped at 4784), Spark ~1500.
OUT_LOW = {"meta": {"header": 4000, "labels": 2500, "text": 2500, "closed": 800},
           "anthropic": {"header": 1500, "labels": 500, "text": 900, "closed": 150}}
PROMPT_TOKENS = {"header": 700, "labels": 900, "text": 500, "closed": 250}


def estimate_usd(model: str, task: str, effort: str, image_px: tuple[int, int]) -> float:
    provider = provider_of(model)
    w, h = image_px
    if provider == "anthropic":
        s = min(1.0, 2576 / max(w, h))
        img = min(4784, int(w * s * h * s / 750))
    else:
        img = 1500
    out = OUT_LOW[provider][task] * (2.0 if effort == "medium" else 1.0)
    return float(price(model, img + PROMPT_TOKENS[task], int(out)))
