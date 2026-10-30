"""Always-on voice mode experiments (013). Importing `experiments.voice` loads only the META_* keys and forces
LLM_PROVIDER=meta, so nothing here can call Claude. Every paid call goes to `spend.jsonl` with its cost; the cap
for this task is $5 (CK, 2026-10-30)."""

from .. import voice as _voice  # noqa: F401  (env loader side effect)
