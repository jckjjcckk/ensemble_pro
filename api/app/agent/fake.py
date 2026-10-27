"""A scripted model for tests: an httpx transport that answers /v1/messages like the API would.

    script = [tool("read_page", {"page": 1}), text("done, I think"), tool("commit", {...})]
    client = fake_client(script)
    await run_agent(..., client=client)

Each request pops the next scripted reply, whatever the prompt says; `calls` keeps every request body so a
test can assert what the model was shown (tool results, nudges, the answer on resume). `fail_at` raises an
HTTP 500 on that request, to test pause and retry.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

import httpx2 as httpx
from anthropic import AsyncAnthropic


def tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"type": "tool_use", "id": f"toolu_{uuid.uuid4().hex[:12]}", "name": name, "input": args}


def text(s: str) -> dict[str, Any]:
    return {"type": "text", "text": s}


def truncated(*blocks: dict[str, Any]) -> list[dict[str, Any]]:
    """A reply cut off by max_tokens: the blocks plus a marker the transport turns into stop_reason."""
    return [*blocks, {"type": "_truncated"}]


class ScriptedTransport(httpx.AsyncBaseTransport):
    def __init__(self, script: list[dict[str, Any] | list[dict[str, Any]]], *, model: str = "fake-model", fail_at: int | None = None):
        self.script = list(script)
        self.model = model
        self.fail_at = fail_at
        self.calls: list[dict[str, Any]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        self.calls.append(body)
        n = len(self.calls)
        if self.fail_at == n:
            return httpx.Response(500, json={"type": "error", "error": {"type": "api_error", "message": "scripted outage"}})
        if not self.script:
            return httpx.Response(400, json={"type": "error", "error": {"type": "invalid_request_error", "message": "script exhausted"}})
        step = self.script.pop(0)
        content = step if isinstance(step, list) else [step]
        cut = any(b["type"] == "_truncated" for b in content)
        content = [b for b in content if b["type"] != "_truncated"]
        stop = "max_tokens" if cut else "tool_use" if any(b["type"] == "tool_use" for b in content) else "end_turn"
        return httpx.Response(200, json={
            "id": f"msg_{uuid.uuid4().hex[:12]}", "type": "message", "role": "assistant", "model": self.model,
            "content": content, "stop_reason": stop, "stop_sequence": None,
            "usage": {"input_tokens": 100, "output_tokens": 20},
        })


def fake_client(script: list[Any], **kw: Any) -> tuple[AsyncAnthropic, ScriptedTransport]:
    t = ScriptedTransport(script, **kw)
    c = AsyncAnthropic(api_key="fake", base_url="http://fake", max_retries=0, http_client=httpx.AsyncClient(transport=t))
    return c, t
