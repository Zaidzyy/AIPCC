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
      demo_data.py          # deterministic --demo fixtures (fixed seed, no LLM)
    schemas/                # Pydantic: API request/response + LLM output schemas
    api/routers/            # auth, users, documents, reports, chat, dashboard, integrations
    services/
      rag/                  # ingest, chunk, embed  (ported from prototype)
      llm/                  # LLMProvider abstraction + implementations
      report.py             # parallel section generation, validation, retry
      analytics.py          # dashboard aggregation — GROUP BY in SQL, never ORM loops
      chatbot.py            # chat over ingested docs
      threat_intel.py       # AbuseIPDB / VirusTotal enrichment
      integrity.py          # FIM hash storage + comparison
  alembic/                  # migrations
  tests/                    # pytest
frontend/
  public/video/             # optimized background clips + posters (see manifest.md)
  eslint.config.js          # flat config; react-hooks rules are the ones that matter
  src/
    index.css               # @theme tokens — the whole design system lives here
    App.jsx                 # routes only
    components/charts/      # Recharts wrappers; ChartGrid is lazy-loaded — see below
    components/motion/      # CSS/SVG feature animations (no deps)
    components/ui/          # design system primitives (Radix behaviour, own styling)
    components/layout/      # AppShell, Sidebar, Topbar
    components/common/      # PageHeader, SeveritySpine, AmbientVideo, IntroSequence
    components/report/      # the five report section renderers
    context/AuthContext.jsx # token + current user; the only source of "who am I"
    hooks/queries.js        # every TanStack Query hook and its query keys
    routes/                 # ProtectedRoute, AdminRoute
    pages/                  # one file per route
    lib/apiClient.js        # axios instance, JWT interceptor, 401 handling
    lib/api/                # one module per backend router
    lib/format.js           # severity + status tokens, date/byte formatting
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
python -m app.db.seed --demo       # + six weeks of deterministic demo reports
python -m app.db.seed --reset --demo   # wipe seeded users first, then re-seed
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

**Phases 0–4 complete.** See `AIPCC_CLAUDE_CODE_PROMPTS.md` for the phase sequence and
`AIPCC_REBUILD_PLAN.md` for the full architecture rationale.

In place: backend package + app factory, centralized config, all 10 SQLAlchemy models on UUID keys,
Alembic migrations, explicit seed script, the ported RAG pipeline (ingest/chunk/embed/vectorstore),
`docker-compose.yml` (postgres + backend + frontend + n8n), report generation with a single
canonical schema, concurrent sections, validation + one repair retry, an `LLMProvider` abstraction,
the document/report endpoints n8n calls, OAuth2 password-flow auth with bcrypt, JWT and
role-gated, ownership-scoped endpoints, a persisted RAG chat over ingested documents, the
full React SPA — nine routes behind a single app shell, a Radix-based design system, and every
server read going through TanStack Query — **and five `/dashboard` aggregation endpoints backed by
SQL `GROUP BY`, four Recharts views bound to them, and a `--demo` seed that populates them.**
177 backend tests pass; `npm run lint` is clean.

Not yet built: n8n wiring (Phase 5), export (6), polish (7).

Seed credentials: `admin@aipcc.io` / `admin` (`python -m app.db.seed`).
Add `--ingest` to embed the sample CSV — without it the document is registered but has no chunks,
and report generation fails with "no indexed content for document …".
Add `--demo` for a populated dashboard; it also creates `analyst@aipcc.io` / `analyst`, whose
smaller numbers on the same page are the ownership scoping working.

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

### Decisions taken in Phase 1

- **The canonical schema lives in `app/schemas/report.py`** and its field names are identical to the
  ORM column names, so storage is `Model(**item.model_dump())` with no mapping step to drift.
  Enforced by `tests/test_report.py::TestSchemaAlignment`.
- **Attack risk fields are flat, not nested.** The prototype's prompt nested them under
  `risk_assessment` while the table stored them flat. Flat matches the columns.
- **Prompt JSON skeletons are generated from the Pydantic models** (`json_skeleton`), so renaming a
  field updates the prompt automatically.
- **A section that fails twice returns a typed `SectionError`**, and the report is stored with status
  `partial` or `failed`. One bad section no longer sinks the whole report.
- **Provider failures are not retried** — re-prompting cannot fix a rejected API key.
- **`store_report` is shared** by the Python generator and `POST /store_generated_report`, so
  app-generated and n8n-generated reports land in identical tables.

