-- part_cut (2026-10-28): a derived source holding one instrument's cut system images.
-- NOT APPLIED ANYWHERE YET. The app thread applies it (docs/librarian-contract.md: a handler that needs a
-- column asks the app thread). The only change: `sources.kind` admits 'part_images'. The instrument, the slug,
-- the parent source and the per-system staves live in `sources.meta`; `storage_paths` are the crops in
-- reading order and `page_order` / `page_count` keep their meaning (one "page" = one cut system image).

alter table public.sources drop constraint if exists sources_kind_check;
alter table public.sources
  add constraint sources_kind_check check (kind in ('pdf', 'images', 'musicxml', 'part_images'));
