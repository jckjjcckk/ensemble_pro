# Backlog: known limits we are not fixing during the hackathon

Honest list, kept so the submission can say what Folio does not do yet.

- **Join codes have no guess limit.** An 8-digit code (100 million possibilities) can be tried without a lockout
  beyond Supabase's own rate limits. Fix later: attempts per IP/user in the `join_ensemble` RPC, codes that expire.
- **Deleting a group leaves its files in storage.** Books are shared by reference, so only group-only uploads
  linger. Fix later: a cleanup job on `delete_ensemble`.
- **C-clef misreads when splitting a single choir voice.** Cutting one voice alone (Soprano without Alto) makes
  the recheck ask about alto/tenor C clefs about three times in five pages; pairs of voices cut cleanly. Fix later:
  trust by-order labels on a full system, or a glyph-level clef reader (feature 008).
- **PyMuPDF is AGPL-3.** It rasterizes PDFs for the page reader. Fine while the repo is public and the source is
  available to users; a closed or commercial build would need pypdfium2 (BSD/Apache) instead.
- **Fine-tuning a transcription by hand.** Doubtful bars are listed and the music is shown as read; no bar editor.
- **Per-page rescan** of an unreadable page: button only, not wired, unless the UI branch found it cheap.
- **Voice (feature 013)**: rehearsal speech to actions with Muse Voice Transcribe; script written, no audio, no handler.
