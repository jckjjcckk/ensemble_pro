-- Presence (012, build-queue item 5, 2026-10-28): who is reading a score and on which bar.
--
-- One row per (score, member), upserted by the reader while the score is open: on every page turn (at most one
-- write every 2 s) and once a minute to stay fresh. The header's faces show the members with a fresh row and their
-- bar; a player can follow the admin's bar. Rows older than 10 minutes are ignored by readers (no cron; a reader
-- that leaves deletes its own row, and a stale one is simply never shown).
--
-- `ensemble_id` is copied from the member row by a trigger, never trusted from the client, so the read policy is
-- one membership check and works for a personal book shown in a group (the member row names the group).
-- Realtime carries the rows; the database stays the truth (clients refetch on reconnect).

create table public.presence (
  score_id    uuid not null references public.scores(id) on delete cascade,
  member_id   uuid not null references public.members(id) on delete cascade,
  ensemble_id uuid not null references public.ensembles(id) on delete cascade,
  user_id     uuid not null default auth.uid() references auth.users(id) on delete cascade,
  bar         int  not null default 1 check (bar >= 1),
  part        text,                                     -- parts.name on screen; null = the full score
  updated_at  timestamptz not null default now(),
  primary key (score_id, member_id)
);
create index presence_ensemble on public.presence(ensemble_id);

-- The member row decides the group; every write refreshes the timestamp.
create or replace function public.presence_fill() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  new.ensemble_id := (select ensemble_id from members where id = new.member_id);
  new.updated_at := now();
  return new;
end $$;
create trigger presence_fill before insert or update on public.presence
  for each row execute function public.presence_fill();

alter table public.presence enable row level security;
-- Members of the group read everyone's place; each member writes only their own row.
create policy presence_select on public.presence for select to authenticated using (is_member(ensemble_id));
create policy presence_insert on public.presence for insert to authenticated
  with check (user_id = auth.uid() and member_id = my_member_id(ensemble_id));
create policy presence_update on public.presence for update to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid() and member_id = my_member_id(ensemble_id));
create policy presence_delete on public.presence for delete to authenticated using (user_id = auth.uid());

alter publication supabase_realtime add table public.presence;
