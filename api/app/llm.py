"""Text and vision reasoning through one client. Provider is a setting: Anthropic while experimenting,
Meta's Muse Spark for the submission. Meta's API speaks the Messages format, so the Anthropic SDK is the
client for both, pointed at a different base URL. Every call returns its cost so the caller can charge it.
"""
from dataclasses import dataclass
from decimal import Decimal

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


def _client() -> AsyncAnthropic:
    if settings.llm_provider == "meta":
        # The SDK appends /v1/messages itself; META_API_BASE_URL is written with its /v1 (as Meta documents it).
        base = settings.meta_api_base_url.rstrip("/")
        base = base[:-3] if base.endswith("/v1") else base
        return AsyncAnthropic(api_key=settings.meta_api_key, base_url=base, max_retries=1)
    return AsyncAnthropic(api_key=settings.anthropic_api_key, max_retries=1)


def model_name() -> str:
    return settings.meta_model if settings.llm_provider == "meta" else settings.anthropic_model


async def complete(
    user_text: str, *, system: str | None = None, effort: str = "low", max_tokens: int = 4096,
    image_png_b64: str | None = None,
) -> Completion:
    content: list[dict] = []
    if image_png_b64:
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_png_b64}})
    content.append({"type": "text", "text": user_text})
    kwargs: dict = {
        "model": model_name(), "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": content}],
    }
    if system:
        kwargs["system"] = system
    # Both providers take output_config.effort on /v1/messages (Meta verified 2026-10-27: "low" cut Spark's
    # reasoning from ~310 to ~70 output tokens). Spark's reasoning counts against max_tokens, so give it room:
    # a 64-token cap returned an empty reply.
    kwargs["output_config"] = {"effort": effort}
    if settings.llm_provider == "meta":
        kwargs["max_tokens"] = max(max_tokens, 1024)
    res = await _client().messages.create(**kwargs)
    text = "".join(b.text for b in res.content if b.type == "text")
    usage = res.usage
    model = res.model or model_name()
    cost = price(model, usage.input_tokens, usage.output_tokens)
    kind = "spark" if settings.llm_provider == "meta" else "claude"
    return Completion(text, Charge(settings.llm_provider, model, kind, cost, usage.input_tokens, usage.output_tokens))
