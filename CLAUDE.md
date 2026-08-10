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
| Auth | OAuth2 password flow, bcrypt, JWT for humans; revocable API keys for machines |

---

## Repo layout

```
backend/
  app/
    main.py                 # app factory, router registration, CORS, middleware
    core/
      config.py             # pydantic-settings — ALL env access happens here
      security.py           # bcrypt hashing, JWT create/verify, auth dependencies
      api_key.py            # long-lived machine credentials (SHA-256, not bcrypt)
      share_token.py        # read-one-report capability tokens (neither JWT nor API key)
      middleware.py         # security response headers — two CSPs: API vs /docs
      correlation.py        # one request id: response header, every log line, every audit row
      logging.py            # JSON in ci/prod, console in local; the access log
      tracing.py            # OpenTelemetry — off by default, console or OTLP
    db/
      session.py            # engine + session factory (NEVER drop/create on import)
      models.py             # SQLAlchemy models
      seed.py               # explicit seed script, run manually
      demo_data.py          # deterministic --demo fixtures (fixed seed, no LLM)
      prune.py              # drops aged auth_attempts — never touches audit_log
    schemas/                # Pydantic: API request/response + LLM output schemas
    api/routers/            # auth, users, documents, reports, shares, chat,
                            #   dashboard, alerts, api_keys, audit, attack
    services/
      rag/                  # ingest, chunk, embed  (ported from prototype)
      llm/                  # LLMProvider abstraction + implementations
      export/               # layout.py (one document model) + pdf_writer + docx_writer
      report.py             # parallel section generation, validation, retry
      report_stream.py      # SSE progress: the generation task, and the frames it publishes
      analytics.py          # dashboard aggregation — GROUP BY in SQL, never ORM loops
      severity.py           # the free-text severity ladder, defined once
      chatbot.py            # chat over ingested docs
      integrity.py          # SHA-256 sealing + safe upload-path resolution
      share.py              # share-link rules: creation, expiry, revocation, classification
      ratelimit.py          # IP lockout + per-account progressive delay, state in Postgres
      audit.py              # the append-only trail: action vocabulary, redaction, record()
      llm/pricing.py        # tokens -> money; unpriced model costs null, never 0
      grounding.py          # citation validation: fabricated chunk ids are caught here
      attack_matrix.py      # the ATT&CK grid, detections on it, and the Navigator layer
      attack_graph.py       # entities and edges from stored rows — never a second LLM pass
    eval/                   # the evaluation harness — see backend/EVAL.md
      data/                 # vendored ATT&CK + CWE + the Navigator layer schema, all
                            #   pinned, checksummed and attributed in SOURCES.md
      golden/               # committed log + hand-labelled expected findings
      fixtures/             # recorded provider responses, replayed by the CI gate
      validators.py         # MITRE / CVE / CWE checks
      metrics.py            # hallucination, grounding, recall, precision, cost
      run.py                # python -m app.eval.run [--live] [--record] [--gate]
      vendor.py             # python -m app.eval.vendor [--only attack|cwe|navigator]
  alembic/                  # migrations
  tests/                    # pytest
frontend/
  public/video/             # optimized background clips + posters (see manifest.md)
  eslint.config.js          # flat config; react-hooks rules are the ones that matter
  vite.config.js            # app build *and* Vitest, so both resolve `@/` identically
  src/
    index.css               # @theme tokens — the whole design system lives here
    App.jsx                 # routes only
    components/attack/      # the ATT&CK matrix grid and its technique dialog
    components/graph/       # the attack graph; GraphCanvas is the lazy d3-force boundary
    components/charts/      # Recharts wrappers; ChartGrid is lazy-loaded — see below
    components/motion/      # CSS/SVG feature animations (no deps)
    components/ui/          # design system primitives (Radix behaviour, own styling)
    components/layout/      # AppShell, Sidebar, Topbar
    components/common/      # PageHeader, SeveritySpine, AmbientVideo, IntroSequence
    components/report/      # section renderers, ReportBody (shared with the public
                            #   share view), ExportMenu, ShareDialog, classification
    context/AuthContext.jsx # token + current user; the only source of "who am I"
    hooks/queries.js        # every TanStack Query hook and its query keys
    hooks/useGenerationStream.js  # the SSE run: live sections, reconnect, resume
    routes/                 # ProtectedRoute, AdminRoute
    pages/                  # one file per route
    lib/apiClient.js        # axios instance, JWT interceptor, 401 handling
    lib/api/                # one module per backend router
    lib/format.js           # severity + status tokens, date/byte formatting
    test/                   # setup.js (jsdom shims) + utils.jsx (renderWithProviders)
n8n/                        # workflow JSONs + IMPORT.md
.github/workflows/ci.yml    # backend lint+migrate+pytest, frontend lint+test+build
docker-compose.yml
```

---

## Commands

