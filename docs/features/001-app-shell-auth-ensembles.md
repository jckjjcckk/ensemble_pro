# 001 Web app shell, auth, ensembles, roles and permissions

Status: working (local stack verified end to end; hosted sign-in verified through `/me`; hosted UI not yet checked by CK) | Meta model: none.

## Purpose

The shell every other feature lives in: sign-in, the account's memberships, the context switcher (My
library / each ensemble), the library of score covers, the score and practice screens, and the row-level
permissions that decide who sees what. Roles and the sync model are decided in 000.

## What exists

Web (`web/`, Vite + React 19 + TypeScript, Tailwind v4, OpenSheetMusicDisplay 2.2, supabase-js, react-router
8, vite-plugin-pwa). Folio is the app at `/`; exploration 5 became `web/src/app/` on 2026-10-27:

| File | What |
|---|---|
| `web/src/App.tsx` | the router only |
| `web/src/app/App.tsx` | shell: routes `/`, `/scan`, `/score/:id`, `/practice`; loads a token set's fonts the first time it is chosen |
| `web/src/app/auth.tsx` | `AuthProvider`, `SignIn` (email + password only: accounts are created by hand, so no sign-up and no reset), `useAuth` |
| `web/src/app/data.tsx` | `useWorld`: members, ensembles, scores, parts through RLS; signed URLs for score files; Realtime row changes on scores/parts/members trigger a refetch; `importMusicXml` (feature 002) |
| `web/src/app/store.tsx` | app state, `WORDMARK = 'Folio'`, display setting; the store takes the world |
| `web/src/app/Library.tsx` | context switcher, folders of covers, information box (facts, read flags as counts, parts with holder and one-word difficulty, brief for admins, Open score / Practise / Order pages / Retake pages), dock with Resume practice and Scan pages, Import MusicXML for admins and owners |
| `web/src/app/ScoreDoc.tsx`, `ScoreStage.tsx`, `Ruler.tsx`, `marks.tsx`, `geometry.ts` | score screen (feature 010), margin notes, ruler, markings (feature 012) |
| `web/src/app/Practice.tsx` | practice screen, mock state (feature 014) |
| `web/src/app/Scan.tsx` | scan intake, mock draft (feature 002) |
| `web/src/app/Display.tsx` | display sheet: token set Instrument (default) or Bound, theme auto/light/dark, persisted as `folio.display`; Sign out lives here |
| `web/src/app/styles.css` | tokens; root class `.fo` |
| `web/src/mock/` | `data.ts`, `ScoreView.tsx`: the mock world still used by annotations, practice state, scan draft, presence |
| `web/src/lib/supabase.ts`, `lib/api.ts` | anon client; `apiHealth()` |
| `.claude/launch.json` (gitignored) | starts the web dev server for the in-app browser |

Roles in the UI: role is read from the membership of the ensemble that owns a score (`owner` for the personal
library). Only admin or owner can cut, import, order pages. Seats match parts by name. `members.role` admin
maps to the mock's "leader".

Database (`supabase/migrations/20261027120000_folio_schema.sql`, written and verified locally 2026-10-27,
pushed to the hosted project the same evening):

- `profiles` (trigger from `auth.users`, backfill; `budget_usd` default 10, `spent_usd`), `ensembles` (creator
  becomes admin by trigger), `members` (role admin|player, `part` = seat name), `scores` (owner user xor
  ensemble, status uploaded|ordering|processing|ready|failed, facts, `current_interpretation_id`), `sources`,
  `interpretations`, `parts`, `measures`, `measure_placements`, `annotations`, `rehearsal_sessions`, `jobs`,
  `spend`, `usage_events` (the last three in feature 007; records in 002 and 004).
- RLS on every table. Helper functions `is_member`, `is_admin`, `my_member_id`, `my_part`, `can_read_score`,
  `can_edit_score`, `can_see_annotation` are SECURITY DEFINER. Realtime publication: scores, annotations,
  jobs, rehearsal_sessions, interpretations, members. Private bucket `scores`, keys `{score_id}/...`,
  policies through `can_read_score` / `can_edit_score`.
- Lesson: a select policy must not go through a stable function that re-reads the same table
  (`INSERT ... RETURNING` cannot see its own row), so `scores` policies use the row's columns.

