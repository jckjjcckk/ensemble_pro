"""E2E night 2026-10-31: the real chain (hosted Supabase, the Mac dev API, yoga's stable worker) driven as the iPad
would drive it, one test account at a time.

A session for a test account comes from the service role (`generate_link` + `verify`, no password and no sign-in
screen); every write after that goes through RLS with that account's token, exactly as supabase-js would send it,
and every API call goes to the dev API with the same body as `web/src/lib/api.ts` and `web/src/app/data.tsx`.

Nothing here prints a key, a token or the project URL.

    cd api && PYTHONPATH=. uv run python -m experiments.e2e_night.<script>
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from app.db import db

HERE = Path(__file__).resolve().parent
API_DIR = HERE.parent.parent
ROOT = API_DIR.parent
RESULTS = HERE / "results"
LEDGER = HERE / "spend.jsonl"
CAP_USD = 12.0
API = os.environ.get("E2E_API", "https://folio-api-dev.jckjjcckk.com").rstrip("/")
TOKENS = Path(os.environ.get("E2E_TOKENS", "/private/tmp/claude-501/-Users-ckjiang-Documents-muse/c322debc-0f64-428b-a5ee-2e7fbc0c306c/scratchpad/tokens.json"))
GROUP = "Hart House Quartet"
ADMIN = "admin1@muse.test"


def _web_env() -> dict[str, str]:
    env = {}
    for line in (ROOT / "web" / ".env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


_ENV = _web_env()
SB_URL = _ENV["VITE_SUPABASE_URL"].rstrip("/")
PUB = _ENV["VITE_SUPABASE_PUBLISHABLE_KEY"]


def now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


# ---------------------------------------------------------------- sessions (service role, no password)

def token(email: str) -> str:
    """An access token for a test account, cached until five minutes before it expires."""
    cache = json.loads(TOKENS.read_text()) if TOKENS.exists() else {}
    hit = cache.get(email)
    if hit and hit["expires_at"] - 300 > time.time():
        return hit["access_token"]
    # A new link spends the one before it: two scripts refreshing at once refuse each other (otp_expired). Lock, then
    # read the cache again, and try a fresh link up to three times.
    import fcntl
    with open(str(TOKENS) + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        cache = json.loads(TOKENS.read_text()) if TOKENS.exists() else {}
        hit = cache.get(email)
        if hit and hit["expires_at"] - 300 > time.time():
            return hit["access_token"]
        for attempt in range(3):
            link = db().auth.admin.generate_link({"type": "magiclink", "email": email})
            hashed = link.properties.hashed_token
            r = httpx.post(f"{SB_URL}/auth/v1/verify", headers={"apikey": PUB}, json={"type": "magiclink", "token_hash": hashed}, timeout=20)
            if r.status_code == 200:
                break
            time.sleep(2 + attempt * 3)
        else:
            raise RuntimeError(f"verify for {email} refused: {r.status_code}")
        body = r.json()
        cache[email] = {"access_token": body["access_token"], "expires_at": body.get("expires_at") or time.time() + body["expires_in"]}
        TOKENS.write_text(json.dumps(cache))
        os.chmod(TOKENS, 0o600)
        return body["access_token"]


class As:
    """One account, as the iPad would act: Supabase REST/Storage/RPC under RLS, and the dev API."""

    def __init__(self, email: str = ADMIN):
        self.email = email
        self.tok = token(email)
        self.uid = db().table("profiles").select("id").eq("email", email).single().execute().data["id"]
        self.sb = httpx.Client(base_url=SB_URL, timeout=60)
        self.api_http = httpx.Client(base_url=API, timeout=180)

    def _h(self, extra: dict | None = None) -> dict:
        self.tok = token(self.email)
        h = {"apikey": PUB, "Authorization": f"Bearer {self.tok}"}
        h.update(extra or {})
        return h

    def rest(self, method: str, path: str, **kw) -> httpx.Response:
        headers = self._h({"Prefer": "return=representation", **kw.pop("headers", {})})
        return self.sb.request(method, f"/rest/v1/{path}", headers=headers, **kw)

    def rpc(self, name: str, args: dict) -> httpx.Response:
        return self.sb.post(f"/rest/v1/rpc/{name}", headers=self._h(), json=args)

    def upload(self, key: str, data: bytes, ctype: str) -> httpx.Response:
        return self.sb.post(f"/storage/v1/object/scores/{key}", headers=self._h({"Content-Type": ctype, "x-upsert": "true"}), content=data)

    def download(self, key: str) -> httpx.Response:
        return self.sb.get(f"/storage/v1/object/authenticated/scores/{key}", headers=self._h())

    def list_storage(self, prefix: str) -> list[dict]:
        r = self.sb.post("/storage/v1/object/list/scores", headers=self._h(), json={"prefix": prefix, "limit": 1000})
        return r.json() if r.status_code == 200 else []

    def api(self, method: str, path: str, **kw) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token(self.email)}", **kw.pop("headers", {})}
        if "json" in kw:
            headers.setdefault("Content-Type", "application/json")
        return self.api_http.request(method, path, headers=headers, **kw)


# ---------------------------------------------------------------- the ledger

def spent() -> float:
    if not LEDGER.exists():
        return 0.0
    return sum(float(json.loads(l)["usd"]) for l in LEDGER.read_text().splitlines() if l.strip())


def guard(next_usd: float = 0.0) -> None:
    if spent() + next_usd > CAP_USD:
        sys.exit(f"STOP: ledger {spent():.4f} + {next_usd:.4f} would pass the ${CAP_USD} cap")


NIGHT_START = "2026-10-31T09:20:00+00:00"


def _slug_of_scores() -> dict[str, str]:
    out = {}
    for f in RESULTS.glob("*.json"):
        try:
            d = json.loads(f.read_text())
        except Exception:  # noqa: BLE001
            continue
        if isinstance(d, dict) and d.get("score_id") and d.get("slug"):
            out[d["score_id"]] = d["slug"]
    return out


def sync_ledger(user_id: str, book: str | None = None, since: str = NIGHT_START) -> float:
    """Copy the account's `usage_events` rows (one per model call, charged by whichever API made it) into spend.jsonl, once
    each (by event id), each under the book its job worked on. Run it before a book is deleted: the job ids go null with
    the jobs. `book` is only the fallback for a call whose job is gone."""
    rows_old = [json.loads(l) for l in LEDGER.read_text().splitlines() if l.strip()] if LEDGER.exists() else []
    seen = {r.get("event") for r in rows_old}
    rows: list[dict] = []
    while True:     # PostgREST answers at most 1000 rows a request: page through
        page = db().table("usage_events").select("id,job_id,provider,model,kind,input_tokens,output_tokens,units,cost_usd,created_at") \
            .eq("user_id", user_id).gte("created_at", since).order("created_at").order("id").range(len(rows), len(rows) + 999).execute().data or []
        rows += page
        if len(page) < 1000:
            break
    jobs: dict[str, dict] = {}
    jids = sorted({r["job_id"] for r in rows if r.get("job_id")})
    for i in range(0, len(jids), 50):
        for j in db().table("jobs").select("id,kind,score_id,payload").in_("id", jids[i:i + 50]).execute().data or []:
            jobs[j["id"]] = j
    slugs = _slug_of_scores()
    added = 0.0
    with LEDGER.open("a") as f:
        for r in rows:
            if r["id"] in seen:
                continue
            j = jobs.get(r.get("job_id") or "") or {}
            sid = j.get("score_id") or (j.get("payload") or {}).get("score_id")
            row = {"ts": r["created_at"], "event": r["id"], "book": slugs.get(sid or "", book), "job": r.get("job_id"), "job_kind": j.get("kind"),
                   "provider": r["provider"], "model": r["model"], "kind": r["kind"], "input_tokens": r["input_tokens"],
                   "output_tokens": r["output_tokens"], "units": r["units"], "usd": float(r["cost_usd"])}
            f.write(json.dumps(row) + "\n")
            added += row["usd"]
    return added


def cost_of(job_ids: list[str]) -> float:
    if not job_ids:
        return 0.0
    rows = db().table("usage_events").select("cost_usd").in_("job_id", job_ids).execute().data or []
    return round(sum(float(r["cost_usd"]) for r in rows), 4)


# ---------------------------------------------------------------- results

def save(name: str, data: Any) -> Path:
    RESULTS.mkdir(exist_ok=True)
    p = RESULTS / f"{name}.json"
    p.write_text(json.dumps(data, indent=1, default=str))
    return p


def load(name: str) -> Any:
    p = RESULTS / f"{name}.json"
    return json.loads(p.read_text()) if p.exists() else None


def group_id() -> str | None:
    rows = db().table("ensembles").select("id").eq("name", GROUP).execute().data
    return rows[0]["id"] if rows else None
