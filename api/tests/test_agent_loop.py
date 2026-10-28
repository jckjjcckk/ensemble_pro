"""The agent loop against a scripted model: no network, no database."""
from __future__ import annotations

import json

import pytest

from app.agent import AgentState, Refusal, Stop, ToolBox, run_agent
from app.agent.fake import fake_client, text, tool, truncated

SYSTEM = "You slice pages."


def box(staves: int = 2) -> ToolBox:
    b = ToolBox()

    @b.tool("read_page", "Read a page.", {"properties": {"page": {"type": "integer"}}, "required": ["page"]})
    def read_page(args, state):
        state.scratch["read"] = state.scratch.get("read", []) + [args["page"]]
        return {"page": args["page"], "staves": staves}

    @b.tool("commit_parts", "Commit the parts on a page.", {"properties": {"page": {"type": "integer"}, "parts": {"type": "array", "items": {"type": "string"}}}, "required": ["page", "parts"]}, commit=True)
    def commit_parts(args, state):
        if len(args["parts"]) != staves:
            raise Refusal(f"page {args['page']} has {staves} staves but you named {len(args['parts'])} parts")
        raise Stop("done", parts=args["parts"])

    return b


def last_results(body: dict) -> list[dict]:
    content = body["messages"][-1]["content"]
    return [json.loads(c["content"]) for c in content if c.get("type") == "tool_result"]


@pytest.mark.asyncio
async def test_happy_path_persists_every_turn_and_charges():
    client, t = fake_client([tool("read_page", {"page": 1}), tool("commit_parts", {"page": 1, "parts": ["Violin", "Cello"]})])
    saved, charged = [], []
    st = await run_agent(system=SYSTEM, tools=box(), user_text="go", client=client, persist=saved.append, charge=charged.append)
    assert st.status == "done" and st.result == {"parts": ["Violin", "Cello"]}
    assert st.turn == 2 and len(saved) == 2 and len(charged) == 2
    assert st.scratch["read"] == [1]
    assert last_results(t.calls[1]) == [{"page": 1, "staves": 2}]      # the model saw the tool result
    assert t.calls[0]["tools"][0]["name"] == "read_page" and t.calls[0]["tools"][0]["input_schema"]["additionalProperties"] is False
    assert st.cost_usd > 0 and st.input_tokens == 200


@pytest.mark.asyncio
async def test_commit_refusal_is_feedback_then_accepted():
    client, t = fake_client([tool("commit_parts", {"page": 1, "parts": ["Violin"]}), tool("commit_parts", {"page": 1, "parts": ["Violin", "Cello"]})])
    st = await run_agent(system=SYSTEM, tools=box(), user_text="go", client=client)
    assert st.status == "done"
    fb = last_results(t.calls[1])[0]
    assert "2 staves" in fb["error"] and fb["refusals"] == 1 and fb["max_refusals"] == 3


@pytest.mark.asyncio
async def test_escalates_after_max_refusals_then_resumes_with_answer():
    bad = tool("commit_parts", {"page": 1, "parts": ["Violin"]})
    client, t = fake_client([bad, bad, bad, tool("commit_parts", {"page": 1, "parts": ["Violin", "Cello"]})])
    st = await run_agent(system=SYSTEM, tools=box(), user_text="go", client=client, max_refusals=3)
    assert st.status == "needs_review" and "refused 3 times" in st.question
    assert st.question_payload["tool"] == "commit_parts"
    assert json.loads(st.messages[-1]["content"][0]["content"])["status"] == "needs_review"
    # nothing changed: no model call
    again = await run_agent(system=SYSTEM, tools=box(), state=AgentState.from_dict(st.to_dict()), client=client)
    assert again.status == "needs_review" and len(t.calls) == 3
    # the answer becomes the next user message and the run goes on with the same history
    st2 = await run_agent(system=SYSTEM, tools=box(), state=AgentState.from_dict(st.to_dict()), answer="It is Violin and Cello.", client=client)
    assert st2.status == "done" and st2.turn == 4
    body = t.calls[3]
    assert body["messages"][-1] == {"role": "user", "content": "It is Violin and Cello."}
    assert len(body["messages"]) == 1 + 3 * 2 + 1                    # user, 3×(assistant, tool_result), answer


@pytest.mark.asyncio
async def test_plain_text_is_nudged_then_fails():
    client, t = fake_client([text("I think it is a quartet."), tool("read_page", {"page": 1}), text("a"), text("b"), text("c"), text("d")])
    st = await run_agent(system=SYSTEM, tools=box(), user_text="go", client=client, max_nudges=3, max_turns=10)
    assert st.status == "failed" and "prose" in st.result["error"]
    assert t.calls[1]["messages"][-1]["content"].startswith("Plain text is not accepted")
    assert st.nudges == 4 and st.turn == 6


