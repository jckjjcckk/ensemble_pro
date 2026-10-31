"""Text and vision reasoning through one client. Provider is a setting: Anthropic while experimenting,
Meta's Muse Spark for the submission. Meta's API speaks the Messages format, so the Anthropic SDK is the
client for both, pointed at a different base URL. Every call returns its cost so the caller can charge it.

Effort "minimal" is the one exception: Meta's Messages endpoint refuses it, only chat completions takes it, and it
halves Spark's time on a page read (004-speed-eval) and a voice line (013-always-on). So `effort="minimal"` with Meta
goes to /v1/chat/completions (`chat`); every other effort stays on Messages. With Anthropic, "minimal" is sent as
"low" on Messages (Claude has no minimal).
"""
import asyncio
import json
import time
from dataclasses import dataclass, field
from decimal import Decimal

import httpx
from anthropic import AsyncAnthropic

from .settings import settings
from .spend import Charge

# USD per 1M tokens, (input, output). Anthropic rates from the Claude API reference (2026-10);
# Meta rates from dev.meta.ai pricing, verified 2026-10-27.
PRICES: dict[str, tuple[Decimal, Decimal]] = {
    "claude-opus-5-5": (Decimal("4"), Decimal("20")),
    "claude-sonnet-5-5": (Decimal("2"), Decimal("10")),
    "claude-haiku-5-5": (Decimal("0.10"), Decimal("0.50")),
    "muse-spark-1.3": (Decimal("1.25"), Decimal("4.25")),
    "muse-spark-1.3-contributor": (Decimal("0.10"), Decimal("0.20")),
}


def price(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    p_in, p_out = PRICES.get(model, (Decimal("5"), Decimal("25")))  # unknown model: priced like Opus 5
    return (p_in * input_tokens + p_out * output_tokens) / Decimal(1_000_000)


@dataclass(frozen=True)
class Completion:
    text: str
    charge: Charge
    api: str = "messages"            # "messages" | "chat"
    truncated: bool = False          # the reply stopped at the output budget
    seconds: float = 0.0
    first_token_s: float | None = None


CHAT_EFFORT = "minimal"
# One model call's ceiling, both APIs (the SDK's default is 600 s). The longest Spark call measured is a 45 s page read;
# a Messages call that hung for 10 minutes stalled a convert in the speed pass (2026-10-30), so a stuck call is retried.
CALL_TIMEOUT_S = 180.0
CHAT_RETRY_S = 1.0
# Tests hand the chat branch a fake transport here (httpx.MockTransport); None is the network.
_chat_transport: httpx.AsyncBaseTransport | None = None


def uses_chat(effort: str, provider: str | None = None) -> bool:
    return effort == CHAT_EFFORT and (provider or settings.llm_provider) == "meta"


@dataclass
class ChatReply:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int | None = None
    cached_tokens: int = 0
    finish_reason: str | None = None
    seconds: float = 0.0
    first_token_s: float | None = None
    raw_usage: dict = field(default_factory=dict)


def chat_content(text: str, image_png_b64: str | None = None) -> str | list[dict]:
    if not image_png_b64:
        return text
    return [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_png_b64}"}}, {"type": "text", "text": text}]


async def chat(messages: list[dict], *, effort: str = CHAT_EFFORT, max_tokens: int = 4096, model: str | None = None,
               stream: bool = False, timeout: float = CALL_TIMEOUT_S) -> ChatReply:
    """One call on Meta's /v1/chat/completions, the request shape of the voice and page-read evals
    (`experiments/voice_stream/common.py`, `experiments/pageread_speed/common.py`): `reasoning_effort`,
    `max_completion_tokens` (Spark's reasoning counts against it, so at least 1024), usage as prompt/completion
    tokens. Streamed (SSE, usage in the last event) when `stream`. One retry on a transport error, 429 or 5xx."""
    model = model or settings.meta_model
    body: dict = {"model": model, "messages": messages, "reasoning_effort": effort,
                  "max_completion_tokens": max(max_tokens, 1024)}
    if stream:
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}
    url = settings.meta_api_base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {settings.meta_api_key}"}
    last: Exception | None = None
    for attempt in range(2):
        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=timeout, transport=_chat_transport) as c:
                if not stream:
                    r = await c.post(url, json=body, headers=headers)
                    if r.status_code != 200:
                        raise _ChatHTTP(r.status_code, r.text[:300])
                    d = r.json()
                    ch = (d.get("choices") or [{}])[0]
                    text = (ch.get("message") or {}).get("content") or ""
                    return _reply(text, d.get("model") or model, d.get("usage") or {}, ch.get("finish_reason"),
                                  time.monotonic() - t0, None)
                text, usage, finish, first = "", {}, None, None
                async with c.stream("POST", url, json=body, headers=headers) as r:
                    if r.status_code != 200:
                        raise _ChatHTTP(r.status_code, (await r.aread())[:300].decode("utf-8", "replace"))
                    got_model = model
                    async for line in r.aiter_lines():
                        if not line.startswith("data:") or line.strip() == "data: [DONE]":
                            continue
                        ev = json.loads(line[5:])
                        got_model = ev.get("model") or got_model
                        if ev.get("usage"):
                            usage = ev["usage"]
                        for chn in ev.get("choices") or []:
                            d = (chn.get("delta") or {}).get("content")
                            if d:
                                if first is None:
                                    first = time.monotonic() - t0
                                text += d
                            if chn.get("finish_reason"):
                                finish = chn["finish_reason"]
                return _reply(text, got_model, usage, finish, time.monotonic() - t0, first)
        except _ChatHTTP as e:
            last = e
            if not (e.status == 429 or e.status >= 500) or attempt:
                raise RuntimeError(f"chat completions HTTP {e.status}: {e.body!r}") from None
        except httpx.TransportError as e:
            last = e
            if attempt:
                raise
        await asyncio.sleep(CHAT_RETRY_S)
    raise RuntimeError(f"chat completions failed: {last}")


