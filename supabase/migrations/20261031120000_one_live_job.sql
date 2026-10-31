-- One live job of a kind per book (007, CK 2026-10-31: never submit a duplicate job).
-- A split by instrument (`part_cut`, per set of parts: `payload.parts_key`), a conversion to Digital (`omr_convert`,
-- whose book is `payload.score_id` because `jobs.score_id` stays empty) and the reading of a PDF (`process_pages`)
-- may each have one row queued or running per book. The routes refuse a second request with 409 naming the live job
-- (a job parked on an unanswered question counts there too); this index holds the rule when two requests race.

-- Rows that already break the rule keep the oldest live one; the later ones are failed with a sentence.
update public.jobs j
set status = 'failed', error = 'duplicate of a job already under way on this book', finished_at = now()
from (
  select id, row_number() over (
           partition by kind, coalesce(score_id::text, payload->>'score_id'), coalesce(payload->>'parts_key', '')
           order by created_at, id) as n
  from public.jobs
  where status in ('queued', 'running') and kind in ('part_cut', 'omr_convert', 'process_pages')
) d
where j.id = d.id and d.n > 1;

create unique index if not exists jobs_one_live on public.jobs (
  kind,
  (coalesce(score_id::text, payload->>'score_id')),
  (coalesce(payload->>'parts_key', ''))
) where status in ('queued', 'running') and kind in ('part_cut', 'omr_convert', 'process_pages');
