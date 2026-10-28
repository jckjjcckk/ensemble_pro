# The agent loop

How Folio runs a model as an agent: `api/app/agent/`. Built 2026-10-27 after reading Meta's Agents 101
workshop (`meta-models/legal-agent-workshop`) and the pi agent framework (`earendil-works/pi`), and after
verifying that Messages-style tool use works on Muse Spark through the Anthropic SDK (tool_use blocks,
tool_result round trips, `tool_choice: any`).

## The claim it exists to make

A mid-size model becomes trustworthy on a hard task when the loop, not the model, carries the guarantees:
deterministic geometry does the measuring, the model only labels and decides; every result goes through a
commit tool whose checks the model cannot skip; the run parks for a human when the checks keep failing; and
every turn is persisted, charged and logged. Spark on the grounding tap test alone scored 9/28; OpenCV plus
Spark labels scored 28/28 at $0.008 a page. The loop is how the second number reaches the product.

## Contract

```python
from app.agent import ToolBox, Refusal, Stop, run_agent, AgentState

box = ToolBox()

@box.tool("read_page", "Read one page.", {"properties": {"page": {"type": "integer"}}, "required": ["page"]})
def read_page(args, state): ...                    # returns a dict the model reads

@box.tool("commit_parts", "...", {...}, commit=True)
def commit_parts(args, state):
    if bad: raise Refusal("page 3 has 3 staves but you named 2 parts")   # feedback, model retries
    raise Stop("done", parts=args["parts"])                             # the run is over

state = await run_agent(system=..., tools=box, user_text="...", persist=save, charge=ctx.charge,
                        max_turns=24, max_cost_usd=1.0, max_refusals=3)
# later, when the admin answers:
state = await run_agent(system=..., tools=box, state=AgentState.from_dict(saved), answer="Violin, Viola, Cello")
```

Rules the loop enforces:

| Rule | Why |
|---|---|
| One tool call per turn (extra calls are refused with a message) | The model reads each result before the next decision; Meta runs parallel calls by default otherwise. |
| A tool returns a dict; `{"error": ...}` means retry, `{"status": ...}` means stop | One vocabulary for tools, logs and the information box. |
| `Refusal` inside a commit tool counts; `max_refusals` on the same tool → `needs_review` with the last feedback as the question | Checks live where the model cannot skip them, and a stuck run asks a human instead of burning budget. |
| Plain-text reply → nudge ("call exactly one tool"); truncated reply → "think less"; `max_nudges` → `failed` | Spark sometimes narrates instead of acting; the nudge costs one short turn. |
| Last turn gets a nudge to finish or ask; turn or cost limit → `paused` | A paused run keeps its history and can be continued. |
| `persist(state)` after every turn; `charge(Charge)` after every model call | The job row is the truth; the shared spend cap sees every turn. |
| Resume = previous state + the answer as the next user message; no answer → no model call | Same reasoning continues; the workshop's `progress.resume` rule. |
| The loop never touches the database | Handlers decide where state lives; tests run on a scripted transport. |

