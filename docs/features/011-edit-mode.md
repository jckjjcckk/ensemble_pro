# 011 Edit mode: structural fixes with a typed Question/Answer contract

Status: built for the two kinds (R3 dialogs, 2026-10-28 night; answer route `POST /jobs/{id}/answer`) | Meta model: Muse Spark 1.3 raises the questions through the agent loop (006); the answer is human.

## Purpose

When the librarian cannot decide a structural fact (which staves are a part's, what parts a page has, page
order, a part name, bar numbering), it parks and asks the admin one typed question. The admin answers on
their iPad; the job resumes. Edit mode is part of splitting and distributing (008, 004, 010): structural
fixes only, never notation editing (out of the hackathon, 000).

## The contract

A Question is `jobs.result.question` (text) plus a typed payload with: `kind`, a page target (page, system,
and for staves the `staff_boxes` with an `image_key` to the numbered overlay), the agent's `proposal` and
`last_attempt` with the `feedback` that refused it, and the allowed answers, which always include **absent**
where the thing may simply not be printed. The Answer is a small JSON in the shape the payload's
`answer_format` gives. Kinds so far:

| kind | from | payload | answer |
|---|---|---|---|
| `choose_staves` | `part_cut` (008) | `page, system, instrument ("Soprano + Alto"), instruments [..], interpretation_id, proposal, blocks [{staves, instruments}], staves_per_instrument, last_attempt, feedback, staff_boxes [{index, y_top, y_bottom, x0, x1}], image_key, allowed {staves, blocks, absent: true}, answer_format` | `{staves: [11, 12]}`, `{blocks: [[11], [13]]}` or `{staves: "absent"}` |
| parts on a page (unnamed) | `process_pages` (004) | the page and what Spark saw | part names top to bottom, list or comma-separated |

Planned: `set_page_order` (continuity check failed), `assign_parts(page, parts)`, a part name conflict, a
measure numbering gap (`finish` refuses with the gap).

Mechanics: `ctx.needs_review(question, payload, interpretation_id)` sets `interpretations.status =
'needs_review'`, writes the question to the job row, marks the job `done`. The admin's answer goes through a
route in the app thread that queues a follow-up job of the same kind with the same payload plus `answer`
and `resume_from: <job id>`; the handler loads `result["agent"]` (or `params.state`) and continues without
paying for the pages already read. The loop's refusal counter is cleared on resume.

## The screens (R3, 2026-10-28 night; docs/design/r3/F_Parts, F_Staves, F_BookUnread, F_Details, F_CheckBar)

`web/src/app/StaffQuestion.tsx` keeps one entry point (`StaffQuestion`, opened from the Book sheet's Answer, the
Stand's "…" status row and the Split panel) and draws two centred dialogs over a dimmed shelf or sheet, header
"Needs you · …" with Later (closes, the yellow dot stays):

- **Which parts are on page N** (`process_pages`): Same as earlier pages (`known_parts`), What the reader found on
  this page (`spark_parts`), Something else (typed, one name per staff, top to bottom). The real page image sits
  beside them with a label on every staff from the current choice; staff positions are the reading's own systems
  (`interpretations.params.state.pages[N].geometry.systems`, boxes as page fractions, split evenly by the staff
  count). A chip says whether the names fit the staves ("6 staves · matches": one name per staff, a keyboard one
  short takes two staves, or an even run such as two pianos over four staves). Header "page N of M · k answered"
  (k = the book's jobs carrying `resume_from`). Confirm sends `{"answer": "Violin, Viola, …"}`.
- **Choose the staves** (`part_cut` `choose_staves`): the page (the numbered overlay `image_key`, else the page
  image) with the question's system lit and the rest dimmed; tap a staff to choose it, again to let go (any set:
  a skipped staff splits the cut into blocks); the proposal starts selected. "Use this staff" sends
  `{"staves": [...]}`, "The Viola isn't on this page" sends `{"staves": "absent"}`.

Two kinds of doubt that are not job questions use the same voice:

- **The key or meter not read with confidence.** `signature.py` keeps Spark's best guess beside the blank
  (`scores.key_sig_guess`, `meter_guess`, `signature_confidence {key, time}`; migration
  `20261029000000_reader_unsure.sql`); the Book sheet shows an amber banner ("Best guess: G major, 1 sharp. Confirm
  it in Details.") and the staff draws a dashed amber "?" where the signature goes. **Details** (`Details.tsx`,
  `PATCH /scores/{id}`) edits title, composer, key (15 keys around the circle of fifths per mode, the guess outlined
  in amber), one time signature, the cover clef, one speed with its marking and bar numbering. Saving the key or
  meter sets `scores.signature_confirmed`, after which a re-read never overwrites them.
- **Doubtful bars in a Digital copy** (`CheckBars.tsx`, `/score/{id}/check`, from the Book sheet's "n bars the
  reader is unsure about · Check"). The list is `flagged_bars` of the transcription's meta with its reasons in
  plain words (beats, not whole-note fractions); for the chosen bar the scan's crop (the flagged box on the page
  image) sits above the engraved copy's crop (the bar's box from the engraving's `.mpos`). "Wrong, use the scan
  here" / "Looks right" upsert `bar_decisions (score_id, bar, decision 'scan' | 'digital', decided_by,
  decided_at)`; the engraved Stand then draws the scan's bar over the engraved one (`ScanPatches`). The reader never
  rewrites music.

## Rules and decisions

- Admin only. Players never see questions.
- Never active during a rehearsal session: questions wait until the session ends, so no stand is interrupted
  by a librarian decision.
- One question at a time per job; the information box shows it as a short line, never a chat window.
- "Absent" is a first-class answer in every kind where the part may not be printed (cut-away layouts).
- Answers are the admin's words, applied as a successful commit without a recheck.
- The UI shows counts and flags only (000 recognition confidence).

## Open issues (asks from the intelligence thread to the app thread)

- ~~A route that answers a parked job~~: `POST /jobs/{id}/answer` (008, 2026-10-28) queues the same kind with
  `answer`, `resume_from` and the question's `interpretation_id`; only for a job `done` with
  `result.question`, owner or admin, once.
- A waiting state for the score badge (`scores.status` lacks `needs_review`; read `interpretations.status`).
- Nullable `measure_placements.page` for measures a reprocess does not find.
- The information box reading `summary` fields (`pages, systems, measures, first_measure, last_measure, title,
  composer, parts, difficulty, key_sig, meter, flagged, models, log, pages_read, question`).
- ~~A screen that shows the overlay with the `staff_boxes`~~: the R3 Choose the staves dialog.

## Next steps

1. The badge state (app thread); the answer route is in.
2. Answer both kinds end to end on the local stack with a worker running (seen in the pane on real parked
   questions; not submitted here, since the resumed jobs call Spark).
3. "pages with the same layout will not ask again" (F_Parts) needs `process_pages` to reuse an answer across pages;
   today each ambiguous page asks.
