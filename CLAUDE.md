# CLAUDE.md — AIPCC

> Copy this file to the root of the **new** repo. It is the context every Claude Code session starts from.
> Keep it current: when architecture changes, update this file in the same commit.

---

## What this is

**AIPCC — AI-Powered Cybersecurity Co-Pilot.** Ingests security logs (CSV / JSON / TXT / LOG), runs a
RAG pipeline over them, and produces structured security reports: attack types (MITRE-mapped), risk
assessment, vulnerabilities (CVE/CWE), anomalies, and an event timeline. Also provides a
"talk to your data" chat over ingested documents, a threat-intel enrichment path, and file-integrity
monitoring.

**This repo is a ground-up rebuild.** A working prototype exists (university group project, 7
contributors) which proved the RAG + report concept but was incomplete and structurally broken.
Its RAG/report logic is being ported; nothing else is. See `PORTING.md`.

**Purpose: portfolio.** Optimize for clean architecture, reproducibility (one-command run), and
tests — over feature count. A reviewer should be able to clone, run `docker compose up`, log in with
seed credentials, and see a populated app.

---

## Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2.x, Alembic |
| DB | PostgreSQL 16 (via Docker locally; managed Postgres in deploy) |
| Vector store | Chroma, `sentence-transformers/all-MiniLM-L6-v2` embeddings |
| LLM | Provider abstraction — Gemini (default), Ollama (local), Groq. Set `LLM_PROVIDER`. |
| Frontend | React 19 + Vite, react-router-dom, Tailwind, TanStack Query |
| Automation | n8n (report orchestrator + file-integrity engine) |
| Auth | OAuth2 password flow, bcrypt, JWT |

---

## Repo layout

```
backend/
  app/
    main.py                 # app factory, router registration, CORS, middleware
    core/
      config.py             # pydantic-settings — ALL env access happens here
      security.py           # bcrypt hashing, JWT create/verify, auth dependencies
    db/
      session.py            # engine + session factory (NEVER drop/create on import)
      models.py             # SQLAlchemy models
      seed.py               # explicit seed script, run manually
    schemas/                # Pydantic: API request/response + LLM output schemas
    api/routers/            # auth, users, documents, reports, chat, dashboard, integrations
    services/
      rag/                  # ingest, chunk, embed  (ported from prototype)
      llm/                  # LLMProvider abstraction + implementations
      report.py             # parallel section generation, validation, retry
      chatbot.py            # chat over ingested docs
      threat_intel.py       # AbuseIPDB / VirusTotal enrichment
      integrity.py          # FIM hash storage + comparison
  alembic/                  # migrations
  tests/                    # pytest
frontend/
  public/video/             # optimized background clips + posters (see manifest.md)
  src/
    components/motion/      # CSS/SVG feature animations (no deps)
    components/ui/          # design system primitives
    pages/                  # one file per route
    lib/apiClient.js        # axios instance, JWT interceptor, 401 handling
n8n/                        # workflow JSONs + IMPORT.md
docker-compose.yml
```

---

## Commands

```bash
# Full stack (primary path)
docker compose up                  # backend + frontend + postgres + n8n
docker compose up postgres -d      # just the DB

# Backend
cd backend
uvicorn app.main:app --reload
alembic upgrade head               # apply migrations
alembic revision --autogenerate -m "msg"
python -m app.db.seed              # seed demo data (never automatic)
pytest

# Frontend
cd frontend
npm install
npm run dev
```

---

## Conventions

