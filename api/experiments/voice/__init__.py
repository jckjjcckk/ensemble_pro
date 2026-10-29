"""Voice eval (013). Importing the package loads only the META_* keys and forces LLM_PROVIDER=meta, before
anything imports app.settings: this experiment never calls Claude."""

import os
from pathlib import Path

import dotenv

_API = Path(__file__).resolve().parent.parent.parent


def _load_env() -> None:
    cands = [Path(os.environ["FOLIO_ENV"])] if os.environ.get("FOLIO_ENV") else []
    cands += [_API / ".env", Path.home() / "Documents" / "muse" / "api" / ".env"]
    for p in cands:
        if p.exists():
            vals = dotenv.dotenv_values(p)
            for k in ("META_API_KEY", "META_API_BASE_URL"):
                if vals.get(k):
                    os.environ[k] = vals[k]
            break
    os.environ["LLM_PROVIDER"] = "meta"
    os.environ.pop("ANTHROPIC_API_KEY", None)


_load_env()
