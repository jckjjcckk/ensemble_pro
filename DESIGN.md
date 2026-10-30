# Design

<!-- impeccable:design-schema 1 -->

Folio's committed visual world. Written 2026-10-27 when exploration 5 (Instrument) became the app; its direction contract is in [docs/design/explorations/5.md](docs/design/explorations/5.md). Product truth is in [PRODUCT.md](PRODUCT.md). Code: `web/src/app/`, tokens in `web/src/app/styles.css`.

## Thesis

The score sits above a control surface the right hand can find without looking. One graphite dock, always at the bottom, carries the three places (Library, Book, Group; Read and Practise are a toggle in the book's header) and, in practice, grows into the instrument's panel with tempo as the largest number on screen. The signature shape is a bracket: drawn on the bar ruler, echoed in the score at the loop's ends, reused as the drop slot when ordering scan pages. The music is never crowded by chrome.

## One layout, two token sets

Themes are design tokens only: type, colour, line, radius. The layout, the navigation and every control are the same in both sets and both themes. A display setting (button in the library header; `folio.display` in localStorage) picks the set and the theme (auto, light, dark). Auto follows the iPad's own ambient-light switching.

| | Instrument (default) | Bound |
|---|---|---|
| Scene | Practice room, music rest, late evening under one lamp | Conservatory studio or chamber rehearsal in daylight; a bound full score |
| UI face | Archivo (variable width and weight) | Schibsted Grotesk |
| Measurements (`.num`) | Martian Mono, condensed, tabular | EB Garamond 500, tabular |
| Titles (`.title`, headings, wordmark) | Archivo 650 | EB Garamond 500, scaled ×1.12 |
| Ground / sheet / ink (light) | pale grey-blue / near-white / graphite, OKLCH | ecru `#e8e1d0` / leaf `#f6f1e5` / graphite `#2a2926` |
| Dark variant | graphite ground, pale ink | umber ground, ecru ink |
| Failure, "lost", warnings (`--amber`) | amber | oxblood `#6b1d24` |
| Following, metronome pulse (`--green`) | green, nothing else | muted green |
| Trouble heat (`--heat`) | orange-amber | ochre |
| Dock | graphite in both themes (the instrument, not the page) | warm graphite |

Token names are shared, so components never know which set is active: `--ground --sheet --sheet-edge --raised --ink --ink-2 --ink-3 --rule --rule-2 --wash --wash-2 --green --amber --heat --shadow`, the dock's `--dk --dk-2 --dk-3 --dk-rule --dk-ink --dk-ink-2 --dk-ink-3 --dk-wash --dk-green --dk-amber`, and the type hooks `--font-ui --font-num --font-title --num-weight --num-track --title-weight --title-track --title-scale`.

OSMD draws black ink; `.osmd svg` is repainted from `--ink` so dark themes invert the notation without touching the wrapper.

## Colour means one thing

Green means only "following" and the metronome pulse. Amber (oxblood in Bound) means only lost, warnings and failure. Heat is trouble spots and scan warnings. A book's one status dot is yellow (`--ask`) while the librarian has a question and red (`--fail`) when its run failed; a book being read or converted wears a breathing ink ring, never a spinner. Selection, the current bar, the loop tint and cuts are drawn in ink and ink washes, never in a colour.

Muse blue (`--muse`, `#0066E8`, from CK's swatch) means only "Muse is listening or proposing": the voice button while it hears you, the ghost of a proposed mark, the ruler tick for one. It never marks anything a person made, and a mark the admin accepts is drawn in ink like any other.

## Glass: Muse's material

Only Muse's surfaces are glass (feature 013): the voice button, the proposal cards and the ghost over proposed bars. Everything a person made stays paper and ink. The glass is a light frost (`backdrop-filter: blur(1.2px)`, a tenth of a frosted panel), a near-clear white fill, a silver hairline rim brighter at the top left, an inner shadow for thickness and a soft drop shadow; no refraction (the SVG lens works in WebKit but is not worth its cost yet). Listening: the glass itself lights up in Muse blue from the inside, light pooling at the rim, brightness following the voice level (`--level`, fast attack, slow release). Working: a soft multicolour wash drifts slowly inside the glass (thinking, about 6 s). `prefers-reduced-motion` holds the wash and the glow still. The reference artboard is `M5_GlassSurface` (CK's Downloads, 2026-10-29); the probe that proved it on iPad Safari is described in docs/features/013.

## Density

Medium. Three horizontal bands at most: header (56 px), the work, the dock (ruler 60 to 72 px plus a row of 76 px, or 164 px tall in practice on wide landscape). No side rails. Panels (Markings, History, the library's information box) dock as a right column at 1100 px and wider and slide over the work below that. No modals anywhere; sheets close with ✕ or Escape or a tap outside.

## Signature move: one ruler, many jobs

`Ruler.tsx` draws the whole piece as one line: the bracket (loop in practice, bars on screen in document mode, the cut being drawn), heat bands, cuts hatched, marks and voice notes under the line, presence ticks, the playhead coloured by the listening state. Dragging the bracket edits the loop, the cut or the visible pages.

## Measure OSMD, then draw beside it

`geometry.ts` reads `GraphicSheet.MeasureList` after every render and returns one box per bar in stage coordinates. Cuts, loops, heat, cursors, pins, presence faces and margin notes are positioned overlays. Nobody edits OSMD's DOM.

## Words in the margin, pencil on the staff

Taken from exploration 1. Short pencil-like markings (dynamic, bowing, breath, pencil) sit as pins above their bar. Sentences (text notes, voice-note transcripts) sit in the outer margin of their page, level with the system that holds their bar, collisions stepping down with a tick left at the bar's true height (`MarginLayer` in `marks.tsx`). The margin exists on landscape screens 1180 px and wider; below that the Markings panel carries the same notes.

## Library

Context first (My library, then each ensemble), then folders of score covers. A cover shows composer, title, work and one status badge (reading progress, Needs pages, Order pages, or the player's own part). Tapping a cover opens the information box: facts, read flags as counts only ("2 pages unreadable"), parts with holders and a one-word difficulty, the brief for admins, and the actions. The dock carries Scan pages and Resume practice.

## Touch

See the iPad-first rules in PRODUCT.md and the checklist in `docs/acceptance/touch.md`. On the score stage one pointer gesture has three outcomes: tap selects a bar, a 500 ms hold opens the marking composer on that bar, a horizontal swipe turns the spread. `touch-action: none` and no callout on the stage.

## Motion

One authored moment per screen (the metronome pulse; the drag ghost on scan; the sheet sliding in). Transitions are 120 to 180 ms on an exponential ease-out. `prefers-reduced-motion` removes all of it.

## Browser surfaces

Selection, caret, focus rings (2 px ink, outline-offset 2), scrollbars (thin, `--rule-2`), form controls (`accent-color` ink) and `color-scheme` follow the token set.
