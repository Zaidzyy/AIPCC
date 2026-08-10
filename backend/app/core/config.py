"""Application configuration.

This module is the ONLY place in the codebase that reads the environment.
Everything else imports `settings` from here. See CLAUDE.md > Conventions.
"""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Repo-root-relative anchor so default paths resolve the same way whether the
# app is started from backend/, the repo root, or inside the container.
BACKEND_DIR = Path(__file__).resolve().parents[2]
# `.env.example` sits at the repo root, and docker compose reads the root
# `.env` for its ${VAR} substitution, so that is where a .env is expected.
REPO_ROOT = BACKEND_DIR.parent

# RFC 7518 §3.2 minimum for HS256.
MIN_JWT_SECRET_BYTES = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Absolute paths, not ".env". A relative name resolves against the
        # process working directory, so running the documented
        # `cd backend && uvicorn app.main:app` silently ignored the .env at the
        # repo root and fell back to defaults with no warning.
        # Repo root first, backend/ second; later files win in pydantic-settings,
        # so a backend-local .env can override the shared one.
        env_file=(REPO_ROOT / ".env", BACKEND_DIR / ".env"),
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

    # --- Auth ---------------------------------------------------------------
    # HS256 wants >= 32 bytes of key (RFC 7518 §3.2); PyJWT warns below that.
    # The default is long enough to be valid but is obviously not a secret.
    jwt_secret: str = "dev-only-insecure-secret-change-me-before-deploying"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # --- LLM ---------------------------------------------------------------
    llm_provider: Literal["gemini", "ollama", "groq"] = "gemini"
    # Low by design. This is structured extraction from logs, not creative
    # writing: high temperature makes smaller models drift off the schema and
    # invent MITRE ids. The prototype's 0.7 was arbitrary.
    llm_temperature: float = 0.2
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

    # --- Rate limiting (Phase 8) -------------------------------------------
    # State lives in Postgres, in `auth_attempts`. See CLAUDE.md > Phase 8 for
    # why not Redis and why not process memory.
    #
    # Two controls, because there are two attacks. The per-IP lockout is what
    # actually stops a flood. The per-account control is a *delay and never a
    # lock*, so nobody can take a real user offline by failing their login on
    # purpose — see CLAUDE.md.
    rate_limit_enabled: bool = True
    login_ip_max_failures: int = 5
    login_ip_window_minutes: int = 15
    # Delays start on the failure *after* this many: 3 means failure #4 sleeps.
    login_delay_after_failures: int = 3
    # The cap matters. Each delayed login holds one threadpool thread, so an
    # unbounded backoff would be a denial of service against ourselves.
    login_delay_max_seconds: float = 8.0
    register_ip_max_per_hour: int = 5
    # Change-password is behind a valid session for that exact account, so only
    # the account holder can spend this budget. A hard lock is safe here.
    password_change_max_failures: int = 5
    password_change_window_minutes: int = 15
    # The public share route has no account to key on and is a read, so this is
    # a flood ceiling rather than a brute-force control. Tokens are 32 bytes;
    # guessing one is not the threat, scraping with a valid one is.
    share_ip_max_per_minute: int = 60
    # `python -m app.db.prune` drops attempt rows older than this.
    auth_attempt_retention_days: int = 30
    # `X-Forwarded-For` is caller-supplied and is ignored unless something in
    # front of this app is guaranteed to overwrite it. Trusting it by default
    # would turn a per-IP lockout into a per-attacker-chosen-string lockout —
    # no lockout at all — and would let anyone lock out someone else's address
    # by claiming it.
    trust_proxy_header: bool = False

    # --- Sharing -----------------------------------------------------------
    # Where a share link points. This is the *frontend* origin, not the API's:
    # a share URL is opened by a person in a browser, and the page they land on
    # is a React route. Set it to the deployed origin in production or every
    # link the app hands out will point at somebody's localhost.
    share_base_url: str = "http://localhost:5173"

    # --- CORS --------------------------------------------------------------
    # NoDecode is required. For complex types pydantic-settings tries
    # json.loads() on the raw env value *before* field validators run, so the
    # comma-separated form documented in .env.example raised a SettingsError at
    # import and took the whole app down. NoDecode hands the raw string to the
    # validator below instead.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default=["http://localhost:5173", "http://localhost:3000"]
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, v: object) -> object:
        """Accept a comma-separated string, or a JSON array, or a list."""
        if isinstance(v, str):
            text = v.strip()
            if text.startswith("["):
                import json

                return json.loads(text)
            return [origin.strip() for origin in text.split(",") if origin.strip()]
        return v

    @model_validator(mode="after")
    def _check_jwt_secret(self) -> "Settings":
        """Refuse to start outside local with a weak or default signing key."""
        if self.environment == "local":
            return self
        if len(self.jwt_secret.encode()) < MIN_JWT_SECRET_BYTES:
            raise ValueError(
                f"JWT_SECRET must be at least {MIN_JWT_SECRET_BYTES} bytes in "
                f"{self.environment}. Generate one with: "
                'python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        if self.jwt_secret.startswith("dev-only"):
            raise ValueError(f"the development JWT_SECRET cannot be used in {self.environment}")
        return self

    @property
    def is_local(self) -> bool:
        return self.environment == "local"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
