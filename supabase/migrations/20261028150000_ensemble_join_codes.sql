-- Groups (feature 001, 2026-10-28): an 8-digit join code per ensemble and the four things the browser does with a
-- group through the anon key: create, join, leave, delete. CK: no rotation, no invitations, no auth changes; each
-- action has one confirmation box in the UI. Applied to the LOCAL stack only (`supabase migration up --local`).
--
-- Errors are raised with SQLSTATE P0001 (PostgREST answers 400) and a sentence a musician can read in `message`;
-- `hint` carries a stable key for the code to branch on: not_signed_in, bad_name, bad_code, unknown_code,
-- not_member, last_admin, not_admin, not_found.

-- ---------------------------------------------------------------- the code

-- Eight digits from the CSPRNG (a code is all it takes to join, so not random()). Retries until unused; the unique
-- constraint below is the real guard, and create_ensemble retries when two inserts draw the same code at once.
create or replace function public.new_join_code() returns text
language plpgsql volatile security definer set search_path = public, extensions as $$
declare c text;
begin
  loop
    c := lpad(((('x' || encode(gen_random_bytes(4), 'hex'))::bit(32)::bigint) % 100000000)::text, 8, '0');
    exit when not exists (select 1 from public.ensembles where join_code = c);
  end loop;
  return c;
end $$;

alter table public.ensembles add column join_code text;
update public.ensembles set join_code = public.new_join_code() where join_code is null;
alter table public.ensembles
  alter column join_code set default public.new_join_code(),
  alter column join_code set not null,
  add constraint ensembles_join_code_key unique (join_code),
  add constraint ensembles_join_code_check check (join_code ~ '^[0-9]{8}$');

-- Reading the code: `ensembles_select` already lets every member read every column of their own ensembles
-- (is_member(id) or created_by = auth.uid()), join_code included, so the admin can show it. Non-members see no
-- row at all; nobody can look a group up by its code except through join_ensemble.

-- ---------------------------------------------------------------- a group always keeps an admin

-- members_delete lets anyone delete their own row and members_update lets an admin change any role, so the
-- last-admin rule would be one REST call away from bypassed if it lived only in leave_ensemble. This trigger holds
-- it for every path a signed-in person can take. It stands aside when the ensemble itself is being deleted (the
-- cascade) and for the service role / dashboard (auth.uid() is null), so deleting an account still works.
create or replace function public.keep_an_admin() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if auth.uid() is null or old.role <> 'admin' then
    return case when tg_op = 'DELETE' then old else new end;
  end if;
  if tg_op = 'UPDATE' and new.role = 'admin' and new.ensemble_id = old.ensemble_id then
    return new;
  end if;
  if not exists (select 1 from ensembles where id = old.ensemble_id) then
    return case when tg_op = 'DELETE' then old else new end;
  end if;
  if not exists (select 1 from members where ensemble_id = old.ensemble_id and role = 'admin' and id <> old.id) then
    raise exception 'You are this group''s only admin, so you cannot leave it. Make another member an admin first, or delete the group.'
      using hint = 'last_admin';
  end if;
  return case when tg_op = 'DELETE' then old else new end;
end $$;

create trigger members_keep_an_admin before delete or update of role, ensemble_id on public.members
  for each row execute function public.keep_an_admin();

-- ---------------------------------------------------------------- the four actions

create or replace function public.create_ensemble(name text) returns public.ensembles
language plpgsql volatile security definer set search_path = public as $$
declare
  n text := btrim(coalesce(create_ensemble.name, ''));
  e public.ensembles;
begin
  if auth.uid() is null then
    raise exception 'Sign in to create a group.' using hint = 'not_signed_in';
  end if;
  if n = '' or length(n) > 80 then
    raise exception 'Give the group a name of up to 80 characters.' using hint = 'bad_name';
  end if;
  for attempt in 1..5 loop
    begin
      -- on_ensemble_created makes the caller its first admin
      insert into ensembles (name, created_by) values (n, auth.uid()) returning * into e;
      return e;
    exception when unique_violation then
      null;   -- two groups drew the same code in the same instant: draw again
    end;
  end loop;
  raise exception 'The group could not be created. Try again.' using hint = 'retry';
end $$;

create or replace function public.join_ensemble(code text) returns uuid
language plpgsql volatile security definer set search_path = public as $$
declare
  c text := regexp_replace(coalesce(join_ensemble.code, ''), '[\s-]', '', 'g');
  e uuid;
begin
  if auth.uid() is null then
    raise exception 'Sign in to join a group.' using hint = 'not_signed_in';
  end if;
  if c !~ '^[0-9]{8}$' then
    raise exception 'A join code is 8 digits.' using hint = 'bad_code';
  end if;
  select id into e from ensembles where join_code = c;
  if e is null then
    raise exception 'No group has the code %. Check the digits with the group''s admin.', c using hint = 'unknown_code';
  end if;
  -- idempotent: joining twice, or an admin typing their own code, changes nothing
  insert into members (ensemble_id, user_id, role) values (e, auth.uid(), 'player')
    on conflict (ensemble_id, user_id) do nothing;
  return e;
end $$;

create or replace function public.leave_ensemble(ensemble uuid) returns void
language plpgsql volatile security definer set search_path = public as $$
declare me public.members;
begin
  if auth.uid() is null then
    raise exception 'Sign in first.' using hint = 'not_signed_in';
  end if;
  -- one leave at a time per group, so two admins leaving together cannot leave it with none
  perform 1 from ensembles where id = leave_ensemble.ensemble for update;
  select * into me from members where ensemble_id = leave_ensemble.ensemble and user_id = auth.uid();
  if me.id is null then
    raise exception 'You are not in this group.' using hint = 'not_member';
  end if;
  if me.role = 'admin' and not exists (
    select 1 from members where ensemble_id = leave_ensemble.ensemble and role = 'admin' and id <> me.id
  ) then
    raise exception 'You are this group''s only admin, so you cannot leave it. Make another member an admin first, or delete the group.'
      using hint = 'last_admin';
  end if;
  delete from members where id = me.id;
end $$;

-- Deletes the group and, by the foreign keys, its memberships, scores (with their sources, readings, measures,
-- parts, notes and jobs) and rehearsal sessions. The scores' files in the `scores` bucket are not removed here:
-- storage objects are deleted through the Storage API, not SQL.
create or replace function public.delete_ensemble(ensemble uuid) returns void
language plpgsql volatile security definer set search_path = public as $$
begin
  if auth.uid() is null then
    raise exception 'Sign in first.' using hint = 'not_signed_in';
  end if;
  perform 1 from ensembles where id = delete_ensemble.ensemble for update;
  if not found then
    raise exception 'This group no longer exists.' using hint = 'not_found';
  end if;
  if not is_admin(delete_ensemble.ensemble) then
    raise exception 'Only an admin can delete this group.' using hint = 'not_admin';
  end if;
  delete from ensembles where id = delete_ensemble.ensemble;
end $$;

-- Signed-in people only. new_join_code stays executable by `authenticated` because it is the column default,
-- which runs with the inserting role's rights when a browser inserts an ensemble directly.
revoke execute on function public.create_ensemble(text), public.join_ensemble(text), public.leave_ensemble(uuid),
  public.delete_ensemble(uuid), public.new_join_code(), public.keep_an_admin() from public, anon;
grant execute on function public.create_ensemble(text), public.join_ensemble(text), public.leave_ensemble(uuid),
  public.delete_ensemble(uuid), public.new_join_code() to authenticated, service_role;
