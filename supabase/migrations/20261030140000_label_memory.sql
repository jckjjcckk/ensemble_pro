-- The book's label memory (008 part cut, 006 agentic memory rule; CK 2026-10-30).
--
-- A part cut of a Beethoven concerto asked "which staves are the piano?" on every page, although the book's first
-- reading had read "Klavier" as the piano and the admin had already answered for "Klav.". Work and human answers
-- within a book are now remembered and reused: one JSON per book, written by the API (service role) only.
--
--   {"entries": {"klav": {"label": "Klav.", "part": "Piano", "source": "human" | "model",
--                         "origin": "answer" | "header" | "header-abbreviation" | "page",
--                         "page": 2, "staves": [19, 20], "job_id": "...", "at": "..."}},
--    "updated_at": "..."}
--
-- Keys are the normalised printed label (`app/librarian/label_memory.py`). A human answer overwrites anything; a model
-- read never overwrites a human entry. `process_pages` seeds it from the header; `part_cut` reads it before every page,
-- learns from commits that passed every check and from the admin's answers. Readable with the score row (the same
-- policies); nothing in the browser writes it.

alter table public.scores
  add column if not exists label_memory jsonb not null default '{}'::jsonb;
