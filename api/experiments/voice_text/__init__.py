"""Text-only eval of the second half of the voice pipeline (013): transcript text -> Muse Spark (v4c, chat
completions) -> marks. No speech-to-text. Importing loads only the META_* keys (via experiments.voice) and forces
LLM_PROVIDER=meta. Every paid call goes to this folder's `spend.jsonl`; the cap for this task is $3 (CK, 2026-10-30)."""

from .. import voice as _voice  # noqa: F401  (env loader side effect)
