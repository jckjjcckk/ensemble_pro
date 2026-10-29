# Folio product site: content inventory (2026-10-29)

Read from `~/Documents/Folio_site` (Astro). For the design chat: the words as written, plus the app's screens by name so screenshots can be requested.

Known stale facts to fix on the site: repo link says `ensemble_pro` (now `jckjjcckk/folio-pad`); app URL says `app.folio.jckjjcckk.com` (live app is `folio-app.jckjjcckk.com`); support address `support@folio.jckjjcckk.com` is marked TODO in the source; App Store URL empty; all nine screenshot slots are placeholders.

## Site-wide

- Name: Folio. Tagline: "One score for the whole ensemble".
- Pages: `/`, `/features`, `/support`, `/about`, `/privacy`. No content collections, no markdown; copy is in the `.astro` files.
- Fonts: Archivo (variable, width axis) and Martian Mono (numbers). Theme colour `#ebecef` light, `#1a1c20` dark. OG image `/og.png` (1200×630).
- Visual mismatch with the app: the app's R3 design uses EB Garamond with Inter on warm paper (#F3EFE6) and dark warm charcoal.
- Vocabulary mismatch: site says "library", "information box", "librarian", "Read | Practise toggle"; the R3 app says "Shelf", "Book sheet", "the reader".

### Shared chrome

- Skip link: "Skip to content".
- Header (sticky): bracket-pair icon + "Folio" (links to `/`, aria-label "Folio, home"). Nav: "Features", "Support", "About". Button "Open Folio" (to the app URL, hidden below 560px).
- Footer: wordmark; "One score for the whole ensemble."; nav "Features", "Support", "Privacy", "About", "support@folio.jckjjcckk.com"; "Display" segmented control Auto | Light | Dark; "© 2026 Folio. Built in Toronto for the Meta Global AI Developer Hackathon."

### Shared components

- **AppShot**: every screenshot slot. All are placeholders: an iPad frame with a grey schematic (library / reader / practice / scan / group) captioned "Screenshot to come {screen name}, iPad {landscape|portrait}". Real shots go in `public/shots/` at 2360×1640 (landscape) or 1640×2360 (portrait): iPad Air 11" in Safari, toolbar hidden.
- **Ruler**: an authored SVG, the hero visual. aria-label: "Folio's bar ruler: the piece drawn as one line with a practice loop on bars 112 to 140, a cut at bars 171 to 206, marks under the line, and where each player is." Top row: "Beethoven, String Quartet Op. 18 No. 1" / "I. Allegro con brio · 313 bars · 4 parts". Tempo "92" "of 108". On the line: "112–140", "Vn I", "Vc", "1", "313". Pills: "Following · bar 118" (pulsing green dot), "Loop 112–140", "Cut 171–206", "4 on the stand".
- **Models** table (Home and Features):
  1. "SAM 3.1" / "Sees the page" / "Segments a photographed or scanned page into its systems, so the bar geometry has clean regions to work in. Where the photo is poor, it tells the librarian which pages to retake." / "Scan intake, page reading"
  2. "Muse Spark 1.3" / "Reads and writes" / "Labels what geometry finds: the first bar number, the parts on each system, rehearsal marks, title and composer. Reads handwritten markings, rates each part's difficulty, writes the rehearsal brief, and turns a confirmed spoken note into a marking on the right bar." / "Librarian, information box, voice notes"
  3. "Muse Voice Transcribe" / "Listens to the room" / "Transcribes what the leader says during a rehearsal session, speaker by speaker, so an instruction becomes text anchored to the bars on the stand." / "Rehearsal sessions"

## Home, `/`

- Title: "Folio: One score for the whole ensemble"
- Meta description: "Folio is an AI librarian and practice tool for ensembles on iPad. Import a PDF and it reads itself into bars. One score for the whole group, marks that reach every stand live, and a practice mode built from the same score."

**Hero**
- H1: "One score for the whole ensemble."
- Lede: "Folio reads a PDF or a photographed score into bars, splits it into parts on every player's iPad, and keeps the group's markings in sync while you rehearse. The same score is your practice tool afterwards."
- Buttons: "Open Folio on iPad"; "Coming to the App Store" (disabled while the App Store URL is empty).
- Note: "Folio is in a private release. Accounts are set up by hand for each ensemble: ask for one" (links `/support#account`).
- Visual: the Ruler. Caption: "The bar ruler: the whole piece as one line. The bracket is a practice loop, the hatching a cut the leader made, the ticks are where each player is right now."

