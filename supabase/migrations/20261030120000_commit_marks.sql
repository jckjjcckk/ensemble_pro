-- Voice notes (013): accepting a proposal is one transaction.
--
-- Accepting a card with the admin's edits removes some rows of the mark, changes others (live, text, bars, audience)
-- and adds a row for an audience the admin added. Written as three requests from the stand, a wifi drop between them
-- left half a mark: a live row for one part beside a proposed duplicate, or an added audience silently lost.
-- `commit_marks` does all of it in one statement's transaction, or none of it.
--
-- It runs as the caller (security invoker), so every row it touches passes the same annotations policies a direct
-- write does (`can_lead_layer`, `may_write_mark`); a row the caller may not change, or one already gone, refuses the
-- whole call. Bars are given as numbers and resolved with `measure_ids`; every row written carries its bars in
-- `payload.bar` / `payload.bar_to` as well, which is what a reader's Realtime copy (no joined measures) draws from.
--
--   p_remove  uuid[]  rows to delete
--   p_update  jsonb   [{id, bar_from, bar_to, status?, body?, audience?, audience_part?, audience_member_id?}]
--   p_insert  jsonb   [{id, kind, bar_from, bar_to, status, body, audience, audience_part, audience_member_id, payload}]
--   p_layer   uuid    the mark layer new rows go in (null: the book's own)
--
-- Returns the rows changed and added, as stored.

create or replace function public.commit_marks(p_score uuid, p_layer uuid, p_remove uuid[], p_update jsonb, p_insert jsonb)
returns setof public.annotations
language plpgsql security invoker set search_path = public as $$
declare
  n int;
  x jsonb;
  bar_of jsonb := '{}';
  r public.annotations;
begin
  -- Every bar named, resolved once.
  select coalesce(jsonb_object_agg(m.number::text, m.id), '{}') into bar_of
  from measure_ids(p_score, array(
    select distinct (v->>k)::int
    from jsonb_array_elements(coalesce(p_update, '[]') || coalesce(p_insert, '[]')) v, unnest(array['bar_from', 'bar_to']) k
    where v ? k
  )) m;

  if coalesce(cardinality(p_remove), 0) > 0 then
    delete from annotations where id = any(p_remove) and score_id = p_score;
    get diagnostics n = row_count;
    if n <> cardinality(p_remove) then
      raise exception 'A mark to remove is gone or not yours to remove.' using errcode = '42501';
    end if;
  end if;

  for x in select * from jsonb_array_elements(coalesce(p_update, '[]')) loop
    if not (bar_of ? (x->>'bar_from')) or not (bar_of ? (x->>'bar_to')) then
      raise exception 'This score has no bar %.', coalesce(x->>'bar_from', x->>'bar_to') using errcode = '22023';
    end if;
    update annotations a set
      status             = coalesce(x->>'status', a.status),
      body               = case when x ? 'body' then x->>'body' else a.body end,
      measure_from       = (bar_of->>(x->>'bar_from'))::uuid,
      measure_to         = (bar_of->>(x->>'bar_to'))::uuid,
      audience           = coalesce(x->>'audience', a.audience),
      audience_part      = case when x ? 'audience' then x->>'audience_part' else a.audience_part end,
      audience_member_id = case when x ? 'audience' then (x->>'audience_member_id')::uuid else a.audience_member_id end,
      payload            = a.payload || jsonb_build_object('bar', (x->>'bar_from')::int, 'bar_to', (x->>'bar_to')::int)
    where a.id = (x->>'id')::uuid and a.score_id = p_score
    returning a.* into r;
    if not found then
      raise exception 'A mark to change is gone or not yours to change.' using errcode = '42501';
    end if;
    return next r;
  end loop;

  for x in select * from jsonb_array_elements(coalesce(p_insert, '[]')) loop
    if not (bar_of ? (x->>'bar_from')) or not (bar_of ? (x->>'bar_to')) then
      raise exception 'This score has no bar %.', coalesce(x->>'bar_from', x->>'bar_to') using errcode = '22023';
    end if;
    insert into annotations (id, score_id, ensemble_id, kind, measure_from, measure_to, author_id, body, status,
                             audience, audience_part, audience_member_id, payload)
    values ((x->>'id')::uuid, p_score, p_layer, x->>'kind', (bar_of->>(x->>'bar_from'))::uuid, (bar_of->>(x->>'bar_to'))::uuid,
            auth.uid(), x->>'body', coalesce(x->>'status', 'live'), coalesce(x->>'audience', 'ensemble'),
            x->>'audience_part', (x->>'audience_member_id')::uuid,
            coalesce(x->'payload', '{}') || jsonb_build_object('bar', (x->>'bar_from')::int, 'bar_to', (x->>'bar_to')::int))
    returning * into r;
    return next r;
  end loop;
end $$;

revoke all on function public.commit_marks(uuid, uuid, uuid[], jsonb, jsonb) from public, anon;
grant execute on function public.commit_marks(uuid, uuid, uuid[], jsonb, jsonb) to authenticated;