### Decisions taken in Phase 2

- **`get_current_user` is the only way a route learns who is calling.** No module-level user, ever.
- **Ownership violations return 404, not 403.** A 403 confirms the id is real to someone who should
  not know that.
- **Login is constant-shaped**: identical error text for unknown email and wrong password, and a dummy
  bcrypt verification on the unknown-email path so latency does not distinguish the two.
- **`/auth/register` always creates an `analyst`.** A `role` in the body is ignored, never honoured;
  only the admin-only `POST /users` can set one.
- **`UserPublic.email` is `str`, not `EmailStr`.** Addresses are validated strictly on input.
  Re-validating on output means one bad historical row raises inside the list endpoint and breaks the
  listing for everyone. This was found live: the seeded `admin@aipcc.local` is a reserved-domain
  address that `EmailStr` rejects, and it took down `GET /users`. Seed now uses `admin@aipcc.io`.
- **`JWT_SECRET` must be ≥32 bytes outside `local`**, and the dev default is refused there — HS256
  wants at least that (RFC 7518 §3.2) and PyJWT warns below it.
- **Admins cannot demote, deactivate or delete themselves**, so the last admin can't lock everyone out.

### Decisions taken in Phase 3

**Chat backend** (Phase 3 needed a `/chat` page and `chatbot.py` had never been ported):

- **`services/chatbot.py` takes plain values and returns plain values** — no DB session, no vector
  store handle, no hidden history query. The prototype's `answer_prompt` did all three plus the LLM
  call inside one bare `except`, so a retrieval bug and a provider outage both surfaced as
  `(chat_id, None)`. Persistence lives in the router; the service is testable with neither Postgres
  nor Chroma.
- **The `Chat` / `Message` tables already existed and were unused**, so conversations are persisted
  rather than stateless.
- **Retrieval is scoped per attached document**, and each chunk comes back as a cited `Source`. A
  chat with nothing attached retrieves nothing rather than searching every document in the store.
- **The question is committed before the provider is called.** An outage loses the answer but never
  the question; the turn is marked `failed` and the route returns 502.
- **Chat names are derived from the first message locally.** The prototype spent a second LLM round
  trip on this, so a provider hiccup could fail chat *creation*.

**Frontend:**

- **Colour is a warning.** The chrome is strictly monochrome graphite; chroma appears only where it
  encodes a severity or a state. That is why the primary button is white rather than an accent hue,
  and why the focus ring is white. Anything coloured in this UI is telling the analyst something.
- **The type pairing is inverted:** IBM Plex Mono is the *display* face (titles, section headers,
  every identifier), Plex Sans carries prose. Fonts are self-hosted via `@fontsource`, so there is
  no CDN dependency and the app works offline in Docker.
- **Radix primitives, own styling.** `components/ui/` wraps Radix for the behaviour that is easy to
  get wrong (focus trapping, roving tabindex, dismiss) and writes every visual decision here, rather
  than adopting a generated component library's default look.
- **Never build a class name at runtime.** Tailwind generates utilities by scanning source *text*, so
  a class produced by concatenation or `.replace()` silently never gets a rule. Severity classes are
  written out in full in `lib/format.js`. This was a live bug: `border-critical/60` was assembled
  with `.replace("/35", "/60")` and every severity rule rendered in the default border colour.
- **Do not name a theme colour `canvas`.** It collides with the CSS system-colour keyword and
  Tailwind silently emits no utility and no variable for it. The base surface token is `--color-void`.
- **`get_current_user` has a frontend equivalent:** `AuthContext` is the only place a component
  learns who is calling, and the current user is fetched through TanStack Query keyed on the token —
  not by an ad-hoc effect.
- **A 401 on any request except `/auth/login` clears the token and dispatches an event** that the
  auth context listens for, so the redirect goes through the router instead of a page reload. Login
  is excluded because a 401 there is a form error, not a dead session.
- **Empty is not the same as failed.** Every list view distinguishes loading, empty, error and
  "filtered to nothing", and a report's `errors[]` renders as "these sections could not be
  generated" rather than as silently absent sections.
- **Nothing in the UI is faked.** The topbar status dot polls the real `/health/db`; Settings shows
  the real API base URL; the Profile page is read-only because no update endpoint exists. The
  dashboard says plainly which numbers are client-side counts.