**Steps**, H2 "From a PDF to every stand"
1. "Import, and it reads itself into bars": "Drop in a PDF, photograph the pages, or paste an IMSLP link. The librarian finds every system and bar, numbers them, names the parts, and tells you plainly which pages it could not read."
2. "One score, split into parts": "Assign seats and each member sees their own part, on the pages they are used to. The full score and every part are the same object, so nothing drifts."
3. "Marks that reach every stand, live": "A bowing, a cut, a spoken instruction: made once on the leader's iPad, on every stand in about a second. Players see their notes and the notes addressed to them, nothing else."
4. "Then practise from the same score": "Loop a passage, slow the tempo, hear the other parts, keep a metronome. The trouble spots from rehearsal are already marked on the ruler."

**Feature: library**. H2 "A library that shows its work". "Every score wears one status: reading, needs pages, ready, or your part. Tap a cover and the information box tells you what the librarian did and did not manage: pages read, bars it doubted, parts assigned, with a short log instead of a spinner." Link "How the librarian reads a score" (`/features#librarian`). Image slot (landscape): "Library with the information box open".

**Feature: rehearsal** (image left). H2 "Rehearse without paper". "The admin starts a rehearsal session. A cut skips bars on every stand at once; a page jump turns every page. Say "crescendo from bar 41" and the proposal appears on bar 41 for the leader to confirm. Outside a session, changes sync quietly." Link "What a rehearsal session does" (`/features#live`). Image slot (landscape): "Rehearsal session, the admin's view with presence ticks".

**Feature: practice**. H2 "Practice mode is the same score". "Drag the bracket on the ruler to set a loop. Tempo is the biggest number on the screen. Play along to the other parts, with a metronome if you want one. Nothing to configure before you can start." Link "Practice mode in detail" (`/features#practice`). Image slot (landscape): "Practice mode with the loop bracket and tempo".

**Models**. H2 "Three Meta models, three jobs". Lede: "Folio does the heavy work with Meta's models through the Meta Model API. Each one has one task, and the app shows you its result rather than hiding it." Then the table. Note: "Reading music is hard for any model. Folio pairs the models with plain staff and barline geometry, flags what it doubts, and asks the admin when a page is ambiguous rather than guessing. Why we built it this way." (links `/about`)

**Closing**. H2 "Built for the stand, not the desk". Lede: "iPad in Safari first: two facing pages in landscape, one in portrait, controls you can hit while holding an instrument, readable at arm's length under stage light. A Mac browser window for the librarian's work." Buttons: "Open Folio"; "Get help or an account" (`/support`).

## Features, `/features`

- Title: "Features: Folio"
- Meta description: "What Folio does: an AI librarian that reads PDFs and photos into bars and parts, live markings and cuts across every iPad in the ensemble, and a practice mode with loop, tempo, metronome and other-parts playback."
- H1: "Everything the group knows about a score travels with the score."
- Lede: "Scan, split, distribute, mark, rehearse, practise. Most tools stop at one of these. Folio keeps one score object through all of them."
- In-page nav: "Librarian", "Parts", "Live rehearsal", "Practice", "iPad", "Models".

**`#librarian`**, H2 "The librarian"
- "Import a PDF, photograph the pages, or paste a link to an IMSLP score. Folio orders the pages, finds every system and barline, and numbers the bars across the whole work. Meta's SAM 3.1 segments the page; Muse Spark labels what was found: first bar, parts on each system, rehearsal marks, title, composer. A MusicXML file skips the reading and renders at once."
- "The librarian is an agent that works on its own and stops only when it must. A page that introduces staves it has not seen before becomes a question for the admin, answered in a sentence, and the run continues from where it paused. Nothing is re-read or re-charged."
- Bullets: "Pages the librarian could not read are counted, not hidden: "2 pages unreadable, 5 bars doubtful."" / "Doubtful bars carry a quiet pencil mark in the margin. Tap it to re-read the bar or open the original photo." / "Every run is versioned. Reprocessing a page keeps everyone's markings, because markings point at bars, not at a reading."
- Image slot (landscape): "Information box: pages read, bars doubtful, parts, the librarian's log".

