"""Muse Spark 1.3 through the Anthropic SDK, the way api/app/llm.py does it with LLM_PROVIDER=meta (base URL
without /v1, output_config.effort). Rules from feature 005: effort low, output budget at least 8k tokens
(effort low still spends 2 to 7k output tokens reasoning; runs capped at 3 to 4k came back truncated), Spark
reads text and answers closed questions, never notes.

Keeps a spend tally (spend.json in the run directory, thread-safe) and refuses to call past the cap.
Credentials: api/.env next to this checkout, else ~/muse/api/.env (the OMR box).
"""

from __future__ import annotations

import base64
import json
import os
import re
import threading
import time
from pathlib import Path

MODEL = "muse-spark-1.3"
PRICE_IN, PRICE_OUT = 1.25, 4.25  # $ per M tokens, dev.meta.ai pricing 2026-10-27
MIN_OUTPUT = 8000
ENV_FILES = (Path(__file__).resolve().parents[2] / ".env", Path.home() / "muse" / "api" / ".env")

_lock = threading.Lock()
_state = {"spend": Path(os.environ.get("SPARK_SPEND", "spend.json")), "cap": float(os.environ.get("SPARK_CAP_USD", "1.0"))}


def configure(spend_path: Path | str, cap_usd: float) -> None:
    _state["spend"], _state["cap"] = Path(spend_path), float(cap_usd)


def load_env() -> None:
    for env in ENV_FILES:
        if not env.exists():
            continue
        for line in env.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        return


def client():
    from anthropic import Anthropic

    load_env()
    base = os.environ.get("META_API_BASE_URL", "https://api.meta.ai/v1").rstrip("/")
    base = base[:-3] if base.endswith("/v1") else base
    return Anthropic(api_key=os.environ["META_API_KEY"], base_url=base, max_retries=1, timeout=300)


def spend() -> dict:
    p = _state["spend"]
    return json.loads(p.read_text()) if p.exists() else {"total_usd": 0.0, "calls": []}


def _record(entry: dict) -> None:
    with _lock:
        s = spend()
        s["calls"].append(entry)
        s["total_usd"] = round(s["total_usd"] + entry["cost_usd"], 5)
        _state["spend"].write_text(json.dumps(s, indent=1))


def complete(user_text: str, *, system: str, image_png: bytes | None = None, effort: str = "low",
             max_tokens: int = MIN_OUTPUT, tag: str = "") -> tuple[str, dict]:
    """One Spark call. Returns (text, usage with cost and latency). Raises when the cap is reached."""
    with _lock:
        total = spend()["total_usd"]
    if total >= _state["cap"]:
        raise RuntimeError(f"spend cap reached: ${total:.3f} >= ${_state['cap']}")
    content = []
    if image_png is not None:
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                     "data": base64.b64encode(image_png).decode()}})
    content.append({"type": "text", "text": user_text})
    t0 = time.perf_counter()
    res = client().messages.create(model=MODEL, max_tokens=max(max_tokens, MIN_OUTPUT), system=system,
                                   messages=[{"role": "user", "content": content}], output_config={"effort": effort})
    dt = time.perf_counter() - t0
    text = "".join(b.text for b in res.content if b.type == "text")
    u = res.usage
    cost = u.input_tokens / 1e6 * PRICE_IN + u.output_tokens / 1e6 * PRICE_OUT
    usage = {"tag": tag, "model": res.model or MODEL, "input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
             "cost_usd": round(cost, 5), "latency_s": round(dt, 2), "effort": effort, "stop_reason": res.stop_reason}
    _record(usage)
    return text, usage


def parse_json(text: str):
    """Spark's JSON: strip a code fence or prose, take the outermost object, and on a decode error drop the one
    stray word Spark 1.3 sometimes leaves after a closing bracket (app/librarian/header.py does the same)."""
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError(f"no JSON in: {text[:200]!r}")
    body = text[start:end + 1]
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        pass
    stray = r"(?<=[\]\}])\s*-?[A-Za-z_]+(?:=\d+)?(?=\s*[,\]\}])"
    for repl in ("", "]", "}"):
        try:
            return json.loads(re.sub(stray, repl, body, count=1))
        except json.JSONDecodeError:
            continue
    return json.loads(body)


def ask_json(user_text: str, *, system: str, image_png: bytes | None, tag: str) -> tuple[dict, list[dict], str]:
    """One call, one retry when the reply is truncated or unparseable. Returns (answer, usages, raw)."""
    usages, raw = [], ""
    for attempt in range(2):
        raw, usage = complete(user_text, system=system, image_png=image_png, tag=tag + (" retry" if attempt else ""))
        usages.append(usage)
        try:
            return parse_json(raw), usages, raw
        except (ValueError, json.JSONDecodeError) as e:
            err = str(e)
    return {"error": err, "raw": raw[:500]}, usages, raw
