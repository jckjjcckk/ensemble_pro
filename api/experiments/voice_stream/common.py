"""Shared bits: ledger with a $5 cap, WAV io, the eval's labels and facts, Spark (streamed) with timings."""

from __future__ import annotations

import datetime as dt
import json
import sys
import time
import wave
from pathlib import Path

import numpy as np

from app import llm
from app.settings import settings

from ..voice.voice_eval import FACTS, KEYWORDS, MEMBER_OF, base_id, labels  # noqa: F401

HERE = Path(__file__).resolve().parent
API = HERE.parent.parent
WAVS = API / "fixtures" / "voice" / "audio" / "wav"
LOCAL = HERE / "audio"          # synthetic negatives, piano, the long stream (gitignored with the rest of audio)
RESULTS = HERE / "results"
LEDGER = HERE / "spend.jsonl"
BUDGET_USD = 5.0
ASR_USD_PER_HOUR = 0.18
SR = 16000


def spent() -> float:
    if not LEDGER.exists():
        return 0.0
    return sum(json.loads(l)["usd"] for l in LEDGER.read_text().splitlines() if l.strip())


def log_spend(**row) -> None:
    row = {"ts": dt.datetime.now().isoformat(timespec="seconds"), **row}
    with LEDGER.open("a") as f:
        f.write(json.dumps(row) + "\n")


def guard(next_usd: float) -> None:
    if spent() + next_usd > BUDGET_USD:
        sys.exit(f"STOP: spend {spent():.4f} + {next_usd:.4f} would pass the ${BUDGET_USD} cap")


def asr_usd(seconds: float) -> float:
    return int(seconds) / 3600 * ASR_USD_PER_HOUR      # billed in whole seconds, rounded down


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2 and w.getframerate() == SR, path
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).copy()