**`#parts`** (image left), H2 "One score, every part"
- "The admin assigns seats; each player's iPad opens on their part. Parts are cut from the same pages everyone else reads, so bar 112 is bar 112 for the viola and the conductor alike. Spark rates each part's difficulty in one word, and writes a short brief for the admin."
- "Every account owns a personal library. Joining an ensemble is like joining a shared notebook: you can be admin of one group and a player in another, and your own scores stay yours."
- Image slot (landscape): "A player's part with the admin's notes in the margin".

**`#live`**, H2 "Marks that reach every stand"
- "Pencil a bowing, drop a dynamic, draw a cut across a bar range, leave a voice note. The admin decides whose notes go to whom. A player sees their own notes and the ones addressed to them."
- "During a rehearsal session the leader's changes interrupt: a cut skips the bars on every stand, a page jump turns every page. Say an instruction and Muse Voice Transcribe turns it into text; Spark proposes it as a marking on the bar you meant; the leader confirms with one tap. Outside a session, everything syncs quietly."
- Bullets: "Presence on the ruler: a tick for each member, at the bar they are looking at." / "Follow the admin: a player can lock their pages to the leader's." / "History of every version, admin only."
- Image slot (landscape): "Rehearsal session: a cut landing on four stands".

**`#practice`** (image left), H2 "Practice mode"
- "Read and Practise are two ways of being in one book, a toggle in the header. In practice the dock grows into the instrument's panel: tempo as the largest number on screen, a loop you set by dragging the bracket on the ruler, a metronome, and playback of the other parts so a pianist can rehearse a concerto's tutti or a cellist the quartet's upper voices."
- "Trouble spots from rehearsal show as heat on the ruler, so the passages that need work are already marked. Green on screen means one thing only: Folio is following you."
- Muted: "Listening to your instrument over MIDI, with wrong-note flags and run scoring, is in development and not in this release."
- Image slot (landscape): "Practice mode on a piano music rest, landscape".

**`#ipad`**, H2 "Made for a music stand"
- "Folio is designed for an iPad on a stand at arm's length, often in bad light, with your hands on an instrument."
- Bullets: "Two facing pages in landscape, one page in portrait. The music is never cropped or crowded by controls." / "Every control is at least 44 points. The practice dock's controls are larger." / "Swipe turns the page. Long-press a bar to mark it. Apple Pencil works everywhere a finger does." / "Light and dark follow the room. A second, bound-score look with serif type and ecru paper is a display setting." / "On a Mac, a browser window for scanning, ordering pages and assigning parts."
- Image slot (portrait, max 420px): "Reader in portrait, one page".

**`#models`**, H2 "Which Meta model does what". The table, then muted: "All model calls go through Folio's own server, never from the iPad. The pipeline, the benchmark harness and its numbers are public in the repository." (links the repo)

## Support, `/support`

- Title: "Support: Folio"
- Meta description: "Help with Folio: how to get an account, what you can import, which devices it runs on, what happens to a score after upload, and who sees your markings."
- H1 "Support". Lede: "Folio is made by a very small team, and a musician reads every message. Tell us what you were doing, which score, and on which device, and we will get back to you."

**Ways to reach us** (`id="account"`, H2 visually hidden)
- "Email": "For help, bug reports, feature requests, or to ask for accounts for your ensemble." Button "support@folio.jckjjcckk.com".
- "Accounts for an ensemble": "Send the ensemble's name, how many players and which instruments. We create an admin account for the person running the group and one account per member."
- "Privacy questions": "Read the privacy policy, or write to the same address. Questions about your data are answered by a person."

