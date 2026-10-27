# The librarian contract

How the app thread and the intelligence thread meet. Written 2026-10-27 after the schema (item 1) and the
grounding verdict (item 0). The two threads share the database and this page; they do not share code paths.

## Who owns what

| App thread (`main`) | Intelligence thread (branch `librarian`, merged into `main` by CK, no PRs) |
|---|---|
| `supabase/` migrations, `api/app/{auth,spend,db,llm,worker,settings}.py`, `api/app/routes/`, `web/`, deployment | `api/app/librarian/` (job handlers, geometry, prompts, agent loop), `api/experiments/`, `api/fixtures/` additions, `docs/acceptance/librarian-pipeline.md` |
| The `jobs` table and the worker that claims them | The function that runs for each job kind |
| The intake UI, the processing badge, the information box counts | The numbers behind them |

A handler that needs a new column asks the app thread, which adds a migration. A screen that needs a new
number asks the intelligence thread, which adds it to `interpretations.summary`.

## Jobs

A job is a row in `jobs`. The browser never writes one; the API does, from a route, with `created_by` set to the
caller. The worker (`api/app/worker.py`, inside the API process) claims one at a time through `claim_job()`
(SKIP LOCKED, so several API processes are safe), looks up the handler for `kind`, runs it, and writes the
outcome. A handler that raises is retried with backoff until `max_attempts` (3), then the job is `failed` with
the error text. Progress is a float 0 to 1 and a short note, written to the row as the handler reports it; the
browser subscribes to the row through Realtime and the library cover shows the meter.

```python
# api/app/librarian/__init__.py
@handler("process_pages")
async def process_pages(job: Job, ctx: JobContext) -> dict: ...
```

`JobContext` gives a handler everything it may touch:

| | |
|---|---|
| `ctx.db` | the service-role Supabase client (bypasses RLS: the handler is responsible for writing only its score's rows) |
| `await ctx.progress(0.4, "Read page 3 of 7")` | updates `jobs.progress` and `jobs.result.note` |
| `await ctx.complete(prompt, system=, effort=, image_png_b64=)` | `app.llm.complete` plus the charge, on the job's user, tagged with the job id |
| `ctx.charge(Charge(...))` | records a non-LLM model call (SAM image, Voice Transcribe seconds) |
| `ctx.storage_download(path)` / `ctx.storage_upload(path, bytes, content_type)` | the `scores` bucket |
| `ctx.needs_review(question: str, payload: dict)` | parks the job: `interpretations.status = 'needs_review'`, `jobs.result.question`, job `done`. The admin answers through a route in the app thread, which queues a follow-up job of the same kind with `payload.answer` set. |

The return value is stored in `jobs.result`. Budget is checked by the route that creates the job, not by the
handler; `ctx.complete` and `ctx.charge` always record cost, and the shared cap in `spend` is the hard stop
that `charge_usage` enforces at the next check.

### Job kinds

| kind | owner | payload | writes | model(s) |
|---|---|---|---|---|
| `import_musicxml` | app | `{score_id, source_id}` | `interpretations` (engine `musicxml`), `parts`, `measures`, `scores` facts and `ready` | none (music21) |
| `process_pages` | intelligence | `{score_id, source_id, answer?}` | `interpretations` (engine `opencv-geometry+spark-labels`), `measures`, `measure_placements`, `parts`, `scores` facts, `processing` → `ready` or `failed` | Spark (labels, parts, difficulty, brief), SAM 3.1 optional (system crops), OMR optional later |
| `transcribe_voice` | intelligence | `{score_id, session_id, audio_path, author_id}` | `annotations` with `status = 'proposed'`, `audience`, `measure_from/to` by stable id, `body` = transcript | Voice Transcribe, then Spark |
| `brief` | intelligence | `{score_id}` | `scores.brief`, `parts.difficulty` | Spark |

Each handler's docstring names the Meta model it uses; the README's model table is generated from that.

## Records a page handler writes

Straight from `api/experiments/grounding/README.md` §"Proposed records", now in the schema:

- `interpretations`: one row per run, `version` = previous max + 1 for that score, `engine`, `status`, `params` (dpi, skew per page, thresholds), `summary`, `cost_usd`, `latency_ms`. On success set `scores.current_interpretation_id` to it.
- `interpretations.summary` is what the information box reads: `{pages, systems, measures, first_measure, title, composer, flagged: {pages_unreadable, bars_doubtful}, log: ["Read 14 pages", "Re-read bar 112 twice", ...]}`. Counts only; never percentages.
- `measures`: upsert on `(score_id, number, part)`; `part` null means all parts. **Never delete** a measure row. A measure the new run did not find keeps its row and gets a placement with `confidence = 'low'`, `flag = 'not found in v{n}'`.
- `measure_placements`: one per (interpretation, measure): `page` (1-based into `sources.page_order`), `system`, `box` as fractions of the page image `{x0, y0, x1, y1}`, `confidence` high|medium|low from geometry (barline width, coverage, header-zone merges) with Spark as a second opinion, `flag` text when not high, `rehearsal_mark`.
- `parts`: `name` as printed ("Violin II", "Piano I"), `position`, `difficulty` 1 to 5 (the UI shows one word), `storage_path` of a per-part file when one exists.
- `scores`: `status`, `progress`, `pages`, `bars`, `key_sig`, `meter`, `tempo_bpm`, `duration_sec`, `failure_reason`.

Annotations point at `measures.id`, so a reprocess keeps every marking. Placements are resolved per
`current_interpretation_id` by the client.

## Pages and files

`sources.storage_paths` lists the uploaded files under `scores/{score_id}/` in the private `scores` bucket; `kind`
is `pdf`, `images` or `musicxml`. For pages, the app thread rasterises in the browser (pdf.js) and uploads
`scores/{score_id}/pages/{n}.png`; `page_order` is the committed reading order (1-based indexes into the upload
set). A handler reads pages in `page_order` and reports page numbers in that order.

## Money and models

Every model call goes through `ctx.complete` or `ctx.charge`, on the job's `created_by` user, so the per-user
counter and the shared cap see it. Prices live in `app/llm.py` (`PRICES`) and in the handler for per-image /
per-second models. The intelligence thread tests against `api/fixtures/` and the local Docker stack
(`supabase start`, `api/scripts/smoke_local.py` creates the demo users), never against the hosted project.

## Testing a handler without the app

```bash
cd api && uv run -m app.librarian.run process_pages --score <id>   # runs one handler against the local stack, prints the result
```

(`app/librarian/run.py` is the intelligence thread's; it should construct a `JobContext` from `app.worker.context_for`.)
