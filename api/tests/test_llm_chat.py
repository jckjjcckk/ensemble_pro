"""llm.complete's chat-completions branch (effort "minimal" with Meta) against a fake transport, and the proof that
every other call stays on Messages exactly as before."""
import asyncio
import json
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest

from app import llm
from app.librarian import ask


def _messages_client(calls):
    class Msgs:
        async def create(self, **kw):
            calls.append(kw)
            return SimpleNamespace(content=[SimpleNamespace(type="text", text='{"ok": true}')], model=kw["model"],
                                   usage=SimpleNamespace(input_tokens=100, output_tokens=20), stop_reason="end_turn")
    return SimpleNamespace(messages=Msgs())


@pytest.fixture
def meta(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_provider", "meta")
    monkeypatch.setattr(llm.settings, "meta_api_key", "test-key")
    monkeypatch.setattr(llm.settings, "meta_api_base_url", "https://meta.test/v1")
    sent: list[dict] = []
    msgs: list[dict] = []
    monkeypatch.setattr(llm, "_client", lambda provider=None: _messages_client(msgs))
    return SimpleNamespace(sent=sent, msgs=msgs, mp=monkeypatch)


def _transport(sent, responses):
    it = iter(responses)

    def handle(req: httpx.Request) -> httpx.Response:
        sent.append({"url": str(req.url), "body": json.loads(req.content), "auth": req.headers.get("authorization")})
        return next(it)
    return httpx.MockTransport(handle)


def _ok(text='{"a": 1}', finish="stop", pt=1200, ct=300):
    return httpx.Response(200, json={"model": "muse-spark-1.3", "choices": [{"message": {"content": text}, "finish_reason": finish}],
                                     "usage": {"prompt_tokens": pt, "completion_tokens": ct, "completion_tokens_details": {"reasoning_tokens": 200}}})


def test_default_effort_stays_on_messages(meta):
    meta.mp.setattr(llm, "_chat_transport", _transport(meta.sent, []))
    c = asyncio.run(llm.complete("hi"))
    assert c.api == "messages" and not meta.sent
    assert meta.msgs[0]["output_config"] == {"effort": "low"} and meta.msgs[0]["max_tokens"] == 4096
    assert c.charge == llm.Charge("meta", "muse-spark-1.3", "spark", llm.price("muse-spark-1.3", 100, 20), 100, 20)
    c = asyncio.run(llm.complete("hi", effort="medium", system="s"))
    assert c.api == "messages" and meta.msgs[1]["output_config"] == {"effort": "medium"} and meta.msgs[1]["system"] == "s"


def test_minimal_goes_to_chat_with_image_and_budget(meta):
    meta.mp.setattr(llm, "_chat_transport", _transport(meta.sent, [_ok()]))
    c = asyncio.run(llm.complete("read this", system="json only", effort="minimal", max_tokens=8000, image_png_b64="QUJD"))
    assert c.api == "chat" and c.text == '{"a": 1}' and not c.truncated and not meta.msgs
    (s,) = meta.sent
    assert s["url"] == "https://meta.test/v1/chat/completions" and s["auth"] == "Bearer test-key"
    b = s["body"]
    assert b["reasoning_effort"] == "minimal" and b["max_completion_tokens"] == 8000 and "stream" not in b
    assert b["messages"][0] == {"role": "system", "content": "json only"}
    assert b["messages"][1]["content"][0] == {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}}
    assert b["messages"][1]["content"][1] == {"type": "text", "text": "read this"}
    assert c.charge.input_tokens == 1200 and c.charge.output_tokens == 300 and c.charge.kind == "spark"
    assert c.charge.cost_usd == (Decimal("1.25") * 1200 + Decimal("4.25") * 300) / Decimal(1_000_000)


def test_minimal_budget_floor_and_length(meta):
    meta.mp.setattr(llm, "_chat_transport", _transport(meta.sent, [_ok(finish="length")]))
    c = asyncio.run(llm.complete("x", effort="minimal", max_tokens=64))
    assert meta.sent[0]["body"]["max_completion_tokens"] == 1024 and c.truncated
    assert meta.sent[0]["body"]["messages"] == [{"role": "user", "content": "x"}]


def test_minimal_with_anthropic_is_low_on_messages(meta):
    meta.mp.setattr(llm.settings, "llm_provider", "anthropic")
    meta.mp.setattr(llm, "_chat_transport", _transport(meta.sent, []))
    c = asyncio.run(llm.complete("x", effort="minimal"))
    assert c.api == "messages" and meta.msgs[0]["output_config"] == {"effort": "low"} and not meta.sent


def test_streamed_chat_joins_deltas_and_reads_usage(meta):
    sse = "\n\n".join([
        'data: {"model":"muse-spark-1.3","choices":[{"delta":{"content":"{\\"no"}}]}',
        'data: {"choices":[{"delta":{"content":"ne\\": true}"},"finish_reason":"stop"}]}',
        'data: {"choices":[],"usage":{"prompt_tokens":500,"completion_tokens":40}}',
        "data: [DONE]"]) + "\n\n"
    meta.mp.setattr(llm, "_chat_transport", _transport(meta.sent, [httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})]))
    c = asyncio.run(llm.complete("x", effort="minimal", provider="meta", stream=True))
    assert c.text == '{"none": true}' and c.charge.input_tokens == 500 and c.charge.output_tokens == 40
    assert meta.sent[0]["body"]["stream"] is True and meta.sent[0]["body"]["stream_options"] == {"include_usage": True}
    assert c.first_token_s is not None


def test_chat_retries_once_on_5xx_not_on_4xx(meta, monkeypatch):
    monkeypatch.setattr(llm, "CHAT_RETRY_S", 0)
    meta.mp.setattr(llm, "_chat_transport", _transport(meta.sent, [httpx.Response(503, text="busy"), _ok()]))
    assert asyncio.run(llm.complete("x", effort="minimal")).text == '{"a": 1}' and len(meta.sent) == 2
    meta.sent.clear()
    meta.mp.setattr(llm, "_chat_transport", _transport(meta.sent, [httpx.Response(400, text="bad")]))
    with pytest.raises(RuntimeError, match="HTTP 400"):
        asyncio.run(llm.complete("x", effort="minimal"))
    assert len(meta.sent) == 1


class _Ctx:
    def __init__(self):
        self.charges = []

    def charge(self, c):
        self.charges.append(c)

    png_b64 = staticmethod(lambda b: "UE5H")


def test_ask_model_minimal_uses_chat_and_charges(meta):
    meta.mp.setattr(llm, "_chat_transport", _transport(meta.sent, [_ok('not json'), _ok('{"systems": []}')]))
    ctx = _Ctx()
    data = asyncio.run(ask.ask_model(ctx, None, "muse-spark-1.3", "label", b"png", effort="minimal", require="systems"))
    assert data["_api"] == "chat" and data["systems"] == [] and len(data["_retries"]) == 1
    assert len(ctx.charges) == 2 and all(c.kind == "spark" for c in ctx.charges)
    b = meta.sent[0]["body"]
    assert b["messages"][0]["content"] == ask.ASK_SYSTEM and b["messages"][1]["content"][0]["image_url"]["url"].endswith("UE5H")


def test_ask_model_low_unchanged(meta):
    msgs = []
    ctx = _Ctx()
    data = asyncio.run(ask.ask_model(ctx, _messages_client(msgs), "muse-spark-1.3", "q", b"png"))
    assert data["_api"] == "messages" and msgs[0]["output_config"] == {"effort": "low"} and msgs[0]["max_tokens"] == 2048