**FAQ**, H2 "Questions we get asked" (accordion, first open)
1. "How do I get an account?": "Folio is in a private release and there is no sign-up form. The person running your ensemble asks us for accounts, and we create one for each member by hand. Email support@folio.jckjjcckk.com with your ensemble's name, how many players, and which instruments. You sign in with an email address and a password."
2. "What can I import?": "A PDF, photographs of the pages taken with the iPad, or a MusicXML file. For a public-domain score on IMSLP, open it in Safari and paste the link; Folio downloads the PDF and reads the work's details from the link. A MusicXML file renders at once; a PDF or photos are read into bars first, which takes a few minutes for a ten-page score."
3. "Which devices does Folio run on?": "Folio is built for iPad in Safari and installs to the home screen like an app. On a Mac it runs in a browser window, landscape only, for scanning, ordering pages and assigning parts. Open it at app.folio.jckjjcckk.com. An App Store listing is coming."
4. "What happens after I upload a score?": "The score shows up in your library straight away with a status: ordering pages, reading, ready, or needs pages. Tap its cover for the information box, which lists what the librarian did: pages read, bars it doubted, parts it named, and a short log. If a page is ambiguous, the librarian asks you a question there and continues once you answer."
5. "What if a page cannot be read?": "Folio tells you. The cover says "Needs pages" and the information box counts them: "2 pages unreadable". Retake those pages from the same screen and only they are re-read. Bars the librarian doubted carry a small pencil mark in the margin; tap it to re-read the bar or to see the original photo. You can always read the original pages as they are."
6. "Who can see my markings and notes?": "Your own markings are yours. In an ensemble, the admin decides whose notes go to whom: a player sees their own notes and the admin's notes addressed to them. Admins see every version. Scores and markings are stored per ensemble and are never visible to anyone outside it."
7. "Does Folio work offline?": "Folio needs a connection: scores are stored on our servers and markings sync live through them. Pages you have already opened keep showing if the wifi drops for a moment, but a rehearsal session needs every iPad online to receive cuts and page jumps."
8. "Can I use any score I own?": "You are responsible for having the right to use a score you import. Scores stay in a private bucket for your ensemble and are never redistributed by Folio. Our own test material is public-domain editions from IMSLP."

## About, `/about`

- Title: "About: Folio"
- Meta description: "Why Folio exists: a pianist's tool for the rehearsal where nobody holds paper, built in Toronto for the Meta Global AI Developer Hackathon."
- H1 "About Folio". Lede: "Folio started with a pianist's annoyance: the parts disagree, the cut is on three stands and not the fourth, and the page with the pencilled bowing is in someone else's bag. Everything the group knows about a piece should travel with the piece."
- "What it is": "An AI librarian and practice tool for ensembles. It reads a PDF or photographed score into bars, splits it into parts on every member's iPad, keeps markings and cuts in sync while you rehearse, and turns the same score into a practice tool with loop, tempo, metronome and other-parts playback. One score object serves the whole life of the music."
- "How it treats the machine": "Reading music is a hard visual task, and we would rather be honest than impressive. Folio pairs plain staff and barline geometry with Meta's models, SAM 3.1 for the page, Muse Spark for labels and language, Muse Voice Transcribe for the room, and shows you the result: pages read, bars doubted, the question it had to ask. A librarian that says "I could not read page 4" is more useful than one that pretends it did." / "We measure this. The same benchmark runs Meta's model and Anthropic's Claude through one harness, and both numbers are published in the repository."
- "Who makes it": "Folio is built in Toronto by CK Jiang, a pianist and software developer, who also makes the training tools at Zephyr Lab (zephyrlab.ca). It was built for the Meta Global AI Developer Hackathon in October and November 2026. The code is public at github.com/jckjjcckk/ensemble_pro." (stale repo name)
- "Design rules we hold to": "The music is the interface. Controls recede; the score is never crowded." / "Readable at arm's length under bad light, operable with one hand or a pencil." / "Honest about machine output: states, confidence and failures are visible, never behind a spinner." / "One layout for every context. Themes are tokens: type, colour, line."
- "Get in touch": "support@folio.jckjjcckk.com, or the support page."

## Privacy Policy, `/privacy` (footer and Support only)

