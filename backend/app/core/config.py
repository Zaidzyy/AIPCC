"""Application configuration.

This module is the ONLY place in the codebase that reads the environment.
Everything else imports `settings` from here. See CLAUDE.md > Conventions.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo-root-relative anchor so default paths resolve the same way whether the
# app is started from backend/, the repo root, or inside the container.
BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- App ---------------------------------------------------------------
    app_name: str = "AIPCC"
    environment: Literal["local", "ci", "production"] = "local"
    debug: bool = False

    # --- Database ----------------------------------------------------------
    # Points at the Docker Postgres by default. Never a managed/external DB.
    database_url: str = "postgresql+psycopg://aipcc:aipcc@localhost:5432/aipcc"

    # --- Auth (wired up in Phase 2; defined here so config stays central) ---
    jwt_secret: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # --- LLM ---------------------------------------------------------------
    llm_provider: Literal["gemini", "ollama", "groq"] = "gemini"
    llm_temperature: float = 0.7
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"

    # --- RAG / vector store ------------------------------------------------
    chroma_dir: Path = BACKEND_DIR / "chroma_langchain_db"
    chroma_collection: str = "AIPCC_db"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_device: str = "cpu"
    chunk_size: int = 1000
    chunk_overlap: int = 0
    hf_token: str | None = None

    # --- Uploads -----------------------------------------------------------
    upload_dir: Path = BACKEND_DIR / "uploads"

    # --- CORS --------------------------------------------------------------
    cors_origins: list[str] = Field(
        default=["http://localhost:5173", "http://localhost:3000"]
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, v: object) -> object:
        """Accept a comma-separated string so .env stays readable."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    @property
    def is_local(self) -> bool:
        return self.environment == "local"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