```bash
# Full stack — the only two commands a reviewer needs
cp .env.example .env
docker compose up                  # postgres + backend + frontend + n8n
# → http://localhost:5173, admin@aipcc.io / admin
# The backend container runs `alembic upgrade head` then `seed --demo --ingest`
# before uvicorn binds. Both are idempotent; the second boot is a no-op.

docker compose up postgres -d      # just the DB, to run the backend on the host
docker compose exec backend pytest # the suite, without a local Python

# Backend (on the host)
cd backend
uvicorn app.main:app --reload
alembic upgrade head               # apply migrations
alembic revision --autogenerate -m "msg"
python -m app.db.seed              # seed demo data
python -m app.db.seed --demo       # + six weeks of deterministic demo reports
python -m app.db.seed --ingest     # + embed the sample CSV (needed to generate)
python -m app.db.seed --service-token  # + an API key for the n8n workflows (shown once)
python -m app.db.seed --reset --demo   # wipe seeded users first, then re-seed
python -m app.db.prune                 # drop aged rate-limit rows (never the audit log)
python -m app.db.prune --days 0        # ...or all of them
pytest
ruff check app tests               # lint; config in backend/ruff.toml

# Evaluation — see backend/EVAL.md
python -m app.eval.run             # replay the recorded fixtures
python -m app.eval.run --gate      # ...and exit non-zero on a regression (this is what CI runs)
python -m app.eval.run --live      # call the configured provider for real
python -m app.eval.vendor          # refresh the vendored ATT&CK and CWE catalogues

# Frontend
cd frontend
npm ci
npm run dev
npm test                           # Vitest + Testing Library
npm run lint
npm run build
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
- **CI is the arbiter of "works".** `.github/workflows/ci.yml` runs backend lint + migrations +
  pytest against a Postgres service container, and frontend lint + Vitest + build — all from a
  clean checkout with none of this machine's state.

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

**Phases 0–15 complete and merged. The project is finished.**
See `AIPCC_CLAUDE_CODE_PROMPTS.md` for the phase sequence and
`AIPCC_REBUILD_PLAN.md` for the full architecture rationale.

In place: backend package + app factory, centralized config, all 10 SQLAlchemy models on UUID keys,
Alembic migrations, explicit seed script, the ported RAG pipeline (ingest/chunk/embed/vectorstore),
`docker-compose.yml` (postgres + backend + frontend + n8n), report generation with a single
canonical schema, concurrent sections, validation + one repair retry, an `LLMProvider` abstraction,
the document/report endpoints n8n calls, OAuth2 password-flow auth with bcrypt, JWT and
role-gated, ownership-scoped endpoints, a persisted RAG chat over ingested documents, the
full React SPA — nine routes behind a single app shell, a Radix-based design system, and every
server read going through TanStack Query — **and five `/dashboard` aggregation endpoints backed by
SQL `GROUP BY`, four Recharts views bound to them, and a `--demo` seed that populates them,
**and the full n8n integration — revocable API keys for machine callers, SHA-256 file-integrity
sealing with the four endpoints the FIM engine needs, a security-alerts table with its own view,
threat-intel enrichment persisted alongside reports, and both workflow JSONs corrected to call
the real endpoints with auth attached,
**and report export to PDF and DOCX from one format-independent layout, a closed
`Public | Internal | Confidential` classification enforced at the API, and revocable, expiring,
read-only share links with a public route outside the authenticated shell,
**and a one-command `docker compose up` verified from empty volumes, Vitest/Testing-Library
frontend tests, and a GitHub Actions pipeline running backend lint + migrations + pytest against a
Postgres service container alongside frontend lint + tests + build,
**and login brute-force protection — a hard per-IP lockout plus a per-account progressive delay
that is never a lock — security response headers on every response with separate policies for the
API and its docs, and an append-only audit log enforced by a Postgres trigger, with an admin-only
filterable view,
**and end-to-end observability: a correlation id on every response header, log line and audit row,
structured JSON logging, OpenTelemetry spans across HTTP/SQL/retrieval/LLM, and per-call LLM token
and cost accounting captured at the provider seam and surfaced as three dashboard charts,
**and evidence grounding: stable chunk identity, row and line provenance recorded at ingest,
citations validated against what the model was actually shown, fabricated citations counted, and
every finding's source log rows visible in the UI,
**and an evaluation harness measuring hallucination and grounding rates against the real published
MITRE ATT&CK and CWE catalogues and a hand-labelled golden log, with a deterministic replayed CI
gate that needs no API key and an in-app Evaluation page,
**and the MITRE ATT&CK matrix — tactics and the tactic→technique grid vendored from the same
pinned ATT&CK release the validator reads, per-report and aggregate detection endpoints, a
readable 14-column matrix whose cells trace back to the findings behind them, and an ATT&CK
Navigator layer export validated against a JSON Schema derived from MITRE's published spec,
**and streamed report generation — the five concurrent sections surfaced over SSE with per-section
started / retrying / completed / failed events, a visible repair retry, a report row reserved
before the first byte so a dropped connection reconnects through `GET /reports/{id}/status`
instead of restarting, and the non-streaming `POST /generate_report` untouched for API clients,
**and the attack graph — entities and relationships derived from a report's own anomaly and
timeline columns plus the citations Phase 10 recorded, with no second extraction pass, an identity
rule that refuses to merge two principals on anything short of a log row saying they are the same,
risk inherited from the findings that touch each node, and a force-directed SVG view behind its own
lazy boundary,
**and the README — the honest rebuild framing, a one-command quickstart, an architecture diagram,
eighteen captioned screenshots from real runs, and a "what this does not do" section — plus a
LICENSE.** 616 backend tests and 66 frontend tests pass; `ruff check` and `npm run lint` are both
clean with no warnings.

All three n8n workflows have now been executed inside n8n against a running backend with live Groq,
AbuseIPDB and VirusTotal credentials; the captures are in `docs/images/` and `n8n/IMPORT.md` >
Verification status has been corrected accordingly. Nothing in CI executes them.

Seed credentials: `admin@aipcc.io` / `admin` (`python -m app.db.seed`).
Add `--ingest` to embed the sample CSV — without it the document is registered but has no chunks,
and report generation fails with "no indexed content for document …".
Add `--demo` for a populated dashboard; it also creates `analyst@aipcc.io` / `analyst`, whose
smaller numbers on the same page are the ownership scoping working.
Add `--service-token` for the n8n API key (printed once).

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

### Decisions taken in Phase 5

**Authentication for machines** — decided first, because everything else depended on it:

- **A separate credential type, not a longer JWT.** Access tokens expire in 60 minutes, which cannot
  work for a scheduled workflow; raising that lifetime would weaken every human session to suit a
  machine. So n8n gets a revocable API key (`core/api_key.py`) presented in the same
  `Authorization: Bearer` header. The two are told apart by the `aipcc_` prefix, which a JWT can
  never have, so no client code changed.
- **API keys are hashed with SHA-256, not bcrypt.** This is not a relaxation of hard rule #3.
  Bcrypt is slow because a *password* is low-entropy and guessable offline; a key here is 32 bytes
  from `secrets.token_bytes`, so a slow hash buys nothing and costs ~100 ms per request. The
  clear `prefix` is uniquely indexed, so verification is one indexed lookup plus one constant-time
  compare — never a scan that hashes every row.
- **`require_human` refuses API keys on `/users` and `/api-keys`.** A key lives in a credential
  store and is long-lived by design; if one leaks it must not be able to mint a second credential
  or create an admin. It can do the workflow's job and nothing beyond it. This is what makes an
  admin-role service account acceptable — and the FIM engine needs admin, because
  `/get_all_reports` is owner-scoped.
- **The service account has no login path.** Its password hash is a random value nobody holds.

**File integrity:**

- **The hash lives on the report, not the document.** A report is a statement about a file at a
  point in time. Re-hashing the document row later would only ever say what the file is *now* —
  which is the question the FIM engine exists to answer differently.
- **`UNKNOWN` is the honest default and renders grey.** "Nobody has checked this" is the absence of
  a check, not a mild version of "fine", and colouring it green would assert something unverified.
- **A caller-supplied file name is a database key, never a path.** `/uploads/{document_name}`
  resolves the name against the `documents` table and serves *that row's* stored path;
  `settings.upload_dir / name` would happily open `../../.env`. The stored path is then still
  checked to resolve inside the upload directory, because a row written by older code is untrusted
  input too.
- **Missing bytes are 410, not 404.** The record exists and the file does not; those are different
  problems and the FIM engine handles them differently.
- **A report with no sealed hash is skipped, not failed.** Comparing against a null hash would mark
  every unsealable report TAMPERED — a false accusation, not a finding. The workflow filters first.

**Ownership and attribution:**

- **A report belongs to the owner of the document it analyses, not to the caller.** Found while
  testing the service key end to end: `/reports` is owner-scoped, so attributing to the caller filed
  every workflow-generated report under `n8n@aipcc.io`, where the analyst whose log it described
  could never see it. Resolved inside `store_report`, so both write paths share one rule. Not a
  hard-rule #2 violation: the caller is still resolved from their token and still authorized against
  the document — ownership of the *output* simply follows ownership of the *input*.
- **Alerts follow the same rule**, for the same reason.
- **Severity on an alert is normalised on the way in, and never rejected.** "CRITICAL", "Sev 1" and
  "critical" are one bucket; anything unrecognisable becomes `medium`. Losing an alert because its
  severity was spelled oddly is worse than filing it one notch off.

**`open_alerts` is now a real KPI**, replacing the Phase 4 note explaining why it was absent.

### n8n workflows — which system is authoritative

**n8n orchestrates; the backend decides.** The Orchestrator duplicates
`services/report.py`, and they are not peers: the **Python generator is authoritative**. It owns the
canonical schema, validation, the repair retry and the section-error contract. The Orchestrator is a
*client* of that schema — it produces sections and hands them to `/store_generated_report`, which
validates them exactly as the Python path does before anything reaches the database.

n8n owns scheduling, third-party enrichment (Groq, AbuseIPDB, VirusTotal) and DOCX rendering: work
about *when* and *from where*, not about *what is true*. That is why the store endpoint re-validates
everything and why `integrity_state` is a closed enum. A workflow can be edited by anyone with n8n
access; the invariants cannot be edited from there at all.

Both JSONs in `n8n/` were corrected in Phase 5 — see `n8n/IMPORT.md` for the full list. The FIM
graph as exported could not have worked even with auth: it read `$json.report[0].document_name`
against an API that returns a flat object, downloaded the same file twice, and ran every minute.

Prototype commits `c836a19` and `bd55a3f` added partial `file_hash` / security-alert support that is
absent from its final tree — `git show` recovers it as reference material.

### Bugs found and fixed in Phase 5

- **`token_urlsafe` emits `_`.** `extract_prefix` split the key on every separator, so a secret
  containing an underscore — roughly two in three — produced four parts, failed the length check and
  401'd. Fixed with `maxsplit=2`; regression-tested over 200 generated keys.
- **A stray `</content>` tag** had been sitting at the end of
  `frontend/src/components/motion/motion.css` since Phase 3, producing a CSS syntax warning on every
  build. Removed.

### Decisions taken in Phase 6 — backend

**Export:**

- **One document model, two renderers.** `services/export/layout.py` turns a report into headings,
  labelled paragraphs and table rows; `pdf_writer` and `docx_writer` walk that and never read a
  report field. So the PDF and the DOCX cannot disagree about content — only about typography — and
  a new report field is added in one place instead of two.
- **Narrative sections are findings, enumerative sections are tables.** Attack types, risks and
  vulnerabilities carry paragraphs of prose; a six-column table of paragraphs is unreadable on
  paper at any width. Anomalies, timeline and threat intel are short and are read down the column.
- **Null fields are dropped from a finding and dashed in a table.** On screen a `—` sits in a dense
  grid and reads as "nothing here"; printed as its own labelled paragraph it reads as a defect. A
  table keeps its grid either way, so there a gap has to be visibly a gap.
- **`python-docx` + `reportlab`, both pure-Python wheels.** WeasyPrint would let the export reuse
  the app's CSS but needs GTK on the host, which breaks "clone and `docker compose up`" for the sake
  of a nicer box model.
- **The print palette is the inverse of the app's, not a copy.** The UI's hues are tuned to glow on
  near-black and go muddy on white. What carries over is the rule: chroma only where it means
  something — a severity, or a classification.
- **The severity ladder now lives in `services/severity.py`** and `analytics.severity_bucket`
  *generates its SQL `CASE` from it*. It had been written twice; a third copy for the exporter was
  the point where they would drift. `format.js` stays a hand copy — a browser cannot import Python.
- **Model output is escaped in both writers.** ReportLab treats a `Paragraph` as markup and DOCX is
  XML, so an LLM emitting `<b>` or `&` is a rendering failure in one and an injection in the other.
- **A section never starts in the last 30 mm of a page** (`CondPageBreak`). A heading stranded above
  its content reads as a document that ran out of room. `KeepTogether` cannot fix it — the heading
  and the first table row are separate flowables.
- **The DOCX uses Word's built-in styles and real `PAGE`/`NUMPAGES` fields.** A DOCX is an editable
  deliverable; it will be pasted into a longer write-up, so it should inherit the recipient's
  template and keep working page numbers rather than arriving as fifty hard-styled paragraphs.

**Classification:**

- **Three levels, not four.** `Public | Internal | Confidential`, closed on input in
  `schemas/report.Classification`. The prototype's "Restricted" sat between Confidential and nothing
  with no rule attached to it, so it meant whatever the reader assumed. The migration folds existing
  `Restricted` rows *up* to Confidential.
- **`Classification` on the way in, `str` on the way out.** Same asymmetry as `UserPublic.email`,
  for the same reason: one historical row outside the vocabulary would raise inside `GET /reports`
  and take the listing down for every report the caller owns.
- **Reclassifying does not revoke links.** `resolve_share` re-reads the classification on every
  open, so raising a report to Confidential kills its links immediately and lowering it restores
  them. Revoking on write would silently destroy links a mistake could otherwise undo.

**Share links:**

- **A share token is a capability, not a credential.** It never reaches `get_current_user`; it is
  only read from the path of `/share/{token}`, and the routes that accept it read exactly one row.
  A JWT for the owning user would mean a link forwarded to a contractor carries the whole account.
- **It deliberately does not reuse `core/api_key.py`.** The two look alike, but an API key answers
  "which principal is calling" and a share token answers "may this request see this row". Merging
  them would put the capability into the `Authorization` header, one `looks_like_*` bug away from
  being treated as an identity. The `shr_` namespace cannot collide with `aipcc_`.
- **`SharedReport` is built by listing what may be exposed, not by stripping `ReportDetail`.**
  Inheriting and deleting fields means the next field added leaks by default. No `user_id`, no
  `report_id`, no `document_id`, no sealed hash, no owner address.
- **Three refusals, three codes, on purpose.** Unknown *and revoked* → 404 with an identical body:
  revocation usually answers a leak, and must not confirm to whoever leaked it that they held
  something real. Expired → 410 with the date, because that holder was given the link legitimately
  and needs "ask for a new one", not "the app is broken". Classification → 403, a policy answer.
- **Classification is enforced on read, not only on create.** The link holder never loads the UI
  that would hide a button, so anything checked only at creation time is not enforced at all.
- **The justification *is* the override.** No boolean: a checkbox records that somebody clicked, a
  sentence records that somebody decided. It is stored on the share and it raises a `share-link`
  security alert owned by the report's owner — an override that lives only in a column nobody
  queries is not oversight.
- **`require_human` guards the owner routes**, as it does `/api-keys`. A leaked machine key must not
  be able to mint a link and walk a report out of the system.
- **A report belongs to its document's owner, and a share belongs to its report** — Phase 5's rule,
  unchanged. Revocation is authorized through the report, not through `created_by`, so an admin can
  kill a link on somebody else's report.

### Decisions taken in Phase 6 — frontend

- **`/share/:token` is outside `ProtectedRoute` *and* outside `AppShell`.** Not a styling choice:
  the shell exists to move between a user's reports and there is nothing here for a link holder to
  move to. A shell with every nav item removed is still a shell with "Dashboard" one CSS rule away
  from coming back.
- **`components/report/ReportBody.jsx` is shared by the authenticated page and the public one.**
  Two renderings of one report would be two places for a section to go missing, and the public one
  is the copy nobody on the team ever looks at.
- **Classification is an icon, not a hue.** It is a state and would be entitled to colour under this
  app's rule — but red already means critical severity, and the classification pill sits two inches
  from a severity badge. On paper it gets red, because there it sits alone in the page furniture.
- **The three share refusals get three different pages.** 404 "not valid", 410 "expired", 403
  "classification was raised". One "something went wrong" would leave the reader unable to tell
  whether to ask for a new link or to stop asking.
- **`active` is read from the server, never recomputed from `expires_at`.** Otherwise the dialog and
  the link itself disagree for anyone whose machine clock is off.
- **Export is a mutation, not a query.** It produces a file the user takes away, it has no cached
  representation, and pressing it twice must download twice.
- **The export toast is deliberately generic on failure.** The endpoint answers with a blob, so an
  error arrives as JSON *inside* a Blob that `errorMessage` cannot read; parsing it back out for a
  case that means "the report went away" is not worth the code.
- **The share list is fetched only while the dialog is open**, so Report Detail does not pay for a
  request most visits never need.

### Bugs found and fixed in Phase 6

- **`Content-Disposition` is not a CORS-safelisted response header.** Found live: the export
  downloaded correctly, the header was sent, and the browser hid it from JavaScript — so every file
  silently saved under the client's fallback name. Nothing failed, which is exactly why it now has
  a test. Fixed with `expose_headers` on the CORS middleware.
- **The demo seed emitted a fourth classification.** `--demo` wrote "Restricted", which the closed
  vocabulary does not contain; the migration folds those rows up to Confidential and the seed now
  draws from a weighted list of the three real levels.

### Decisions taken in Phase 7 — reproducibility, tests, CI

**One-command run** — verified by actually doing it: containers removed, fresh volumes, only
`cp .env.example .env`, and the result was a logged-in dashboard with 44 reports.

- **The stack seeds itself on first boot**, and that is a deliberate exception, not a lapse. Hard
  rule #1 is about *schema* creation, which still only ever happens through Alembic; `seed.py` is
  idempotent and prints "already present" on every boot after the first. The alternative is a
  reviewer running `docker compose up`, reaching a login form and having no credentials — an app
  that is running and unusable.
- **`--ingest` had to *become* idempotent to allow that.** As a hand-run script it re-embedded
  unconditionally; on a startup command that meant another full copy of the same 195 chunks per
  restart, quietly degrading retrieval for as long as nobody looked. The guard asks Chroma
  (`count_chunks(document_id)`) rather than inferring from "did we just create the document row" —
  the database and the vector store are separate volumes and go out of step, so a wiped chroma
  volume with the DB intact must still re-embed.
- **The embedding model is baked into the backend image.** Otherwise the first ingest downloads
  MiniLM from Hugging Face *after* the build, so `docker compose up` keeps a network dependency and
  fails behind a rate limit with a stack trace instead of a report. ~90 MB on a 3.3 GB image.
- **`env_file` replaces the enumerated `environment:` block.** Restating each variable in
  docker-compose.yml meant every new setting had to be added in two places, and forgetting the
  second produced a container silently running on defaults. `environment:` still wins, so the four
  values that must differ inside the container are pinned there and nothing else is.
- **`.env.example` now boots the stack unedited.** `JWT_SECRET=` was empty, which is
  present-but-empty rather than absent, so the config default never applied; `LLM_TEMPERATURE` said
  0.7, contradicting both the code and the Phase 1 decision that chose 0.2. `CHROMA_DIR` and
  `UPLOAD_DIR` were removed outright — their defaults are absolute, and a relative value in `.env`
  resolves against the process working directory, which is the exact class of silent config bug
  this project has already paid for twice.
- **`npm ci`, not `npm install`,** in the frontend image and in CI, so the lockfile is what ships.

**Frontend tests** — Vitest + Testing Library, 30 tests, chosen for what breaks *silently*:

- **The 401 interceptor**, including its carve-out: a 401 from `/auth/login` is a wrong password,
  not a dead session, and getting that backwards logs you out of a session you never had.
- **`ProtectedRoute`'s third state.** The obvious case — an anonymous visitor is redirected — fails
  loudly the first time anyone tries it. The refresh bounce does not: a stored token mid-exchange
  reads as unauthenticated for one render and throws the user to /login and back on every reload.
- **`AuthContext`**, at the seam between the token in storage and the user in memory.
- **`Reports`**, through all four states, because "empty is not the same as failed" is a rule that
  erodes silently — a refactor that folds the error branch into the empty branch breaks nothing
  visible in development, where the API is always up.
- **Vitest config lives in `vite.config.js`**, not a second file: two configs are two chances for
  the test build and the real build to resolve `@/` differently.

**CI** — three jobs, from a clean checkout with none of this machine's state.

- **Postgres as a service container with a healthcheck.** Without one the runner starts the job
  immediately and the first test connects before Postgres is listening.
- **`ENVIRONMENT: ci`**, which is not `local`, so `config.py` demands a real signing key — the
  environment guard is itself exercised on every run.
- **Migrations run as their own step**, so a broken migration fails where it happened rather than
  as a confusing test error.
- **`ruff check` only; `ruff format` is not enforced.** The formatter would rewrap every docstring
  and comment in this codebase, and the comments carry most of the reasoning — a reformat that
  turns a paragraph explaining a bug into differently-wrapped lines is a large diff that hides real
  ones. `B008` is not switched off either: `extend-immutable-calls` names FastAPI's `Depends`,
  `Query` and friends, so the check keeps working on a real `def f(x=[])`.
- **The backend image is not built in CI, and that is stated rather than skipped.** It installs
  torch and bakes in the model — around 3.3 GB — which exceeds what a standard runner holds
  alongside its toolchain. The same `requirements.txt` is installed from scratch in the backend job,
  so what is left unproven is the Dockerfile alone.

**Cleanup:** `ruff --fix` across the tree; `langchain-core` dropped (nothing imports it, and all
three providers pin it themselves); `lru_cache` removed from `services/llm`;
`@radix-ui/react-avatar` and `@radix-ui/react-scroll-area` removed (`Avatar` is hand-written and
nothing scrolls through Radix). `npm run lint` is clean with no warnings: the twelve
`react-refresh/only-export-components` warnings are switched off **for the design system and the
auth provider only**, where they fire on Radix re-exports, a `cva` object and two hooks that must
live beside their provider. The rule stays on for pages and feature components, where a stray
non-component export really does cost state on every save.

### Decisions taken in Phase 8 — security hardening and the audit trail

**Brute force — two controls, because there are two attacks:**

- **Per source address: a hard lockout.** Five failures in fifteen minutes and that address gets
  429 until the oldest ages out. This is the control that actually stops a flood.
- **Per account: a progressive delay, and never a lock.** The textbook per-account lockout is a
  trap — it hands anyone a one-request denial of service against any address they can guess, which
  trades one vulnerability for another. So the account side sleeps (2s, 4s, 8s, capped) and stays
  answerable to whoever knows the password. It exists for the *distributed* spray, where every
  request comes from a fresh address and the per-IP counter never fills.
- **The cap on the delay is not cosmetic.** Each delayed login holds one threadpool thread, so an
  unbounded backoff is a denial of service inflicted on ourselves. What keeps the number of
  concurrently-sleeping requests small is the per-IP lockout: a single address dies after five.
- **The delay is applied to unknown addresses too**, keyed on whatever was typed. Skipping it when
  the account does not exist would make the delay itself an enumeration oracle — fast means "no
  such user", slow means "that one is real".
- **A successful login does not refund the IP budget.** Otherwise an attacker holding one valid
  account resets their spray allowance at will. It *does* reset the account delay, because that is
  counted since the account's last success.
- **A login against a suspended account counts as a failure.** Otherwise a disabled account is an
  unlimited, unrated oracle for testing passwords.
- **`X-Forwarded-For` is ignored unless `TRUST_PROXY_HEADER` is set.** It is caller-supplied:
  trusting it with no proxy guaranteed to overwrite it keys the lockout on a string the attacker
  chooses — no lockout at all — and simultaneously lets anyone lock out someone else's address by
  claiming it. Everyone behind one proxy sharing a counter is a usability problem; this is the
  absence of the feature.
- **Change-password gets a real lock, and that is consistent, not contradictory.** Reaching the
  route requires a valid session for that exact account, so only the account holder can spend the
  budget. Nobody can lock a stranger out of it.
- **The public `/share/{token}` route is throttled per address, not per token.** It is not a
  brute-force control — a token is 32 bytes from `secrets` and nobody guesses one — it is a ceiling
  on what a *leaked* link can be used for, since these are the only unauthenticated reads in the
  app. Keyed per address because the abuse is one host pulling repeatedly, and per-token keying
  would give an attacker holding two links two budgets.

**Where the rate-limit state lives — Postgres, and the honest cost:**

- In-process memory is wrong the moment there is a second worker: each replica gets its own
  counter, so N replicas mean N× the allowed attempts, and a restart clears it.
- Redis is the conventional answer — O(1), native TTL — but it is a fifth container and a hard
  dependency that forces a fail-open/fail-closed decision onto the login path.
- Postgres costs one write and one indexed count per authentication attempt, and has **no automatic
  expiry**: `python -m app.db.prune` is the answer, and nothing runs it for you. The index makes the
  window query cheap regardless of table size, so an unpruned table is a disk-space problem rather
  than a correctness one. This would be the wrong choice for a per-request API limiter.
- **`at` is stamped by the application, not `func.now()`.** The window arithmetic uses the
  application clock, and mixing a database clock into one side of the comparison makes the window
  silently wider or narrower by however far the two containers have drifted.

**The audit log:**

- **Append-only is enforced twice.** No endpoint updates or deletes a row, *and* a Postgres trigger
  raises on UPDATE, DELETE and TRUNCATE. The trigger is the one that still holds after somebody adds
  a well-meaning "clean up old entries" endpoint. TRUNCATE needs its own statement-level trigger —
  it never fires a row-level one, so without it "append-only" is one `TRUNCATE audit_log` from false.
- **`actor_id` deliberately has no foreign key.** Every other actor reference in this schema
  cascades on delete, which is right for data a user owns and catastrophic here: deleting a user
  would erase the record of what that user did — the single most interesting case the log exists
  for. The uuid is stored unenforced and `actor_label` keeps the address as it read at the time.
- **A failed login is recorded even though the request raises**, which is the whole difficulty.
  A route that raises never commits, so `record()` commits itself; call sites therefore call it
  either right after the business commit or right before raising, so that commit has nothing else
  pending. Testing this took a third attempt — see below.
- **A failed login is never attributed to the account as its actor.** Nobody proved they were that
  user; that is what "failed" means. The account is the *target*, the attempted address is
  `actor_label`, and `actor_type` is `anonymous`. Recording `actor_id = <that user>` would state in
  the log that the user did this. Found by reading the rendered page, where "admin@aipcc.io — Login
  failure" was indistinguishable from something the admin had actually done.
- **Redaction is enforced, not trusted.** `detail` values are stripped by key name and clipped to
  500 characters, and anything structured is flattened to a string first so a nested dict cannot
  smuggle a forbidden key past the check. "Never record document contents" is a length problem as
  much as a naming one. It redacts rather than raising: an audit write is not the place to turn a
  programming mistake into a failed request.
- **Reads of the log are not themselves audited.** Otherwise the page shows its own visit as the
  newest entry and a scheduled dashboard fills the log with the fact that it looked.
- **Only integrity *changes* are recorded**, not every check. The FIM engine re-checks on a
  schedule; logging each verdict would bury the real events under a thousand daily rows saying the
  file is still fine.
- **`/audit` is `require_human_admin`**, matching `/users` and `/api-keys`. It is the most useful
  single read in the application for somebody who should not have it, and a machine key lives in a
  credential store it can be copied out of.
- **`POST /auth/logout` does not invalidate anything, and says so.** Access tokens are stateless
  JWTs; revoking one needs a jti deny-list checked on every request — a real feature with a real
  cost, not something to imply with an endpoint that returns 204. It exists for the audit line.

**Security headers:**

- **Two CSPs, because the API and its docs are different documents.** The API answers JSON to a
  fetch, so `default-src 'none'` costs nothing. FastAPI's `/docs` is a real HTML page pulling
  Swagger UI from jsDelivr with an inline bootstrap, and under the strict policy it renders as a
  blank page. That is not hypothetical — it is what one CSP for the whole app does, and it is only
  visible in a browser. `/openapi.json` is data, so it keeps the strict policy.
- **HSTS only over HTTPS** (or in production behind a terminator). Sending it on `http://localhost`
  is spec-forbidden and a real foot-gun: a browser that caches HSTS for `localhost` then refuses
  plain HTTP for every other project on the machine, with no obvious cause.