- Title: "Privacy Policy: Folio"
- Meta description: "Folio's privacy policy: what we collect, how scores and markings are stored, which services process them, and how to reach us."
- H1 "Privacy Policy". "Effective 28 October 2026. Applies to the Folio app at app.folio.jckjjcckk.com and to this website."
- Lede: "Folio stores the scores, parts and markings your ensemble works from, and nothing it does not need for that. We do not sell your data, we do not show ads, and we do not use your scores or recordings to train models."
- "Who we are": "Folio is made by a small team in Toronto, Canada. For anything in this policy, write to support@folio.jckjjcckk.com."
- "Accounts": "There is no public sign-up. Accounts are created by hand when the person running an ensemble asks for them, one per member. To create an account we need an email address; you choose a password. Your account can own a personal library and belong to any number of ensembles, as an admin or a player. Which one you are is recorded on each membership."
- "What we collect": "Account details. Your email address, a hashed password, the display name you give us, and your ensemble memberships and roles." / "Scores you import. The PDF, photographs or MusicXML files you upload, the images we render from them, and what the librarian reads from them: pages, systems, bars, parts, titles and composers, together with its confidence flags and a log of what it did." / "Markings and notes. Pencil markings, dynamics, cuts, text notes, and voice notes with their transcripts, each attached to a bar in a score, with who made it, when, and who it is addressed to." / "Rehearsal and practice activity. Which bar each member is on during a rehearsal session, the cuts and page jumps the admin sends, and practice settings such as loops and tempo." / "Usage records. Each processing job and model call is recorded with its cost, so that we can keep a budget per account. We do not run third-party analytics or advertising trackers." / "This website collects nothing: it has no forms, no analytics and no cookies. Your display preference is kept in your own browser."
- "How we use it": "Only to do what you asked Folio to do: read your score into bars and parts, show each member their part, keep markings in sync across the ensemble, transcribe spoken notes during a rehearsal session, and run practice mode. Your email is used to sign you in and to answer messages you send us."
- "Where it is stored": "Accounts, scores, markings and activity are stored with Supabase (supabase.com), which hosts our database, file storage and live sync. Score files live in a private storage bucket per ensemble or personal library. Access is enforced row by row: a member can read only the scores of the ensembles they belong to, and sees only the markings addressed to them. Supabase's own practices are described in its privacy policy (supabase.com/privacy)."
- "Services that process your data": "Folio's heavy work is done by AI models that run outside the app. Data goes to them only for the task at hand and only through Folio's own server; the app on your iPad never talks to a model directly." / "Meta Model API (Meta Platforms, Inc.). Images of your score pages are sent to SAM 3.1 and Muse Spark to be segmented and labelled; recordings made during a rehearsal session are sent to Muse Voice Transcribe to be transcribed. We use the standard, non-training tier of the API." / "Anthropic (Anthropic, PBC). During development we run some page-reading tasks through Claude as well, to compare results. The same rules apply: only for the task, and not for training." / "Cloudflare serves this website and routes traffic to the app and its server." / "We do not sell, rent or trade your data with anyone, and no third party is given access to your library for its own purposes."
- "How long we keep it": "Your scores, markings and account stay as long as your account is active, so that your ensemble's work is there when you open Folio next. Usage records are kept for our accounting. If you want something removed from your library, ask us at the address below and a person will take care of it."
- "Your rights": "You can ask us what we hold about you, ask for a copy of it, and ask us to correct it. You can also withdraw from an ensemble, which stops its admins from addressing notes to you. Write to support@folio.jckjjcckk.com and we will answer within a few days."
- "Children": "Folio is for musicians of any age, but accounts are only created at the request of the adult running an ensemble, a teacher, or the account holder themselves if they are an adult. We do not knowingly create accounts for children without such a request."
- "Changes": "When this policy changes, the effective date at the top changes with it, and the new version lives at this address: folio.jckjjcckk.com/privacy."
- "Contact": "support@folio.jckjjcckk.com"

## Assets (`public/`)

