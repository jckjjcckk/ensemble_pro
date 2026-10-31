"""The part cut's speed pass (2026-10-30): pages read ahead of the agent in two waves, the label guard that sends a
doubtful minimal read back to low, and the recheck skipped where the book's memory and the page's proposal agree.
The fake here answers by what is asked (agent turns in order, label calls by page), so calls made ahead of the agent
land where they belong."""
from __future__ import annotations

import json
import re

import httpx2 as httpx
import pytest
from anthropic import AsyncAnthropic

import app.librarian.part_cut as pc
from app.agent.fake import text, tool
from app.librarian.part_cut import label_guard, part_cut

from tests.test_part_cut import HEADER, KLAV_HEADER, RECHECK_PIANO, commit, world


class RoutingTransport(httpx.AsyncBaseTransport):
    """Agent turns pop `turns` in order; a label call answers `labels[page]` (a list: one reply per call of that page);
    a recheck answers `recheck`; the header call answers `header`."""

    def __init__(self, turns, labels, header, recheck=RECHECK_PIANO):
        self.turns, self.labels, self.header, self.recheck = list(turns), {k: list(v) for k, v in labels.items()}, header, recheck
        self.calls: list[tuple[str, int | None, dict]] = []

    async def handle_async_request(self, request):
        body = json.loads(request.content)
        prompt = body["messages"][0]["content"][-1].get("text", "") if isinstance(body["messages"][0]["content"], list) else ""
        if body.get("system") == pc.SYSTEM:
            kind, page, block = "turn", None, self.turns.pop(0)
        elif prompt.startswith("This image is a block of staves"):
            kind, page, block = "recheck", None, self.recheck
        elif "For each system give" in prompt:
            page = int(re.match(r"Page (\d+)", prompt).group(1))
            kind, block = "label", self.labels[page].pop(0)
        else:
            kind, page, block = "header", None, self.header
        self.calls.append((kind, page, body))
        stop = "tool_use" if block["type"] == "tool_use" else "end_turn"
        return httpx.Response(200, json={"id": "m", "type": "message", "role": "assistant", "model": "fake-model", "content": [block],
                                         "stop_reason": stop, "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 5}})


def routing_client(turns, labels, header=HEADER, recheck=RECHECK_PIANO):
    t = RoutingTransport(turns, labels, header, recheck)
    return AsyncAnthropic(api_key="fake", base_url="http://fake", max_retries=0, http_client=httpx.AsyncClient(transport=t)), t


def label(wanted=(4, 5), margins=()):
    return text(json.dumps({"systems": [{"index": 1, "wanted_staves": list(wanted), "status": "playing",
                                         "margin_labels": [{"text": t, "staves": s} for t, s in margins]}], "confidence": "high"}))


@pytest.mark.asyncio
async def test_every_page_is_read_ahead_once_the_header_is_known():
    turns = [tool("read_header", {})]
    for n in (1, 2, 3):
        turns += [tool("read_page", {"page": n}), commit(n, [4, 5])]
    turns += [tool("finish", {})]
    client, t = routing_client(turns, {n: [label()] for n in (1, 2, 3)})
    job, ctx, db = world(3)
    out = await part_cut(job, ctx, client=client)
    assert out["systems_cut"] == 3 and out["questions"] == 0
    kinds = [k for k, _, _ in t.calls]
    # the three label calls go out once the header is back, beside the agent's next turn: all three before the turn
    # after it (the one that commits page 1), so pages 2 and 3 are read long before the agent asks for them
    assert kinds[:3] == ["turn", "header", "turn"] and kinds[3:6] == ["label", "label", "label"]
    assert sorted(p for k, p, _ in t.calls if k == "label") == [1, 2, 3]          # each page read once
    assert sorted(ctx.result["agent"]["scratch"]["prereads"]) == ["1", "2", "3"]


@pytest.mark.asyncio
async def test_a_page_the_agent_never_reaches_is_not_left_running():
    turns = [tool("read_header", {}), tool("read_page", {"page": 1}), commit(1, [4]), commit(1, [4]), commit(1, [4])]
    client, t = routing_client(turns, {n: [label()] for n in (1, 2)})
    job, ctx, db = world(2)
    out = await part_cut(job, ctx, client=client)
    assert out["question_payload"]["kind"] == "choose_staves"                       # parked on page 1; page 2 was read ahead


def test_label_guard_names_duplicates_shared_staves_and_family_names():
    header = {"instruments": [{"label": "Horn I, II"}, {"label": "Horn III, IV"}, {"label": "Piano"}]}
    ok = {"systems": [{"index": 1, "wanted_staves": [4, 5], "margin_labels": [{"text": "Pno.", "staves": [4, 5]}, {"text": "Cor. I", "staves": [1]}]}]}
    assert label_guard(ok, ["Piano"], header) == []
    dup = {"systems": [{"index": 1, "wanted_staves": [4, 5], "margin_labels": [{"text": "Hr.", "staves": [1]}, {"text": "Hr.", "staves": [2]}]}]}
    assert "read on staves [1] and [2]" in label_guard(dup, ["Piano"], header)[0]
    fam = {"systems": [{"index": 1, "wanted_staves": [1], "margin_labels": [{"text": "Horn", "staves": [1]}]}]}
    assert "family name" in label_guard(fam, ["Horn I, II"], header)[0]
    shared = {"systems": [{"index": 1, "wanted": [{"instrument": "Soprano", "staves": [3]}, {"instrument": "Alto", "staves": [3]}]}]}
    assert "staff 3 given to both" in label_guard(shared, ["Soprano", "Alto"], None)[0]


@pytest.mark.asyncio
async def test_a_doubted_minimal_label_read_is_read_again_at_low(monkeypatch):
    monkeypatch.setattr(pc, "LABEL_EFFORT", "minimal")
    doubted = label(margins=[("Fl.", [1]), ("Fl.", [2])])                 # one label on two staves: the guard doubts it
    turns = [tool("read_header", {}), tool("read_page", {"page": 1}), commit(1, [4, 5]), tool("finish", {})]
    client, t = routing_client(turns, {1: [doubted, label()]})
    job, ctx, db = world(1)
    out = await part_cut(job, ctx, client=client)
    assert out["systems_cut"] == 1
    assert [p for k, p, _ in t.calls if k == "label"] == [1, 1]                     # read twice: minimal, then low
    sc = ctx.result["agent"]["scratch"]
    assert sc["label_fallbacks"][0]["page"] == 1 and "'Fl.'" in sc["label_fallbacks"][0]["why"][0]
    assert sc["prereads"]["1"]["_effort"] == "low"


@pytest.mark.asyncio
async def test_a_settled_label_skips_the_recheck_but_a_label_filled_block_still_asks():
    """Page 1: the proposal and the known label "Klavier" agree on [4, 5]: no recheck. Page 2: the proposal names no
    staves and only the label puts the piano on [4, 5] (source model, not agreed): the recheck runs."""
    turns = [tool("read_header", {}), tool("read_page", {"page": 1}), commit(1, [4, 5]),
             tool("read_page", {"page": 2}), commit(2, [4, 5]), tool("finish", {})]
    labels = {1: [label(margins=[("Klavier", [4, 5])])], 2: [label(wanted=(), margins=[("Klav.", [4, 5])])]}
    client, t = routing_client(turns, labels, header=KLAV_HEADER)
    job, ctx, db = world(2)
    out = await part_cut(job, ctx, client=client)
    assert out["systems_cut"] == 2
    sc = ctx.result["agent"]["scratch"]
    assert sc["commits"]["1:1"]["rechecks"][0]["verdict"] == "remembered"
    assert sc["commits"]["2:1"]["rechecks"][0]["verdict"] == "yes"
    assert sum(1 for k, _, _ in t.calls if k == "recheck") == 1