- **A pure ASGI middleware, not `BaseHTTPMiddleware`.** The latter wraps every response in an
  anonymous task and re-emits the body — a lot of machinery to append six constant headers, and the
  layer that historically interferes with streaming and background tasks.
- **Added after CORS so it ends up outermost.** `add_middleware` prepends, so the last one added
  wraps everything — which is what puts headers on responses no route sees: CORS preflights, which
  `CORSMiddleware` answers itself, and anything an exception handler produces.
- **The middleware appends and never overwrites.** A route that set its own framing policy knows
  something the middleware does not.
- **The SPA's CSP lives in `vite.config.js`,** because Vite is what serves those documents; a header
  set by FastAPI never reaches a page on :5173. It carries `'unsafe-inline'` for scripts and that is
  stated rather than hidden — the dev server injects an inline module preamble and the React Refresh
  runtime, and `ws:` in `connect-src` is HMR. Removing either does not harden the app, it breaks
  development, which is how a CSP gets deleted. A production build served statically has no inline
  script and should tighten to hashes or nonces.

**Bugs found in Phase 8:**

- **`timedelta(0)` is falsy.** `prune(older_than=older_than or default)` silently ignored
  `--days 0` — the only way to clear the table — fell back to the 30-day default, and printed
  "pruned 0". Found by running the command, not by reading it.
