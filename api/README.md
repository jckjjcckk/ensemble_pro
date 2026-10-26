# Muse API

FastAPI backend. Owns every call to the Meta Model API, OMR, and music21 processing.

```bash
cp .env.example .env   # fill in keys
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

Docs at http://localhost:8000/docs once running.