- **Env access only through `app/core/config.py`.** No bare `os.getenv` anywhere else.
- **Pydantic schemas are the contract.** The report generator and the DB-storage layer must use the
  *same* schema objects — field names must never be duplicated as string literals in two places.
  (The prototype's #1 bug was exactly this drift.)
- **Routers stay thin.** Business logic lives in `services/`, DB access in `db/`.
- **Every new endpoint gets a test.** Minimum: happy path + auth rejection.
- **Frontend server state goes through TanStack Query.** No `fetch` in components.
- **Absolute imports** in frontend via `@/` alias.

---

## Hard rules — never reintroduce these

These are the specific defects of the prototype. Reintroducing one is a regression:

1. **Never call `Base.metadata.drop_all()` / `create_all()` at import time.** The prototype wiped its
   database on every boot. Schema changes go through Alembic only.
2. **Never hardcode a `current_user`.** The user comes from the JWT via `get_current_user`.
3. **Never store plaintext passwords.** bcrypt, always.
4. **Never render pages without a router.** The prototype stacked every page in `App.jsx`.
5. **Never let LLM output reach the DB unvalidated.** Parse → validate against the Pydantic schema →
   retry once on failure → typed error. No silent `except: pass`.
6. **No debug UI in committed code.** No "DEBUG: App mounted" banners.

---

## LLM policy

One story, not three. `LLM_PROVIDER` selects the backend:
- `gemini` (default) — runnable with a single API key, so a reviewer can start it easily.
- `ollama` — local execution, the data-sovereignty story. Documented, optional.
- `groq` — used by the n8n orchestrator.

The README must describe what the code actually does. The prototype's README claimed local Ollama and
AES-256 encryption that did not exist — do not repeat that.

---

## Motion / video assets

Already produced and optimized — do not regenerate:
- `frontend/public/video/` — 7 clips (MP4 + WebM + posters). Read `manifest.md` before using any of
  them; it contains hard usage rules (never two moving things at once, motion behind content only).
- `frontend/src/components/motion/` — 4 dependency-free CSS/SVG feature animations.

Ambient motion plays for all users. The **only** `prefers-reduced-motion` gate in the app is skipping
the intro clip's full-screen flash.

---

## Current status

**Phase 0 (Foundation) — complete.** See `AIPCC_CLAUDE_CODE_PROMPTS.md` for the phase sequence and
`AIPCC_REBUILD_PLAN.md` for the full architecture rationale.

In place: backend package + app factory, centralized config, all 10 SQLAlchemy models on UUID keys,
Alembic initial migration, explicit seed script, the ported RAG pipeline (ingest/chunk/embed/
vectorstore), `docker-compose.yml` (postgres + backend + frontend + n8n), and the frontend scaffold
(Vite + React 19 + Router + Tailwind v4 + TanStack Query) with one placeholder route.

Not yet built: auth (Phase 2), report generation (Phase 1), real pages (Phase 3). `services/llm/` and
`schemas/` are empty packages awaiting Phase 1.

### Decisions taken in Phase 0

- **Table names are lowercase** (`users`, not the prototype's `USER`). `USER` is reserved in Postgres.
  Column names are unchanged, so ported logic still lines up.
- **`core/security.py` and `bcrypt` landed early.** `seed.py` creates an admin user, and writing a
  plaintext password even temporarily would break hard rule #3. Only `hash_password` / `verify_password`
  so far; JWT and the auth dependencies arrive in Phase 2.
- **`ingest()` takes `(path, extension, document_id)`**, not a `Document` ORM object. This is what
  removed the prototype's `from backend.main import *` circular import, and it makes RAG ingestion
  testable with no database.
- **`seed.py --ingest` is opt-in.** Default seeding is DB-only; embedding the sample CSV is behind a
  flag because it triggers the MiniLM download.
- **Hard rules are enforced by tests**, not convention alone — see
  `tests/test_foundation.py::TestHardRules`. The scanner masks comments and string literals before
  matching, so it tests code rather than prose.

### Known gap carried into Phase 5

The three n8n workflow JSONs described in `AIPCC_REBUILD_PLAN.md` §2 **do not exist in the prototype
repo** and were never committed to it on any branch. `PORTING.md` lists them as portable; there is
nothing to port. They must be exported from whichever n8n instance holds them, or rebuilt. Related:
commits `c836a19` and `bd55a3f` in the prototype added `file_hash` / security-alert endpoints that are
absent from its current tree — recoverable with `git show` as reference material.

**Update this section at the end of every phase.**
