"""Sign in to the HOSTED project as one demo account and call the running API's /me.

    cd api && uv run scripts/me_hosted.py            # prompts for the email and the password (never echoed)

Reads VITE_SUPABASE_URL and VITE_SUPABASE_PUBLISHABLE_KEY from ../web/.env, VITE_API_URL likewise
(default http://localhost:8000). The password is typed in the terminal and goes only to Supabase Auth.
"""
import getpass
import json
import sys
from pathlib import Path

import httpx

env = {}
for line in (Path(__file__).resolve().parents[2] / "web" / ".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
url, key = env["VITE_SUPABASE_URL"].rstrip("/"), env["VITE_SUPABASE_PUBLISHABLE_KEY"]
api = env.get("VITE_API_URL", "http://localhost:8000").rstrip("/")

email = input("email [admin@muse.test]: ").strip() or "admin@muse.test"
password = getpass.getpass("password: ")
r = httpx.post(f"{url}/auth/v1/token?grant_type=password", headers={"apikey": key}, json={"email": email, "password": password}, timeout=20)
if r.status_code != 200:
    print("sign-in failed:", r.status_code, r.text[:200]); sys.exit(1)
token = r.json()["access_token"]
print("signed in; token alg:", json.loads(__import__("base64").urlsafe_b64decode(token.split(".")[0] + "==")).get("alg"))
r = httpx.get(f"{api}/me", headers={"Authorization": f"Bearer {token}"}, timeout=20)
print("GET /me ->", r.status_code)
print(json.dumps(r.json(), indent=2))
