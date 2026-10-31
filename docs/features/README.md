# Feature files

One file per feature. Each starts with a status (idea | designed | prototype | working | shipped) and the Meta
model it uses, then: purpose, what exists (files, scripts, tests, output dirs), results and numbers, rules
and decisions, open issues, next steps. The session handoff (`docs_offline/progress.md`, gitignored) holds
only the roadmap, status per feature, the decisions log, CK's to-do and the setup state, and points here.

| # | File | Status | Meta model |
|---|---|---|---|
| 000 | [Foundations](000-foundations.md) | decisions | all named per feature |
| 001 | [App shell, auth, ensembles, roles](001-app-shell-auth-ensembles.md) | working | none |
| 002 | [Score upload and storage](002-score-upload-and-storage.md) | working (MusicXML) / prototype (pages) | none |
| 003 | [Score header and page geometry](003-score-header-and-page-geometry.md) | working | Spark (header) |
| 004 | [PDF to bar-numbered pages](004-pdf-to-bar-numbered-pdf.md) | working | Spark (labels) |
| 004 | [Page read speed eval: effort minimal, trimmed answer](004-speed-eval.md) | experiment, minimal shipped with a guard | Spark (labels) |
| 005 | [PDF to MusicXML, OMR on the box](005-pdf-to-musicxml-omr.md) | prototype | Spark (text, closed questions) |
| 006 | [Agent loop harness](006-agent-loop-harness.md) | working | Spark (agent) |
| 007 | [Jobs, spend, per-page metadata](007-jobs-spend-and-page-metadata.md) | working / idea | none |
| 008 | [Part extraction by cutting](008-part-extraction-by-cutting.md) | prototype | Spark (labels, recheck) |
| 009 | [OMR engine comparison](009-omr-engine-comparison.md) | working | none |
| 010 | [Distribution and reading view](010-distribution-and-reading-view.md) | prototype | none |
| 011 | [Edit mode](011-edit-mode.md) | designed | Spark (asks) |
| 012 | [Symbols layer](012-symbols-layer.md) | prototype | Spark (proposes) |
| 013 | [Collaboration intelligence](013-collaboration-intelligence.md) | built (push-to-talk) | Voice Transcribe + Spark |
| 013 | [Always-on listening (research)](013-always-on.md) | research | Voice Transcribe realtime + Spark |
| 013 | [Text eval and prompt v4d](013-text-eval.md) | experiment | Spark |
| 013 | [Library-of-context eval, prompt v4e](013-v4e-eval.md) | experiment, adopted (a, b) | Spark + Voice Transcribe |
| 014 | [Rehearsal tools: play the parts](014-rehearsal-tools.md) | working (local stack, digital books) | none (music21 MIDI, Tone.js) |
| 015 | [iOS wrapper](015-ios-wrapper.md) | idea | none |
| 016 | [Benchmark tool](016-benchmark-tool.md) | to design | Spark, SAM optional |
| 017 | [Demo and submission](017-demo-and-submission.md) | designed | all three |
| 018 | [E2E night: every book through the real chain](018-e2e-night.md) | run 2026-10-31, six fixes on main (yoga to move) | Spark, Voice Transcribe |
