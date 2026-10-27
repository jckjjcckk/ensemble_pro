# Acceptance: the librarian pipeline (scan to parts)

Build-queue item 6's engine: `process_pages` in `api/app/librarian/`. Run against the local Docker stack only
(`supabase start`, then `uv run scripts/smoke_local.py` once so admin@muse.test exists). Meta models: Muse Spark 1.3
labels each page; the geometry is OpenCV. Everything below runs from `api/`.

1. Seed a two-page score with the experiment pages (Goldberg Aria, clean; Rachmaninoff two-piano p.3, noisy):
   `uv run -m app.librarian.run seed --pages experiments/grounding/pages/goldberg-bga-p01.png experiments/grounding/pages/rach1-2pf-gutheil-p03.png`
   and keep the printed `score_id`.
2. `uv run -m app.librarian.run process_pages --score <id>`: the job finishes `done` with `result.question`
   asking which parts are on page 2 (four staves where page 1 had two); the interpretation is `needs_review`.
   Nothing is charged twice later: page 1 is kept.
3. `uv run -m app.librarian.run process_pages --score <id> --answer "Piano I, Piano II"`: resumes from page 2,
   the score comes back `ready` with 41 bars, parts Piano / Piano I / Piano II with a difficulty each.
4. `uv run experiments/grounding/tap_test_db.py --score <id>` reads the placements back from the database and
   taps the centre of every ground-truth bar: 28/28 and 13/13, `ALL PASS`.
5. `uv run -m app.librarian.run show --score <id>`: key G major, meter 3/4, a two-sentence brief, title and
   composer read from the page, `summary.log` lines fit for the information box, `flagged.bars_doubtful` = 4
   (bar 17 after the repeat, two partly broken barlines, the wide cadenza bar 41), rehearsal mark 1 on bar 37.
6. In the database, `usage_events` has one `muse-spark-1.3` row per page tagged with the job id, about $0.009 to
   $0.011 each; `interpretations.cost_usd` is their sum.
7. Reprocess (`process_pages --score <id>` again, answer again): interpretation v2, same 41 measure rows (ids
   unchanged, so annotations survive), `scores.current_interpretation_id` moves to v2.
