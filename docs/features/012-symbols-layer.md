# 012 Symbols layer: one record type for every mark

Status: prototype (quick marks and scribbles on the score screen, written to `annotations` and `scribbles` and refetched on Realtime notifications, local stack only; rehearsal-session live push is build-queue item 5, not built) | Meta model: Muse Spark 1.3 proposes marks from voice notes (013); the layer itself uses none, and scribbles are never interpreted.

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
pages of the part at once; they are small) and refetch on any change; the reader's pages save 3 s after a
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

## Next steps

1. Migration for the remaining deltas (comment kind, job author, soft delete); `highlight` and `scribbles`
   are in 20261028180000. Apply it to the hosted project (CK).
2. Try tap-to-mark and scribbling on the iPad with a Pencil (touch.md lines for the stage still hold: a
   short tap opens the menu and never turns the page).
3. Item 5: rehearsal session start and end, live push of cuts and marks during a session, reconnect recovery
   (the score screen already reads and writes real annotations and refetches on Realtime notifications).
4. Undo as a per-device stack over the record's history.