- **Two audit tests passed on a bug.** The obvious assertion — do the request, then query — cannot
  detect a missing commit: the test session *is* the route's session, and an intervening query
  autoflushes the uncommitted row into the same transaction. Confirmed by deleting the commit and
  watching them still pass. `db.rollback()` after the request is what closes the gap; it discards
  to the savepoint exactly as closing an uncommitted session would, so only a genuinely committed
  row survives. Both tests now fail without their commit.
- **The audit tests were only correct on an empty machine.** Running the app locally for five
  minutes leaves a dozen real rows, and `len(entries) == 1` then fails — the same trap the Phase 4
  dashboard tests already paid for. Scoped with an autouse baseline timestamp. This is the one table
  where the usual escape hatch does not exist: you cannot delete the noise, because the trigger
  refuses to.

**Verified in a browser, not by reading:** `/docs` renders fully under the relaxed policy; the SPA
loads with fonts, ambient video and HMR intact and no CSP violations in the console; and a live
sequence of failed logins against the running server showed 401 at ~510 ms for the first three,
2.5 s on the fourth, 4.5 s on the fifth and `429` with `Retry-After: 891` on the sixth, all of it
landing in the audit view.

### Decisions taken in Phase 9 — observability and cost accounting

**Correlation:**

- **A `ContextVar`, not a parameter.** Threading an id through `generate_report` →
  `generate_section` → `LLMProvider.generate` would put an observability concern in the signature
  of every function it passes, and the first place somebody forgot to pass it would be a silent
  hole rather than an error. `contextvars` propagates into `asyncio.gather` tasks and across
  `asyncio.to_thread` for free, which is exactly the fan-out this app uses.
- **An inbound `X-Request-ID` is untrusted input.** It is echoed in a response header and written
  into log records, so a newline in it forges a log line and a CR forges a header. Filtered to
  `[A-Za-z0-9_-]`, truncated to 64, and replaced entirely if nothing survives — an empty string
  would read as "no correlation" everywhere downstream.
- **Correlation is added to the middleware stack last**, so it ends up outermost and the id exists
  before the access log runs. Reversed, every request line carries a null id — the one field it
  exists for.

**Logging:**

- **Ours replaces uvicorn's access log rather than joining it.** Uvicorn's is unstructured, carries
  no actor and no correlation id, and cannot be made to; running both doubles every request.
- **The access line logs the route *template*, never the resolved path.** `/reports/{report_id}` is
  one log key; the resolved path is one per report, which makes the log unaggregatable and puts
  identifiers into it for no benefit. The query string is dropped outright.
- **`default=str` in the JSON formatter.** A UUID or a datetime passed in an `extra=` must not be
  able to take down logging — a log line is not the place to raise.

**Tracing:**

- **Off by default, and that is the honest reading of "console exporter by default".** The console
  exporter prints a multi-line dump per span; enabled out of the box, `docker compose up` becomes a
  wall of JSON and the first thing anyone does is switch it off. `OTEL_ENABLED=true` turns it on,
  and Jaeger sits behind an optional compose profile so the default run stays one command.
