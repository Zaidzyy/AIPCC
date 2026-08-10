"""Application configuration.

This module is the ONLY place in the codebase that reads the environment.
Everything else imports `settings` from here. See CLAUDE.md > Conventions.
"""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Repo-root-relative anchor so default paths resolve the same way whether the
# app is started from backend/, the repo root, or inside the container.
BACKEND_DIR = Path(__file__).resolve().parents[2]
# `.env.example` sits at the repo root, and docker compose reads the root
# `.env` for its ${VAR} substitution, so that is where a .env is expected.
REPO_ROOT = BACKEND_DIR.parent

# RFC 7518 §3.2 minimum for HS256.
MIN_JWT_SECRET_BYTES = 32


class ModelPrice(BaseModel):
    """What one model costs, per million tokens, in USD.

    Per *million* rather than per token because that is the unit every provider
    publishes, so a value copied off a pricing page can be pasted in unchanged.
    Converting by hand is how a price ends up wrong by three orders of
    magnitude in a way nobody notices until the total looks plausible.
    """

    input_usd_per_1m: float = Field(ge=0)
    output_usd_per_1m: float = Field(ge=0)


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

    # --- Observability (Phase 9) -------------------------------------------
    # `auto` means JSON everywhere except `local`, where a human is reading the
    # terminal. Pinned explicitly when you want the other one — reproducing a
    # log-parsing bug locally, or reading a container log by eye.
    log_level: str = "INFO"
    log_format: Literal["auto", "json", "console"] = "auto"

    # Tracing is **off by default**, and the exporter it defaults to when turned
    # on is the console. Emitting a span dump to stdout on every request out of
    # the box would make `docker compose up` unreadable and would be the first
    # thing anyone switched off — see CLAUDE.md > Phase 9.
    otel_enabled: bool = False
    otel_service_name: str = "aipcc-backend"
    # Set this and spans go to a collector instead of the console. Base URL,
    # e.g. http://localhost:4318 — the exporter appends /v1/traces.
    otel_exporter_otlp_endpoint: str | None = None

    # --- LLM cost accounting ------------------------------------------------
    # Prices are **configuration, not constants**: they change without warning,
    # they differ per account, and a number compiled into the code is one nobody
    # will remember to look at. Override with the LLM_PRICES env var as JSON:
    #
    #   LLM_PRICES={"gemini-2.5-flash":{"input_usd_per_1m":0.3,"output_usd_per_1m":2.5}}
    #
    # The defaults below are published list prices as of 2026-08 and are a
    # starting point, not a source of truth — check them against the provider's
    # pricing page before quoting any figure this app produces.
    #
    # A model that is **not in this table costs `null`, never `0`.** "I do not
    # know what this costs" and "this is free" are the pair of states that must
    # never look alike, exactly as on the dashboard aggregates. Ollama is the
    # only genuine zero, because it runs locally — and it still reports tokens.
    llm_prices: dict[str, ModelPrice] = Field(
        default_factory=lambda: {
            "gemini-2.5-flash": ModelPrice(input_usd_per_1m=0.30, output_usd_per_1m=2.50),
            "gemini-2.5-pro": ModelPrice(input_usd_per_1m=1.25, output_usd_per_1m=10.00),
            "llama-3.3-70b-versatile": ModelPrice(
                input_usd_per_1m=0.59, output_usd_per_1m=0.79
            ),
            # Local. Free at the point of use, and the tokens still count.
            "llama3.1": ModelPrice(input_usd_per_1m=0.0, output_usd_per_1m=0.0),
        }
    )

    # --- Evaluation gate (Phase 11) ----------------------------------------
    # What `python -m app.eval.run --gate` enforces, in configuration rather
    # than in code because a quality bar is a project decision that moves as
    # the system improves, and one buried in a function is one nobody raises.
    #
    # **These are regression thresholds calibrated to the committed fixture,
    # not the product's aspiration.** The gate replays a frozen recording, so
    # the numbers it produces are constants until the *harness* changes — which
    # is exactly what a gate on a fixture can detect. The committed cassette is
    # a real recording from `llama3.1:8b`, deliberately a small local model,
    # and it scores 75% on technique-name accuracy: it fabricates three ATT&CK
    # names and five citations, all of which the validators catch. Holding that
    # fixture to a 10% bar would leave CI permanently red and prove nothing;
    # holding it to its own baseline catches a validator that stops catching,
    # a parser that starts dropping findings, or a prompt that has drifted.
    #
    # A live run against the configured provider is the number that describes a
    # model — see backend/EVAL.md, which records both.
    eval_max_hallucination_rate: float = 0.80
    eval_min_grounding_rate: float = 0.90
    eval_min_section_success_rate: float = 0.80
    # The floor that makes the gate mean something on a frozen fixture. Rate
    # thresholds alone are weak here: a validator that *stopped catching*
    # anything would send the hallucination rate to zero and sail through every
    # bound above. The committed cassette contains four known identifier
    # defects, so the gate fails if the harness detects fewer than it did.
    eval_min_detected_issues: int = 4

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
