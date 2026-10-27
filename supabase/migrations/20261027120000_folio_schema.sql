-- Folio schema, build-queue item 1 (2026-10-27).
-- Three layers: source (sources), interpretation (interpretations, measures, measure_placements),
-- collaboration (ensembles, members, annotations, rehearsal_sessions). Jobs are durable rows.
-- Measure identity is stable: annotations point at measures.id, never at an interpretation row.

create extension if not exists pgcrypto;

-- ---------------------------------------------------------------- helpers

create or replace function public.set_updated_at() returns trigger
language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end $$;

-- ---------------------------------------------------------------- profiles (one per auth user)

create table public.profiles (
  id            uuid primary key references auth.users(id) on delete cascade,
  email         text,
  display_name  text,
  budget_usd    numeric(10,4) not null default 10,
  spent_usd     numeric(10,4) not null default 0,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create trigger profiles_updated before update on public.profiles for each row execute function public.set_updated_at();

create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, email, display_name)
  values (new.id, new.email, coalesce(new.raw_user_meta_data->>'display_name', split_part(coalesce(new.email, ''), '@', 1)))
  on conflict (id) do nothing;
  return new;
end $$;

create trigger on_auth_user_created after insert on auth.users
  for each row execute function public.handle_new_user();

-- Users that already exist (the five demo accounts on the hosted project).
insert into public.profiles (id, email, display_name)
select id, email, split_part(coalesce(email, ''), '@', 1) from auth.users
on conflict (id) do nothing;

-- ---------------------------------------------------------------- ensembles and members

create table public.ensembles (
  id          uuid primary key default gen_random_uuid(),
  name        text not null,
  created_by  uuid not null references auth.users(id),
  created_at  timestamptz not null default now()
);

create table public.members (
  id           uuid primary key default gen_random_uuid(),
  ensemble_id  uuid not null references public.ensembles(id) on delete cascade,
  user_id      uuid not null references auth.users(id) on delete cascade,
  role         text not null check (role in ('admin', 'player')),
  -- The seat: a part name that matches parts.name on the ensemble's scores ("Violin II", "Viola").
  part         text,
  display_name text,
  created_at   timestamptz not null default now(),
  unique (ensemble_id, user_id)
);
create index members_user on public.members(user_id);

-- Whoever creates an ensemble is its first admin.
create or replace function public.handle_new_ensemble() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.members (ensemble_id, user_id, role)
  values (new.id, new.created_by, 'admin')
  on conflict do nothing;
  return new;
end $$;
create trigger on_ensemble_created after insert on public.ensembles
  for each row execute function public.handle_new_ensemble();

-- Role helpers. SECURITY DEFINER so policies on members can call them without recursing.
create or replace function public.is_member(e uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from members where ensemble_id = e and user_id = auth.uid());
$$;

create or replace function public.is_admin(e uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from members where ensemble_id = e and user_id = auth.uid() and role = 'admin');
$$;

create or replace function public.my_member_id(e uuid) returns uuid
language sql stable security definer set search_path = public as $$
  select id from members where ensemble_id = e and user_id = auth.uid();
$$;

create or replace function public.my_part(e uuid) returns text
language sql stable security definer set search_path = public as $$
  select part from members where ensemble_id = e and user_id = auth.uid();
$$;

-- ---------------------------------------------------------------- scores (owned by a user or an ensemble)

create table public.scores (
  id             uuid primary key default gen_random_uuid(),
  owner_user_id  uuid references auth.users(id) on delete cascade,
  ensemble_id    uuid references public.ensembles(id) on delete cascade,
  title          text not null,
  composer       text,
  work           text,
  folder         text not null default '',
  status         text not null default 'uploaded'
                 check (status in ('uploaded', 'ordering', 'processing', 'ready', 'failed')),
  progress       real,
  failure_reason text,
  key_sig        text,
  meter          text,
  bars           int,
  duration_sec   int,
  tempo_bpm      int,
  pages          int,
  brief          text,
  -- Which interpretation the client reads placements from.
  current_interpretation_id uuid,
  created_by     uuid not null references auth.users(id),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  check ((owner_user_id is null) <> (ensemble_id is null))
);
create index scores_ensemble on public.scores(ensemble_id);
create index scores_owner on public.scores(owner_user_id);
create trigger scores_updated before update on public.scores for each row execute function public.set_updated_at();

