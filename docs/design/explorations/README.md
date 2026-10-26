# Design explorations

Five parallel visual directions for the same product, built on the same data, so the owner can pick one to build on and steal parts from the others. Product truth lives in [/PRODUCT.md](../../../PRODUCT.md) and is not up for debate here. Visitor mode for every screen is **Operate**: a musician came to do a job.

Each exploration is a self-contained React app mounted at `/N` and written only inside `web/src/explorations/N/`. Four of five will be deleted; the survivor becomes the real app, so build it as if it will ship.

## Rules every exploration follows

**Files.** Write only inside `web/src/explorations/N/` and the single document `docs/design/explorations/N.md`. Do not touch `web/src/explorations/shared/`, `web/src/App.tsx`, `index.html`, `vite.config.ts`, `package.json`, or anything outside your folder. Do not run `npm install`; there are no new dependencies. Icons are hand-authored inline SVG in one stroke weight, or none. Fonts come from Google Fonts through a `<link>` your root component appends to `document.head` on mount, or an `@import` at the top of your own CSS file.

**Isolation.** Your root element carries the class `xN` (for example `x3`) and every CSS variable, font, and reset you need is scoped under `.xN`. Nothing leaks to other routes. Tailwind utilities are fine; your own `styles.css` imported from your `App.tsx` is fine.

**Data.** Import everything from `../shared` ([data.ts](../../../web/src/explorations/shared/data.ts)). It has ensembles, members with roles and live positions, six scores in five processing states, parts, seven annotations on the Beethoven including a cut at bars 227 to 246 and two voice notes, a practice state mid-loop on bars 178 to 190 with trouble spots and four sessions of history, and an eight-page scan draft with two warnings. Use these values as they are. Invent nothing: no customers, logos, testimonials, pricing, or statistics that are not in the file.

**Score rendering.** Use `ScoreView` from `../shared`. It wraps OpenSheetMusicDisplay, takes a fixture URL, a zoom and an OSMD `pageFormat` ("Endless", "A4_P", "A4_L", or a custom one), and gives you the OSMD instance through `onReady` for cursors and measure positions. With a page format set, OSMD emits one SVG per page inside the container, so two facing pages in landscape is a CSS layout of those page elements. The SVG ink is black by default; style it from your palette with CSS on `.xN svg` (fill and stroke on paths, text and rects) rather than editing the wrapper. A dark direction must invert the ink that way.

**Screens.** Every exploration ships these routes under its prefix, complete with real data and the states named:

| Route | Screen | Must show |
|---|---|---|
| `/N` | Library | All six scores with their five states (ready, processing with progress, failed with the reason, ordering, uploaded), parts per score, difficulty, who updated what. A role switch (player, leader, pianist, librarian) that changes what is shown, never where things are. |
| `/N/scan` | Scan intake | The Fauré draft: eight page thumbnails in order, drag to reorder, delete, retake, the two warnings visible, and a single Process action. Processing never starts until the user commits the order. |
| `/N/score/s-beethoven` | Document mode | The Beethoven quartet rendered by ScoreView. Part switcher. The cut at 227 to 246 visible on the score. The dynamic at 41, the bowing at 57, the viola note at 121, the two voice notes with transcripts. Presence: four members online, three at bar 41, one at 39, one offline. A way to add a marking, a cut, a voice note. |
| `/N/practice` | Practice mode | Violin I, loop 178 to 190, tempo 120 of 132 (91 percent), metronome on, other parts on, listening "following". Trouble spots visible in or near the score. The four-session history reachable. Controls operable with one hand while holding an instrument. |

**Form factors.** Design and verify at four sizes, in this order of priority: iPad landscape 1194 by 834 showing two facing pages, iPad portrait 834 by 1194 showing one page, Mac 1440 by 900, and a half-width Mac window 720 by 900 that adapts rather than breaks. Touch targets 44 pt and up on iPad. Keyboard operable on Mac.

**Process.** This project carries the Impeccable skill at `.claude/skills/impeccable/`. Its launcher script is absent, so follow the "Launcher unavailable" fallback in its `SKILL.md`: read [PRODUCT.md](../../../PRODUCT.md), then `reference/new-work.md` for the direction contract (your direction below is pinned, so skip the user interview and the world workshop and go to the concept and contract), then `reference/operate.md` and `reference/mode-operate.md` for what a working screen may and may not borrow from its world, then `reference/craft-floor.md` immediately before writing UI. Build fully, inspect once, fix in one batch, stop. Verify with `npm run build` from `web/`; the build must pass with no TypeScript errors. Do not open a browser or start servers; the owner screenshots all five together afterwards. Do not commit.

**Tone, binding.** Premium, quiet, professional. Not playful. Not an admin panel. The score is never crowded by chrome. Light or dark is chosen from the use scene your direction names, not by habit.

**Deliverable.** Working screens plus `docs/design/explorations/N.md`: your direction contract in the form new-work.md describes, with the palette as named tokens, the type pairing with sources, density rules, the signature move and where it lives on each screen, the navigation model, what you would cut if this became the product, and three things you think the other directions should steal from yours.

