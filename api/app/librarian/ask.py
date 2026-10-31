"""One image+text question to the model outside the agent loop, answered as JSON (Muse Spark 1.3 in the product).

Used by part_cut (header, labels, recheck) and by process_pages (the signature read). Moved here from part_cut so
process_pages can use it without importing part_cut (which imports process_pages). Every attempt is charged to the
job's user through `ctx.charge`; the answer goes through the header's JSON repair.
"""
from __future__ import annotations

import json
from typing import Any

from anthropic import AsyncAnthropic

from .. import llm
from ..llm import price
from ..settings import settings
from ..spend import Charge
from . import JobContext
from . import header as hdr

# The in-tool calls (header, labels, recheck) are not agent turns: with the agent's SYSTEM ("call exactly one tool
# per turn") Spark sometimes answers a label request with a pretend read_header call instead of the JSON asked for.
ASK_SYSTEM = "You are an orchestral librarian reading a scanned page of a full score. Answer with strict JSON only, no prose."


class NoJSON(ValueError):
    """Every attempt of an in-tool call failed to give the JSON asked for; carries what the attempts cost."""
    def __init__(self, msg: str, cost_usd: float):
        super().__init__(msg)
        self.cost_usd = cost_usd


async def ask_model(ctx: JobContext, client: AsyncAnthropic, model: str, prompt: str, png: bytes, *, max_tokens: int = 2048,
                    effort: str = "low", retries: int = 1, require: str | None = None, system: str = ASK_SYSTEM) -> dict[str, Any]:
    """One image+text call outside the loop (header, labels, recheck, signature), charged like a turn. The answer is
    parsed with the JSON repair; a reply cut off at max_tokens or one that does not parse is asked again (`retries`
    times, every attempt charged); so is JSON without the `require`d list. `_cost_usd` is the sum, `_retries` the reasons; raises when no attempt parsed.
    `effort="minimal"` with Spark goes to chat completions (`llm.chat`), same prompt, image and system; `_api` says which."""
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": ctx.png_b64(png)}}, {"type": "text", "text": prompt}]
    is_meta = settings.llm_provider == "meta" or model.startswith("muse")
    total, why, data, err = 0.0, [], None, None
    use_chat = effort == llm.CHAT_EFFORT and is_meta
    if effort == llm.CHAT_EFFORT and not is_meta:
        effort = "low"
    for _ in range(retries + 1):
        if use_chat:
            r = await llm.chat([{"role": "system", "content": system},
                                {"role": "user", "content": llm.chat_content(prompt, ctx.png_b64(png))}],
                               effort=effort, max_tokens=max_tokens, model=model)
            n_in, n_out, got_model, text, truncated = r.input_tokens, r.output_tokens, r.model or model, r.text, r.finish_reason == "length"
        else:
            res = await client.messages.create(model=model, max_tokens=max(max_tokens, 1024) if is_meta else max_tokens, system=system,
                                               messages=[{"role": "user", "content": content}], output_config={"effort": effort})
            n_in, n_out, got_model = res.usage.input_tokens, res.usage.output_tokens, res.model or model
            text = "".join(b.text for b in res.content if b.type == "text")
            truncated = res.stop_reason == "max_tokens"
        cost = price(got_model, n_in, n_out)
        ctx.charge(Charge("meta" if is_meta else "anthropic", got_model, "spark" if is_meta else "claude", cost, n_in, n_out))
        total += float(cost)
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
        why.append(f"truncated at {n_out} output tokens" if truncated else f"unparseable: {err}")
    if data is None:
        raise NoJSON(f"no JSON after {len(why)} attempt(s): {'; '.join(why)}", total)
    data["_cost_usd"], data["_retries"], data["_api"] = total, why, "chat" if use_chat else "messages"
    return data