- **Four things are traced** — HTTP, SQL, retrieval, and each LLM call — because those are the four
  places a report generation spends time. The first two come from instrumentation packages; the
  last two are hand-written, since there is no off-the-shelf instrumentation for what this app does.
- **No prompt, completion or document content on any span.** Traces ship to a collector; log data
  does not leave this system that way. Spans carry counts, models, latencies and section names.
- **Instrumentation failing must not stop the app booting.** Observability is how you find out
  something is wrong; it does not get to be the thing that is wrong.

**Cost accounting:**

- **`LLMProvider` is the seam, and `generate()` in the base class does the measuring.** Every LLM
  call in the app goes through it — sections, repair retries, chat — so the accounting cannot miss
  a path added later, and a fourth provider is measured without its author doing anything. The
  abstract method became `_invoke`; `complete()` is now a thin wrapper. A test fake that overrode
  the *public* method would skip the timing and the token capture entirely, so both fakes were
  moved to `_invoke` and that is written down where they live.
- **Unknown is null, never zero — three times over.** A provider that reports no usage gives null
  tokens; a model absent from the price table gives a null cost; a report with no usage rows gets
  null totals rather than `0`. Zero would put "this was free" and "nobody measured it" in the same
  bucket, quietly drag every aggregate down, and leave a figure that still looks plausible. Same
  rule as `UNKNOWN` integrity and the dashboard's `—`, and `formatUsd` in the frontend has its own
  test because one `?? 0` there would undo all of it.
- **Prices are configuration, in USD per *million* tokens.** That is the unit every provider
  publishes, so a value can be pasted off a pricing page unconverted — converting by hand is how a
  price ends up wrong by three orders of magnitude in a way nobody notices. Model lookup falls back
  to the **longest** matching configured key, so `gemini-2.5-flash-lite` is not billed at
  `gemini-2.5-flash` rates. Ollama is in the table as an explicit zero rather than by omission:
  free because it is local, with tokens still counted.
- **A row per call, not per section.** That is what makes the retry rate measurable at all — a
  section that needed its repair prompt writes two rows, and the first is the interesting one.
- **Usage is recorded before the response is judged.** A call that produced unusable JSON still
  spent its tokens, and a cost that counted only successful calls would understate exactly the
  reports that went wrong most expensively. A provider *outage* records nothing, because that call
  never reached the model and inventing zeros for it would drag every average down.
- **Chat spend lands in the same table**, with a null `report_id`. Leaving it out would make "what
  does this system cost to run" quietly exclude a whole feature.
- **Usage is attributed to the report's owner, not the caller** — Phase 5's rule, so an
  n8n-generated report's spend appears on the analyst's dashboard rather than the service account's.
- **`generation_ms` is wall-clock, not the sum of section latencies.** The sections run
  concurrently; summing them reports about five times the truth. Measured: 94 ms elapsed against
  459 ms summed.
- **p95 as well as p50, computed with `percentile_cont` in Postgres.** A mean over five concurrent
  sections hides the one slow section that decides how long the analyst actually waited. Reports
  with no timing — pre-Phase-9 rows, and anything stored by n8n — are excluded rather than counted
  as fast.
- **`unpriced_calls` is surfaced on the dashboard**, because a total that silently excludes calls
  nobody could price reads as complete when it is not.
- **The cost charts are graphite.** Spend is not a severity and not a state, so under this app's
  colour rule it gets no hue; a taller area already says "more". They live in the *same* lazy chunk
  as the other four, because a second `React.lazy` boundary would download Recharts twice.

**Bugs and traps found in Phase 9:**

- **OpenTelemetry's proxy tracer caches its provider on first use.** Modules capture a tracer at
  import time, which yields a `ProxyTracer` that binds to whatever provider exists the first time a
  span is started — and keeps it. A per-test provider therefore works exactly once: the first
  tracing test passed and every later one saw an empty exporter. Fixed with one session-scoped
  autouse provider in `conftest.py`.
- **A test asserted against the wrong log line.** `next(r for r in caplog.records ...)` returns the
  *first* access record, which for a test that had to mint an API key first was the JWT call that
  minted it. The helper now returns the list and callers take the last.

### Decisions taken in Phase 10 — evidence grounding

**Chunk identity:**

- **`(document_id, chunk_id)` is the citation key, and it is now the Chroma id too.** The pair was
  already stable — the splitter is deterministic, so the same bytes produce the same chunk at the
  same index — but Chroma's own id was random, so re-ingesting a file *appended* a second copy of
  every chunk rather than replacing it. `chunk_key()` makes re-ingest an upsert, makes a citation
  resolvable by primary key instead of a metadata scan, and turns the Phase 7 idempotency guard
  into a second line of defence rather than the only one. Verified: re-ingesting the sample CSV
  leaves 197 chunks, not 394.
- **The model cites integers, not composite keys.** "chunk 7" is something a language model gets
  right; a uuid pair is something it invents. The document is implied by which report is being
  generated, so nothing is lost.

**Row and line provenance:**

- **Recorded at ingest, because that is the only moment it exists.** `chunk_logs` serialises a
  DataFrame to CSV and hands the text to a character splitter; once the chunks come back there is
  no way to recover which rows produced them.
- **Exact or absent, never approximate.** The row mapping assumes `to_csv` writes one physical line
  per row, which is false when a field contains a newline — `to_csv` quotes it and every row number
  after it is wrong. The assumption is *checked* against the row count, and when it fails row
  provenance is omitted for that document and logged. A citation that points at the wrong log rows
  is worse than one that admits it cannot point at any, because a wrong one is only discovered by
  someone checking it, which is the thing citations exist to avoid.
- **The offset search is a forward scan from a cursor, not `text.find(chunk)`.** Log files repeat;
  a hundred lines can be byte-identical, and searching from zero mis-locates every chunk after the
  first duplicate.
- **Line numbers are 1-based, row indices 0-based.** Lines are shown to a person next to a log file
  and no editor numbers its first line 0; rows are DataFrame indices and pandas starts at 0.
  Mixing them is why the header offset gets its own test.

**The evidence table:**

- **One table for all five sections, not five.** Per-section tables would be five migrations for
  one concept, five joins to render a report, and five queries to compute a grounding rate — and
  Phase 11 wants that rate as one number. The cost is that `item_id` carries no foreign key,
  because it points into one of five tables; the cascade on `report_id` covers deletion anyway.
- **The excerpt is a copy, not a reference.** Chroma is a separate volume from Postgres and the two
  can go out of step. A report that could no longer show what it was based on because the vector
  store was rebuilt would be a report whose evidence evaporated.
- **`evidence` is a schema field with no column, and `id` is a column the model must never see.**
  Both exclusions live in one place — `STORAGE_EXCLUDED` and `PROMPT_EXCLUDED` in
  `schemas/report.py` — and `storage_dump()` applies them, so no storage code names a field as a
  string literal and hard rule "field names are never written twice" survives intact.
- **The skeleton shows `"evidence": [0]`, not `null`.** It is the one field where the prompt has to
  teach a *shape*: a model told `null` returns null, and every finding in the report comes back
  ungrounded.

**Validation, and what happens to a finding that fails it:**

- **Validity is judged against what the section was actually shown**, not merely against the
  document. A chunk that exists but was never retrieved for that section is still a fabrication —
  the model cannot have read it. The two are counted separately (`unknown_citations`,
  `unseen_citations`) because they are different failures.
- **An ungrounded finding is flagged, never dropped.** Dropping it would make the report look
  cleaner than the model's actual output — the same failure as an empty section reported as a
  success — and it would make the grounding rate unmeasurable, since the ungrounded findings would
  no longer exist to count. The UI says "Ungrounded" in amber next to the claim.
- **Citation coercion is deliberately permissive; validation is not.** Models write `[0, 3]`,
  `["0","3"]`, `"0, 3"`, `"chunk 3"`, `3` and `[{"chunk_id": 2}]` for the same thing. Failing a
  whole section over the punctuation would be absurd when the *next* step checks the number against
  the document. What coercion never does is invent: a string with no digits yields no citation
  rather than a reference to chunk 0.
- **`evidence` is excluded from `is_empty()`.** Otherwise a stray `"evidence": [0]` on an otherwise
  all-null item rescues the skeleton and reopens the exact hole Phase 1 closed.

**UI:**

- **The public share view gets no evidence at all**, and `groupEvidence` returns `null` there
  rather than an empty map. A share link grants read of a *report*; shipping the raw log excerpts
  with it would hand the holder more of the source data than the report itself contains. `null`
  (no disclosures at all) and `[]` (this finding is ungrounded) are different states and the
  component renders them differently — with a frontend test for exactly that distinction.
- **Native `<details>`, not a Radix disclosure.** A report can hold sixty findings; sixty pieces of
  React state to reproduce keyboard handling and find-in-page that the browser already has is a bad
  trade.
- **Section rows now load with an explicit `ORDER BY id`.** Without one Postgres may return
  findings in a different order on each load, so the exported PDF would stop matching the screen.
  Latent before this phase; evidence made it visible.

**Verified by running:** a real ingest of the sample CSV produced 197 chunks whose row spans were
checked against the source file (chunks 0, 1, 2 and 50 — first and last row of each present in the
chunk text); re-ingest upserted rather than duplicated; a lookup of a fabricated chunk id returned
nothing; and the report page showed a grounded finding's two citations as `ROWS 4–9 · CHUNK 1` and
`ROWS 10–14 · CHUNK 2` with the log lines beneath, alongside an amber "Ungrounded" marker on a
finding that cited nothing.