- **Video obeys `public/video/manifest.md`.** `AmbientVideo` enforces the poster, the muted/looping
  autoplay, `preload="none"`, the readability scrim and pausing off-screen. Rule 1 — never two
  moving things at once — is a routing decision: the Generate page unmounts the `object-core` panel
  before the `loading-ring` state mounts. The intro's reduced-motion gate is the app's only one.
- **`eslint.config.js` was missing** even though `npm run lint` was in package.json from Phase 0, so
  the command had never once run. It needs `react/jsx-uses-vars`, or every component referenced only
  from JSX reads as an unused variable.

**Backend fix found while wiring the frontend:**

- **`env_file` is anchored to absolute paths.** A bare `".env"` resolves against the working
  directory, so the documented `cd backend && uvicorn app.main:app` silently ignored the `.env` at
  the repo root — where `.env.example` lives and where docker compose reads it — and generation
  failed with "provider unreachable" for no visible reason.
- **`cors_origins` needs `NoDecode`.** pydantic-settings runs `json.loads()` on complex types
  *before* field validators, so the comma-separated form documented in `.env.example` raised a
  `SettingsError` at import.

### Decisions taken in Phase 4

- **Aggregation is `services/analytics.py`, and it never loads ORM objects.** Every figure is a
  `GROUP BY` executed in Postgres. The dashboard is the one screen that reads across *all* of a
  user's reports, so per-row Python cost is the whole cost. The only loops in that module walk the
  aggregated rows — one per day, one per severity.
- **Severity is normalised in SQL, not in the browser.** `severity_bucket()` folds the free-text
  `risk_level` into the canonical ladder with a `CASE` over prefix matches, so "Sev 1", "CRITICAL "
  and "critical" are one bucket. The ladder mirrors `severityToken` in `lib/format.js` deliberately:
  same buckets, same prefixes, two runtimes.
- **Empty days are zeros, not absent rows.** A line chart that closes the gap between two distant
  dates draws a trend that did not happen, so the series endpoints emit a bucket per day in the
  window and fill the misses.
- **There is no `open_alerts` KPI yet.** Alerts arrive in Phase 5 with the table that backs them.
  A tile showing a hardcoded zero would be a lie in the shape of a feature, so the fourth KPI is
  `attention_required` — reports that came back partial or failed — which is a real number today.
- **A failed aggregate renders as `—`, never `0`.** On a security dashboard "I could not read this"
  and "there are none" are the one pair of states that must never look alike.
- **`--demo` calls no LLM.** `app/db/demo_data.py` is fixture data driven by a fixed-seed
  `random.Random`, so two runs on the same day produce identical rows: screenshots are reproducible
  and a bug in an aggregate cannot hide behind data that moved. It is idempotent per user — re-run
  with `--reset --demo` to rebuild.
- **`--demo` also seeds an analyst.** Ownership scoping is invisible with one account; with two,
  the same dashboard showing 44 reports to the admin and 22 to the analyst demonstrates it.
- **Recharts is behind `React.lazy`.** It is ~395 kB, and /dashboard is the landing route, so
  importing it eagerly put the whole charting library in front of the first paint (entry bundle
  588 → 985 kB). `components/charts/ChartGrid.jsx` is the lazy boundary; **nothing else may import
  `recharts` directly** or the chunk merges back into the entry bundle. There is deliberately no
  barrel file in `components/charts/` for that reason.
- **Colour still only encodes severity or state.** The severity chart is chromatic and the
  "needs attention" bar segment is amber; frequency and volume are graphite, because a taller bar
  already says "more" and spending a hue on it would dilute every hue that means something.
- **Chart axis dates are parsed field by field.** `new Date("2026-07-01")` is parsed as UTC
  midnight, so west of Greenwich every bucket renders labelled one day early.
- **Admin-scoped tests assert deltas, not absolutes.** The `db` fixture rolls back but an admin's
  query still sees every pre-existing row in the developer's database, so `== 2` is only correct on
  an empty machine.

### n8n workflows

Recovered and committed to `n8n/` — see `n8n/IMPORT.md`. They were never in the prototype repo; they
came from a live n8n instance. Phase 1 built the three endpoints the Orchestrator needs. The FIM
engine still needs four endpoints that arrive in Phase 5 (`/uploads/{name}`,
`/documents/{id}/download`, `PATCH /api/report/integrity/{id}`, `POST /api/security/alert`).

Prototype commits `c836a19` and `bd55a3f` added partial `file_hash` / security-alert support that is
absent from its final tree — `git show` recovers it as Phase 5 reference material.

**Update this section at the end of every phase.**
