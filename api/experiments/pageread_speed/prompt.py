"""The page-read prompt, copied from app/librarian/labels.py at bfac5d9 (PROMPT, 013 v4e), so the experiment never
changes the app. `full` is the app's prompt verbatim; `trimmed` drops the book-level questions (title, composer,
key, meter, difficulty, brief: items 5-7 and their JSON fields) for pages after the book's first page."""
from __future__ import annotations

from app.librarian.labels import PROMPT as APP_PROMPT

HEAD = """This is a scanned page of printed sheet music. Blue boxes with provisional numbers (1..{n}, reading left to right, top to bottom) mark the measures that a geometry detector found. Dashed grey boxes mark staff systems; system {systems_desc}.
{parts_context}
Answer these questions about the page. Do not re-locate anything; only label what is drawn.
1. first_measure_number: the real measure number of provisional measure 1, using printed measure numbers, rehearsal letters or the musical context if visible; if the page starts with an incomplete pickup bar say so (is_pickup true). If nothing on the page tells you, answer 1 with confidence "low".
2. systems: for each system, the part names of its staves top to bottom (e.g. ["Piano I", "Piano II"] for a two-piano score where each part has two staves; ["Piano"] for a piano grand staff; ["Violin I", "Violin II", "Viola", "Cello"] for a quartet). Give staves_per_part so the counts add up to the staves in that system. Use the names as printed, in English, with Roman numerals for numbered parts.
3. rehearsal_marks: any boxed numbers or letters, with the provisional measure they are attached to.
4. doubtful_measures: provisional measure numbers that do not look like real measures (for example a box that spans only a clef or key signature, or two boxes that are really one bar split by a note stem), each with a reason.
"""
BOOK = """5. title and composer if printed; key_signature (e.g. "G major") and time_signature (e.g. "3/4") as printed at the start, else null.
6. parts_difficulty: for every distinct part name on the page, a difficulty from 1 (easy) to 5 (virtuoso) for an amateur player, judged from the notation on this page.
7. brief: two sentences a librarian would write about this music for the ensemble: what it is and what will take the most work. No preamble.
"""
LANDMARKS = """{k}. landmarks: what is printed on this page that marks a place in the music, each with the provisional measure (the blue box number) it is printed over, exactly as for rehearsal marks: tempo words (Allegro, Adagio, meno mosso, a tempo, rit., ritenuto, Tempo I) and metronome marks; a key signature or time signature that changes (not the ones repeated at the start of every system); double barlines; repeat signs; segno, coda, "To Coda", Fine, D.C., D.S.; section titles (Trio, Var. 2, Cadenza). Give "text" as printed (for a key change the new signature, e.g. "3 flats"; for a time signature, e.g. "3/4"; for repeat signs "start repeat" or "end repeat"; for a double barline "double bar"). For a double barline or an end repeat give the box it closes (the box to its left); for everything else the box it stands over or begins. Do not count bars or give bar numbers; only point at a box. If you cannot tell which box it belongs to, give null. List only what you can see printed: a repeat sign is two dots beside a double barline, so never infer a start repeat from an end repeat or from the form of the music; for a key change count the sharps or flats of the new signature; one barline can carry two landmarks (an end repeat and Fine). Leave out dynamics, hairpins, articulations, fingering, pedal marks, expression words (dolce, cresc., espress., con forza), the clef, key and time signature at the start of each system, and the final barline of the piece.
"""
JSON_FULL = """
Return only JSON:
{{"first_measure_number": 1, "is_pickup": false, "confidence": "high|medium|low",
 "systems": [{{"index": 1, "parts": ["Piano"], "staves_per_part": [2]}}],
 "rehearsal_marks": [{{"mark": "1", "provisional_measure": 9}}],
 "doubtful_measures": [{{"provisional_measure": 5, "reason": "..."}}],
 "title": "", "composer": "", "key_signature": null, "time_signature": null,
 "parts_difficulty": [{{"part": "Piano", "difficulty": 3}}],
 "brief": "",
 "landmarks": [{{"kind": "tempo|key_change|meter_change|double_bar|repeat|coda|segno|fine|section", "text": "Adagio", "provisional_measure": 12}}]}}"""
JSON_TRIM = """
Return only JSON:
{{"first_measure_number": 1, "is_pickup": false, "confidence": "high|medium|low",
 "systems": [{{"index": 1, "parts": ["Piano"], "staves_per_part": [2]}}],
 "rehearsal_marks": [{{"mark": "1", "provisional_measure": 9}}],
 "doubtful_measures": [{{"provisional_measure": 5, "reason": "..."}}],
 "landmarks": [{{"kind": "tempo|key_change|meter_change|double_bar|repeat|coda|segno|fine|section", "text": "Adagio", "provisional_measure": 12}}]}}"""

FULL = HEAD + BOOK + LANDMARKS.replace("{k}", "8") + JSON_FULL
TRIMMED = HEAD + LANDMARKS.replace("{k}", "5") + JSON_TRIM
assert FULL == APP_PROMPT, "prompt.py has drifted from app/librarian/labels.py PROMPT"


def build(geo: dict, known: list[str], *, trimmed: bool) -> str:
    from app.librarian.labels import parts_context
    systems_desc = ", ".join(f"{s['index']} has {s['staves']} staves" for s in geo["systems"]) or "none"
    return (TRIMMED if trimmed else FULL).format(n=len(geo["measures"]), systems_desc=systems_desc, parts_context=parts_context(known))