### Decisions taken in Phase 11 — the evaluation harness

Full rationale in **`backend/EVAL.md`**, which is written for a reader who has
not seen this file. The decisions:

**The reference data:**

- **Vendored from the publishers, never hand-written.** ATT&CK Enterprise v17.1 (823 techniques)
  and CWE v4.20 (969 weaknesses), downloaded by `app/eval/vendor.py`, pinned, SHA-256'd and
  attributed in `data/SOURCES.md`. An approximated technique list would make every hallucination
  number a fiction — worse than reporting none — so `TestCatalogue` spot-checks the files against
  known facts and a truncated or invented catalogue fails the suite.
- **What is committed is a derivation, not the raw download.** The STIX bundle is 45 MB of graph
  data; this project needs an id and a name. The derivation script ships with its output so the
  projection is auditable and reproducible.
- **Deprecated and revoked techniques are kept and flagged.** A model naming `T1022` did not invent
  an id — ATT&CK retired it — and counting that as a hallucination would make the rate climb with
  the calendar rather than with model behaviour.
- **CVE existence is deliberately not checked, and the harness says so.** The list is unbounded and
  grows daily, so checking it needs a network call; a gate that needs the internet fails on a bad
  day and is deleted on the next. Format is checked, and the docs state that this is weaker.

**The gate:**

- **CI replays; it never calls a model.** A live gate needs a secret, costs money per push, and is
  non-deterministic — and a flaky quality gate gets `continue-on-error`'d within a week and deleted
  within a month. The eval job runs with no Postgres, no Chroma, no embedding model, no network and
  no API key: it chunks the committed golden log with the real `chunk_logs` and replays responses
  recorded once from Gemini.
- **The fixtures are real recordings, not synthetic.** A real key was available, so they were
  recorded rather than written. `TestReplay` asserts the cassette's `recorded_from` names a real
  provider, because a synthetic fixture would change what every replayed number means.
- **Keyed by the SHA-256 of the exact prompt**, and by attempt number so a repair retry replays its
  *second* response. Change a prompt and replay misses loudly with "re-record" — silently replaying
  an old response against a new prompt would report the old model's quality as the new prompt's.
- **A replayed call reports no tokens and no cost.** It spent nothing; reporting the recorded
  numbers would make a replayed run look like it cost money.
- **The committed fixture is deliberately the *weak* model, and the thresholds are calibrated to
  it.** `llama3.1:8b` fabricated three ATT&CK technique names and cited five chunks it was never
  given; every one is caught. A cassette of clean output would prove much less — a validator that
  silently stopped working would look identical to a model that made no mistakes. The thresholds
  are therefore regression bounds on a frozen recording, not the product's aspiration, and
  `EVAL.md` prints the replayed and live numbers side by side so the two can never be confused.
- **`EVAL_MIN_DETECTED_ISSUES` is what makes the rest mean anything.** On a frozen fixture a
  validator that stopped catching would send the hallucination rate to *zero* and sail through
  every upper bound — the regression would look like an improvement. So the gate also fails when
  fewer than the fixture's four known identifier defects are found.
- **Recording is serialised and paced; the application is not.** Five full-log prompts at once is
  exactly what free provider tiers limit on, by input tokens per minute. Recording concurrently
  returned `RESOURCE_EXHAUSTED` repeatedly and produced cassettes missing two or three sections.
- **Refusing to answer is not a passing grade.** Every rate is `None` on a zero denominator, which
  would sail through every threshold, so the gate separately fails a run that emitted no
  identifiers or no findings at all.

**The metrics:**

- **Two recalls, because one number could not honestly carry both meanings.** Coverage (the label
  appears anywhere) and distinct (one label per finding). The first live run scored 100% coverage
  and 55.6% distinct: three attack findings covered seven labels because one was a campaign
  narrative mentioning PowerShell, SMB, the beacon and the log clearing in passing. Bundling is
  defensible analysis, not an error — but scoring it as seven recalled findings would be
  flattering, and only reporting the strict number would penalise a good summary. The gap is the
  interesting figure. *(The first version of the matcher reported only coverage, and its
  "unmatched findings" list was wrong as a result — found by reading the output, not the code.)*
- **MITRE agreement is reported, never enforced.** The live run scored 14.3%, and the model was
  arguably right more often than the label: `T1567.002` (*Exfiltration to Cloud Storage*) for an
  upload to a CDN where the label said `T1041`, and `T1543.003` (*Windows Service*) where the label
  said `T1547` for a log containing both a Run key and a service. Enforcing agreement would measure
  proximity to one labeller's opinion; the gate acts on *validity* instead.
- **Precision counts only findings labelled benign as false positives.** A finding the labeller did
  not think of may be right; `rlee` reading a PDF called an attack is not.

**What the harness does not cover, stated rather than implied:** retrieval quality (golden
retrieval is a fixed selection over a 35-row log, so a worse retriever would not move these
numbers), generalisation beyond one synthetic CSV, and the behaviour of the current model in
replay mode. All three are in `EVAL.md` under "What it does not prove".

**Two measurements, both real** — `EVAL.md` carries the table:
- *Live*, `gemini-2.5-flash`, 2026-08-10: hallucination 0.0% (0/6), grounding 100% (23/23),
  coverage recall 100%, distinct recall 55.6%, precision 100%, 45,096 tokens, $0.078, 32.7 s.
- *Replayed baseline*, `llama3.1:8b`: hallucination 75.0% (3/4), grounding 95.7% (22/23), five
  fabricated citations, coverage recall 66.7%. This is the committed fixture, and it is the weak
  model on purpose.

**Bugs the harness found in the product, which is the point of having one:**
- **`pandas.to_csv` uses `os.linesep`** — CRLF on Windows, LF on Linux — so chunk boundaries,
  chunk ids, character offsets and row spans were all platform-dependent, quietly contradicting
  Phase 10's determinism claim. Found by CI, where every recorded fixture missed. Fixed with an
  explicit `lineterminator="
"` and a regression test.
- **A number in a text field sank a whole section.** The golden log's `user_id` is numeric, the
  model returned `4471` rather than `"4471"`, and Pydantic rejected an int for a `str` field — for
  every item, twice, retry included. `_blank_to_none` now coerces numeric scalars, dropping a
  whole float's `.0` because "4471.0" is a different string from what the log contains.
- **The model crammed several technique ids into one field** (`"T1059.001, T1543.003, T1071.001"`).
  Valid ids, unusable output. The attack prompt now requires exactly one identifier.
- **The recorder's own pacing collapsed on failure**, because `_last_call` was only stamped after a
  successful call — so the first rate-limited call removed all spacing from the rest.

### Decisions taken in Phase 12 — the MITRE ATT&CK matrix

**The reference data, again from the publisher:**

- **Tactics come from the same pinned download the validator already reads.** Phase 11 needed only
  `{technique id: name}`; the matrix needs the columns and the tactic→technique mapping too, and
  taking those from a second source would let the grid and the hallucination checker disagree about
  what ATT&CK contains. `vendor.py` now also projects `x-mitre-tactic` objects and each
  attack-pattern's `kill_chain_phases`. 823 techniques, 14 tactics, 679 techniques placed.
- **Column order is read from the bundle's own `x-mitre-matrix` object**, not sorted by TA-number.
  The published matrix runs Reconnaissance → Impact, which is the order every analyst reads it in;
  sorting by id happens to agree today and would silently stop agreeing the moment MITRE inserts
  one. A tactic the matrix object does not list raises rather than being dropped.
- **`--only` was added to the vendor script.** The CWE URL is `cwec_latest.xml.zip` — deliberately
  unpinned upstream — so re-running the whole script to refresh ATT&CK would bump the committed CWE
  catalogue version as a side effect of an unrelated change.
- **The Navigator layer format is vendored too, as a derived JSON Schema.** MITRE publishes the
  format as markdown property tables and no machine-readable schema, so `vendor_navigator_schema()`
  parses those tables into JSON Schema 2020-12, checksums the source document and records it in
  `SOURCES.md`. Same discipline as the catalogues: an approximated format is how you ship a file
  that looks right and does not open.
- **The derived schema disallows unknown properties**, which the prose does not say in so many
  words — but the tables enumerate the format exhaustively, so a key absent from them is not part
  of it. That strictness is the entire reason to have the schema: it is what turns `techniqueId`
  into a failing test rather than a field the Navigator silently ignores.
- **An unrecognised type string in the spec raises.** A permissive fallback would let a future
  revision quietly degrade the schema into one that validates anything.

**What happens to a technique the model got wrong** — the phase asked for a decision, and it is
two decisions, because there are two different failures:

- **Real id, wrong name → placed, and marked `unverified`.** The detection happened; the model's
  description of it did not survive the check. The cell carries the **catalogue's** name, never the
  model's, because rendering the model's wording onto a matrix cell would print the fabrication as
  a label. Amber marker, and the dialog states the mismatch in the validator's own words.
- **Non-existent, malformed, or retired → no cell at all, and reported beside the matrix.** There
  is no column to put them in; inventing a placement would be the fabrication again, in our UI.
  Retired ids are here for a reason worth keeping straight: `T1022` was real, so it is not a
  hallucination — but MITRE does not draw revoked techniques on the published matrix, so neither
  does this.
- **Neither is ever dropped.** Dropping either would make the matrix look cleaner than the output
  behind it — the same failure as an empty section reported as a success.
- **Unplaceable ids are absent from the Navigator layer's `techniques` but named in its
  `description` and counted in its `metadata`.** A layer is a set of cells and they have none; a
  file that simply omitted them would read as a clean run.

