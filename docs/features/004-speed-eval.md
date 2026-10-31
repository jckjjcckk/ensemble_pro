# 004 speed eval: effort minimal and a trimmed page answer

Status: experiment, 2026-10-30 (no app code changed) | Meta model: Muse Spark 1.3 (the per-page label read of 004,
`labels.label_page`) | Code: `api/experiments/pageread_speed/` (`prepare.py`, `run.py`, `score.py`, `prompt.py`; results
gitignored under `results/`, every call in `spend.jsonl`) | Spend: **$1.53 of the $4 cap, 107 calls** (3 header reads,
104 page reads).

## Question

Page reading spends about 13 s a page in one Spark call at effort low, and latency follows output tokens (reasoning
included). Two candidate fixes from today's investigation, measured here before they ship:

- **(2) effort `minimal`**, which only the chat-completions format accepts (Messages refuses it), as
  `experiments/voice_stream/common.py` already calls it.
- **(4) a trimmed answer**: title, composer, key, meter, difficulty and brief are asked on every page but used from the
  first (key and meter come from the signature read anyway). Trimmed = items 5-7 and their JSON fields left out on every
  page after the book's first; the first page keeps the full prompt.

| variant | API | effort | answer |
|---|---|---|---|
| A (today) | Messages (`llm.complete`, the app's call) | low | full |
| B | chat completions, not streamed | minimal | full |
| C | Messages | low | trimmed after page 1 |
| D | chat completions | minimal | trimmed after page 1 |

## Method

- Pages: the 016 corpus, all 10 (Goldberg BGA p1-3, Rach 1 Gutheil full score p1-3, Beethoven 9 p172-175) plus Chopin
  op. 26/1 pp. 14-16 from today's landmarks eval (013 v4e; Goldberg p2-3 are the other two of its five). 13 pages x 4
  variants x 2 runs = 104 reads.
- The app's path without the database: `import_pdf.render_page` at 150 dpi (Beethoven 9: the grounding experiment's
  150 dpi PNGs, 3153 px; the full PDF is not on this machine; Rach 1: the 5-page copy in
  `~/Downloads/stave-extractor/api/fixtures/pdf`), the score header read once per book with `labels.read_header`
  (Messages, low; Chopin is read mid-book, so no header and "Piano" seeded as the part already read), then
  `cut.page_measures` with the header's staff count. Geometry is frozen once, so every variant labels the same boxes.
- Each book is read in page order as `process_pages` does: the parts read on earlier pages go into the next prompt, and
  `process_pages.assign_parts` (imported, unchanged) says whether the app would park on a question. The prompt is
  copied into `prompt.py`; an assert proves the full variant is byte-identical to `labels.PROMPT`. Parsing is
  `label_page`'s, verbatim. One retry on bad JSON (none needed: 0 parse failures in 104).
- Same message for both APIs (image then text, no system prompt, 8000-token budget). Cost at the app's list price
  ($1.25 / $4.25 per M), no cache discount, for both APIs.
- Concurrency 4, chains shuffled so all variants share the server load. Absolute seconds are therefore a little above a
  lone call (A's Goldberg p1 is 12-14 s, as in the investigation); compare variants, not against 13 s.
- Scoring: bars per page against 004's by-eye table; the 016 label GT (piano staves per Rach system, the soprano staff
  on Beethoven 9, mapped onto `page_measures`' staff numbers: Rach aligns 1:1; on Beethoven 9 the page-edge fakes are
  masked so the soprano is staff 12 of 16, checked by eye on p173), plus "piano on both staves of every system" on the
  keyboard pages; first bars as printed (Goldberg, Rach, Chopin; Beethoven 9 prints none); landmarks against today's 20,
  counted by eye on the annotated pages with the same boxes (rules in `score.py`: a double bar at a repeat's box is the
  same barline; a metronome mark given apart from its tempo word is not extra; every new disagreement checked on the
  image).

## Results

### Speed and cost (all 26 reads per variant; "trimmed pages only" = the 20 pages after a book's first)