create or replace function public.can_read_score(s uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from scores
    where id = s and (owner_user_id = auth.uid() or (ensemble_id is not null and is_member(ensemble_id)))
  );
$$;

create or replace function public.can_edit_score(s uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from scores
    where id = s and (owner_user_id = auth.uid() or (ensemble_id is not null and is_admin(ensemble_id)))
  );
$$;

-- ---------------------------------------------------------------- source layer

create table public.sources (
  id           uuid primary key default gen_random_uuid(),
  score_id     uuid not null references public.scores(id) on delete cascade,
  kind         text not null check (kind in ('pdf', 'images', 'musicxml')),
  -- Paths in the `scores` bucket: scores/{score_id}/... One per file.
  storage_paths text[] not null default '{}',
  -- Reading order of pages as indexes into the rasterised page set (1-based). Null until committed.
  page_order   int[],
  page_count   int,
  meta         jsonb not null default '{}',
  created_by   uuid not null references auth.users(id),
  created_at   timestamptz not null default now()
);
create index sources_score on public.sources(score_id);

-- ---------------------------------------------------------------- interpretation layer

create table public.interpretations (
  id          uuid primary key default gen_random_uuid(),
  score_id    uuid not null references public.scores(id) on delete cascade,
  source_id   uuid references public.sources(id) on delete set null,
  version     int not null default 1,
  engine      text not null,   -- 'musicxml' | 'opencv-geometry+spark-labels' | 'omr'
  status      text not null default 'queued'
              check (status in ('queued', 'running', 'done', 'failed', 'needs_review')),
  params      jsonb not null default '{}',
  summary     jsonb not null default '{}',
  cost_usd    numeric(10,6) not null default 0,
  latency_ms  int,
  created_at  timestamptz not null default now(),
  finished_at timestamptz,
  unique (score_id, version)
);

alter table public.scores
  add constraint scores_current_interpretation_fk
  foreign key (current_interpretation_id) references public.interpretations(id) on delete set null;

create table public.parts (
  id          uuid primary key default gen_random_uuid(),
  score_id    uuid not null references public.scores(id) on delete cascade,
  name        text not null,
  position    int not null default 0,
  difficulty  smallint check (difficulty between 1 and 5),
  -- Path in the bucket of a per-part MusicXML, when one exists (Path A).
  storage_path text,
  created_at  timestamptz not null default now(),
  unique (score_id, name)
);

-- Stable identity: one row per (score, number, part). Reprocessing never deletes rows here.
create table public.measures (
  id        uuid primary key default gen_random_uuid(),
  score_id  uuid not null references public.scores(id) on delete cascade,
  number    int not null,              -- 1-based musical measure number; pickup = 0
  part      text,                      -- null = whole score / all parts
  label     text,                      -- printed label if it differs ("9", "A", "1 bis")
  created_at timestamptz not null default now(),
  unique nulls not distinct (score_id, number, part)
);

create table public.measure_placements (
  interpretation_id uuid not null references public.interpretations(id) on delete cascade,
  measure_id        uuid not null references public.measures(id) on delete cascade,
  page              int not null,      -- 1-based index into sources.page_order
  system            int,               -- 1-based system index on that page
  box               jsonb not null,    -- {x0, y0, x1, y1} as fractions 0..1 of the page image
  confidence        text not null default 'high' check (confidence in ('high', 'medium', 'low')),
  flag              text,
  rehearsal_mark    text,
  primary key (interpretation_id, measure_id)
);
create index placements_measure on public.measure_placements(measure_id);

-- ---------------------------------------------------------------- collaboration layer

