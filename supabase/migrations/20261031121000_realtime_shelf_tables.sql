-- The shelf listens to parts, sources and ensembles too (web/src/app/data.tsx, useWorld), but they were never in the
-- Realtime publication. Realtime then delivers nothing at all on a channel that binds a table outside the publication,
-- not even the rows of the tables inside it, so the iPad heard no row change: a job's progress, an answered question
-- resuming, a finished split or reading showed only after the next manual reload (found 2026-10-31 on the local stack;
-- the pianist's 3.5 minutes of a stale question). RLS still decides which rows reach whom.
do $$
declare t text;
begin
  foreach t in array array['parts', 'sources', 'ensembles'] loop
    if not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = t) then
      execute format('alter publication supabase_realtime add table public.%I', t);
    end if;
  end loop;
end $$;