State (`AgentState`): messages (full Messages-API history, assistant blocks stored as the SDK dumped them, so
Spark's `redacted_thinking` blocks go back verbatim), status, turn, cost and tokens, refusals per tool,
question and payload, result, log lines, and `scratch` for the tools' working data.

## Where it plugs into the jobs

- A handler creates the toolbox with closures over `JobContext`, calls `run_agent` with
  `persist=lambda s: jobs.result["agent"] = s` and `charge=ctx.charge`, then maps the status: `done` →
  write records and finish; `needs_review` → `ctx.needs_review(question, payload)`; `paused` → requeue the
  same job with the state in its payload; `failed` → raise so the worker retries or fails the score.
- The answer route (app thread) queues a job of the same kind with the same payload plus `answer` and
  `resume_from: <job id>`; the handler loads `result["agent"]` from that job and passes `answer`.
- Spark settings that matter: `max_tokens` ≥ 2048 per turn (reasoning counts against it; 1024 produced an
  empty reply after a `redacted_thinking` block), `effort: low` for labelling turns, `high` only for the
  turn that resolves an ambiguity. Prompt caching on Meta is automatic on the shared prefix, so the system
  prompt and tool definitions should stay byte-identical across turns (they do).

## First uses

**Path B page slicing (item 6).** Tools: `list_pages` (order, size, first measure from labels), `read_page`
(geometry + Spark labels, cached per page), `set_page_order` (checks measure continuity across the order),
`assign_parts(page, parts top to bottom)` (commit: part count must match staff groups, names must be known
or newly declared), `reread(page, effort)` (second pass on a doubtful page), `ask_admin(question, options)`,
`finish` (commit: every page assigned, numbering continuous, else refuse with the gap). The handler then
writes interpretations, measures, placements and parts exactly as `process_pages` does today. Extraction
(crop a part's staff band from each system and stitch a per-part PDF) is a tool only for scores with many
staves; small scores distribute the original page with the part's band highlighted.

**Part cut (`api/app/librarian/part_cut.py`, 2026-10-28).** The first handler on the loop. Payload
`{score_id, instrument, pages?, interpretation_id?}`. Tools: `read_header` (Spark reads page 1: instruments, staves
each, clefs, key, time), `list_pages`, `read_page` (OpenCV staves/systems/barlines from `cut.py`, then Spark labels
the numbered overlay: which staves are the instrument's per system), `commit_system(page, system, staves | "absent")`
(commit: staves exist in the system, count matches the header, crop verify, Spark re-reads the crop alone and must
name the same instrument), `finish` (commit: refuses while a page or system is uncommitted). Three refusals park
the run with the typed question `{kind: "choose_staves", page, system, proposal, last_attempt, feedback, staff_boxes,
image_key, allowed, answer_format}`; the answer `{staves: [...] | "absent"}` is applied as a successful commit and
the run resumes (`payload.resume_from` = the job that asked). State lives in `jobs.result.agent`. Outputs: cleaned
crops at `{score_id}/parts/{slug}/p{page:03}-s{k}.png`, a `sources` row of kind `part_images` (migration
`20261028090000_part_images_source.sql`, not applied yet), an interpretation (engine `part-cut-agent`) whose summary
holds the counts and the log, with the page-intake placements copied under it (same measure ids). Tests:
`api/tests/test_part_cut.py` on PIL-drawn pages.

**Voice note → proposed annotations (item 7).** Tools: `score_facts` (part list, measure range, rehearsal
marks), `propose(kind, measure_from, measure_to, audience, text, quote)` (commit: `quote` must be a verbatim
span of the transcript, bars inside the range, audience a known part or `ensemble`, else refuse),
`finish`. Scored against `api/fixtures/voice/script.csv`.

## Tests

`api/tests/test_agent_loop.py`: eight cases on `app/agent/fake.py`, a scripted `httpx2` transport the
Anthropic client accepts as `http_client`, so the loop runs offline in under a second. Covers the happy
path and persistence, refusal feedback, escalation and resume, nudges, one-call-per-turn, turn and cost
limits, unknown tools and tool exceptions. `api/scripts/smoke_agent.py` runs a three-page pretend score
against the live provider (Spark: 7 turns, $0.006, 10 s on 2026-10-27).

## Borrowed and not borrowed

From the workshop: checks inside the commit tool, the refuse-then-escalate rule, resume as the next user
message, the plain-text nudge, the last-turn nudge, the transport-level fake. Not borrowed: file-based
state, a synchronous client, no cost cap, fail-open judges, the OpenAI Responses API (our Messages client
already works on Meta, and one client keeps the Claude comparison runs identical).

From pi (`earendil-works/pi`, read 2026-10-27): tool calls from a reply that hit `max_tokens` are never
run, they are refused as possibly truncated and the model re-issues them; arguments are validated against
the schema before dispatch and the error names the key, the expected type and what arrived; errors are
tool results, never exceptions out of the loop; the refusal counter resets when the commit succeeds (as
their crash `restarts` counter resets on a state change). Not borrowed from pi: a task per turn and per
tool call, the replicated JSON-op documents and watches (Supabase Realtime on the job row is our watch),
codemode (the model writing scripts that call tools; our verify step needs the model to look at crops,
which codemode keeps out of context), mid-transcript system messages. One thing pi does that we should add
when the loop meets long scores: compaction, never cutting at a tool result, keeping the recent ~20k tokens.
