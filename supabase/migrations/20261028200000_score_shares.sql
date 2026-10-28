-- Share a book with a group (001, 010, 2026-10-28). Applied to the LOCAL stack only (`supabase migration up --local`).
--
-- CK asked for "share a book to a group": does it copy, or share permission to view the personal file, and it does not
-- share the annotations? Decision: share by REFERENCE. Not a copy, not a move. The book stays in its owner's personal
-- library (`scores.owner_user_id`); a `score_shares` row gives one group permission to read it. Unsharing deletes the
-- row and the group stops seeing the book at once.
--
-- Who reads what
--   * The book and everything the reader needs (`scores`, `sources`, `parts`, `measures`, `interpretations`,
--     `measure_placements`, `jobs`, and the files under `{score_id}/` in the `scores` bucket): its owner, the members of
--     the group that owns it (a group's book), and the members of every group it is shared with. All of these go
--     through `can_read_score`, which now also asks `is_shared_with_me`; the storage read policy calls
--     `can_read_score` on the first folder of the key, so it widens with it and is not rewritten here.
--   * Writing the book (import, split, convert, delete, its sources, parts, measures rows, readings, files) stays with
--     `can_edit_score`: the owner of a personal book, or an admin of the group that owns a group's book. A share gives
--     no write. Only personal books can be shared, and only by their owner, who must be a member of the group.
--
-- Marks on a shared book: a LAYER per group
--   `annotations.ensemble_id` and `scribbles.ensemble_id` (new, nullable) say which group a mark is addressed to.
--   Read the layer of a mark as g = coalesce(mark.ensemble_id, scores.ensemble_id):
--   * a personal book, mark.ensemble_id null: the owner's PRIVATE mark. Only the owner reads or writes it, before and
--     after any share. Nothing the owner marked privately is ever shown to a group.
--   * a personal book, mark.ensemble_id = g: the group's layer on that book. Readable only while the book is shared
--     with g, by members of g, with the usual audience rules counted inside g (ensemble = all of g, part = g's seat,
--     member = g's member row). Any member of g may write the marks players may write (a live highlight for the
--     group; a note, bowing, pencil to themselves as `member` audience, never a cut); an ADMIN of g leads the layer
--     (writes to anyone, cuts, sees and removes every mark in it), as an admin does on the group's own books. The
--     book's owner is an ordinary member of g in g's layer (they can unshare instead).
--   * a group's book (scores.ensemble_id = g): null means g, as before this migration, so every existing row keeps
--     today's behaviour. A mark written with ensemble_id = g on g's own book is stored as null (trigger
--     `normalise_mark_group`), so the group's own book has one layer and one scribble row per page, part and author.
--   Unsharing hides the group's layer and keeps it; sharing again brings it back. Deleting the group deletes its layer
--   (foreign key cascade). When the owner leaves a group, or is removed from it, the shares of their books there are
--   deleted (trigger `members_drop_shares`).
--
-- RPCs: `share_score(score uuid, ensemble uuid)` returns the `score_shares` row (idempotent: sharing twice returns the
-- same row); `unshare_score(score uuid, ensemble uuid)` returns nothing (idempotent). Refusals are SQLSTATE P0001
-- (PostgREST 400) with a sentence in `message` and a key in `hint`, like the group RPCs: not_signed_in, not_found,
-- not_owner, not_member.
--
-- Breaking for the reader: the scribbles unique key gains `ensemble_id`, so an upsert must name
-- `onConflict: 'score_id,page,part,user_id,ensemble_id'`.

-- ---------------------------------------------------------------- 1. the share

create table public.score_shares (
  score_id    uuid not null references public.scores(id) on delete cascade,
  ensemble_id uuid not null references public.ensembles(id) on delete cascade,
  shared_by   uuid not null default auth.uid() references auth.users(id) on delete cascade,
  created_at  timestamptz not null default now(),
  primary key (score_id, ensemble_id)
);
create index score_shares_ensemble on public.score_shares(ensemble_id);

-- Only a book in someone's own library is shared; a group's book belongs to its group. Holds for every path,
-- the service role included.
create or replace function public.share_personal_only() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if not exists (select 1 from scores where id = new.score_id and owner_user_id is not null) then
    raise exception 'A group''s book stays with its group. Only a book in your own library can be shared.'
      using hint = 'not_owner';
  end if;
  return new;
end $$;
create trigger score_shares_personal_only before insert or update on public.score_shares
  for each row execute function public.share_personal_only();

-- SECURITY DEFINER so the policies on scores and score_shares can ask each other without recursing.
create or replace function public.score_owner(s uuid) returns uuid
language sql stable security definer set search_path = public as $$
  select owner_user_id from scores where id = s;
$$;

create or replace function public.is_shared_with_me(s uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from score_shares sh join members m on m.ensemble_id = sh.ensemble_id
    where sh.score_id = s and m.user_id = auth.uid()
  );
$$;

alter table public.score_shares enable row level security;
-- Members of the group and the book's owner read; only the owner shares (and must be in the group) and unshares.
create policy score_shares_select on public.score_shares for select to authenticated
  using (is_member(ensemble_id) or score_owner(score_id) = auth.uid());
create policy score_shares_insert on public.score_shares for insert to authenticated
  with check (shared_by = auth.uid() and score_owner(score_id) = auth.uid() and is_member(ensemble_id));
create policy score_shares_delete on public.score_shares for delete to authenticated
  using (score_owner(score_id) = auth.uid());
-- No update policy: a share is made or removed, never changed.

-- The owner leaving a group (or being removed) takes their books' shares there with them.
create or replace function public.drop_shares_on_leave() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  delete from score_shares sh using scores sc
  where sh.score_id = sc.id and sh.ensemble_id = old.ensemble_id and sc.owner_user_id = old.user_id;
  return old;
end $$;
create trigger members_drop_shares after delete on public.members
  for each row execute function public.drop_shares_on_leave();

-- ---------------------------------------------------------------- 2. reading a shared book

create or replace function public.can_read_score(s uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from scores
    where id = s and (owner_user_id = auth.uid() or (ensemble_id is not null and is_member(ensemble_id)))
  ) or is_shared_with_me(s);
$$;

-- Still on the row's own columns for the owner and the group (INSERT ... RETURNING must see its new row); the share
-- is looked up by id in score_shares, which a definer function reads without re-entering this policy.
drop policy if exists scores_select on public.scores;
create policy scores_select on public.scores for select to authenticated
  using (owner_user_id = auth.uid() or (ensemble_id is not null and is_member(ensemble_id)) or is_shared_with_me(id));

-- sources, interpretations, parts, measures, measure_placements, jobs and storage reads already go through
-- can_read_score; their write policies go through can_edit_score, which is unchanged.

-- ---------------------------------------------------------------- 3. mark layers

-- The group a mark speaks to: its own ensemble_id, else the group that owns the book; null = the owner's private layer.
create or replace function public.mark_group(s uuid, g uuid) returns uuid
language sql stable security definer set search_path = public as $$
  select coalesce(g, (select ensemble_id from scores where id = s));
$$;

-- May the caller read marks in layer g of book s?
create or replace function public.can_read_layer(s uuid, g uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select coalesce((
    select case
      when sc.ensemble_id is not null then (g is null or g = sc.ensemble_id) and is_member(sc.ensemble_id)
      when g is null then sc.owner_user_id = auth.uid()
      else is_member(g) and exists (select 1 from score_shares sh where sh.score_id = s and sh.ensemble_id = g)
    end
    from scores sc where sc.id = s
  ), false);
$$;

-- Does the caller lead layer g of book s (write to anyone, cut, remove any mark)? A group's admin on the group's own
-- book (what can_edit_score said before), the owner in their private layer, a group's admin in that group's layer.
create or replace function public.can_lead_layer(s uuid, g uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select coalesce((
    select case
      when sc.ensemble_id is not null then (g is null or g = sc.ensemble_id) and is_admin(sc.ensemble_id)
      when g is null then sc.owner_user_id = auth.uid()
      else is_admin(g) and exists (select 1 from score_shares sh where sh.score_id = s and sh.ensemble_id = g)
    end
    from scores sc where sc.id = s
  ), false);
$$;

-- On a group's own book, ensemble_id = that group is the same layer as null: store it as null.
create or replace function public.normalise_mark_group() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if new.ensemble_id is not null and new.ensemble_id = (select ensemble_id from scores where id = new.score_id) then
    new.ensemble_id := null;
  end if;
  return new;
end $$;

-- ---------------------------------------------------------------- 4. annotations

alter table public.annotations add column ensemble_id uuid references public.ensembles(id) on delete cascade;
create index annotations_score_group on public.annotations(score_id, ensemble_id);
create trigger annotations_normalise_group before insert or update of ensemble_id, score_id on public.annotations
  for each row execute function public.normalise_mark_group();

-- Who sees a mark: its author always; whoever leads its layer; anyone who reads the layer when the mark is live and
-- addressed to the layer's group, to their seat in it, or to them.
create or replace function public.can_see_annotation(a public.annotations) returns boolean
language sql stable security definer set search_path = public as $$
  select a.author_id = auth.uid()
      or can_lead_layer(a.score_id, a.ensemble_id)
      or (a.status = 'live' and can_read_layer(a.score_id, a.ensemble_id) and (
            a.audience = 'ensemble'
         or (a.audience = 'part'   and a.audience_part = my_part(mark_group(a.score_id, a.ensemble_id)))
         or (a.audience = 'member' and a.audience_member_id = my_member_id(mark_group(a.score_id, a.ensemble_id)))
      ));
$$;

-- The rules a player writes under, in one place for insert and update.
create or replace function public.may_write_mark(s uuid, g uuid, p_author uuid, p_kind text, p_audience text,
                                                 p_member uuid, p_status text) returns boolean
language sql stable security definer set search_path = public as $$
  select can_read_layer(s, g) and (
    can_lead_layer(s, g)
    or (p_author = auth.uid() and (
          (p_audience = 'member' and p_member = my_member_id(mark_group(s, g)) and p_kind <> 'cut')
       or (p_kind = 'highlight' and p_audience = 'ensemble' and p_status = 'live')
    ))
  );
$$;

drop policy if exists annotations_select on public.annotations;
create policy annotations_select on public.annotations for select to authenticated using (can_see_annotation(annotations));
drop policy if exists annotations_insert on public.annotations;
create policy annotations_insert on public.annotations for insert to authenticated
  with check (author_id = auth.uid()
              and may_write_mark(score_id, ensemble_id, author_id, kind, audience, audience_member_id, status));
drop policy if exists annotations_update on public.annotations;
create policy annotations_update on public.annotations for update to authenticated
  using (author_id = auth.uid() or can_lead_layer(score_id, ensemble_id))
  with check (may_write_mark(score_id, ensemble_id, author_id, kind, audience, audience_member_id, status));
drop policy if exists annotations_delete on public.annotations;
create policy annotations_delete on public.annotations for delete to authenticated
  using (author_id = auth.uid() or can_lead_layer(score_id, ensemble_id));

-- ---------------------------------------------------------------- 5. scribbles

alter table public.scribbles add column ensemble_id uuid references public.ensembles(id) on delete cascade;
alter table public.scribbles drop constraint if exists scribbles_score_id_page_part_user_id_key;
alter table public.scribbles
  add constraint scribbles_layer_key unique nulls not distinct (score_id, page, part, user_id, ensemble_id);
create trigger scribbles_normalise_group before insert or update of ensemble_id, score_id on public.scribbles
  for each row execute function public.normalise_mark_group();

-- Everyone who reads the layer sees every drawing in it; only the author writes their own.
drop policy if exists scribbles_select on public.scribbles;
create policy scribbles_select on public.scribbles for select to authenticated using (can_read_layer(score_id, ensemble_id));
drop policy if exists scribbles_insert on public.scribbles;
create policy scribbles_insert on public.scribbles for insert to authenticated
  with check (user_id = auth.uid() and can_read_layer(score_id, ensemble_id));
drop policy if exists scribbles_update on public.scribbles;
create policy scribbles_update on public.scribbles for update to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid() and can_read_layer(score_id, ensemble_id));
-- scribbles_delete (the author's own) is unchanged.

-- ---------------------------------------------------------------- 6. the two actions

create or replace function public.share_score(score uuid, ensemble uuid) returns public.score_shares
language plpgsql volatile security definer set search_path = public as $$
declare
  sc public.scores;
  sh public.score_shares;
begin
  if auth.uid() is null then
    raise exception 'Sign in first.' using hint = 'not_signed_in';
  end if;
  select * into sc from scores where id = share_score.score;
  if sc.id is null or not can_read_score(sc.id) then
    raise exception 'This book no longer exists.' using hint = 'not_found';
  end if;
  if sc.owner_user_id is null then
    raise exception 'A group''s book stays with its group. Only a book in your own library can be shared.' using hint = 'not_owner';
  end if;
  if sc.owner_user_id <> auth.uid() then
    raise exception 'Only the book''s owner can share it.' using hint = 'not_owner';
  end if;
  if not exists (select 1 from ensembles where id = share_score.ensemble) then
    raise exception 'This group no longer exists.' using hint = 'not_found';
  end if;
  if not is_member(share_score.ensemble) then
    raise exception 'You are not in this group.' using hint = 'not_member';
  end if;
  insert into score_shares (score_id, ensemble_id, shared_by) values (sc.id, share_score.ensemble, auth.uid())
    on conflict (score_id, ensemble_id) do nothing;
  select * into sh from score_shares where score_id = sc.id and ensemble_id = share_score.ensemble;
  return sh;
end $$;

create or replace function public.unshare_score(score uuid, ensemble uuid) returns void
language plpgsql volatile security definer set search_path = public as $$
declare sc public.scores;
begin
  if auth.uid() is null then
    raise exception 'Sign in first.' using hint = 'not_signed_in';
  end if;
  select * into sc from scores where id = unshare_score.score;
  if sc.id is null or not can_read_score(sc.id) then
    raise exception 'This book no longer exists.' using hint = 'not_found';
  end if;
  if sc.owner_user_id is distinct from auth.uid() then
    raise exception 'Only the book''s owner can stop sharing it.' using hint = 'not_owner';
  end if;
  delete from score_shares where score_id = sc.id and ensemble_id = unshare_score.ensemble;
end $$;

revoke execute on function public.share_score(uuid, uuid), public.unshare_score(uuid, uuid),
  public.share_personal_only(), public.drop_shares_on_leave(), public.normalise_mark_group() from public, anon;
grant execute on function public.share_score(uuid, uuid), public.unshare_score(uuid, uuid) to authenticated, service_role;

-- ---------------------------------------------------------------- 7. realtime: a share made or removed reloads the shelves

alter publication supabase_realtime add table public.score_shares;

-- ---------------------------------------------------------------- 8. storage keys that are not a book's folder

-- The bucket policies cast the key's first folder to uuid. One stray key whose first folder is not a uuid (the local
-- stack holds two, `scores/{id}/pages/n.png`) made every listing of the bucket fail for everyone, the owner included
-- ("invalid input syntax for type uuid"), because the policy is evaluated on rows the prefix filter has not yet
-- removed. Same rules as before (read with can_read_score, write with can_edit_score); a key that names no book
-- simply matches no book.
create or replace function public.score_folder(key text) returns uuid
language sql immutable as $$
  select case when split_part(key, '/', 1) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
              and strpos(key, '/') > 0
         then split_part(key, '/', 1)::uuid end;
$$;

drop policy if exists scores_bucket_read on storage.objects;
create policy scores_bucket_read on storage.objects for select to authenticated
  using (bucket_id = 'scores' and can_read_score(public.score_folder(name)));
drop policy if exists scores_bucket_insert on storage.objects;
create policy scores_bucket_insert on storage.objects for insert to authenticated
  with check (bucket_id = 'scores' and can_edit_score(public.score_folder(name)));
drop policy if exists scores_bucket_update on storage.objects;
create policy scores_bucket_update on storage.objects for update to authenticated
  using (bucket_id = 'scores' and can_edit_score(public.score_folder(name)));
drop policy if exists scores_bucket_delete on storage.objects;
create policy scores_bucket_delete on storage.objects for delete to authenticated
  using (bucket_id = 'scores' and can_edit_score(public.score_folder(name)));