create table public.annotations (
  id                 uuid primary key default gen_random_uuid(),
  score_id           uuid not null references public.scores(id) on delete cascade,
  kind               text not null
                     check (kind in ('marking', 'cut', 'voice', 'text', 'dynamic', 'bowing', 'breath')),
  measure_from       uuid not null references public.measures(id) on delete cascade,
  measure_to         uuid not null references public.measures(id) on delete cascade,
  audience           text not null default 'ensemble' check (audience in ('ensemble', 'part', 'member')),
  audience_part      text,
  audience_member_id uuid references public.members(id) on delete cascade,
  author_id          uuid not null references auth.users(id) on delete cascade,
  status             text not null default 'live' check (status in ('proposed', 'live')),
  body               text,             -- text of a note, transcript of a voice note, pencil symbol
  audio_path         text,             -- bucket path of the recording for kind = 'voice'
  payload            jsonb not null default '{}',
  session_id         uuid,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  check (audience <> 'part' or audience_part is not null),
  check (audience <> 'member' or audience_member_id is not null)
);
create index annotations_score on public.annotations(score_id);
create trigger annotations_updated before update on public.annotations for each row execute function public.set_updated_at();

create table public.rehearsal_sessions (
  id           uuid primary key default gen_random_uuid(),
  ensemble_id  uuid not null references public.ensembles(id) on delete cascade,
  score_id     uuid references public.scores(id) on delete set null,
  started_by   uuid not null references auth.users(id),
  started_at   timestamptz not null default now(),
  ended_at     timestamptz,
  -- Live position pushed to every stand during the session.
  state        jsonb not null default '{}',
  updated_at   timestamptz not null default now()
);
create index sessions_ensemble_open on public.rehearsal_sessions(ensemble_id) where ended_at is null;
create trigger sessions_updated before update on public.rehearsal_sessions for each row execute function public.set_updated_at();

alter table public.annotations
  add constraint annotations_session_fk
  foreign key (session_id) references public.rehearsal_sessions(id) on delete set null;

-- ---------------------------------------------------------------- jobs (durable; the API process polls them)

create table public.jobs (
  id           uuid primary key default gen_random_uuid(),
  kind         text not null,          -- 'import_musicxml' | 'process_pages' | 'transcribe_voice' | ...
  status       text not null default 'queued' check (status in ('queued', 'running', 'done', 'failed')),
  progress     real not null default 0,
  attempts     int not null default 0,
  max_attempts int not null default 3,
  error        text,
  payload      jsonb not null default '{}',
  result       jsonb not null default '{}',
  score_id     uuid references public.scores(id) on delete cascade,
  created_by   uuid references auth.users(id) on delete set null,
  run_after    timestamptz not null default now(),
  locked_at    timestamptz,
  created_at   timestamptz not null default now(),
  started_at   timestamptz,
  finished_at  timestamptz,
  updated_at   timestamptz not null default now()
);
create index jobs_queue on public.jobs(run_after) where status = 'queued';
create index jobs_score on public.jobs(score_id);
create trigger jobs_updated before update on public.jobs for each row execute function public.set_updated_at();

-- The worker claims one job at a time; SKIP LOCKED makes several workers safe.
create or replace function public.claim_job() returns public.jobs
language plpgsql security definer set search_path = public as $$
declare j public.jobs;
begin
  select * into j from jobs
  where status = 'queued' and run_after <= now()
  order by created_at
  for update skip locked
  limit 1;
  if j.id is null then return null; end if;
  update jobs set status = 'running', attempts = attempts + 1, locked_at = now(), started_at = coalesce(started_at, now())
  where id = j.id returning * into j;
  return j;
end $$;

-- ---------------------------------------------------------------- spend: shared hard cap, per-user reporting

create table public.spend (
  id         int primary key check (id = 1),
  cap_usd    numeric(10,4) not null default 60,
  spent_usd  numeric(10,4) not null default 0,
  updated_at timestamptz not null default now()
);
insert into public.spend (id) values (1);

create table public.usage_events (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid references auth.users(id) on delete set null,
  job_id        uuid references public.jobs(id) on delete set null,
  provider      text not null,         -- 'meta' | 'anthropic'
  model         text not null,
  kind          text not null,         -- 'spark' | 'sam' | 'voice' | 'claude'
  input_tokens  int not null default 0,
  output_tokens int not null default 0,
  units         real not null default 0,  -- images, audio seconds, when tokens do not apply
  cost_usd      numeric(10,6) not null,
  created_at    timestamptz not null default now()
);
create index usage_user on public.usage_events(user_id, created_at);

