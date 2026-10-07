"""Runtime configuration from environment."""
import os
from dotenv import load_dotenv
from pydantic import BaseModel, Field

class Settings(BaseModel):
    llm_provider: str = "mock"
    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None
    llm_model: str = "gemini-2.5-flash"
    llm_timeout_seconds: float = 30.0
    history_window: int = 12
    database_url: str = "data/sessions.db"
    session_ttl_seconds: int = 86400
    rate_limit_per_minute: int = 30
    app_version: str = "2.0.0"


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        llm_provider=os.getenv("LLM_PROVIDER", "mock"),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
        gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
        llm_model=os.getenv("LLM_MODEL", "gemini-2.5-flash"),
        llm_timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "30")),
        history_window=int(os.getenv("HISTORY_WINDOW", "12")),
        database_url=os.getenv("DATABASE_URL", "data/sessions.db"),
        session_ttl_seconds=int(os.getenv("SESSION_TTL_SECONDS", "86400")),
        rate_limit_per_minute=int(os.getenv("RATE_LIMIT_PER_MINUTE", "30")),
    )
