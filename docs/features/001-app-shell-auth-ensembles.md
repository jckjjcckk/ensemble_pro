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

### Groups in the app (web, 2026-10-28)

"Ensemble" is "group" on every screen; tables and code keep `ensembles`. `web/src/app/Groups.tsx` (+ `groups.css`),
the RPC wrappers `createGroup`, `joinGroup`, `leaveGroup`, `deleteGroup` in `data.tsx` (a refusal with a `hint`
shows its `message` as is; anything else, such as a signed-out call or a missing function, becomes a sentence).

- **The group shelf** (the library switcher row, when a group is open) carries a people control, "5 people", that
  opens `/group`: the group sheet. It shows the group's name, the join code in two groups of four digits at 54 px
  (the measurement face, read out across a room; from `ensembles.join_code`, loaded with `select('*')` so a stack
  without the column still works), the members with their parts and Admin, then Leave group and, for an admin,
  Delete group. Each opens one confirmation box in place of the sheet's foot (Cancel / the red action), and the
  RPC's sentence shows in that box when it refuses (last admin, not admin). Leaving or deleting returns the library
  to My library.
- **The library's top level** carries Create a group (a name, then the new code large with "Read it out") and Join a
  group (one field, `inputMode="numeric"`, digits only, shown as "4820 1937"; the button wakes at eight digits).
  A group made or joined opens as soon as the reloaded world has it. Below 780 px both show as 44 pt icons.
- **The Group place** in the dock (`/group`) opens the open group's sheet, or, from My library, a start sheet: your
  groups (tap to open one), Create, Join.
- Verified on fake data only (a temporary `?view=harness` route, removed): sheet faces, the confirmation box, the
  refusal sentence for a signed-out call, 1024x768 light and 768x1024 dark. Not seen against a signed-in account.

## Sharing a book with a group (2026-10-28)

CK asked for "share a book to a group": does it copy, or share permission to view the personal file, and it does
not share the annotations? Decision: **share by reference, not a copy and not a move.** The book stays in its owner's
personal library; a `score_shares` row lets one group read it; unsharing removes the row and the group stops seeing
it at once. Migration `supabase/migrations/20261028200000_score_shares.sql`, **applied to the local stack only**.

Policy rules in plain words:

- **Reading the book.** The owner, members of the group that owns it (a group's book), and members of every group it
  is shared with read the score, its sources, parts, measures, readings, placements, jobs and the files under
  `{score_id}/` in the bucket. All of them go through `can_read_score`, which now also asks `is_shared_with_me`
  (SECURITY DEFINER, so `scores` and `score_shares` policies can ask each other without recursing); `scores_select`
  adds `is_shared_with_me(id)` to its column rules.
- **Writing the book** (import, split, convert, export from the API, delete, sources, parts, measures rows, files)
  is unchanged: `can_edit_score`, the owner of a personal book or an admin of the group that owns a group's book. A
  share gives no write, whatever the reader's role in the group.
- **Only personal books are shared, only by their owner, only into a group the owner is in.** A trigger refuses a
  share of a group's book on every path. When the owner leaves a group (or is removed), the shares of their books
  there are deleted (trigger `members_drop_shares`). Deleting the book or the group deletes its shares.
- **Marks are layers.** `annotations.ensemble_id` and `scribbles.ensemble_id` (new, nullable, cascade with the group)
  name the group a mark is addressed to; the layer is `coalesce(mark.ensemble_id, scores.ensemble_id)`.
  - Personal book, `ensemble_id` null: the owner's **private** layer, read and written by the owner only, before and
    after any share. A group never sees it.
  - Personal book, `ensemble_id = g`: group g's layer on that book, readable while the book is shared with g by
    members of g, with the audience rules counted inside g (ensemble, g's seat, g's member row). Any member writes
    what a player may write (a live highlight for the group; a note, bowing or pencil to themselves as `member`
    audience; never a cut); an **admin of g leads the layer** (writes to anyone, cuts, sees and removes every mark),
    exactly as on the group's own books. The book's owner is an ordinary member in g's layer.
  - A group's own book: null means the book's group, as before, so every existing row behaves as today. A mark
    written with `ensemble_id` = the book's own group is stored as null (trigger `normalise_mark_group`): one layer,
    one scribble row per page, part and author.
  - Unsharing hides g's layer and keeps it; sharing again brings it back. A mark's author always reads their own mark.
- Helpers: `score_owner`, `is_shared_with_me`, `mark_group`, `can_read_layer`, `can_lead_layer`, `may_write_mark`.
  `can_see_annotation` and the four annotation policies and three scribble policies are rewritten on them; the update
  policy now also checks the new row (an author can no longer move a note into another layer or make a private note
  public by an update). Realtime publication gains `score_shares`.
- Storage policies hardened in the same migration, same rules: the key's first folder goes through
  `score_folder(key)` (null when it is not a uuid) before `can_read_score` / `can_edit_score`. Two stray keys on the
  local stack (`scores/ed1c9897…/pages/n.png`) made every listing of the bucket fail for everyone, the owner included
  ("invalid input syntax for type uuid"), which broke Open PDF's page listing locally.

RPCs (`security definer`, execute for `authenticated` only; refusals SQLSTATE P0001 / PostgREST 400, sentence in
`message`, key in `hint`, like the group RPCs):

| Call | Returns | Refusals (`message` / `hint`) |
|---|---|---|
| `share_score(score uuid, ensemble uuid)` | the `score_shares` row (`score_id`, `ensemble_id`, `shared_by`, `created_at`); sharing twice returns the same row | "This book no longer exists." / `not_found` (missing or not readable); "A group's book stays with its group. Only a book in your own library can be shared." / `not_owner`; "Only the book's owner can share it." / `not_owner`; "This group no longer exists." / `not_found`; "You are not in this group." / `not_member`; "Sign in first." / `not_signed_in` |
| `unshare_score(score uuid, ensemble uuid)` | nothing; idempotent | "This book no longer exists." / `not_found`; "Only the book's owner can stop sharing it." / `not_owner` |

`score_shares` RLS: members of the group and the book's owner read; the owner inserts (as `shared_by`, and must be a
member of the group) and deletes; no updates.

**For the reader (ScoreDoc, ink.ts):** write `ensemble_id` on every annotation and scribble from
`useStore().markGroupFor(score)` (null on a group's own book and for the owner in their own library; the group's id
when a shared book is open from that group's shelf). Filter reads by the same layer (`.is('ensemble_id', null)` or
`.eq('ensemble_id', g)`): the owner of a shared book can read their private layer and every group layer they are in,
so an unfiltered select mixes them. **Breaking:** the scribbles unique key is now
`(score_id, page, part, user_id, ensemble_id)`, so the upsert must say
`onConflict: 'score_id,page,part,user_id,ensemble_id'`; the old four-column `onConflict` gets 42P10. Someone else's
shared book arrives with `ensembleId` = the first of the account's groups it is shared with, so `contextFor` gives the
account's role there; use `useStore().canEditBook(score)` for anything that changes the book itself.

Verified on the local stack:

- SQL as owner (piano), members of the group (violin2, cello), its admin, and a non-member (groups-c), in one
  rolled-back transaction: 47 of 47 checks, plus every expected refusal (not_member, not_owner, not_found, RLS on
  `score_shares`, `sources`, `parts`, `annotations`, `scribbles`, 42501 from `measure_ids`).
- The browser's PostgREST and Storage calls from Node with supabase-js, the anon key and locally minted HS256 user
  JWTs (fixtures by the service role, removed after): 51 of 51, including signed URLs and page listing for the
  member, no write for the member, Realtime INSERT and DELETE on `score_shares` heard by the member, the group layer
  written and filtered, the old scribble `onConflict` refused with 42P10.
- `api/scripts/smoke_local.py` ALL PASS and `api/tests/test_groups_local.py` 3 passed after the migration.

### Sharing in the app (web, 2026-10-28)