**The layer:**

- **No entry pins a detection to a tactic.** A finding says a technique was observed; it does not
  say under which tactic. Navigator reads a missing `tactic` as "annotate under every column this
  technique appears in", which is exactly what is known — pinning each one to a single column would
  put a guess into a file an analyst reads as data.
- **`versions.navigator` is `4.9.0`, the spec's own stated minimum**, not the newest release.
  Claiming the latest would assert compatibility with something never tested here.
- **An unverified cell gets an explicit `color`, which overrides the gradient in Navigator.** That
  is the point: "we could not stand behind this one" must not render as "this one was seen once".
- **`gradient.maxValue` is floored at 1.** `maxValue` must be strictly greater than `minValue`, so
  a layer with a single detection would otherwise emit `0..0` and fail to open.
- **A layer export is audited as `report.export` with `format: navigator-layer`**, rather than as a
  new action. It is a report leaving the system, and one vocabulary keeps "what left, and when"
  answerable with one query.

**The grid, and how it stays readable** — the phase named three options and this took the third
plus one of the others:

- **Sub-techniques do not get cells.** 679 placed techniques collapse to 211 parents, so the whole
  grid is ~245 cells and needs no virtualisation at all. A detection on `T1059.001` shades the
  `T1059` cell and the cell says how many sub-techniques are behind it.
- **All fourteen columns are always drawn, including empty ones.** The recognisable thing about
  this diagram is its shape; hiding quiet tactics redraws it per report and loses the "nothing was
  seen here" reading, which on a security page is information. An empty column says "No detections"
  rather than being an empty box.
- **A density switch rather than a scroll trick**: "Detected only" is the honest default for a
  report, "Full matrix" shows the coverage gap.
- **Frequency is an ink ramp, not a hue** — Phase 4's rule, unchanged: a darker cell already says
  "more", and spending a colour on volume dilutes every colour that means something. The only
  chroma on the grid is amber, and it means exactly one thing: this identifier did not verify.
  (The phase brief said "colour encodes detection intensity"; the app's standing rule won, because
  a page where hue means both "frequent" and "severe" makes both unreadable.)
- **The five shading bands are written out in full**, never assembled — the Tailwind scan rule that
  already cost this project a bug in Phase 3.
- **No new dependency and no lazy boundary.** The matrix is CSS grid and buttons; there was nothing
  to import, so unlike the charts it costs the bundle nothing.
- **`/attack/matrix` is not owner-scoped and is cached with `staleTime: Infinity`.** It is MITRE's
  data, identical for every caller, and re-fetching 89 KB of grid per navigation would be the most
  expensive no-op in the app. The detections beside it are scoped exactly as `/reports` is.

**Two smaller decisions:**

- **`reports_considered` is counted separately from the join.** A report that named no technique
  still had its log read; taking the denominator from the joined rows would silently drop it and
  inflate any rate computed from those two numbers.
- **The `--demo` seed now contains three deliberately defective identifiers** — one real-id/wrong-
  name, one invented, one revoked. Without them a demo database renders fourteen clean detections
  and the part of the page that matters, how a bad identifier is *handled*, has no data and looks
  like a feature nobody built. It is the same argument Phase 11 makes for committing the weak
  model's cassette: output with no defects in it cannot demonstrate a validator.

**Verified by running:** the page renders 15 techniques over 141 detections from 44 real seeded
reports, with `T1053` shaded amber and its dialog quoting *"T1053 is 'Scheduled Task/Job', not
'Cron Job Persistence'"*, `T1888` and `T1022` listed below the grid as unplaceable, per-report
scoping narrowing it to 3 techniques over 4 detections, and the exported layer validating against
the derived schema. **Not verified:** the layer has not been opened in the live ATT&CK Navigator —
the browser tooling available here refuses `mitre-attack.github.io` — so what is proven is
conformance to the published format, not the round trip through MITRE's app.

### Decisions taken in Phase 13 — streaming report generation

**The transport:**

- **SSE, not WebSocket.** The traffic is one-directional and short-lived — the server has things to
  say, the client has nothing to send after the request that started it. SSE is that shape exactly,
  it is plain HTTP so it survives proxies and the existing CSP, and it adds no second protocol to
  the deployment story. A WebSocket would buy bidirectionality nobody wants and cost an upgrade
  handshake intermediaries mishandle.
- **POST + `fetch` + `ReadableStream`, not `EventSource`.** `EventSource` cannot set an
  `Authorization` header, and its only workaround is a token in the query string — which this
  project refuses on principle and which would be worse than a principle here, because
  `core/logging.py` writes a request line for every call. Thirty extra lines of client keep the JWT
  out of the URL, the access log and the browser history. `lib/api/stream.js` is the one module in
  the app that does not go through the axios client: axios buffers the whole body before it
  resolves, which is exactly what a stream exists to avoid.
- **`X-Accel-Buffering: no` on the response.** nginx buffers proxied responses by default, which
  turns a live stream into one delivery at the end — the precise failure this endpoint exists to
  prevent, and invisible in development.

**Where the work runs — the decision the rest follows from:**

- **Generation does not live in the response body.** The likeliest failure of a two-minute stream is
  that the client goes away: a sleeping laptop, a closed tab, a proxy timeout. If the work were
  driven by the response generator, Starlette closing it would abandon a report mid-write. So the
  generation *and its storage* run in an `asyncio.Task` with its own session, and the response body
  only forwards what that task publishes. Hanging up costs the events, never the report.
- **The report row is reserved before the first byte.** `reserve_report` writes a row in
  `generating` — a status the column has documented since Phase 0 and that nothing had ever written
  — and its id goes out in the opening frame. That is what makes reconnection possible at all: an
  id that exists only once generation *finishes* is no use to somebody whose connection dropped
  halfway. The client falls back to `GET /reports/{id}/status` and **never restarts generation**,
  which would pay for the same report twice and store it twice.
- **The task is held in a module-level set.** The event loop keeps only a weak reference, so a long
  generation can be garbage-collected mid-flight — an asyncio foot-gun whose symptom is a report
  that silently never appears.
- **`store_report` gained an optional `report=`, rather than a second storage function.** The
  section, evidence and usage writes are the part that must never differ between the app path, the
  n8n path and the streaming path; a second copy of them is precisely how the prototype's field
  names drifted.
- **A reserved row is never left in `generating`.** Any exception marks it `failed` — "still
  running" attached to something that is not running is the one state a status endpoint cannot
  describe honestly.

**The events:**

- **Guaranteed order:** `started` once, then per-section frames, then exactly one `stored`. A client
  that has seen `stored` knows the report is written; one that has not knows only that it might be.
- **`retrying` is the point of the feature, not a leak.** A section failing validation and coming
  back on the repair prompt is this system demonstrating the robustness it has claimed since
  Phase 1, and a spinner hides it completely. The frame carries the attempt number and the stage
  and reason the first attempt was rejected, verbatim.
- **`completed` is emitted after grounding resolves, not after the model returns.** A terminal
  event that arrives before the work behind it finishes is the standard way a progress stream ends
  up lying — and it lets the row show "3 findings · 3 ungrounded" while the run is still going.
- **`elapsed_ms` is per section, measured from that section's own start.** The five run
  concurrently; a clock shared between them would say nothing about any of them.
- **A failure carries the typed `SectionError`, not a string.** The stage is what separates a
  provider outage from a model that will not produce valid JSON, and the UI shows the two
  differently.
- **The progress hook can never fail a section.** A stream nobody is reading is not a reason to
  lose a report that generated correctly, so `emit` swallows and logs.
- **A heartbeat comment every 15 s.** A section can take 90 s and an idle connection is what proxies
  reap; three bytes, ignored by every client.

**Frontend:**

- **All five sections are listed as pending from the opening frame.** A list that grows as results
  land reflows on every event and hides how much is still outstanding.
- **The live counter is client-side; the settled number is the server's.** Only the server knows how
  long the work took, and only the client can tick while it is still taking it. The server's
  `elapsed_ms` on `started` is always ~0, and a number frozen at `0.0s` beside a spinner reads as
  broken — which is exactly how it looked in the first live run.
- **The in-flight report id is written to `sessionStorage`**, so navigating away and back resumes
  the status poll rather than losing the run. Session-scoped, not local: a generation in flight is
  not interesting in another tab next week.
- **The clock is held in state, never read during render.** `Date.now()` in a render body is not a
  pure function of props, and the lint rule that says so is right.
- **`useGenerateReport` and `reportsApi.generate` were deleted rather than left unused.** The
  browser now only streams; `POST /generate_report` remains for n8n and other API clients and is
  covered by the backend suite. Their cache invalidation became
  `useInvalidateAfterGeneration`, which the stream calls on its terminal frame — and which now also
  invalidates the ATT&CK matrix, since a new report changes it too.

**Verified by running**, against a real local model rather than a fake: five rows filling in live
with per-section timers, `Timeline complete 47.0s · 5 findings` while three others were still
analysing, `3 findings · 3 ungrounded` in amber, automatic navigation to the finished report — and,
on a weaker model, two sections showing **"Retrying — repair prompt · First attempt rejected —
validation: every item was empty; the all-null template was returned instead of findings from the
log data"**, which is the exact event this phase exists to surface. A Gemini run with three
sections rate-limited exercised the `failed` path with a real provider error and stored `partial`.

### Decisions taken in Phase 14 — the attack graph

**Where the graph comes from:**

