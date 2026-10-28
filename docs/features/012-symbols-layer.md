# 012 Symbols layer: one record type for every mark

Status: designed (the `annotations` table exists; the score screen shows mock markings; Realtime fan-out of cuts is build-queue item 5, not built) | Meta model: Muse Spark 1.3 proposes marks from voice notes (013); the layer itself uses none.

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

## The cellist's feedback (carried as rules)

- Personal marks and ensemble marks must be separate. A player's own fingerings never appear on another
  stand; the leader's cut appears on every stand.
- Repeats, bar numbering and handwriting are what AI gets wrong, so the user fixes them: the layer must
  make fixing a mark as cheap as making one (tap, edit, remove, undo), and never lock a model's mark.

## What exists in the UI

`web/src/app/marks.tsx` and the score screen: text notes and voice transcripts in the outer margin level with
their bar (landscape at 1180 px and wider), pencil-like markings as pins, the marking composer on long-press,
the Markings panel in portrait, the cut at bars 227 to 246 and the seven mock annotations on the Beethoven.
The smoke test (`smoke_local.py`) proves the policies: a cut for the ensemble, a bowing for Violin II only, a
player's private note, a non-member sees nothing.

## Build-queue item 5 (Oct 29): shared score, annotations, cuts, Realtime

Annotations on stable measure ids, audience rules, admin starts and ends a rehearsal session, cut
propagation, reconnect recovery (client keeps an `updated_at` cursor and refetches on reconnect). Done means:
a cut on the admin iPad shows on four stands in under 1 s; an iPad that drops wifi during the cut has it
after reconnect.

## Next steps

1. Migration for the deltas (comment kind, job author, soft delete) from the app thread.
2. Item 5: real annotations on the score screen, Realtime, rehearsal session start and end.
3. Undo as a per-device stack over the record's history.
