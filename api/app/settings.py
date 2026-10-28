from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Supabase (new key model: sb_secret_... bypasses RLS, server only)
    supabase_url: str = ""
    supabase_secret_key: str = ""

    # LLM provider for text + vision reasoning. SAM and Voice Transcribe always go through Meta.
    llm_provider: Literal["anthropic", "meta"] = "anthropic"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5-5"
    meta_api_key: str = ""
    meta_api_base_url: str = "https://api.meta.ai/v1"
    meta_model: str = "muse-spark-1.3"

    # Seeds profiles.budget_usd for new rows (the live value is the table).
    per_user_budget_usd: float = 10.0
    cors_origins: str = "http://localhost:5173"

    # An imported PDF longer than this fails with a sentence instead of being read (002): about $0.01 and 5-10 s
    # of reading per page, so 40 pages is about $0.40 and five minutes. Raise it in api/.env when CK says.
    pdf_max_pages: int = 40

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def jwks_url(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"


settings = Settings()