def write_wav(path: Path, x: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(x.astype(np.int16).tobytes())


def wav_bytes(x: np.ndarray) -> bytes:
    import io
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(x.astype(np.int16).tobytes())
    return buf.getvalue()


def speech_span(x: np.ndarray, frame_ms: int = 20) -> tuple[float, float]:
    """(first, last) second with energy well above the clip's floor: a rough speech onset and end for timing."""
    n = SR * frame_ms // 1000
    f = x[: len(x) // n * n].astype(np.float32).reshape(-1, n)
    db = 10 * np.log10((f ** 2).mean(axis=1) + 1e-9)
    floor = np.percentile(db, 10)
    on = np.where(db > max(floor + 20, 50))[0]      # int16 scale: room noise 30-45 dB, CK's speech 65-80 dB
    if not len(on):
        return 0.0, len(x) / SR
    return on[0] * frame_ms / 1000, (on[-1] + 1) * frame_ms / 1000


PRICE = {"muse-spark-1.3": (1.25, 0.15, 4.25), "muse-spark-1.3-contributor": (0.10, 0.002, 0.20)}


async def spark_chat(system: str, user: str, *, tag: str, uid: str, effort: str = "low", max_tokens: int = 8192,
                     model: str = "muse-spark-1.3") -> dict:
    """One Spark call on /v1/chat/completions, streamed (SSE deltas): this endpoint takes reasoning_effort
    "minimal" (Messages refuses it) and streams the answer token by token (Messages sends it in one piece)."""
    import httpx
    guard(0.03)
    body = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "reasoning_effort": effort, "max_completion_tokens": max_tokens, "stream": True,
            "stream_options": {"include_usage": True}}
    base = settings.meta_api_base_url.rstrip("/")
    t0 = time.monotonic()
    first_tok = first_obj = None
    text, usage = "", {}
    async with httpx.AsyncClient(timeout=120) as c:
        async with c.stream("POST", f"{base}/chat/completions", json=body,
                            headers={"Authorization": f"Bearer {settings.meta_api_key}"}) as r:
            if r.status_code != 200:
                raise RuntimeError(f"chat HTTP {r.status_code}: {(await r.aread())[:300]!r}")
            async for line in r.aiter_lines():
                if not line.startswith("data:") or line.strip() == "data: [DONE]":
                    continue
                ev = json.loads(line[5:])
                if ev.get("usage"):
                    usage = ev["usage"]
                for ch in ev.get("choices") or []:
                    d = (ch.get("delta") or {}).get("content")
                    if d:
                        if first_tok is None:
                            first_tok = time.monotonic() - t0
                        text += d
                        if first_obj is None and first_complete_object(text) is not None:
                            first_obj = time.monotonic() - t0
    took = time.monotonic() - t0
    pin, pcache, pout = PRICE[model]
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
    tin, tout = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
    reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
    usd = ((tin - cached) * pin + cached * pcache + tout * pout) / 1e6
    log_spend(kind=tag, id=uid, usd=round(usd, 6), secs=round(took, 2), input_tokens=tin, cached_tokens=cached,
              output_tokens=tout, reasoning_tokens=reasoning, model=model, effort=effort, api="chat")
    return {"text": text, "seconds": took, "first_token": first_tok, "first_object": first_obj, "usd": usd,
            "input_tokens": tin, "cached_tokens": cached, "output_tokens": tout, "reasoning_tokens": reasoning}


async def spark_stream(system: str, user: str, *, tag: str, uid: str, effort: str = "low", max_tokens: int = 8192,
                       model: str | None = None, stream: bool = True) -> dict:
    """One Spark call on /v1/messages (the app's path); with stream=True, the time to the first text token and to
    the first complete JSON object."""
    from anthropic import AsyncAnthropic
    guard(0.03)
    model = model or settings.meta_model
    base = settings.meta_api_base_url.rstrip("/")
    base = base[:-3] if base.endswith("/v1") else base
    client = AsyncAnthropic(api_key=settings.meta_api_key, base_url=base, max_retries=1)
    kw = dict(model=model, max_tokens=max_tokens, system=system, messages=[{"role": "user", "content": user}],
              extra_body={"output_config": {"effort": effort}})
    t0 = time.monotonic()
    first_tok = first_obj = None
    text = ""
    if stream:
        async with client.messages.stream(**kw) as s:
            async for ev in s:
                if ev.type == "text":
                    if first_tok is None:
                        first_tok = time.monotonic() - t0
                    text += ev.text
                    if first_obj is None and first_complete_object(text) is not None:
                        first_obj = time.monotonic() - t0
            msg = await s.get_final_message()
    else:
        msg = await client.messages.create(**kw)
        text = "".join(b.text for b in msg.content if b.type == "text")
    took = time.monotonic() - t0
    u = msg.usage
    cached = getattr(u, "cache_read_input_tokens", 0) or 0
    usd = float(llm.price(model, u.input_tokens, u.output_tokens))
    if cached:
        rate = 0.002 if "contributor" in model else 0.15
        usd += cached * rate / 1e6
    log_spend(kind=tag, id=uid, usd=round(usd, 6), secs=round(took, 2), input_tokens=u.input_tokens,
              cached_tokens=cached, output_tokens=u.output_tokens, model=model, effort=effort)
    return {"text": text, "seconds": took, "first_token": first_tok, "first_object": first_obj, "usd": usd,
            "input_tokens": u.input_tokens, "cached_tokens": cached, "output_tokens": u.output_tokens,
            "blocks": [b.type for b in msg.content]}


def first_complete_object(s: str):
    """The first complete JSON object in a partial reply: `{"none": true}`, or the first mark of an array."""
    i = s.find("{")
    if i < 0:
        return None
    depth, instr, esc = 0, False, False
    for j in range(i, len(s)):
        c = s[j]
        if instr:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                instr = False
            continue
        if c == '"':
            instr = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(s[i:j + 1])
                except ValueError:
                    return None
    return None