## The five directions

Per the Operate rules, a world lends only type, palette, density and one signature move. Navigation and controls stay standard web components the musician already knows. The five differ in world and in organisation: navigation model, how work areas divide the screen, which data leads, density, and where the signature move sits.

### 1. Reading room

Scene: a music stand in a bright rehearsal room, daylight. The score is paper and the device disappears. Light only.

- Organisation: no persistent navigation. The score fills the viewport edge to edge. A thin edge control appears on tap at the top (back, part, role) and at the bottom (tools), and both hide on the next tap or after a pause. Library and scan are quiet full-screen lists reached from the top edge.
- Data that leads: the music, then bar numbers, then the margin.
- Density: lowest of the five. One thing at a time.
- Signature move: the margin. Annotations, presence initials and voice notes live in a true outer margin column beside the staves, at the bar they belong to, the way a conductor's pencil works. In landscape the margin sits outside both facing pages; in portrait it collapses to a gutter that opens on tap.
- Type: a text serif with real italics for titles and transcripts, a humanist grotesk for controls. Palette: paper white, warm black ink, one graphite grey, one muted red reserved for cuts and failures.

### 2. Pit

Scene: an orchestra pit or a dim stage, stand light only. Dark only. Ink is light on a near-black ground, and nothing glows.

- Organisation: a narrow left rail with the four roles and the three areas (library, scan, score). The score takes the rest. Practice mode replaces the rail with a right-hand control column so the left hand never crosses the body.
- Data that leads: where everyone is. The ensemble's live position is the first thing read.
- Density: low to medium; everything legible at 60 cm in the dark.
- Signature move: the presence strip. A horizontal bar ruler runs along the top of the score for the whole piece, with a dot per member at their bar, the cut shown as a gap in the ruler, and voice notes as small marks. Tap a dot to jump; tap a mark to hear. It is the same ruler in practice mode, carrying the loop and trouble spots instead of people.
- Type: a grotesk with clear numerals built for low light, generous size. Palette: near black, two greys of ink, one warm amber for state and selection, one cool blue reserved for "someone else". Red only for failure.

### 3. Console

Scene: the librarian and conductor at a Mac, then the same shell on an iPad. The one direction that is Mac-first and dense.

- Organisation: three resizable panes: a list (scores, or parts, or members), the score, and an inspector (annotations, processing results, part assignment, session history). A command palette on ⌘K and a search field do the navigation; the panes collapse to one on a half-width window and to tabs on iPad portrait.
- Data that leads: processing truth. Confidence, failures, which pages failed and why, who has which part.
- Density: highest of the five, but spaced like a professional editor, never cramped.
- Signature move: the track lane. Under the toolbar a lane runs the length of the piece with markings, cuts and voice notes as labelled pills at their bars, filterable by kind and author. It is a timeline with ordinary controls, not a DAW costume.
- Type: a precise grotesk with tabular figures everywhere numbers appear. Palette: cool neutral greys, one restrained blue for selection and links, state colours only on state. Follows the system light or dark setting; both must be finished.

### 4. Bound

Scene: a conservatory studio or a chamber rehearsal. Warm, material, unhurried. Light by default with a dim variant.

- Organisation: a single top bar carrying the ensemble name, the role, and the areas. Below it the work. No side rails.
- Data that leads: the part. Which part am I reading, which part is being discussed.
- Density: medium.
- Signature move: part tabs. Along the top edge of the score the parts of the work sit as index tabs the way a bound full score is tabbed, the active one lifted; the leader sees all tabs, a player sees theirs raised and the others flat. Switching parts is one tap on the edge. In practice mode the tabs become Solo, With orchestra, Click.
- Type: typographic, with an old-style serif for titles and large quiet numerals for bar numbers and tempo, and a grotesk for labels. Palette: ecru ground, graphite ink, one deep oxblood used only for cuts and failures, no other accent.

### 5. Instrument

Scene: a piano music rest, the Casio under the iPad, a pianist's hands busy. Practice-first; the other screens exist to get here. Theme follows ambient light through the system setting.

- Organisation: a bottom dock with three areas (Library, Score, Practice) and, in practice mode, the dock grows into a control surface: tempo as the largest number on screen, a loop bracket, metronome, other-parts and listening toggles, all reachable by the right hand without looking. In landscape the score sits above the dock; in portrait the dock narrows to one row.
- Data that leads: the current bar and the tempo.
- Density: low in the score, high in the dock.
- Signature move: the loop bracket. A bar ruler above the dock carries a draggable bracket for the loop; the same span is tinted in the score itself, and trouble-spot heat sits under the ruler as faint shading. Listening status is a single word next to the bar number: following, lost.
- Type: a grotesk with large tabular numerals and a monospace used only for the tempo and bar readouts, since those are measurements. Palette: graphite ground, pale ink, one green reserved for "following" and the metronome pulse, amber for "lost" and warnings.
