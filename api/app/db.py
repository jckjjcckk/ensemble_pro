"""One Supabase client with the secret key. It bypasses RLS: every write it makes is the API's responsibility."""
from functools import lru_cache

from supabase import Client, create_client

from .settings import settings


@lru_cache(maxsize=1)
def db() -> Client:
    if not settings.supabase_url or not settings.supabase_secret_key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SECRET_KEY must be set in api/.env")
    return create_client(settings.supabase_url, settings.supabase_secret_key)