API (`api/app/`): `auth.py` `CurrentUser` (401 no or bad token, 403 no profile; JWKS path for hosted ES256
tokens, Supabase Auth for the local stack's HS256), `spend.py` `BudgetedUser` (402) (feature 007), `routes/me.py`
`GET /me` (account, memberships, what it may still spend), `routes/llm.py` `POST /llm/probe`.

Auth model: Supabase email + password, signups off in the dashboard, so the only accounts are the ones CK
creates by hand. That is the whitelist; no `allowed` column. No admin role in the app: the secret key and
the dashboard are the admin (reset = set `spent_usd` to 0; disable = set budget to 0).

Scripts and checks:

- `api/scripts/smoke_local.py` on the local Docker stack: ALL PASS, 50 checks (roster, score, measures, cut
  for the ensemble, bowing for Violin II only, player's private note, non-member sees nothing, storage
  read/write, job claim, charge, `/me`, 401/403/402). Creates the five demo users locally.
- `api/scripts/me_hosted.py`: admin signed in on the hosted project 2026-10-27, ES256 token verified against
  the JWKS, `/me` 200, budget 10, shared cap 60. Five profiles backfilled on the hosted project.
- `api/scripts/seed_hosted.py`: "Hart House Chamber Players" (admin = Ada Okafor / Viola; Lin Zhou Violin I,
  Noor Haddad Violin II, Inès Marchand Cello); piano has a personal library only; the three fixture scores
  seeded (commit 2c2a6b9).
- Checked in the in-app browser against the local stack: admin sign-in, covers, information box with parts
  and holders, score renders from a signed URL, browser import went queued to ready in under 8 s by
  Realtime, violin2 sees the Vn II badge and no import button. `npm run build` and `npx tsc -b --noEmit` pass.
  Checked at 1194x834 (both token sets, light and dark) and 834x1194.
- `docs/acceptance/touch.md`: twelve lines CK runs on a real iPad (not yet run).

## Groups: join codes and four actions (2026-10-28)

CK: no auth changes. A group has an 8-digit numeric join code, never rotated. Create, join, leave and delete, each
behind one confirmation box in the UI. Migration `supabase/migrations/20261028150000_ensemble_join_codes.sql`,
**applied to the local stack only** (`supabase migration up --local`), not hosted; `supabase db push` when CK says.

- `ensembles.join_code text not null unique`, check `join_code ~ '^[0-9]{8}$'`, default `new_join_code()`: eight
  digits from `gen_random_bytes` (leading zeros kept), redrawn until unused. Existing ensembles were backfilled.
- Reading it: the existing `ensembles_select` policy already lets every member (and the creator) read all columns of
  their own ensembles, so admin and players see the code with `select('id,name,join_code')`. Non-members see no row;
  the only way from a code to a group is `join_ensemble`.
- RPCs (supabase-js `supabase.rpc(name, args)` with the signed-in user's session; `security definer`,
  `set search_path = public`; execute revoked from `anon`, granted to `authenticated`):

| Call | Returns | Refusals (`error.message` / `error.hint`) |
|---|---|---|
| `create_ensemble(name text)` | the `ensembles` row (with `join_code`); the caller becomes admin through the existing trigger; retries a code collision | "Give the group a name of up to 80 characters." / `bad_name` (name trimmed) |
| `join_ensemble(code text)` | the ensemble's `uuid`; the caller is added as `player`; idempotent (an existing member keeps their role); spaces and dashes in the code are ignored | "A join code is 8 digits." / `bad_code`; "No group has the code 12345678. Check the digits with the group's admin." / `unknown_code` |
| `leave_ensemble(ensemble uuid)` | nothing | "You are not in this group." / `not_member`; "You are this group's only admin, so you cannot leave it. Make another member an admin first, or delete the group." / `last_admin` |
| `delete_ensemble(ensemble uuid)` | nothing; cascades to members, the group's scores (sources, interpretations, measures, parts, annotations, jobs) and rehearsal sessions | "Only an admin can delete this group." / `not_admin`; "This group no longer exists." / `not_found` |

  Every refusal is SQLSTATE P0001, which PostgREST answers with 400; any call without a session gets "Sign in ..."
  / `not_signed_in` (or 401 from PostgREST for the anon role). Branch on `hint`, show `message`.
- A group always keeps an admin: trigger `members_keep_an_admin` (before delete or role/ensemble change on
  `members`) refuses, with the same `last_admin` message, the last admin deleting their own membership or demoting
  themselves straight through REST, which `members_delete` / `members_update` would otherwise allow. It stands
  aside for the ensemble's own cascade and for the service role (auth.uid() null), so deleting an account still works.
- Not removed by `delete_ensemble`: the deleted scores' files in the `scores` bucket (storage objects go through the
  Storage API). The browser can list `{score_id}/` and remove them first, or a later API route can.
- Tests `api/tests/test_groups_local.py` (local stack; skipped when it is down or the migration is not applied):
  three throwaway accounts `groups-a/b/c@muse.test` with a fresh password per run, made with the service-role
  client, call the RPCs through the anon key as the browser does; create, join twice, unknown and malformed codes,
  stranger sees nothing, last admin refused by RPC, direct delete and direct demotion, a second admin may leave,
  delete refused for a player and a non-member, cascade to members and a score, anon refused, a direct insert
  still gets a code, the check and unique constraints, codes spread. 3 tests, pass.

## Rules and decisions

- Secrets only in `api/.env`; the browser gets only `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`,
  `VITE_API_URL`.
- The Supabase DB password is known only to CK. Never delete hosted data without CK's explicit approval.
- Themes are tokens only; one layout. iPad-first rules in 000 are binding.
- Public repo from day 0 (CK). No PRs; CK is the only reviewer; push only when CK says.

## Open issues

- Groups: the migration is local only; the UI (create, join by code, show the code to the admin, leave, delete,
  one confirmation each) is not built. Join codes have no attempt limit: 10^8 codes, so guessing one takes
  millions of signed-in calls, but a rate limit would close it.

- Not checked on a real iPad yet (CK runs `touch.md`). Not checked on the hosted project from the UI (CK
  signs in at :5173 and imports `web/public/fixtures/beethoven-op18no1-mv1.musicxml` into Hart House).
- Not built: chrome hide/show on tap with a visible handle in document mode (PRODUCT.md rule 7).
- Still mock: annotations, practice state, scan draft, presence. Practice and Scan read mock score ids.
- `scores.status` lacks `needs_review`: the badge should read `interpretations.status` or the check extended.
- Teammates: nobody yet; onboarding = add a Supabase user, share the repo; each claims their own $150 credits.

## Next steps

1. CK: hosted UI check and `touch.md` on the iPad.
2. Waiting state for the score badge; answer route for parked jobs (feature 011).
3. Replace the remaining mock state as features 012, 013, 014 land.
