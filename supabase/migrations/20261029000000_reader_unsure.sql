-- When the reader is unsure (010, 011; 2026-10-28 night, CK's R3 artboards F_BookUnread, F_Details, F_CheckBar).
--
-- 1. The signature's best guess. `process_pages` reads the key and time signature of the first system with Spark and
--    leaves `key_sig` / `meter` null when it is unsure. It now keeps what it would have said: `key_sig_guess`,
--    `meter_guess` (same canonical strings) and `signature_confidence` `{key, time}` (high | medium | low). The book
--    sheet shows the guess in an amber banner; the owner confirms it in Details, which writes `key_sig` / `meter` and
--    sets `signature_confirmed`, after which a re-read never touches them.
-- 2. Details: `tempo_text` (the marking beside the speed, "Andante"), `cover_clef` (only the cover uses it; the pages
--    keep their own clefs), `first_bar` / `first_bar_page` (bar numbering: the first bar on that page carries that
--    number; `PATCH /scores/{id}` renumbers `measures` through `shift_measures`, and marks follow because they point
--    at `measures.id`).
-- 3. `bar_decisions`: the owner's verdict on a doubtful bar of the Digital copy (`flagged_bars` in the musicxml
--    source's meta). 'scan' = the copy is wrong here, the stand draws the scan's bar over it; 'digital' = looks right.
--    The reader never rewrites music. Everyone who reads the book reads the decisions (the stand draws them); only
--    whoever may edit the book writes them.

alter table public.scores
  add column if not exists key_sig_guess text,
  add column if not exists meter_guess text,
  add column if not exists signature_confidence jsonb,
  add column if not exists signature_confirmed boolean not null default false,
  add column if not exists tempo_text text,
  add column if not exists cover_clef text check (cover_clef in ('treble', 'bass', 'alto', 'grand')),
  add column if not exists first_bar int,
  add column if not exists first_bar_page int check (first_bar_page >= 1);

-- Shift every bar number of a book by `delta`, keeping each measure's id (marks stay on their bar). Two passes
-- through negative numbers so the (score_id, number, part) uniqueness never sees a collision mid-update.
create or replace function public.shift_measures(s uuid, delta int) returns void
language plpgsql security definer set search_path = public as $$
begin
  if auth.role() <> 'service_role' and not can_edit_score(s) then
    raise exception 'Only the owner or an admin can renumber this book';
  end if;
  if delta = 0 then
    return;
  end if;
  update measures set number = -number - 1000000 where score_id = s;
  update measures set number = -number - 1000000 + delta where score_id = s;
end;
$$;

create table public.bar_decisions (
  score_id   uuid not null references public.scores(id) on delete cascade,
  bar        int not null,
  decision   text not null check (decision in ('scan', 'digital')),
  decided_by uuid not null default auth.uid() references auth.users(id) on delete cascade,
  decided_at timestamptz not null default now(),
  primary key (score_id, bar)
);

alter table public.bar_decisions enable row level security;
create policy bar_decisions_select on public.bar_decisions for select to authenticated using (can_read_score(score_id));
create policy bar_decisions_insert on public.bar_decisions for insert to authenticated
  with check (can_edit_score(score_id) and decided_by = auth.uid());
create policy bar_decisions_update on public.bar_decisions for update to authenticated
  using (can_edit_score(score_id)) with check (can_edit_score(score_id) and decided_by = auth.uid());
create policy bar_decisions_delete on public.bar_decisions for delete to authenticated using (can_edit_score(score_id));

alter publication supabase_realtime add table public.bar_decisions;