class _ChatHTTP(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(status)
        self.status, self.body = status, body


def _reply(text: str, model: str, u: dict, finish: str | None, secs: float, first: float | None) -> ChatReply:
    return ChatReply(text, model, int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0),
                     (u.get("completion_tokens_details") or {}).get("reasoning_tokens"),
                     int((u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0), finish, secs, first, u)


def _client(provider: str | None = None) -> AsyncAnthropic:
    if (provider or settings.llm_provider) == "meta":
        # The SDK appends /v1/messages itself; META_API_BASE_URL is written with its /v1 (as Meta documents it).
        base = settings.meta_api_base_url.rstrip("/")
        base = base[:-3] if base.endswith("/v1") else base
        return AsyncAnthropic(api_key=settings.meta_api_key, base_url=base, max_retries=1, timeout=CALL_TIMEOUT_S)
    return AsyncAnthropic(api_key=settings.anthropic_api_key, max_retries=1, timeout=CALL_TIMEOUT_S)


def model_name(provider: str | None = None) -> str:
    return settings.meta_model if (provider or settings.llm_provider) == "meta" else settings.anthropic_model


async def complete(
    user_text: str, *, system: str | None = None, effort: str = "low", max_tokens: int = 4096,
    image_png_b64: str | None = None, provider: str | None = None, stream: bool = False,
) -> Completion:
    """`provider` overrides LLM_PROVIDER for one call: voice notes always use Spark, the model their prompt was tuned on.
    `effort="minimal"` with Meta goes to chat completions (`stream` applies there only); everything else is Messages."""
    provider = provider or settings.llm_provider
    if uses_chat(effort, provider):
        msgs: list[dict] = [{"role": "system", "content": system}] if system else []
        msgs.append({"role": "user", "content": chat_content(user_text, image_png_b64)})
        r = await chat(msgs, effort=effort, max_tokens=max_tokens, model=model_name(provider), stream=stream)
        cost = price(r.model, r.input_tokens, r.output_tokens)
        return Completion(r.text, Charge(provider, r.model, "spark", cost, r.input_tokens, r.output_tokens), "chat",
                          r.finish_reason == "length", r.seconds, r.first_token_s)
    if effort == CHAT_EFFORT:
        effort = "low"           # Claude on Messages has no minimal
    t0 = time.monotonic()
    content: list[dict] = []
    if image_png_b64:
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_png_b64}})
    content.append({"type": "text", "text": user_text})
    kwargs: dict = {
        "model": model_name(provider), "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": content}],
    }
    if system:
        kwargs["system"] = system
    # Both providers take output_config.effort on /v1/messages (Meta verified 2026-10-27: "low" cut Spark's
    # reasoning from ~310 to ~70 output tokens). Spark's reasoning counts against max_tokens, so give it room:
    # a 64-token cap returned an empty reply.
    kwargs["output_config"] = {"effort": effort}
    if provider == "meta":
        kwargs["max_tokens"] = max(max_tokens, 1024)
    res = await _client(provider).messages.create(**kwargs)
    text = "".join(b.text for b in res.content if b.type == "text")
    usage = res.usage
    model = res.model or model_name(provider)
    cost = price(model, usage.input_tokens, usage.output_tokens)
    kind = "spark" if provider == "meta" else "claude"
    return Completion(text, Charge(provider, model, kind, cost, usage.input_tokens, usage.output_tokens), "messages",
                      getattr(res, "stop_reason", None) == "max_tokens", time.monotonic() - t0)
