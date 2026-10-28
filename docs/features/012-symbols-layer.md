# 012 Symbols layer: one record type for every mark

Status: prototype (quick marks and scribbles on the score screen; item 5 built 2026-10-28: marks, cuts and scribbles arrive on every stand live from Realtime row changes, presence faces with bars, Follow the admin, reconnect resync; Realtime measured at p50 0.47 s, max 0.48 s from a script on the local stack; not seen between two signed-in browsers or on iPads; local stack only, migrations not on the hosted project; rehearsal sessions not built) | Meta model: Muse Spark 1.3 proposes marks from voice notes (013); the layer itself uses none, and scribbles are never interpreted.

## Purpose

Everything anyone adds to a score, by hand or by a model, is a symbol: pencil marking, cut, dynamic, bowing,
breath, text note, voice note, comment. One record type, so every mark can be shown, filtered, removed,
edited and undone the same way, whoever or whatever made it.

## The design

One record for every mark, including comments:

| Field | Values |
|---|---|
| `kind` | marking, cut, voice, text, dynamic, bowing, breath, comment |
| `measure_from`, `measure_to` | stable `measures.id` (never an interpretation row), so a reprocess keeps the mark |
| `author` | a **person** (member) or a **job** (the librarian run that proposed it) |
| `audience` | ensemble, part, member; **default by kind** (a cut defaults to ensemble, a bowing to the part, a text note to the member who wrote it) |
| `state` | proposed, live |
| `body`, `audio_path`, `payload`, `session_id` | the content; the rehearsal session it was made in |

Rules: all AI and human marks live together in the one table; every mark is individually removable,
editable and undoable; a proposed mark goes live only when the admin confirms (voice proposals, 013); marks
sync quietly outside a rehearsal session and push live during one (000 sync model); personal marks and
ensemble marks are separate audiences of the same type, never mixed into one view by accident.

What the schema has today (`annotations`, migration 20261027120000): `kind` marking | cut | voice | text |
dynamic | bowing | breath; `measure_from/to` → `measures.id`; `audience` ensemble | part | member with
`audience_part` / `audience_member_id`; `author_id` → `auth.users`; `status` proposed | live; `body`,
`audio_path`, `payload`, `session_id`; `can_see_annotation` policy. Deltas the design needs: a `comment`
kind, an author that can be a job (`author_job_id`), audience defaults by kind, and an undo history (or
soft delete with `deleted_at`).

## Quick marks: tap a bar (2026-10-28)

CK: "the current marking is too complicated. Nobody goes to marking settings and provides the exact measure
number." So a player marks from the music, never from a form:

- **A short tap on a bar** opens a small menu anchored on that bar (`MarkMenu.tsx`; scale 0.96 to 1 and fade,
  180 ms in, 120 ms out, the `Pop` of `Sheet.tsx`): **Highlight**, **Note**, **Scribble**, and in practice
  **Loop from here** (keeps the loop's length, else 4 bars, and moves the playhead there). The tapped bar is
  washed in ink while the menu is open. Below the bar when it fits above the page foot and the keyboard, above
  it otherwise.
- **Highlight** toggles the reader's own highlight on that bar: a highlighter wash under the notes
  (`--mark`), seen by the whole ensemble. Other people's highlights on the bar stay.
- **Note** opens a one-line field under the menu with the keyboard; Return (or Save) saves. A quick note is
  personal (audience `member`), shown in the margin or as a pin like every text note.
- **A tap on a bar that carries marks** opens the same menu with the marks listed first (what, who, "only you
  see it" for a personal note) and **Remove** on the ones the reader may remove (their own; an admin or owner
  any).
- The menu is the only thing a tap produces. A tap anywhere else closes it and is spent (it does not open a
  menu on the bar under it, it does not turn the page); Escape closes it; a swipe still turns the page.
- **Press and hold** still opens the full composer on the held bar, now with the bar shown, not a bar field.
- **The dock** of a player carries the part switch and one line ("Tap a bar to highlight it, write a note or
  draw on the page."). The composer with its bar stepper, the cut and the voice note are the admin's (and the
  library owner's) instruction tools in the dock. Composer markings and cuts now write the same rows.

Record shape (what the collaboration item will push live). A highlight:

```
annotations { score_id, kind: 'highlight', measure_from = measure_to = measures.id of the bar,
              audience: 'ensemble', author_id, status: 'live', body: null,
              payload: { bar, bar_to, part: <parts.name on screen or null>, via: 'quick' } }
```

A quick note is the same with `kind: 'text'`, `body: <the text>`, `audience: 'member'`,
`audience_member_id: <the author's member row>` (in a personal library, `audience: 'ensemble'`: only the
owner reads it). Composer markings keep their kinds; an admin's go to `ensemble` or `part`, a player's to
`member`.

Migration `20261028180000_quick_marks_scribbles.sql` (applied to the local stack only): `kind` admits
`highlight`; any reader of a score may insert a live ensemble highlight (players could only write notes to
themselves before; everything else unchanged); `measure_ids(score, numbers[])` returns the stable
`measures.id` of the bars, creating a missing whole-score row, for anyone who can read the score (players
cannot write `measures`). Policies checked as violin2 and cello: highlight for the ensemble allowed, a player's
text note to the ensemble refused, the cello sees the highlight and not the private note and cannot delete
it, a non-member reads nothing and gets no measure ids.

## Scribbles (2026-10-28)

Scribble turns the stage into a drawing surface (`InkLayer.tsx`): Pencil and finger, `touch-action: none` only
while scribbling, Pencil pressure when there is one. Once a Pencil has drawn, a finger or palm does not; a
second finger drops the stroke in progress. A small graphite bar floats at the foot of the stage: pen,
eraser (whole strokes), ink, red, blue (`--ink`, `--pen-red`, `--pen-blue`, with dark and Bound values),
Done (or Escape). The page-turn edges and the ruler still work. "We don't process drawings for now":
strokes are stored and synced, never read by a model.

Everyone's strokes on the score and part draw faintly (0.32), the reader's own at full ink, always, not only
while scribbling.

One row per (score, page as drawn, part, author) in `scribbles` (`id`, `score_id`, `page int` 1-based,
`part text null` = parts.name on screen or null for the full score, `user_id`, `strokes jsonb`, `updated_at`;
unique nulls not distinct; RLS: members and owners read, the author writes; in the Realtime publication).
`strokes` is an array of:

```
{ id, color: 'ink' | 'red' | 'blue', width: <fraction of page width>, aspect: <page h / w>,
  bar: <bar number under the pen at touch-down> | null, box: [x, y, w, h] of that bar,
  points: [[x, y, pressure], ...] }        // x, y fractions of the page, 4 places; RDP-simplified at 0.6 px
```

A digital score re-engraves on every rotation and resize, so the page a stroke was drawn on does not hold
the same bars afterwards. A stroke is therefore placed by its bar: the touch-down point keeps its relative
place in the bar, and the shape scales with the bar's height (the staff), never stretched. A stroke begun
within 40 px of the last one and within 6 s shares its bar, so a hairpin's two lines or a word move as one.
A stroke with no bar (a scanned page, later) sits on its page by fractions. Rows load with the score (all
pages of the part at once; they are small) and then stay live (item 5, below); the reader's pages save 3 s after a
stroke and at once on Done and on leaving the score or the part. The bar says Saving, Saved, or "Not saved,
retrying".

A score that is not in Supabase (the mock world, the practice screen) keeps marks and ink in memory for the
session behind the same functions (`ink.ts`), and the bar says "This device only".

Verified 2026-10-28 in the in-app browser (Chromium, 1194x834 and 834x1194) on a temporary harness that
mounted the real score and practice screens on the mock quartet without sign-in (removed before commit):
the tap menu, highlight, note with Return, marks with Remove, dismissal without a page turn, hold to the
composer without a bar field, admin dock tools, pen pressure, colours, eraser, palm rejection, strokes
following their bars through a rotation, Loop from here. The Supabase path was exercised with the same
PostgREST calls from a script as violin2 and cello (embed, `measure_ids`, insert, upsert with a null part).
Not seen: the signed-in screen end to end, Realtime between two devices, Safari, a real Pencil, the on-screen
keyboard over the note field.

## The cellist's feedback (carried as rules)

- Personal marks and ensemble marks must be separate. A player's own fingerings never appear on another
  stand; the leader's cut appears on every stand.
- Repeats, bar numbering and handwriting are what AI gets wrong, so the user fixes them: the layer must
  make fixing a mark as cheap as making one (tap, edit, remove, undo), and never lock a model's mark.

## What exists in the UI

`web/src/app/marks.tsx` and the score screen: text notes and voice transcripts in the outer margin level with
their bar (landscape at 1180 px and wider), pencil-like markings as pins, the marking composer on long-press,
the Markings panel in portrait, the cut at bars 227 to 246 and the seven mock annotations on the Beethoven.
Since 2026-10-28 the quick menu, highlights and scribbles below (`MarkMenu.tsx`, `InkLayer.tsx`, `ink.ts`,
`Ink.css`).
The smoke test (`smoke_local.py`) proves the policies: a cut for the ensemble, a bowing for Violin II only, a
player's private note, a non-member sees nothing.

## Build-queue item 5 (Oct 29): shared score, annotations, cuts, Realtime

Annotations on stable measure ids, audience rules, admin starts and ends a rehearsal session, cut
propagation, reconnect recovery (client keeps an `updated_at` cursor and refetches on reconnect). Done means:
a cut on the admin iPad shows on four stands in under 1 s; an iPad that drops wifi during the cut has it
after reconnect.

### Built 2026-10-28: live marks, presence, Follow

**Live marks.** The reader subscribes once per layer to row changes of `annotations`, `scribbles` and `presence`
for the open score (`useLiveRows` in `presence.ts`) and applies each insert, update and delete to its own state
(`useBarMarks`, `useScribbles` in `ink.ts`): no refetch per change, no engrave (only the overlay layers redraw; the
`score-engrave` performance mark count stays at 1 through every arrival). Realtime is the notification, the
database is the truth:

- A filtered `postgres_changes` subscription (`score_id=eq.X`) receives INSERT and UPDATE with the full row but
  **no DELETE** (Realtime cannot filter deletes). Deletes come from a second, unfiltered DELETE binding, which under
  RLS carries the primary key only (`{ id }`; `{ score_id, member_id }` for presence); the reader drops ids it holds.
  Measured on the local stack.
- A row from Realtime has no embedded bar numbers: they come from a `measures.id → number` cache learnt from every
  query, else from `payload.bar` / `payload.bar_to`, else the one row is fetched by id. A scribble row too large to
  travel (`errors` set, or no `strokes`) is refetched.
- Writes stay optimistic, with the uuid made on the device (`newId`, `getRandomValues`, since `randomUUID` needs a
  secure context and an iPad on the LAN over http is not one), so a mark and its own Realtime echo are one row.
- **Resync.** On every join of the channel (`SUBSCRIBED`, the first one included, which closes the gap between the
  first fetch and the subscription; then after `CHANNEL_ERROR` / `TIMED_OUT` / `CLOSED`, a wifi drop or a sleeping
  iPad, when the client rejoins on its own) the score's rows are fetched once and reconciled: the fetch replaces the
  list, marks written here and not yet confirmed are kept, marks being removed here are dropped, and changes that
  arrive while the fetch is in flight are held and applied on top of it. Nothing lost, nothing doubled.
- A mark, cut, highlight or stroke that arrives from someone else is drawn with a 200 ms opacity fade
  (`.is-arriving`, `Ink.css`; none under reduced motion); only arrivals, never a reload or a re-engrave.
- **Layers** (feature 001, `20261028200000_score_shares.sql`): every insert and upsert names
  `ensemble_id: useStore().markGroupFor(score)`, every read filters `.is('ensemble_id', null)` or
  `.eq('ensemble_id', g)`, and Realtime rows of another layer are ignored. The scribble upsert uses
  `onConflict: 'score_id,page,part,user_id,ensemble_id'`. A stack without the column (the hosted project until the
  share migration is pushed) is learnt from the first refusal (`PGRST204` / `42703` / `42P10`) and the reader goes
  on without it.

**Presence.** Migration `20261028210000_presence.sql` (applied to the local stack only):

```
presence { score_id → scores, member_id → members, ensemble_id (copied from the member row by a trigger, never
           from the client), user_id default auth.uid(), bar int ≥ 1, part text null (parts.name on screen),
           updated_at (set by the trigger on every write); primary key (score_id, member_id) }
RLS: select is_member(ensemble_id); insert / update user_id = auth.uid() and member_id = my_member_id(ensemble_id);
     delete own row. In the supabase_realtime publication.
```

`usePresence` writes the reader's place (the first bar on the spread, the part on screen) on every page turn, at
most once every 2 s (a turn inside the window is written when it closes), once a minute to stay fresh, and again
after a resync; on leaving the score (and on `pagehide`) it deletes its own row. Rows older than 10 minutes are
ignored on read and re-checked every 30 s; no cron. Presence exists for a score read in a group (a group's book, or
a shared book opened from the group's shelf), signed in.

**Faces.** The header shows the other members of that group, admin first, then whoever is reading: initials (or
the seat, "Va", "Vc", for an account without a display name) over the bar they are on, "off" when not reading. The
admin's face is filled ink. Each face is a 44 × 44 pt button; a tap shows that member's bar (touch.md line 8). Six
faces at most (three below 780 px), then "+n"; the Markings panel's "Reading now" lists everyone. The stage shows
small faces at each reader's bar and the ruler a tick.

**Follow.** Players only, default off, in the header: "Follow" with a dot that is green while following (green
means following, nothing else) and a hollow green ring while the admin is not reading the score. On, the spread
turns whenever the admin's bar leaves it (`ScoreStage`'s `follow` prop, the one the practice playhead uses). Any
turn of the player's own switches it off (swipe, turn buttons, arrow keys via the new `onUserTurn`; the ruler, a
face or a marking via `jump`), so the page never moves under the player's hand; while the quick menu, the scribble
tools or the composer are open it holds still and catches up when they close.

**Measured** (script on the local Docker stack, locally minted JWTs for the local test accounts, the reader's own
subscription shape; scratchpad `live-verify.mjs`). Four stands on the quartet's score: the admin writes, Violin I,
Violin II and Cello listen.

| What | n | p50 | p95 | max |
|---|---|---|---|---|
| Admin's cut, insert request sent → event on each of three stands | 60 | 472 ms | 481 ms | 481 ms |
| Cut removed → delete event on each stand | 60 | 523 ms | 531 ms | 531 ms |
| Commit → arrival (Realtime alone) | 60 | 467 ms | 475 ms | 475 ms |
| Violin II scribble page saved (up to 25 KB row) → Cello | 5 | 424 ms | 435 ms | 435 ms |
| Admin page turn (presence upsert) → three stands | 30 | 460 ms | 463 ms | 463 ms |
| Admin leaves (own row deleted) → three stands | 3 | 437 ms | | |

Every cut reached every stand (0 of 20 missing). The latency is almost all Realtime's own polling of the WAL on
the local stack (commit → arrival ~0.47 s); the hosted project may differ. RLS on what arrives: Violin II's
highlight reached Cello; Violin II's private note did not (and did reach Violin II); Cello writing the admin's
presence row was refused (42501); a non-member read 0 presence rows. **A wifi drop:** the Cello's socket was closed;
the channel went `CHANNEL_ERROR` then `SUBSCRIBED` again after 1.0 s; a cut made while it was away did not arrive as
an event, the one refetch on rejoin had it exactly once, and the next change after the rejoin arrived (506 ms).
Found on the way: a Realtime client whose token is set once by hand rejoins with the publishable key after a drop
and then receives nothing under RLS; the browser is safe because supabase-js hands Realtime the session's token
through a callback on every join (the script now does the same).

**Seen in the UI** through a temporary harness (removed before commit): the real score screen at 1194 × 834 and
834 × 1194, on a fake quartet behind a fake PostgREST, with Realtime payloads injected into the reader's own change
handlers. An admin's cut, a Violin I highlight and a Cello scribble drew within one frame (26 ms) with the 200 ms
fade and no engrave; presence faces with bars, the admin's filled; Follow turned the spread to the admin's bar 60,
then 150, held still while the quick menu was open and caught up when it closed, switched off on a turn button,
after which the admin's next move did not turn the page; a tap on a face showed that bar; the reader's own highlight
and its Realtime echo stayed one row; during a simulated drop the admin removed a cut and added another, and the
resync left exactly the database's four marks. The request shapes the reader sends (insert with `ensemble_id` and
the bars embedded, the layer-filtered read, the five-column scribble upsert twice = one row, the presence upsert,
read and delete) were run as Violin II against the local stack.

**Not seen:** two signed-in browsers (the local accounts' password is CK's), Safari, an iPad, a real wifi drop
(the socket was closed by hand), more than four stands, the hosted project, a shared book's group layer end to end.

## Next steps

1. Migration for the remaining deltas (comment kind, job author, soft delete); `highlight` and `scribbles`
   are in 20261028180000. Apply it to the hosted project (CK).
2. Try tap-to-mark and scribbling on the iPad with a Pencil (touch.md lines for the stage still hold: a
   short tap opens the menu and never turns the page).
3. Item 5, the rest: two iPads signed in as admin and player (a cut in under 1 s, Follow, a real wifi drop);
   rehearsal session start and end (page jumps pushed only during a session); push `20261028210000_presence.sql`
   to the hosted project with the others (CK).
4. Undo as a per-device stack over the record's history.