-- One transaction, one row lock: the shared counter can never be overspent by concurrent calls.
-- Returns the new totals. Never refuses (the call already happened); the API refuses *before* calling a model.
create or replace function public.charge_usage(
  p_user_id uuid, p_provider text, p_model text, p_kind text,
  p_input_tokens int, p_output_tokens int, p_units real, p_cost_usd numeric, p_job_id uuid default null
) returns table (shared_spent numeric, shared_cap numeric, user_spent numeric, user_budget numeric)
language plpgsql security definer set search_path = public as $$
begin
  update spend set spent_usd = spent_usd + p_cost_usd, updated_at = now() where id = 1
    returning spent_usd, cap_usd into shared_spent, shared_cap;
  update profiles set spent_usd = spent_usd + p_cost_usd where id = p_user_id
    returning spent_usd, budget_usd into user_spent, user_budget;
  insert into usage_events (user_id, job_id, provider, model, kind, input_tokens, output_tokens, units, cost_usd)
    values (p_user_id, p_job_id, p_provider, p_model, p_kind, p_input_tokens, p_output_tokens, p_units, p_cost_usd);
  return next;
end $$;

-- ---------------------------------------------------------------- row level security

alter table public.profiles            enable row level security;
alter table public.ensembles           enable row level security;
alter table public.members             enable row level security;
alter table public.scores              enable row level security;
alter table public.sources             enable row level security;
alter table public.interpretations     enable row level security;
alter table public.parts               enable row level security;
alter table public.measures            enable row level security;
alter table public.measure_placements  enable row level security;
alter table public.annotations         enable row level security;
alter table public.rehearsal_sessions  enable row level security;
alter table public.jobs                enable row level security;
alter table public.spend               enable row level security;   -- no policies: service role only
alter table public.usage_events        enable row level security;

-- profiles: read your own. Budget edits happen in the dashboard.
create policy profiles_select on public.profiles for select to authenticated using (id = auth.uid());
-- No update policy: budget and spend are written by the dashboard and the service role only.

-- ensembles: members read; anyone signed in may create one (and becomes its admin); admins edit.
create policy ensembles_select on public.ensembles for select to authenticated using (is_member(id) or created_by = auth.uid());
create policy ensembles_insert on public.ensembles for insert to authenticated with check (created_by = auth.uid());
create policy ensembles_update on public.ensembles for update to authenticated using (is_admin(id));
create policy ensembles_delete on public.ensembles for delete to authenticated using (is_admin(id));

-- members: everyone in the ensemble sees the roster; admins manage it.
create policy members_select on public.members for select to authenticated using (is_member(ensemble_id));
create policy members_insert on public.members for insert to authenticated with check (is_admin(ensemble_id));
create policy members_update on public.members for update to authenticated using (is_admin(ensemble_id));
create policy members_delete on public.members for delete to authenticated using (is_admin(ensemble_id) or user_id = auth.uid());

-- scores: owner or member reads; owner or admin writes. Written on the row's own columns, not through
-- can_read_score(id): a stable function cannot see the row an INSERT ... RETURNING is returning.
create policy scores_select on public.scores for select to authenticated
  using (owner_user_id = auth.uid() or (ensemble_id is not null and is_member(ensemble_id)));
create policy scores_insert on public.scores for insert to authenticated
  with check (created_by = auth.uid() and (owner_user_id = auth.uid() or (ensemble_id is not null and is_admin(ensemble_id))));
create policy scores_update on public.scores for update to authenticated
  using (owner_user_id = auth.uid() or (ensemble_id is not null and is_admin(ensemble_id)));
create policy scores_delete on public.scores for delete to authenticated
  using (owner_user_id = auth.uid() or (ensemble_id is not null and is_admin(ensemble_id)));

-- score children: read with the score, write with edit rights.
create policy sources_select on public.sources for select to authenticated using (can_read_score(score_id));
create policy sources_write  on public.sources for all    to authenticated using (can_edit_score(score_id)) with check (can_edit_score(score_id) and created_by = auth.uid());

create policy interpretations_select on public.interpretations for select to authenticated using (can_read_score(score_id));
create policy interpretations_write  on public.interpretations for all    to authenticated using (can_edit_score(score_id)) with check (can_edit_score(score_id));

