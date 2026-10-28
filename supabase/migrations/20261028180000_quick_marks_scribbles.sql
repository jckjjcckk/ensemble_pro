-- Quick marks and scribbles (012, 2026-10-28). CK: "Nobody goes to marking settings and provides the exact
-- measure number." A tap on a bar opens Highlight, Note, Scribble; this migration is what those three write.
--
-- 1. `annotations.kind` admits 'highlight': a colour wash over one bar that the ensemble sees.
-- 2. Any reader of a score may write a live highlight addressed to the ensemble (players could only write notes
--    to themselves before). Everything else about who writes what is unchanged.
-- 3. `measure_ids(score, numbers[])`: a player tapping bar 12 needs the stable `measures.id` of bar 12, and only
--    editors may write `measures`. The function returns the ids, creating a missing whole-score row, for anyone
--    who can read the score.
-- 4. `scribbles`: free drawing over the score, stored and synced, never interpreted. One row per
--    (score, page as drawn, part, author); `strokes` is a JSON array of simplified polylines in page fractions,
--    each anchored to the bar it was drawn over (shape in docs/features/012-symbols-layer.md).

-- ---------------------------------------------------------------- 1. the highlight kind

alter table public.annotations drop constraint if exists annotations_kind_check;
alter table public.annotations
  add constraint annotations_kind_check
  check (kind in ('marking', 'cut', 'voice', 'text', 'dynamic', 'bowing', 'breath', 'highlight'));

-- ---------------------------------------------------------------- 2. readers may highlight for the ensemble

drop policy if exists annotations_insert on public.annotations;
create policy annotations_insert on public.annotations for insert to authenticated
  with check (author_id = auth.uid() and can_read_score(score_id) and (
    can_edit_score(score_id)
    or (audience = 'member' and audience_member_id = my_member_id((select ensemble_id from scores where id = score_id)) and kind <> 'cut')
    or (kind = 'highlight' and audience = 'ensemble' and status = 'live')
  ));

-- ---------------------------------------------------------------- 3. stable bar ids for any reader

create or replace function public.measure_ids(p_score uuid, p_numbers int[])
returns table (number int, id uuid)
language plpgsql security definer set search_path = public as $$
#variable_conflict use_column
begin
  if not can_read_score(p_score) then
    raise exception 'score % is not readable', p_score using errcode = '42501';
  end if;
  insert into measures (score_id, number, part)
  select p_score, n, null from unnest(p_numbers) as n
  on conflict (score_id, number, part) do nothing;
  return query
    select m.number, m.id from measures m
    where m.score_id = p_score and m.part is null and m.number = any(p_numbers);
end;
$$;
revoke all on function public.measure_ids(uuid, int[]) from public, anon;
grant execute on function public.measure_ids(uuid, int[]) to authenticated;

-- ---------------------------------------------------------------- 4. scribbles

create table public.scribbles (
  id         uuid primary key default gen_random_uuid(),
  score_id   uuid not null references public.scores(id) on delete cascade,
  page       int not null check (page >= 1),          -- 1-based page the strokes were drawn on
  part       text,                                     -- the part on screen (parts.name); null = full score
  user_id    uuid not null default auth.uid() references auth.users(id) on delete cascade,
  strokes    jsonb not null default '[]' check (jsonb_typeof(strokes) = 'array' and pg_column_size(strokes) < 1000000),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique nulls not distinct (score_id, page, part, user_id)
);
create index scribbles_score on public.scribbles(score_id);
create trigger scribbles_updated before update on public.scribbles for each row execute function public.set_updated_at();

alter table public.scribbles enable row level security;
-- Members and owners read every member's drawing on the score; only the author writes their own.
create policy scribbles_select on public.scribbles for select to authenticated using (can_read_score(score_id));
create policy scribbles_insert on public.scribbles for insert to authenticated
  with check (user_id = auth.uid() and can_read_score(score_id));
create policy scribbles_update on public.scribbles for update to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid() and can_read_score(score_id));
create policy scribbles_delete on public.scribbles for delete to authenticated using (user_id = auth.uid());

alter publication supabase_realtime add table public.scribbles;