- **No second extraction pass, as instructed — and the reason is worth keeping.** The nodes come
  from typed columns already stored (`anomalies.user_id/user_name/source_ip/destination_ip/
  protocol`, `timeline_events.entity`) and the edges from those same rows plus Phase 10's
  citations. Asking a model to extract entities would produce a second set of claims needing a
  second validator, and the shape of this whole project is that model output is checked before it
  is believed.
- **Per report, never across an account.** A graph built from every report a user owns would join
  entities that were never observed together, which is the one thing a graph must not do.

**Identity — the DECISION NEEDED, and the bug that settled it:**

- **Normalisation is case, whitespace and *surrounding* punctuation. Nothing else.** `JDOE`,
  `jdoe ` and `"jdoe"` are one node; **`j.doe` and `jdoe` are not**, and neither are
  `jdoe@corp.com` and `jdoe@partner.com`. Every additional rule that looks obvious — strip dots,
  strip a domain, strip a `CORP\` prefix — is a way to merge two people who are not the same
  person. A duplicate node is recoverable by a human reading the graph; a fabricated identity is
  not, because it looks exactly like a real one.
- **Two different identifiers merge only when a log row says they are one principal, *and* the
  pairing is unambiguous across the report.** An anomaly carrying `user_id=4471` and
  `user_name=rlee` is the schema asserting it. But the first version of this module unioned
  transitively, and the first run against real generated data produced a node called `application`
  carrying the aliases `20`, `21`, `37` and `system` — a generic display name had welded four
  principals into one actor touching four hosts. Now a name seen against several ids merges
  nothing, and there is a regression test named after it.
- **A merge is displayed as a claim.** Aliases are always shown with the sentence explaining why
  the merge was allowed, rather than silently applied.
- **Node *type* is allowed to be a guess; node *identity* never is.** Deciding that `vpn-gw-01` is
  a host puts the wrong icon on a correct node; deciding two names are one person puts a
  relationship on the canvas that was never observed. That asymmetry is why `classify()` uses
  shape heuristics freely and `normalize()` uses none.
- **`entity` is a real fifth type, not a gap.** The timeline's `entity` column is free text, so
  "Unauthorised user" and "System" arrive beside `10.14.2.37` and `powershell.exe`. Filing those
  under `user` because three of four buckets are taken would be a guess rendered as a fact.
- **Null markers are not entities.** `n/a`, `none`, `unknown`, `-` are the model writing "absent".
  Found by looking at a rendered graph, where `n/a` had become a user node with its own edges.

**Edges:**

- **An anomaly row asserts exactly what it contains**: user→source, source→destination labelled
  with the protocol, and user→destination *only* when there is no source to route through —
  otherwise the graph would claim a direct relationship the row does not describe.
- **Shared citations connect what no column relates.** Two findings that cite the same chunk were
  read out of the same log rows; that is how a timeline entity, which has no address and no user
  column, joins the graph at all. It is a weaker claim, so it is drawn dashed and pulls less hard
  in the layout.
- **A chunk naming more than six entities creates no edges.** A widely-shared retrieval hit is not
  evidence of a specific relationship, and without the cap the graph becomes a clique.

**Risk:**

- **Anomalies and timeline events carry no severity column**, so a node's risk has to come from the
  sections that do. Two routes, and which one was used is recorded and shown: `evidence` (the
  finding cites a chunk this node's own finding also cites) and `mention` (the node's label appears
  verbatim in the finding's text). "The model wrote this address into its description" and "both
  were read out of the same log lines" are different strengths of claim, and an analyst deciding
  whether to act on the graph needs to know which one they are looking at.
- **A mention must match a whole identifier.** `10.0.0.7` is not named by a finding that says
  `10.0.0.76`, and a plain substring test attaches a critical severity to the wrong host in a way
  that looks entirely plausible on a canvas. The trailing lookahead rejects a dot only when a word
  character follows it — the first version rejected any dot, which meant `10.0.0.2` never matched
  "Traffic to 10.0.0.2." — the way most findings actually end. Both caught by tests.
- **Aliases are scanned too**: a node keyed on `Ana Silva` should still match a description that
  says `a.silva`.

**Legibility:**

- **Capped at 60 nodes, ranked by risk then degree, and the cap is stated on screen.** A graph that
  silently drops nodes to stay readable lies about the report it claims to describe. If something
  must go it is the isolated unrated node, never the critical one, and edges are filtered after
  truncation so none dangle.
- **`d3-force` and nothing else** — the simulation only, rendered as SVG by our own component. The
  whole lazy chunk measures **17.5 kB raw / 6.9 kB gzipped**. `react-force-graph` pulls in
  three.js; `cytoscape` and `vis-network` are 300–400 kB and arrive with a complete visual language
  this app would then override. Same trade as `components/ui/` makes with Radix: take the
  behaviour that is hard, write the appearance.
- **Behind `React.lazy`, like `ChartGrid`.** A report page whose reader never opens the graph
  should not download a physics engine. Nothing else may import `d3-force` directly.
- **The layout runs to a fixed tick count and stops**, computed in a `useMemo` rather than an
  effect. A graph that never settles cannot be read, and a permanent animation frame on a page
  left open is a laptop fan.
- **Honest empty state.** A report with no entity data says so, in the backend's own words, rather
  than rendering an empty canvas — and a failed request renders differently again.

**Bug found by looking rather than reading:** every risk-rated node drew as an invisible disc.
Tailwind's `bg-*` sets `background-color`, which an SVG shape ignores completely, so the coloured
nodes had no fill at all and looked exactly like nodes the layout had lost. Fixed with
`fill="currentColor"` plus the severity's `text-*` class.

**Demo data:** a handful of `--demo` findings now name the entities their anomalies carry
(`10.14.5.72`, `vpn-gw-01`, `svc_backup`). Demo documents are never ingested, so demo reports have
no citations at all — without a mention path the seeded graph would be entirely grey, and the risk
weighting would look like a feature nobody built.

**Verified by running:** a real seeded report renders 20 entities and 11 relationships — hosts,
named users, isolated timeline hosts kept on canvas, protocol-labelled edges, amber and cyan nodes
against graphite unrated ones — and clicking `10.14.9.11` dims the rest, shows `HOST / ADDRESS ·
HIGH · 1 observation`, its two edges, and its two findings labelled `mention` and `source`.

### Decisions taken in Phase 15 — the README

- **The rebuild framing is the opening, not a footnote.** "Rebuilt from a university group
  prototype" with the link, the specific defects named, and the note that the six worst are
  enforced by tests. A README that hides its origin invites the reader to discover it; one that
  states it up front is the stronger claim, and it is the one PORTING.md asked for.
- **Live figures lead; the CI cassette is quarantined behind a purpose column.** A skimmer must
  never meet "75% hallucination" without immediate context, so *Headline numbers* carries only the
  live `gemini-2.5-flash` run (0.0% / 100%) and the Evaluation section opens by pointing back at
  it. The comparison table has a **Purpose** row — "validator regression harness" against "model
  measurement" — because the two numbers answer different questions and a table without it invites
  reading them as better-and-worse.
- **`docs/images/` is 18 captions, and every caption says what to notice.** Not "the ATT&CK
  matrix" but "`T1022` is deprecated, `T1888` does not exist, so they are named rather than
  silently discarded". A caption that only labels the image wastes the one moment the reader is
  already looking.
- **The screenshots are of the honesty features wherever there was a choice.** Amber "Ungrounded"
  markers, the unverified-technique dialog quoting the validator verbatim, `total tokens
  [redacted]` in the audit log, the `REPLAYED` badge on the Evaluation page, `No enrichment for
  this report`. Those are the most interesting thing in the product and they are framed as the
  system showing its work — which is why the `--demo` seed's three deliberately defective
  identifiers exist at all.
- **Every number was re-measured for this phase rather than copied from here.** That caught three
  stale figures: 613 backend tests is now **616**, the sample CSV is **195** chunks and not 197,
  and the CI job count is **four**, not three. Bundle sizes come from an actual `npm run build`
  (entry 662.37 kB / 203.52 kB gzipped; ChartGrid 410.73 kB; GraphCanvas 17.47 kB / 6.88 kB).
- **`n8n/IMPORT.md` > Verification status was false and was corrected in the same commit.** It
  still said the workflows had never been executed inside n8n; all three have, and the captures
  are committed. The replacement says what the runs do *not* prove — nothing in CI executes them —
  rather than upgrading them to "tested".
- **A live share link was created for the screenshot and revoked immediately after.** The token is
  partly legible in `share-dialog.jpg`; it is a localhost URL and now inert, but a live capability
  token does not belong in a public repository under any reading.
- **The "what this does not do" section is EVAL.md's, widened.** Unevaluated retrieval, one
  synthetic CSV, replay saying nothing about the current model, unverified CVE existence, the
  Navigator layer never opened in the real Navigator, `logout` not revoking, and Postgres-backed
  rate limiting being the wrong choice for a per-request limiter. It closes on the prototype's
  README claiming Ollama and AES-256 that never existed, because not repeating that is most of the
  reason the section is there.
- **MIT LICENSE, with the vendored data carved out.** The MITRE catalogues are not ours to
  sublicense; the licence points at `SOURCES.md` rather than restating terms that could drift.
- **Screenshots are captured at 1512×982 from the real app on the demo seed**, and one report was
  generated live through the streaming UI during capture — which is where the evidence-citation
  screenshot (`ROWS 52–56 · CHUNK 10` over real log lines) and the $0.017 on the cost chart come
  from. That run came back `partial` with two empty sections, and it was left that way rather than
  re-rolled for a prettier screenshot.

**Update this section at the end of every phase.**
