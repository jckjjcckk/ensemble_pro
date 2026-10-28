"""The agent loop: a model, a toolbox, a state that survives every turn.

    state = await run_agent(system=..., tools=box, user_text="Read the pages", persist=save, charge=ctx.charge)

Each turn sends the whole history to the model with the tool definitions, appends what came back, runs the
tool calls (one per turn by default: the first call is run, the rest are refused so the model re-issues them
after seeing the result), appends the tool results, and persists the state. The run ends when a tool raises
`Stop`, when the turn or cost limit is hit (`status = 'paused'`), when a commit tool has refused too often
(`needs_review` with the last feedback as the question), or when the model keeps answering in prose.

Resume: pass the previous `state` and an `answer`; the answer becomes the next user message and the loop
continues with the same history. Nothing changed → no model call, the state comes back as it was.

The loop never touches the database: `persist(state_dict)` and `charge(Charge)` are callbacks, so handlers
decide where state lives (the job row, an interpretation) and tests run without a database or a network.
"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any

from anthropic import AsyncAnthropic

from ..llm import _client as default_client, model_name as default_model, price
from ..settings import settings
from ..spend import Charge
from .tools import Refusal, Stop, ToolBox

log = logging.getLogger("folio.agent")

PLAIN_TEXT_NUDGE = "Plain text is not accepted here. Call exactly one tool."
LAST_TURN_NUDGE = "This is your last turn. Call the tool that finishes the task now, or ask_admin."
TRUNCATED_NUDGE = "Your reply was cut off before the tool call. Think less and reply with the tool call only."
TRUNCATED_CALL = "This call arrived in a reply that was cut off (max_tokens) and may be incomplete; it was not run. Re-issue it."


@dataclass
class AgentState:
    messages: list[dict[str, Any]] = field(default_factory=list)
    status: str = "running"          # running | done | needs_review | paused | failed
    turn: int = 0
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    refusals: dict[str, int] = field(default_factory=dict)
    nudges: int = 0
    question: str | None = None
    question_payload: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    log: list[str] = field(default_factory=list)
    scratch: dict[str, Any] = field(default_factory=dict)   # tools keep working data here

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any] | None) -> "AgentState":
        if not d:
            return AgentState()
        known = {k: v for k, v in d.items() if k in AgentState.__dataclass_fields__}
        return AgentState(**known)

    @property
    def last_user_text(self) -> str | None:
        for m in reversed(self.messages):
            if m["role"] == "user" and isinstance(m["content"], str):
                return m["content"]
        return None


def _dump_blocks(content: list[Any]) -> list[dict[str, Any]]:
    return [b.model_dump(exclude_none=True) for b in content]


def _tool_result(call_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"type": "tool_result", "tool_use_id": call_id, "content": json.dumps(payload, ensure_ascii=False)}


async def run_agent(
    *,
    system: str,
    tools: ToolBox,
    user_text: str | None = None,
    state: AgentState | None = None,
    answer: str | None = None,
    persist: Callable[[dict[str, Any]], Any] | None = None,
    charge: Callable[[Charge], Any] | None = None,
    client: AsyncAnthropic | None = None,
    model: str | None = None,
    effort: str = "low",
    max_tokens: int = 2048,
    max_turns: int = 24,
    max_cost_usd: float = 1.0,
    max_refusals: int = 3,
    max_nudges: int = 3,
    one_tool_per_turn: bool = True,
) -> AgentState:
    st = state or AgentState()
    if st.status == "needs_review" and answer is None:
        return st                                    # nothing changed, no model call
    if answer is not None:
        st.messages.append({"role": "user", "content": answer})
        st.status, st.question, st.question_payload = "running", None, {}
        st.refusals = {}
        st.log.append("Resumed with the admin's answer")
    elif not st.messages:
        if user_text is None:
            raise ValueError("a new run needs user_text")
        st.messages.append({"role": "user", "content": user_text})
    if st.status in ("done", "failed"):
        return st
    st.status = "running"

    c = client or default_client()
    m = model or default_model()
    is_meta = settings.llm_provider == "meta" or m.startswith("muse")
    defs = tools.definitions()

    async def save() -> None:
        if persist:
            out = persist(st.to_dict())
            if hasattr(out, "__await__"):
                await out

    while True:
        if st.turn >= max_turns or st.cost_usd >= max_cost_usd:
            st.status = "paused"
            st.log.append(f"Paused: {'turn' if st.turn >= max_turns else 'cost'} limit reached")
            await save()
            return st
        last_turn = st.turn == max_turns - 1
        msgs = list(st.messages)
        if last_turn and isinstance(msgs[-1].get("content"), list):
            msgs[-1] = {**msgs[-1], "content": [*msgs[-1]["content"], {"type": "text", "text": LAST_TURN_NUDGE}]}
        kw: dict[str, Any] = {"model": m, "max_tokens": max(max_tokens, 1024) if is_meta else max_tokens,
                              "system": system, "tools": defs, "messages": msgs,
                              "output_config": {"effort": effort}}
        t0 = time.time()
        res = await c.messages.create(**kw)
        st.turn += 1
        u = res.usage
        cost = price(res.model or m, u.input_tokens, u.output_tokens)
        st.cost_usd = float(Decimal(str(st.cost_usd)) + cost)
        st.input_tokens += u.input_tokens
        st.output_tokens += u.output_tokens
        if charge:
            out = charge(Charge("meta" if is_meta else "anthropic", res.model or m, "spark" if is_meta else "claude", cost, u.input_tokens, u.output_tokens))
            if hasattr(out, "__await__"):
                await out
        blocks = _dump_blocks(res.content)
        st.messages.append({"role": "assistant", "content": blocks})
        calls = [b for b in blocks if b["type"] == "tool_use"]
        log.info("agent turn %d: %s in %.1fs, %d call(s), $%.4f", st.turn, res.stop_reason, time.time() - t0, len(calls), cost)

        if calls and res.stop_reason == "max_tokens":
            # pi's rule: a tool call from a truncated reply may be partial; never run it, ask again.
            st.messages.append({"role": "user", "content": [_tool_result(c["id"], {"error": TRUNCATED_CALL}) for c in calls]})
            st.log.append(f"Turn {st.turn}: reply truncated, {len(calls)} call(s) refused")
            st.nudges += 1
            if st.nudges > max_nudges:
                st.status = "failed"
                st.result["error"] = "the model kept running out of room before its tool call"
            await save()
            if st.status == "failed":
                return st
            continue
        if not calls:
            st.nudges += 1
            if st.nudges > max_nudges:
                st.status = "failed"
                st.result["error"] = "the model kept answering in prose instead of calling a tool"
                await save()
                return st
            nudge = TRUNCATED_NUDGE if res.stop_reason == "max_tokens" else PLAIN_TEXT_NUDGE
            st.messages.append({"role": "user", "content": nudge})
            st.log.append(f"Turn {st.turn}: nudged ({res.stop_reason})")
            await save()
            continue
        st.nudges = 0

        results: list[dict[str, Any]] = []
        ended: Stop | None = None
        for i, call in enumerate(calls):
            name, args, cid = call["name"], call.get("input") or {}, call["id"]
            if ended is not None or (one_tool_per_turn and i > 0):
                results.append(_tool_result(cid, {"error": "One tool call per turn. Re-issue this call after reading the previous result."}))
                continue
            if name not in tools:
                results.append(_tool_result(cid, {"error": f"Unknown tool {name!r}. Tools: {', '.join(tools.tools)}"}))
                continue
            problem = tools[name].validate(args) if isinstance(args, dict) else f"{name}: arguments must be an object"
            if problem:
                results.append(_tool_result(cid, {"error": problem}))
                st.log.append(f"Turn {st.turn}: {name} invalid arguments")
                continue
            try:
                out = await tools.call(name, args, st)
                results.append(_tool_result(cid, out))
                st.refusals.pop(name, None)  # a success clears the tool's refusal streak
                st.log.append(f"Turn {st.turn}: {name} ok")
            except Refusal as r:
                n = st.refusals.get(name, 0) + 1
                st.refusals[name] = n
                st.log.append(f"Turn {st.turn}: {name} refused ({n}): {r}")
                if tools[name].commit and n >= max_refusals:
                    ended = Stop("needs_review", question=f"{name} was refused {n} times. Last feedback: {r}",
                                 question_payload={"tool": name, "args": args, "feedback": str(r)})
                    results.append(_tool_result(cid, {"error": str(r), "status": "needs_review"}))
                else:
                    results.append(_tool_result(cid, {"error": str(r), "refusals": n, "max_refusals": max_refusals}))
            except Stop as s:
                ended = s
                results.append(_tool_result(cid, {"status": s.status, **{k: v for k, v in s.result.items() if k != "question_payload"}}))
                st.log.append(f"Turn {st.turn}: {name} → {s.status}")
            except Exception as e:  # noqa: BLE001
                log.warning("tool %s raised: %r", name, e)
                st.log.append(f"Turn {st.turn}: {name} error: {type(e).__name__}: {e}")
                results.append(_tool_result(cid, {"error": f"{type(e).__name__}: {e}"}))
        st.messages.append({"role": "user", "content": results})

        if ended is not None:
            st.status = ended.status
            if ended.status == "needs_review":
                st.question = ended.result.get("question")
                st.question_payload = ended.result.get("question_payload") or {}
            st.result.update({k: v for k, v in ended.result.items() if k not in ("question", "question_payload")})
            await save()
            return st
        await save()