| variant | pages | group | median s | p90 s | median out tok | median reasoning tok | $/page | parse fails |
|---|---|---|---|---|---|---|---|---|
| A | 26 | all | 19.7 | 31.7 | 2904 | - | 0.0176 | 0 |
| A | 12 | keyboard | 17.9 | 22.7 | 2231 | - | 0.0135 | 0 |
| A | 14 | orchestral | 25.1 | 34.8 | 3730 | - | 0.0212 | 0 |
| A | 20 | trimmed pages only | 22.1 | 34.2 | 3118 | - | 0.0187 | 0 |
| B | 26 | all | 10.9 | 14.5 | 1518 | 1063.5 | 0.0123 | 0 |
| B | 12 | keyboard | 9.6 | 11.4 | 1296 | 905.0 | 0.0102 | 0 |
| B | 14 | orchestral | 12.3 | 19.8 | 1765 | 1223.0 | 0.0141 | 0 |
| B | 20 | trimmed pages only | 10.9 | 15.9 | 1496 | 1048.0 | 0.0125 | 0 |
| C | 26 | all | 17.5 | 25.4 | 2500 | - | 0.0153 | 0 |
| C | 12 | keyboard | 15.4 | 20.0 | 2060 | - | 0.0127 | 0 |
| C | 14 | orchestral | 18.3 | 29.3 | 2725 | - | 0.0175 | 0 |
| C | 20 | trimmed pages only | 18.1 | 28.3 | 2610 | - | 0.0162 | 0 |
| D | 26 | all | 9.6 | 15.2 | 1353 | 1037.0 | 0.0116 | 0 |
| D | 12 | keyboard | 9.1 | 9.8 | 1186 | 827.5 | 0.0094 | 0 |
| D | 14 | orchestral | 12.4 | 19.0 | 1884 | 1483.5 | 0.0135 | 0 |
| D | 20 | trimmed pages only | 9.6 | 14.4 | 1314 | 1037.0 | 0.0114 | 0 |


### Accuracy

