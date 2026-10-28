# 011 Edit mode: structural fixes with a typed Question/Answer contract

Status: designed (the contract exists in `part_cut` and `process_pages`; no route, no screen) | Meta model: Muse Spark 1.3 raises the questions through the agent loop (006); the answer is human.

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
| `choose_staves` | `part_cut` (008) | `page, system, instrument, interpretation_id, proposal, last_attempt, feedback, staff_boxes [{index, y_top, y_bottom, x0, x1}], image_key, allowed {staves, absent: true}, answer_format` | `{staves: [11, 12]}` or `{staves: "absent"}` |
| parts on a page (unnamed) | `process_pages` (004) | the page and what Spark saw | part names top to bottom, list or comma-separated |

Planned: `set_page_order` (continuity check failed), `assign_parts(page, parts)`, a part name conflict, a
measure numbering gap (`finish` refuses with the gap).

Mechanics: `ctx.needs_review(question, payload, interpretation_id)` sets `interpretations.status =
'needs_review'`, writes the question to the job row, marks the job `done`. The admin's answer goes through a
route in the app thread that queues a follow-up job of the same kind with the same payload plus `answer`
and `resume_from: <job id>`; the handler loads `result["agent"]` (or `params.state`) and continues without
paying for the pages already read. The loop's refusal counter is cleared on resume.

## Rules and decisions

- Admin only. Players never see questions.
- Never active during a rehearsal session: questions wait until the session ends, so no stand is interrupted
  by a librarian decision.
- One question at a time per job; the information box shows it as a short line, never a chat window.
- "Absent" is a first-class answer in every kind where the part may not be printed (cut-away layouts).
- Answers are the admin's words, applied as a successful commit without a recheck.
- The UI shows counts and flags only (000 recognition confidence).

## Open issues (asks from the intelligence thread to the app thread)

- A route that answers a parked job (queue the same kind with `answer` and `resume_from`).
- A waiting state for the score badge (`scores.status` lacks `needs_review`; read `interpretations.status`).
- Nullable `measure_placements.page` for measures a reprocess does not find.
- The information box reading `summary` fields (`pages, systems, measures, first_measure, last_measure, title,
  composer, parts, difficulty, key_sig, meter, flagged, models, log, pages_read, question`).
- A screen that shows the overlay (`image_key`) with the `staff_boxes` as tappable rows and an "absent" button.

## Next steps

1. The answer route and the badge state (app thread).
2. The `choose_staves` screen on the iPad, then the parts-on-a-page kind.