Real files: `og.png` (1200×630, source `scratch/og.svg`), `favicon.svg`, `apple-touch-icon.png` (180), `icon-192.png`, `icon-512.png`, `robots.txt`, `_headers`. No `public/shots/`. Nine placeholder screenshot slots: Home 3 (library, rehearsal, practice); Features 6 (information box, player's part, rehearsal cut on four stands, practice on a piano rest, portrait reader). Five landscape, one portrait. No terms page; only `/privacy`.

External links: app URL, repo (stale), zephyrlab.ca, supabase.com, supabase.com/privacy. App Store: none yet.

---

# The app's screens, by name (for screenshot requests)

Routes in `web/src/app/App.tsx`. Scan and Practice are pre-R3 and partly mocked. Artboards are the `*.dc.html` files in `docs/design/r3/`, 834×1194 portrait or 1194×834 landscape. There is no `docs/design/r3/shots/` folder in main.

1. **Sign in** (any route without a session). Card: wordmark, "Sign in", "One score for the whole ensemble.", Email, Password, "Sign in". Foot: "Accounts are made by the ensemble's admin. Ask them if you need one." Variants: idle, busy, error.
2. **Shelf, My Library** (`/`). Segmented tab (My Library | Groups) over a grid of book cards (composer, title, engraved key/time staff). Import and Scan at the top; dock at the bottom (Shelf, Stand). Variants: loading, empty ("Nothing on your shelf yet"), full, a card being read, a card with a pending question (yellow dot). Artboards `Main`, `R3_ShelfMineEmpty`.
3. **Shelf, Groups** (`/groups`). One row per group: books, join code, who is on the stand. "Manage groups", "Share one of mine". Variants: empty, populated, dark. Artboards `R3_ShelfGroups`, `R3_ShelfGroupsDark`.
4. **Groups dialog** (`/group`). Open group: eight-digit join code large with Copy, members with roles; other groups as rows; "Join with a code", "New group". Variants: open, join-code entry, create, Leave/Delete confirmation. Artboard `R2_GroupSheet`.
5. **Book sheet** (bottom sheet over the shelf). Identity, PDF/Digital tag, actions: "Open on the stand", "Split by instrument", "Convert to Digital", "Share with a group"; foot: Export MusicXML, Details, Delete. Variants: ready; being read; question pending ("The librarian has a question"); key not read (amber banner); failed (Rescan); "Digitalising in progress"; doubtful bars ("Check"). Artboards `R2_BookSheet`, `F_BookUnread`.
6. **Details** (dialog). Title, composer, key picker (guess outlined amber), time signature, clef, speed with marking, bar numbering start. Variants: unconfirmed, confirmed. Artboard `F_Details`.
7. **Question: which parts are on page N** (owner only). "Same as earlier pages" / "What the reader found on this page" / "Something else", beside a labelled thumbnail. Buttons "Later", "Confirm and keep reading". Artboard `F_Parts`.
8. **Question: choose the staves** (split). One system lit; tap the staves ("Use these staves") or say the part isn't on this page. Artboard `F_Staves`.
9. **Split by instrument** (sheet from the Book sheet). Choose instruments; progress ("Splitting by instrument"), log, result. Variants: none yet, running, stopped, done.
10. **Stand (reader)** (`/score/:id`, or `/score/:id/pages` for PDF pages). Header: Shelf, title and position, Read | Practise, Mine | Group, faces of others, "…" menu. Two facing pages landscape, one portrait, pinch zoom. Tap a bar: vertical quick menu (Highlight, Note, Scribble, Loop from here). Notes above their bar; "Following Anna's page turns" at the foot. Variants: light landscape; dark dimmed paper; dark inverted; portrait; zoomed; quick menu open; a note on a bar; nothing marked; still being read; unreadable page (Rescan page N / Show the scan as is). Artboards `R2_StandLight`, `R2_StandDarkPaper`, `R2_StandDarkInk`, `R3_StandPortrait`, `R3_StandZoom`, `F_Unreadable`.
11. **Strips** (`/score/:id?view=strips`). A PDF split as full-width strips, one system each.
12. **Doubtful bars** (`/score/:id/check`). Flagged bars with reasons; scan above the digital copy; "Wrong, use the scan here" / "Looks right". Variants: bars to check; all clear. Artboard `F_CheckBar`.
13. **Scan** (`/scan`). Photograph pages, drag into order, confirm. Variants: capturing, ordering, sent, all removed. Pre-R3 styling.
14. **Practice** (`/practice?score=`). Big tempo number, loop bracket on the ruler, Metronome, Other parts, Listening, trouble spots, history sheet. Pre-R3, mock data.
15. **Appearance / account menu** (popover). Light/dark, dimmed paper vs inverted, Sign out.

**Ask for first, for marketing:** Stand landscape light with a note and faces (hero); Shelf with 6 to 8 covers, and the Book sheet open; Stand portrait, and Stand dark dimmed paper; the "which parts are on page N" question, and the Book sheet with a pending question or the amber key banner; Doubtful bars with scan above copy; Groups dialog with the join code; Practice only if restyled to R3 in time.
