# Muse

An AI librarian for ensembles. Photograph or upload a score, get clean split parts on every iPad, and let the conductor's markings propagate to the whole group.

Built for the Meta Global AI Developer Hackathon (Oct 27 – Nov 4, 2026).

## Layout

- `web/` — React + Vite PWA, opened in Safari on each iPad
- `api/` — FastAPI backend: Meta Model API calls, OMR, music21 part splitting, budget and whitelist
- `docs/` — design notes and demo plan

## Meta models used

- SAM 3.1 — score page layout segmentation (systems, staves, instrument labels)
- Muse Spark — vision for handwritten markings, reasoning for difficulty ratings and rehearsal briefs
- Muse Voice Transcribe — spoken rehearsal notes anchored to bars