- `data.tsx` loads `score_shares` with the world (`World.shares`, `World.owners`), listens to it on Realtime, and
  wraps the RPCs as `shareBook` / `unshareBook`. A shared book read by someone else gets `ensembleId` = their first
  group it is shared with (never My library). `store.tsx` adds `sharesFor`, `canEditBook`, `markGroupFor`;
  `book.ts` adds `bookShare` (the dot and tags are unchanged: they read the book's own rows, which a share opens).
- **The book page** of a personal book carries **Share with a group** under Split by instrument and Export, and a
  quiet "Shared with Hart House Chamber Players" line. It opens a raised sheet (`ShareSheet` in `Groups.tsx`): the
  account's groups, one row each, the whole row a switch drawn in ink. Off to on shares at once; on to off opens one
  confirmation box in the sheet's foot ("Stop sharing with …? The group stops seeing this book at once. What its
  members marked on it is kept, and comes back if you share it again."). A refusal shows its sentence.
- **The group shelf** shows the group's books in their folders, then a folder **Shared with the group** with a quiet
  "Shared by Lin Zhou" ("Shared by you" for the account's own) under the cover's meta. For someone else's book the
  page and the "…" menu offer only Open PDF / Open Digital: no Split, Convert, Export, Order or Retake pages, no
  Share; its page says "Shared by Lin Zhou from their own library", and a question waiting on it says "Its owner
  answers it." The owner's own cover in My library carries a small people mark (VoiceOver: "shared with …").
- Seen on fake data through a temporary `?view=harness` route (removed before commit) at 1194x834 light and 834x1194
  dark: owner's library and book page, the share sheet, the stop-sharing box, a refused share, the member's group
  shelf, a borrowed PDF and Digital book page and its menu. Not seen signed in against the local stack.

### Three places (web, 2026-10-28)

CK: Library, Book, Group; not five tabs. The dock's area nav (`layout.tsx`) is Library `/`, Book (the last book
opened, kept in `localStorage` `folio.book`: a score, its PDF pages or practice; else the first readable book here;
dimmed until there is one) and Group `/group`. Read and Practise are a segmented toggle at the right of the reader's
header (`BookModes`, shown on `/score/:id` and `/practice`; it replaces the history entry). Practise goes to
`/practice?score={id}`; the practice screen still reads its mock state, the id is there for it. The standalone back
control, 44 pt targets, pressed states and sheet springs are unchanged.

## Rules and decisions

- Secrets only in `api/.env`; the browser gets only `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`,
  `VITE_API_URL`.
- The Supabase DB password is known only to CK. Never delete hosted data without CK's explicit approval.
- Themes are tokens only; one layout. iPad-first rules in 000 are binding.
- Public repo from day 0 (CK). No PRs; CK is the only reviewer; push only when CK says.

## Open issues

- Sharing: migration local only, not hosted. The share sheet and the shelves are not yet seen signed in. The reader
  does not yet write or filter `ensemble_id` (another agent), and its scribble upsert must move to the five-column
  `onConflict` before this migration reaches a stack it runs against. "Shared by" uses the sharer's
  `members.display_name`, which is empty on the local seed ("a member"). The cover foot overlaps a part badge and the
  tag at 834 px portrait (seen on the Beethoven's "Vn II"; not caused by sharing).
- Groups: the migration is local only; the UI is built but not yet run signed in (create, join, leave, delete on the
  local stack). Join codes have no attempt limit: 10^8 codes, so guessing one takes millions of signed-in calls, but
  a rate limit would close it. The admin cannot yet give a member a part or make them admin from the sheet.
- `auth.tsx` still says "the ensemble's admin" on the sign-in card (left alone by CK's rule: no auth changes).

- Not checked on a real iPad yet (CK runs `touch.md`). Not checked on the hosted project from the UI (CK
  signs in at :5173 and imports `web/public/fixtures/beethoven-op18no1-mv1.musicxml` into Hart House).
- Not built: chrome hide/show on tap with a visible handle in document mode (PRODUCT.md rule 7).
- Still mock: annotations, practice state, scan draft, presence. Practice and Scan read mock score ids.
- Teammates: nobody yet; onboarding = add a Supabase user, share the repo; each claims their own $150 credits.

## Next steps

1. CK: hosted UI check and `touch.md` on the iPad.
2. Waiting state for the score badge; answer route for parked jobs (feature 011).
3. Replace the remaining mock state as features 012, 013, 014 land.
