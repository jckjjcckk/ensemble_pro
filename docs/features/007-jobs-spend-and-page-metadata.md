# 007 Jobs, spend tracking and per-page metadata

Status: working (jobs worker and the spend ledger); idea (a per-page metadata record) | Meta model: none (the ledger prices every Spark, SAM and Voice call).

## Purpose

Durable jobs with the database as the queue, a hard shared spend cap that every model call passes through,
and a record of what each page cost and what the models said about it.

## Jobs

- `jobs` table (kind, status queued|running|done|failed, payload, progress, attempts, max_attempts 3, error,
  started/finished, result, created_by, score_id); `claim_job()` with SKIP LOCKED.
- `api/app/worker.py` runs inside the API process (`WORKER=0` disables): polls every 2 s, claims one job,
  runs the handler registered for `kind` (`api/app/librarian/__init__.py`, `@handler`), retries with backoff
  to `max_attempts`, marks the score failed on the last failure, requeues jobs left `running` by a dead
  process after 15 min. `context_for(job_id)` builds a `JobContext`.
- `JobContext`: `ctx.db` (service role; the handler writes only its score's rows), `await ctx.progress(0.4,
  "Read page 3 of 7")`, `await ctx.complete(prompt, system=, effort=, image_png_b64=)` (LLM call plus the
  charge, on the job's user, tagged with the job id), `ctx.charge(Charge(...))` for non-LLM calls (SAM image,
  Voice seconds), `ctx.storage_download(key)` / `ctx.storage_upload(key, bytes, content_type)`,
  `ctx.needs_review(question, payload)` (parks: `interpretations.status = 'needs_review'`,
  `jobs.result.question`, job `done`). The return value is stored in `jobs.result`.
- Job kinds (`docs/librarian-contract.md`): `import_musicxml` (app, 002), `process_pages` (intelligence, 004),
  `part_cut` (008), `transcribe_voice` (013, planned), `brief` (planned: `scores.brief`, `parts.difficulty`,
  Spark). Each handler's docstring names its Meta model; the README's model table is generated from that.
- Ownership: the app thread owns `supabase/` migrations, `auth, spend, db, llm, worker, settings`, `routes/`,
  `web/`, deployment, the `jobs` table and the worker; the intelligence thread owns `api/app/librarian/`,
  `api/experiments/`, `api/fixtures/` additions and the acceptance file. A handler that needs a column asks
  the app thread. The intelligence thread tests against fixtures and the local Docker stack, never the
  hosted project.
- Local run of one handler: `cd api && uv run -m app.librarian.run <kind> --score <id>`.

### Concurrency (2026-10-30, speed pass)

`WORKER_CONCURRENCY` (default 2): the loop claims again while a slot is free and waits the 2 s poll or the end of a
job; on stop the jobs in hand finish; 1 is the old loop. `claim_job`'s SKIP LOCKED keeps concurrent claims apart. Local
stack, two queued 3-second jobs of a test-only kind (`experiments/speed_pass/worker_local.py`): concurrency 2 finished
both in 3.1 s, started 2 ms apart, in 4 of 5 runs; the first run after a cold start ran them one after the other (6.2 s),
not explained. Concurrency 1: 6.1-6.2 s. The handlers' own sync database calls still block the loop while they run.

## Spend

- `spend` table: one row, `cap_usd` 60, service role only. `charge_usage()` runs in one transaction with one
  row lock, so concurrent requests cannot overspend. The per-user counter (`profiles.budget_usd` default 10,
  `spent_usd`) is reporting only; the shared cap is the hard limit (external review 2026-10-26).
- `api/app/spend.py`: `BudgetedUser` answers 402 when either is spent; `charge()` after the call writes a
  `usage_events` row (provider, model, kind, cost, tokens, job id). Budget is checked by the route that
  creates a job, not by the handler; `ctx.complete` and `ctx.charge` always record cost.
- `api/app/llm.py` `PRICES` per 1M tokens: claude-opus-5-5 4/20, claude-sonnet-5-5 2/10, claude-haiku-5-5
  0.10/0.50, muse-spark-1.3 1.25/4.25, muse-spark-1.3-contributor 0.10/0.20; unknown models priced like Opus
  5 (5/25). Per-image and per-second prices live in the handler.
- Settings (`api/.env`): `LLM_PROVIDER` anthropic|meta, `ANTHROPIC_MODEL` claude-opus-5-5, `META_MODEL`
  muse-spark-1.3, `PER_USER_BUDGET_USD` 10.
- Credits: Meta $150 claimed; Anthropic ~$100 for experiments. Teammates must claim their own $150.
- Experiment ledgers (outside the database): `spend.json` per output folder with a cap ($1.50 per piano-cut
  folder, $2.00 for the Audiveris and homr studies, $1.00 for the Goldberg p1-3 run, $1.00 for the
  generalisation run) and `out/piano-cut/spend-global.json` with a $4.00 cap, checked by `spend_check`
  before every call (recheck too); retries are logged as `retry-wasted`. Standing: `spend-global.json` at
  $1.020 after the 2026-10-27 night runs (headers, labels, rechecks across Rach 1, PC3, PC5, Dvořák 9,
  Beethoven 9). Totals by study: grounding ~$0.35; piano cut Rach 1 $0.103; generalisation $0.2287 (Rach 2
  $0.0713, PC3 $0.0819, PC5 $0.0755); hardening $0.243; any-instrument $0.777 (CK's cap that night $2.00;
  Meta total that evening about $1.2); Audiveris $0.50; homr $0.26; Goldberg p1-3 $0.285.
- Incident 2026-10-27: the intelligence thread's first `process_pages` run wrote test rows to the hosted
  project; CK approved the cleanup (score, images, usage events deleted; both spend counters back to 0).

## Per-page metadata (idea)

What exists: `interpretations.summary` (counts, `models`, `log`, `pages_read`, `question`),
`interpretations.cost_usd` and `latency_ms` per run, `measure_placements.confidence` and `flag` per bar,
`usage_events` per model call tagged with the job id, and in the experiments `label-p<NN>.json` (prompt,
raw text, parsed, cost, retries) and `results.json` per system (verify checks, clean erased/kept, edge
flags, recheck answer).

The idea: one record per page per interpretation that carries what the app and the benchmark (016) both
need: models used and their roles, cost and latency per call, geometry counts (staves, systems, bars,
recovered staves), flags (doubtful bars, unreadable, needs_review question), and the log lines for that page.
Today this is spread between `summary`, `params.state` and `usage_events`. Not designed beyond this note.

## Rules and decisions

- The database is the queue and the truth; Realtime is notification. In-process background tasks are not
  enough.
- Every model call goes through `ctx.complete` or `ctx.charge`, on the job's `created_by` user.
- Credits go to iterations on ~10 pages, never 50-page runs or Claude-vs-Spark bakeoffs for now (CK,
  2026-10-27).
- Never test against the hosted project from the intelligence thread.

## Next steps

1. Design the per-page record with 016's needs in view, then add it as a migration from the app thread.
2. A `brief` job kind (Spark) to replace the difficulty heuristic.
