# 006 Agent loop harness

Status: working (11 offline tests, live smoke on Spark; first handler on it is 008) | Meta model: Muse Spark 1.3 as the agent (any Messages-API model works; Claude runs through the same harness for the comparison).

## Purpose

Run a model as an agent so that the loop, not the model, carries the guarantees: deterministic geometry does
the measuring, the model only labels and decides; every result goes through a commit tool whose checks the
model cannot skip; the run parks for a human when the checks keep failing; every turn is persisted, charged
and logged. Spark alone scored 9/28 on the tap test; OpenCV plus Spark labels 28/28 at $0.008 a page. The
loop is how the second number reaches the product. Design note: `docs/agent-loop.md`.

## What exists

`api/app/agent/`:

- `tools.py`: `ToolBox`, `Tool`, `Refusal` (feedback, the model retries), `Stop` (the run is over), argument
  validation against the schema before dispatch (the error names the key, the expected type and what
  arrived). Any other exception is reported to the model once, re-raised if it repeats on the same tool.
- `loop.py`: `run_agent(system, tools, user_text | state + answer, persist, charge, client, model, max_turns,
  max_cost_usd, max_refusals=3)` and `AgentState` (full Messages-API history with assistant blocks stored as
  the SDK dumped them so Spark's `redacted_thinking` goes back verbatim; status; turn; cost and tokens;
  refusals per tool; question and payload; result; log; `scratch` for the tools' working data).
- `fake.py`: a scripted `httpx2` transport the Anthropic client accepts as `http_client`; `tool()`, `text()`,
  `truncated()`, `fail_at`.

Rules the loop enforces:

| Rule | Why |
|---|---|
| One tool call per turn (extra calls refused with a message) | the model reads each result before the next decision; Meta runs parallel calls by default |
| A tool returns a dict; `{"error": ...}` means retry, `{"status": ...}` means stop | one vocabulary for tools, logs and the information box |
| `Refusal` in a commit tool counts; `max_refusals` on the same tool → `needs_review` with the last feedback as the question | checks live where the model cannot skip them; a stuck run asks a human instead of burning budget |
| A successful tool call clears that tool's refusal streak | fixed 2026-10-28 (commit 981bfa6, test `test_success_resets_the_refusal_streak`); the bug was found while drafting 008, whose in-tool workaround was removed in 7f827d8 |
| Plain-text reply → nudge ("call exactly one tool"); truncated reply → "think less"; tool calls from a reply that hit `max_tokens` are refused, never run; `max_nudges` → `failed` | Spark sometimes narrates instead of acting |
| Last turn gets a nudge to finish or ask; turn or cost limit → `paused` | a paused run keeps its history |
| `persist(state)` after every turn; `charge(Charge)` after every model call | the job row is the truth; the shared cap sees every turn |
| Resume = previous state + the answer as the next user message; no answer → no model call | same reasoning continues |
| The loop never touches the database | handlers decide where state lives; tests run offline |

Tests: `api/tests/test_agent_loop.py`, 11 cases (happy path and persistence, refusal feedback, escalation and
resume, nudges, one call per turn, turn and cost limits, unknown tools and exceptions, truncated replies,
invalid arguments, refusal reset); `uv run pytest` (pytest + pytest-asyncio dev deps, `pythonpath=["."]`),
under a second. Live smoke `api/scripts/smoke_agent.py`: a three-page pretend score on Spark, 7 turns,
$0.006 to 0.007, 9 to 10 s, PASS (2026-10-27).

## How a handler plugs in

Create the toolbox with closures over `JobContext`, call `run_agent` with `persist=lambda s: jobs.result["agent"]
= s` and `charge=ctx.charge`, map the status: `done` → write records; `needs_review` →
`ctx.needs_review(question, payload)`; `paused` → requeue the same job with the state in its payload;
`failed` → raise so the worker retries or fails the score. The answer route (app thread, feature 011) queues
a job of the same kind with the same payload plus `answer` and `resume_from: <job id>`.

Spark settings: `max_tokens` at least 2048 per turn (1024 produced an empty reply after a
`redacted_thinking` block), `effort: low` for labelling turns, `high` only for the turn that resolves an
ambiguity. Prompt caching on Meta is automatic on the shared prefix, so the system prompt and tool
definitions stay byte-identical across turns.

First uses: 008 part cut (`read_header`, `list_pages`, `read_page`, `commit_system`, `finish`); the planned
Path B page-slicing tools (`list_pages`, `read_page`, `set_page_order`, `assign_parts`, `reread`, `ask_admin`,
`finish`); 013 voice note (`score_facts`, `propose`, `finish`).

## Agentic memory rule (CK, 2026-10-30)

Work and human answers within a book are remembered and reused: a handler never asks the admin again what an
earlier read or an earlier answer in the same book already settled. The loop's history is not the memory (it ends
with the job and no check reads it); a handler keeps what it learned on the book, with its provenance (human or
model, which page, which job), consults it before it asks, passes it to the model as context for later pages, and
lets a human answer outrank any model read. A genuinely new fact still asks. First use: 008's label memory
(`scores.label_memory`, `app/librarian/label_memory.py`): a printed staff label ("Klav.") is the part the header or
the admin said it is, on every later page and in every later cut of the book.

## Where it came from

Meta's Agents 101 workshop (`meta-models/legal-agent-workshop`, read 2026-10-27, clone in the scratchpad
only): OpenAI SDK Responses API against `api.meta.ai/v1`, flat function schemas, `parallel_tool_calls=False`,
`store=False`, one tool per turn, plain-text replies nudged back to a tool call; checks inside the commit
tool (refuse with feedback, `needs_input` after 3 refusals); ground truth as a JSON file the agent never
sees, scored by code; tests fake the model at the httpx transport; Files API (`purpose="user_data"`) for
PDFs; SAM 3.1 through `responses.create`; no cost cap at all. Borrowed: commit-tool checks, the
refuse-then-escalate rule, resume as the next user message, the plain-text and last-turn nudges, the
transport-level fake, per-fixture ground-truth JSON. Not borrowed: file-based state, a synchronous client,
no cost cap, fail-open judges, the OpenAI Responses API (Messages-style `tools=[...]` works on Meta through
the Anthropic SDK: `stop_reason: tool_use` with correct `input`, `tool_result` round trip accepted,
`tool_choice: any`; one client keeps the Claude comparison identical).

pi (`earendil-works/pi`, reviewed by a subagent): adopted truncation refusal, schema validation, errors as
tool results, refusal counter reset on success. Rejected codemode (the verify step needs the model to look at
crops), a task per turn, the replicated JSON-op documents and watches (Supabase Realtime on the job row is
the watch), mid-transcript system messages. To add when the loop meets long scores: compaction, never
cutting at a tool result, keeping the recent ~20k tokens.

## Next steps

1. Compaction for long scores.
2. Run Claude through the same harness on the same pages for the published comparison (000 positioning).