@pytest.mark.asyncio
async def test_one_tool_per_turn_refuses_the_second_call():
    client, t = fake_client([[tool("read_page", {"page": 1}), tool("read_page", {"page": 2})], tool("commit_parts", {"page": 1, "parts": ["a", "b"]})])
    st = await run_agent(system=SYSTEM, tools=box(), user_text="go", client=client)
    r = last_results(t.calls[1])
    assert r[0] == {"page": 1, "staves": 2} and "One tool call per turn" in r[1]["error"]
    assert st.status == "done"


@pytest.mark.asyncio
async def test_turn_limit_pauses_with_last_turn_nudge():
    client, t = fake_client([tool("read_page", {"page": n}) for n in range(1, 5)])
    st = await run_agent(system=SYSTEM, tools=box(), user_text="go", client=client, max_turns=3)
    assert st.status == "paused" and st.turn == 3
    last = t.calls[2]["messages"][-1]["content"]
    assert last[-1]["type"] == "text" and "last turn" in last[-1]["text"]
    assert st.messages[-1]["content"][-1]["type"] == "tool_result"   # the nudge is not kept in the history


@pytest.mark.asyncio
async def test_unknown_tool_and_tool_exception_are_reported_not_fatal():
    b = box()

    @b.tool("boom", "Fails.", {"properties": {}})
    def boom(args):
        raise ValueError("kaput")

    client, t = fake_client([tool("nope", {}), tool("boom", {}), tool("commit_parts", {"page": 1, "parts": ["a", "b"]})])
    st = await run_agent(system=SYSTEM, tools=b, user_text="go", client=client)
    assert "Unknown tool" in last_results(t.calls[1])[0]["error"]
    assert last_results(t.calls[2])[0]["error"] == "ValueError: kaput"
    assert st.status == "done"


@pytest.mark.asyncio
async def test_cost_limit_pauses():
    client, _ = fake_client([tool("read_page", {"page": n}) for n in range(1, 9)])
    st = await run_agent(system=SYSTEM, tools=box(), user_text="go", client=client, model="claude-opus-5-5", max_cost_usd=0.0015)
    assert st.status == "paused" and st.turn == 2 and "cost" in st.log[-1]


@pytest.mark.asyncio
async def test_calls_from_a_truncated_reply_are_refused_not_run():
    client, t = fake_client([truncated(tool("commit_parts", {"page": 1, "parts": ["a", "b"]})), tool("commit_parts", {"page": 1, "parts": ["a", "b"]})])
    st = await run_agent(system=SYSTEM, tools=box(), user_text="go", client=client)
    assert st.status == "done" and st.turn == 2
    assert "cut off" in last_results(t.calls[1])[0]["error"]           # the first commit never ran


@pytest.mark.asyncio
async def test_invalid_arguments_are_reported_before_the_tool_runs():
    client, t = fake_client([tool("read_page", {}), tool("read_page", {"page": "one"}), tool("read_page", {"page": 1, "extra": 1}),
                             tool("commit_parts", {"page": 1, "parts": ["a", "b"]})])
    st = await run_agent(system=SYSTEM, tools=box(), user_text="go", client=client)
    assert "missing argument(s) page" in last_results(t.calls[1])[0]["error"]
    assert "must be integer" in last_results(t.calls[2])[0]["error"]
    assert "unknown argument(s) extra" in last_results(t.calls[3])[0]["error"]
    assert st.scratch.get("read") is None and st.status == "done"


@pytest.mark.asyncio
async def test_success_resets_the_refusal_streak():
    """Two refusals, a good commit on another page, then two more refusals must not escalate (3 is the cap)."""
    b = ToolBox()

    @b.tool("commit_page", "Commit a page.", {"properties": {"page": {"type": "integer"}, "ok": {"type": "boolean"}}, "required": ["page", "ok"]}, commit=True)
    def commit_page(args, state):
        if not args["ok"]:
            raise Refusal(f"page {args['page']} is wrong")
        state.scratch["done"] = state.scratch.get("done", 0) + 1
        return {"committed": args["page"]}

    @b.tool("finish", "Finish.", {"properties": {}}, commit=True)
    def finish(args, state):
        raise Stop("done", pages=state.scratch.get("done", 0))

    bad, good = {"ok": False}, {"ok": True}
    client, t = fake_client([
        tool("commit_page", {"page": 1, **bad}), tool("commit_page", {"page": 1, **bad}),
        tool("commit_page", {"page": 1, **good}),
        tool("commit_page", {"page": 2, **bad}), tool("commit_page", {"page": 2, **bad}),
        tool("commit_page", {"page": 2, **good}), tool("finish", {}),
    ])
    st = await run_agent(system=SYSTEM, tools=b, user_text="go", client=client, max_refusals=3)
    assert st.status == "done" and st.result["pages"] == 2
    assert last_results(t.calls[4])[0]["refusals"] == 1  # the streak restarted after the good commit on page 1
