from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Supabase (new key model: sb_secret_... bypasses RLS, server only)
    supabase_url: str = ""
    supabase_secret_key: str = ""

    # LLM provider for vision + reasoning. SAM always goes through Meta.
    llm_provider: Literal["anthropic", "meta"] = "anthropic"
    anthropic_api_key: str = ""
    meta_api_key: str = ""
    meta_api_base_url: str = ""

    per_user_budget_usd: float = 10.0
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