create policy parts_select on public.parts for select to authenticated using (can_read_score(score_id));
create policy parts_write  on public.parts for all    to authenticated using (can_edit_score(score_id)) with check (can_edit_score(score_id));

create policy measures_select on public.measures for select to authenticated using (can_read_score(score_id));
create policy measures_write  on public.measures for all    to authenticated using (can_edit_score(score_id)) with check (can_edit_score(score_id));

create policy placements_select on public.measure_placements for select to authenticated
  using (exists (select 1 from public.interpretations i where i.id = interpretation_id and can_read_score(i.score_id)));
create policy placements_write on public.measure_placements for all to authenticated
  using (exists (select 1 from public.interpretations i where i.id = interpretation_id and can_edit_score(i.score_id)))
  with check (exists (select 1 from public.interpretations i where i.id = interpretation_id and can_edit_score(i.score_id)));

-- annotations: who sees what.
--   author always; admins and owners everything on their scores;
--   players: live notes addressed to the ensemble, to their part, or to them.
create or replace function public.can_see_annotation(a public.annotations) returns boolean
language sql stable security definer set search_path = public as $$
  select a.author_id = auth.uid()
      or can_edit_score(a.score_id)
      or (a.status = 'live' and can_read_score(a.score_id) and (
            a.audience = 'ensemble'
         or (a.audience = 'part'   and a.audience_part = my_part((select ensemble_id from scores where id = a.score_id)))
         or (a.audience = 'member' and a.audience_member_id = my_member_id((select ensemble_id from scores where id = a.score_id)))
      ));
$$;

create policy annotations_select on public.annotations for select to authenticated using (can_see_annotation(annotations));
-- Players may write notes to themselves only; admins and owners to anyone.
create policy annotations_insert on public.annotations for insert to authenticated
  with check (author_id = auth.uid() and can_read_score(score_id) and (
    can_edit_score(score_id)
    or (audience = 'member' and audience_member_id = my_member_id((select ensemble_id from scores where id = score_id)) and kind <> 'cut')
  ));
create policy annotations_update on public.annotations for update to authenticated
  using (author_id = auth.uid() or can_edit_score(score_id));
create policy annotations_delete on public.annotations for delete to authenticated
  using (author_id = auth.uid() or can_edit_score(score_id));

-- rehearsal sessions: members see, admins run.
create policy sessions_select on public.rehearsal_sessions for select to authenticated using (is_member(ensemble_id));
create policy sessions_insert on public.rehearsal_sessions for insert to authenticated with check (is_admin(ensemble_id) and started_by = auth.uid());
create policy sessions_update on public.rehearsal_sessions for update to authenticated using (is_admin(ensemble_id));

-- jobs: the API creates and runs them; people watch their own or their scores'.
create policy jobs_select on public.jobs for select to authenticated
  using (created_by = auth.uid() or (score_id is not null and can_read_score(score_id)));

-- usage: your own rows.
create policy usage_select on public.usage_events for select to authenticated using (user_id = auth.uid());

-- ---------------------------------------------------------------- realtime: notification only, the database is truth

alter publication supabase_realtime add table public.scores, public.annotations, public.jobs, public.rehearsal_sessions, public.interpretations, public.members;

-- ---------------------------------------------------------------- storage: one private bucket, paths scores/{score_id}/...

insert into storage.buckets (id, name, public, file_size_limit)
values ('scores', 'scores', false, 209715200)
on conflict (id) do nothing;

create policy scores_bucket_read on storage.objects for select to authenticated
  using (bucket_id = 'scores' and can_read_score(((storage.foldername(name))[1])::uuid));
create policy scores_bucket_insert on storage.objects for insert to authenticated
  with check (bucket_id = 'scores' and can_edit_score(((storage.foldername(name))[1])::uuid));
create policy scores_bucket_update on storage.objects for update to authenticated
  using (bucket_id = 'scores' and can_edit_score(((storage.foldername(name))[1])::uuid));
create policy scores_bucket_delete on storage.objects for delete to authenticated
  using (bucket_id = 'scores' and can_edit_score(((storage.foldername(name))[1])::uuid));
