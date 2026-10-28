-- Engraved layouts (005, 010; 2026-10-28): a digital book's pages, drawn server-side by MuseScore on the OMR box.
--
-- Two changes. `sources.kind` admits 'engraving': one row per layout of a book's notation ('display' = optimised for
-- the iPad page, 'original' = the file's own page size and breaks), `storage_paths` the SVG pages in order
-- (`{score_id}/digital/{layout}/p001.svg`, ...), `page_count`, and `meta = {layout, source_id (the musicxml source
-- engraved), engine, page_mm, bars: [[number, page, x, y, w, h], ...]}` with the bar boxes as fractions of the page,
-- joined to `measures.number`. Reads and writes follow the existing sources policies (the reader of a book reads its
-- pages; the worker writes them with the service key).
--
-- `scores.digital_layout` is the layout the book opens in, chosen from the book's "..." menu by whoever may edit it
-- (the scores update policy), default 'display'.

alter table public.sources drop constraint if exists sources_kind_check;
alter table public.sources
  add constraint sources_kind_check check (kind in ('pdf', 'images', 'musicxml', 'part_images', 'engraving'));

alter table public.scores
  add column if not exists digital_layout text not null default 'display'
  check (digital_layout in ('display', 'original'));
