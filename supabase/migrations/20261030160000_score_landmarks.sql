-- The book's landmarks (013 voice notes, prompt v4e part a; CK 2026-10-30: "Make it happen").
--
-- "Two after the key change", "the bar before the double bar", "in the slow section": a voice note names a place
-- by what is printed there, and the prompt can resolve it to bars only when the score facts list it. One JSON list
-- per book, written by the API (service role) at import and on Convert to Digital (music21 on the MusicXML) and by
-- page reading (the per-page Spark read names what is printed over a bar box; geometry gives the bar number):
--
--   [{"kind": "key_change" | "meter_change" | "tempo" | "double_bar" | "repeat" | "coda" | "segno" | "fine"
--             | "section" | "rehearsal",
--     "label": "<printed text>", "bar": 97, "bar_after": 98 | null, "source": "musicxml" | "page"}]
--
-- bar_after is set for a boundary between two bars (a double bar, an end repeat): "between bars 64 and 65".
-- `app/librarian/landmarks.py` reads and writes it; `transcribe_voice` lists it in the score facts (musicxml
-- entries win over page ones once a book is converted). Readable with the score row (the same policies); nothing in
-- the browser writes it.

alter table public.scores
  add column if not exists landmarks jsonb not null default '[]'::jsonb;