Bars per page come from geometry and are identical in every variant: 28/20/21, 4/9/9, 9/5/9/6 = 004's truth on all
10 corpus pages (Chopin p. 14-15 carry the known geometry errors of today's eval).

| variant | label systems right | pages that would park | first bar right (book's first page) | first bar right (all pages with GT) | Spark-doubted boxes | landmarks found (+ named wrong) of 20 per run | invented |
|---|---|---|---|---|---|---|---|
| A | 84/84 | 0 | 4/4 | 10/18 | 24 | r1: 17 (+1), r2: 17 (+1) | r1: 0, r2: 0 |
| B | 84/84 | 1 | 4/4 | 10/18 | 21 | r1: 17 (+1), r2: 18 (+1) | r1: 2, r2: 1 |
| C | 84/84 | 0 | 4/4 | 10/18 | 9 | r1: 17 (+0), r2: 17 (+1) | r1: 3, r2: 0 |
| D | 80/84 | 0 | 4/4 | 10/18 | 9 | r1: 17 (+1), r2: 16 (+2) | r1: 0, r2: 1 |


- **Label systems** (84 checks per variant): A, B, C all right. D's run 1 named Beethoven 9's chorus as four parts
  "Coro Alto / Tenore / Basso I / II" on every page (it carried page 1's names forward): the soprano staff is called
  "Coro Alto" on 4 pages. Not scored by the GT but wrong too: C run 1 on Beethoven 9 p175 gave Horns 2 staves and
  Trombones 2, dropping Timpani and Bass trombone (low effort, so not a minimal effect).
- **Parking:** B run 1 on Rach p3 named parts generically ("Horn", "Horn", "Clarinet") and the matcher asks a question
  (Horn fits two horn parts). 1 of 4 minimal Rach chains; 0 of 4 at low.
- **First bar:** the app uses only the book's first page: 4/4 for every variant. On later pages all variants say 1 for
  Rach p2-3 and 34 (or 1) for Goldberg p3, the same failure in A.
- **Doubted boxes:** on the 10 corpus pages the geometry count is exactly right, so every doubt there is a false alarm
  (and a landmark over a doubted box is dropped). A 21 false, B 19, C 5, D 7. The two real geometry errors (Chopin p14 box
  19, a key-signature-only box; p15 box 14, three bars in one box) were caught A 3/4, B 2/4, C 4/4, D 2/4 (D missed box 19
  in both runs).
- **Landmarks** (20 printed, per run): A 17 + 1 named wrong both runs, 0 invented; B 17-18, 3 invented in 10 page reads;
  C 17, 3 invented; D 16-17, 1 invented. The inventions: a double bar at Goldberg p3 box 13 (B1, B2, C1), at Chopin p14
  box 2 (B1, D2), at Goldberg p2 box 18 (C1), a start repeat at Chopin p16 box 16 (C1). B2 is the only run that found
  Chopin p15's start repeat at the system start; nobody finds Goldberg p3's. D2 missed Chopin p14's key change.

### Per page, per run

Cell: label systems ok/n, first bar, doubted boxes, landmarks found/named-wrong/invented (eval pages), seconds, output
tokens.

| page | bars (geometry / truth) | A1 | A2 | B1 | B2 | C1 | C2 | D1 | D2 |
|---|---|---|---|---|---|---|---|---|---|
| beethoven9-p172 | 9 / 9 | 1/1, 1, d0, 23.6s, 3559 | 1/1, 1, d0, 17.3s, 2582 | 1/1, 1, d0, 12.7s, 1790 | 1/1, 1, d0, 11.8s, 1674 | 1/1, 1, d0, 17.7s, 2555 | 1/1, 1, d0, 17.4s, 2407 | 0/1, 1, d0, 12.3s, 1952 | 1/1, 1, d0, 23.3s, 2754 |
| beethoven9-p173 | 5 / 5 | 1/1, 1, d0, 21.3s, 3114 | 1/1, 1, d0, 13.6s, 2045 | 1/1, 1, d0, 10.3s, 1485 | 1/1, 1, d0, 11.0s, 1593 | 1/1, 1, d0, 12.9s, 1878 | 1/1, 1, d0, 16.4s, 1945 | 0/1, 1, d0, 5.2s, 669 | 1/1, 1, d0, 10.2s, 1364 |
| beethoven9-p174 | 9 / 9 | 1/1, 1, d0, 27.3s, 3781 | 1/1, 1, d0, 35.1s, 4484 | 1/1, 1, d0, 9.2s, 1476 | 1/1, 1, d2, 13.0s, 1808 | 1/1, 1, d0, 21.8s, 2886 | 1/1, 1, d0, 14.2s, 2018 | 0/1, 1, d1, 6.5s, 769 | 1/1, 1, d1, 14.2s, 1834 |
| beethoven9-p175 | 6 / 6 | 1/1, 1, d0, 25.4s, 3686 | 1/1, 1, d0, 26.3s, 3775 | 1/1, 1, d0, 21.8s, 2597 | 1/1, 1, d0, 22.0s, 2948 | 1/1, 1, d0, 29.8s, 4057 | 1/1, 1, d0, 22.8s, 3519 | 0/1, 1, d0, 16.2s, 2338 | 1/1, 1, d0, 11.7s, 1576 |
| chopin-p14 | 19 / 18 | 5/5, 20, d0, lm 4/1/0, 18.8s, 2507 | 5/5, 20, d1, lm 4/1/0, 17.8s, 2255 | 5/5, 20, d0, lm 4/1/1, 13.7s, 1787 | 5/5, 20, d1, lm 4/1/0, 9.0s, 1312 | 5/5, 20, d1, lm 4/0/0, 18.7s, 2683 | 5/5, 20, d1, lm 4/1/0, 15.9s, 2231 | 5/5, 20, d0, lm 4/1/0, 9.8s, 1286 | 5/5, 20, d0, lm 3/1/1, 9.4s, 1342 |
| chopin-p15 | 14 / 16 | 5/5, 38, d1, lm 3/0/0, 20.6s, 3047 | 5/5, 38, d1, lm 3/0/0, 17.9s, 2207 | 5/5, 38, d0, lm 3/0/0, 11.2s, 1241 | 5/5, 38, d1, lm 4/0/0, 10.2s, 1448 | 5/5, 38, d1, lm 3/0/0, 15.1s, 1590 | 5/5, 38, d1, lm 3/0/0, 15.6s, 2046 | 5/5, 38, d1, lm 3/0/0, 9.5s, 1271 | 5/5, 38, d1, lm 3/1/0, 7.5s, 1075 |
| chopin-p16 | 16 / - | 5/5, 54, d0, lm 2/0/0, 13.7s, 2089 | 5/5, 54, d0, lm 2/0/0, 13.2s, 1838 | 5/5, 54, d0, lm 2/0/0, 10.5s, 1349 | 5/5, 54, d0, lm 2/0/0, 6.8s, 918 | 5/5, 54, d0, lm 2/0/1, 12.6s, 1819 | 5/5, 54, d0, lm 2/0/0, 7.7s, 1114 | 5/5, 54, d0, lm 2/0/0, 4.8s, 633 | 5/5, 54, d0, lm 2/0/0, 7.0s, 961 |
| goldberg-bga-p01 | 28 / 28 | 6/6, 1, d0, 11.8s, 1785 | 6/6, 1, d0, 13.8s, 1594 | 6/6, 1, d0, 8.7s, 1279 | 6/6, 1, d0, 6.5s, 977 | 6/6, 1, d0, 13.9s, 1913 | 6/6, 1, d0, 12.5s, 1938 | 6/6, 1, d0, 9.1s, 1199 | 6/6, 1, d0, 9.4s, 1027 |
| goldberg-bga-p02 | 20 / 20 | 6/6, 1, d0, lm 4/0/0, 13.2s, 1895 | 6/6, 1, d10, lm 4/0/0, 29.4s, 4154 | 6/6, 1, d0, lm 4/0/0, 11.4s, 1506 | 6/6, 1, d0, lm 4/0/0, 10.9s, 1373 | 6/6, 1, d0, lm 4/0/1, 19.1s, 3171 | 6/6, 1, d0, lm 4/0/0, 20.1s, 3054 | 6/6, 1, d0, lm 4/0/0, 9.0s, 1199 | 6/6, 1, d0, lm 4/0/0, 6.8s, 915 |
| goldberg-bga-p03 | 21 / 21 | 6/6, 34, d0, lm 4/0/0, 18.3s, 2456 | 6/6, 34, d0, lm 4/0/0, 22.9s, 3122 | 6/6, 1, d0, lm 4/0/1, 7.6s, 1077 | 6/6, 34, d0, lm 4/0/1, 7.2s, 1072 | 6/6, 34, d0, lm 4/0/1, 21.4s, 2537 | 6/6, 34, d0, lm 4/0/0, 14.5s, 2075 | 6/6, 1, d0, lm 4/0/0, 8.4s, 1174 | 6/6, 34, d0, lm 4/0/0, 10.4s, 1372 |
| rach1-gutheil-p01 | 4 / 4 | 1/1, 1, d0, 14.6s, 2571 | 1/1, 1, d0, 18.0s, 2760 | 1/1, 1, d0, 11.1s, 1740 | 1/1, 1, d0, 10.1s, 1734 | 1/1, 1, d0, 19.0s, 2623 | 1/1, 1, d0, 14.7s, 2462 | 1/1, 1, d0, 11.1s, 1851 | 1/1, 1, d0, 8.5s, 1502 |
| rach1-gutheil-p02 | 9 / 9 | 2/2, 1, d1, 27.6s, 4798 | 2/2, 1, d6, 24.7s, 3848 | 2/2, 1, d7, 9.8s, 1529 | 2/2, 1, d6, 13.4s, 2592 | 2/2, 1, d0, 17.6s, 2827 | 2/2, 1, d4, 19.6s, 3174 | 2/2, 1, d0, 12.5s, 1916 | 2/2, 1, d2, 13.0s, 2040 |
| rach1-gutheil-p03 | 9 / 9 | 2/2, 1, d2, 44.7s, 7001 | 2/2, 1, d2, 34.1s, 5255 | 2/2, 1, d2, PARK, 13.2s, 2248 | 2/2, 1, d2, 15.3s, 2341 | 2/2, 1, d0, 33.1s, 5049 | 2/2, 1, d1, 28.1s, 4315 | 2/2, 1, d1, 20.3s, 3296 | 2/2, 1, d2, 13.7s, 2238 |


### Every read where B, C or D differs from both A runs

- **beethoven9-p172 D1**: labels: system 1: staff 12 read as 'Coro Alto' (staves [12]) | staves per part [[1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]] (A: [[[1, 1, 1, 1, 1, 1, 1, 1, 2, 1, 4, 1]], [[1, 1, 1, 1, 1, 1, 1, 1, 2, 1, 4, 1]]])
- **beethoven9-p172 D2**: staves per part [[1, 1, 1, 1, 1, 1, 2, 2, 1, 4, 1]] (A: [[[1, 1, 1, 1, 1, 1, 1, 1, 2, 1, 4, 1]], [[1, 1, 1, 1, 1, 1, 1, 1, 2, 1, 4, 1]]])
- **beethoven9-p173 D1**: labels: system 1: staff 12 read as 'Coro Alto' (staves [12]) | staves per part [[1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]] (A: [[[1, 1, 1, 1, 1, 1, 1, 1, 2, 1, 4, 1]], [[1, 1, 1, 1, 1, 1, 1, 1, 2, 1, 4, 1]]])
- **beethoven9-p173 D2**: staves per part [[1, 1, 1, 1, 1, 1, 2, 2, 1, 4, 1]] (A: [[[1, 1, 1, 1, 1, 1, 1, 1, 2, 1, 4, 1]], [[1, 1, 1, 1, 1, 1, 1, 1, 2, 1, 4, 1]]])
- **beethoven9-p174 B2**: doubted boxes [1, 2] (A: [[], []])
- **beethoven9-p174 D1**: labels: system 1: staff 12 read as 'Coro Alto' (staves [12]) | staves per part [[1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]] (A: [[[1, 1, 1, 1, 1, 1, 1, 1, 2, 1, 4, 1]], [[1, 1, 1, 1, 1, 1, 1, 1, 2, 1, 4, 1]]]) | doubted boxes [3] (A: [[], []])
- **beethoven9-p174 D2**: staves per part [[1, 1, 1, 1, 1, 1, 2, 2, 1, 4, 1]] (A: [[[1, 1, 1, 1, 1, 1, 1, 1, 2, 1, 4, 1]], [[1, 1, 1, 1, 1, 1, 1, 1, 2, 1, 4, 1]]]) | doubted boxes [3] (A: [[], []])
- **beethoven9-p175 C1**: staves per part [[1, 1, 1, 1, 2, 2, 2, 1, 4, 1]] (A: [[[1, 1, 1, 1, 1, 1, 1, 1, 2, 1, 4, 1]], [[1, 1, 1, 1, 1, 1, 1, 1, 2, 1, 4, 1]]])
- **beethoven9-p175 D1**: labels: system 1: staff 12 read as 'Coro Alto' (staves [12]) | staves per part [[1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]] (A: [[[1, 1, 1, 1, 1, 1, 1, 1, 2, 1, 4, 1]], [[1, 1, 1, 1, 1, 1, 1, 1, 2, 1, 4, 1]]])
- **beethoven9-p175 D2**: staves per part [[1, 1, 1, 1, 1, 1, 2, 2, 1, 4, 1]] (A: [[[1, 1, 1, 1, 1, 1, 1, 1, 2, 1, 4, 1]], [[1, 1, 1, 1, 1, 1, 1, 1, 2, 1, 4, 1]]])
- **chopin-p14 B1**: landmarks invented ["double_bar 'double bar' box 2"] (A: [[], []])
- **chopin-p14 C1**: landmarks missed ['end repeat 18'] (A: [[], []]) | landmarks half_names [] (A: [['end repeat 18'], ['end repeat 18']])
- **chopin-p14 D2**: landmarks missed ['key change (5 flats)'] (A: [[], []]) | landmarks invented ["double_bar 'double bar' box 2"] (A: [[], []])
- **chopin-p15 B1**: doubted boxes [] (A: [[14], [14]])
- **chopin-p15 B2**: landmarks missed [] (A: [['start repeat 1'], ['start repeat 1']])
- **chopin-p15 D2**: landmarks missed [] (A: [['start repeat 1'], ['start repeat 1']]) | landmarks half_names ['start repeat 1'] (A: [[], []])
- **chopin-p16 C1**: landmarks invented ["repeat 'start repeat' box 16"] (A: [[], []])
- **goldberg-bga-p02 C1**: landmarks invented ["double_bar 'double bar' box 18"] (A: [[], []])
- **goldberg-bga-p03 B1**: first bar 1 (A: [34, 34]) | landmarks invented ["double_bar 'double bar' box 13"] (A: [[], []])
- **goldberg-bga-p03 B2**: landmarks invented ["double_bar 'double bar' box 13"] (A: [[], []])
- **goldberg-bga-p03 C1**: landmarks invented ["double_bar 'double bar' box 13"] (A: [[], []])
- **goldberg-bga-p03 D1**: first bar 1 (A: [34, 34])
- **rach1-gutheil-p02 B1**: doubted boxes [2, 3, 4, 6, 7, 8, 9] (A: [[9], [2, 3, 6, 7, 8, 9]])
- **rach1-gutheil-p02 C1**: doubted boxes [] (A: [[9], [2, 3, 6, 7, 8, 9]])
- **rach1-gutheil-p02 C2**: doubted boxes [6, 7, 8, 9] (A: [[9], [2, 3, 6, 7, 8, 9]])
- **rach1-gutheil-p02 D1**: doubted boxes [] (A: [[9], [2, 3, 6, 7, 8, 9]])
- **rach1-gutheil-p02 D2**: doubted boxes [2, 3] (A: [[9], [2, 3, 6, 7, 8, 9]])
- **rach1-gutheil-p03 B1**: would park: page 2 has 11/12 staves per system and Spark reads Horn there, which earlier pages did not have (they had Flutes I, II, Oboes I, II, Clarinets I, II in A, Basso
- **rach1-gutheil-p03 C1**: doubted boxes [] (A: [[2, 7], [2, 3]])
- **rach1-gutheil-p03 C2**: doubted boxes [2] (A: [[2, 7], [2, 3]])
- **rach1-gutheil-p03 D1**: doubted boxes [2] (A: [[2, 7], [2, 3]])

## Verdicts

**(2) effort minimal via chat completions: ship, with a caveat.** It halves the read on both kinds of page: median
19.7 → 10.9 s, p90 31.7 → 14.5 s, output tokens 2904 → 1518, $0.0176 → $0.0123 a page (keyboard 17.9 → 9.6 s,
orchestral 25.1 → 12.3 s). Everything geometry decides is unchanged, label systems 84/84, first bar 4/4, landmarks found
17-18 of 20 against A's 17, and fewer false doubts. The caveat is orchestral naming, which is less stable: one Rach
chain in four parked on generic names ("Horn" x2), and minimal invented 4 double bars in 20 eval-page reads where A
invented none today. Ship it with the park path as it is (a question, not wrong data), and add a low-effort Messages
fallback for a page whose parts do not match, rather than parking at once. The app needs a chat-completions branch in
`llm.complete` (image as `image_url` data URL, `reasoning_effort`, `max_completion_tokens`; usage is
`prompt_tokens` / `completion_tokens`). Not separated here: how much of the gain is the endpoint rather than the
effort (no "low via chat" control). That does not change the decision.

**(4) trimmed answer: ship, with a product caveat.** At low it saves about 500 output tokens a later page (3118 → 2610
median) and 4 s (22.1 → 18.1 s median, p90 34.2 → 28.3), more than the 200-300 tokens estimated, because Spark also
reasons less. On top of minimal the gain is small: B → D 10.9 → 9.6 s median, 1518 → 1353 tokens. Accuracy holds for C
(labels 84/84, landmarks 17, fewer false doubts, the most true doubts). D's run-1 chorus naming and D2's missed key
change look like run noise of minimal on a short prompt, not a trimming effect, but n is 2. The caveat is product, not
accuracy: `process_pages` takes a part's difficulty as the hardest page's rating, so with difficulty asked on page 1
only, a part that rests on page 1 (an orchestral book's later entries) gets the default 3, and one hard passage later in
the book no longer raises a rating. Trimming title, composer, key, meter and brief costs nothing. For difficulty, either
keep `parts_difficulty` on every page (a small part of the saving) or accept page-1 ratings: CK's call.

**Both together (D): about half today's time.** Median 19.7 → 9.6 s, p90 31.7 → 15.2 s, tokens −53 %, $ −34 %. Ship (2)
first. Add (4) when the difficulty question is settled, and check its orchestral naming on a second pair of runs.

## Notes

- The Goldberg header read says 12 staves (6 systems x 2); the geometry is unaffected (no staff recovered). It is the
  app's behaviour, and it is recorded here only because `expected_staves` reached `page_measures`.
- Part names vary by run in every variant (English vs as printed, "I, II" vs "I. II."). `match_part` absorbs that
  within a book.
- Reproduce: `cd api && uv run python -m experiments.pageread_speed.prepare && uv run python -m
  experiments.pageread_speed.run && uv run python -m experiments.pageread_speed.score` (a chain with a results file is
  not re-run).
