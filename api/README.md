# Folio API

FastAPI backend. Owns every call to the Meta Model API, OMR, and music21 processing, and holds all secrets.

```bash
cp .env.example .env   # fill in keys
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

Docs at http://localhost:8000/docs once running.

## Layout

- `app/auth.py`: `CurrentUser` dependency. Verifies the Supabase session token (JWKS for hosted projects, Supabase Auth for the local stack's HS256 tokens), then loads the `profiles` row. No row = not on the list = 403.
- `app/spend.py`: `BudgetedUser` refuses with 402 when the user's budget or the shared cap is spent; `charge()` records a model call through the `charge_usage` function, which takes one row lock so concurrent calls cannot overspend.
- `app/llm.py`: `complete()` for text and vision reasoning; provider is `LLM_PROVIDER` (anthropic or meta, same SDK, different base URL); returns the text and a `Charge` with the cost.
- `app/routes/me.py`: `GET /me`, the account, its memberships and what it may still spend.
- `app/routes/llm.py`: `POST /llm/probe`, the smallest model call, to prove the chain end to end.

## Database

Schema and policies live in `../supabase/migrations/`. Locally:

```bash
supabase start                 # Docker; applies the migrations
uv run scripts/smoke_local.py  # creates the five demo users locally and checks RLS, storage, jobs, spend, /me, 401/403/402
```

Hosted: `supabase link --project-ref <ref>` once (asks for the database password), then `supabase db push`.
