"""Who is calling. The browser sends the Supabase session token as a Bearer header.

Tokens signed with the project's asymmetric key (ES256/RS256, the default on hosted projects) are verified
locally against the JWKS endpoint, cached. HS256 tokens (the local dev stack's legacy secret) are checked
by asking Supabase Auth directly. Either way an unknown or expired token is a 401, and a user without a
profile row is refused: signups are off, the profiles table is the whitelist.
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated

import httpx
import jwt
from fastapi import Depends, HTTPException, Request
from jwt import PyJWKClient

from .db import db
from .settings import settings


@dataclass(frozen=True)
class User:
    id: str
    email: str | None
    display_name: str | None
    budget_usd: Decimal
    spent_usd: Decimal

    @property
    def over_budget(self) -> bool:
        return self.spent_usd >= self.budget_usd


_jwks: PyJWKClient | None = None


def _jwks_client() -> PyJWKClient:
    global _jwks
    if _jwks is None:
        _jwks = PyJWKClient(settings.jwks_url, cache_keys=True, lifespan=3600)
    return _jwks


def _bearer(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "Sign in first")
    return token


async def user_id_from_token(token: str) -> str:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        raise HTTPException(401, "Bad token")
    alg = header.get("alg", "")
    if alg == "HS256":
        # Local stack: let Supabase Auth validate it.
        async with httpx.AsyncClient(timeout=10) as http:
            r = await http.get(
                f"{settings.supabase_url.rstrip('/')}/auth/v1/user",
                headers={"Authorization": f"Bearer {token}", "apikey": settings.supabase_secret_key},
            )
        if r.status_code != 200:
            raise HTTPException(401, "Token refused")
        return r.json()["id"]
    try:
        key = _jwks_client().get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=[alg], audience="authenticated")
    except jwt.PyJWTError:
        raise HTTPException(401, "Token refused")
    return claims["sub"]


def load_user(user_id: str) -> User:
    rows = db().table("profiles").select("id,email,display_name,budget_usd,spent_usd").eq("id", user_id).limit(1).execute().data
    if not rows:
        raise HTTPException(403, "This account is not on the list")
    p = rows[0]
    return User(
        id=p["id"], email=p.get("email"), display_name=p.get("display_name"),
        budget_usd=Decimal(str(p["budget_usd"])), spent_usd=Decimal(str(p["spent_usd"])),
    )


async def current_user(request: Request) -> User:
    return load_user(await user_id_from_token(_bearer(request)))


CurrentUser = Annotated[User, Depends(current_user)]
