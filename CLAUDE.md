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
    db/
      session.py            # engine + session factory (NEVER drop/create on import)
      models.py             # SQLAlchemy models
      seed.py               # explicit seed script, run manually
      demo_data.py          # deterministic --demo fixtures (fixed seed, no LLM)
    schemas/                # Pydantic: API request/response + LLM output schemas
    api/routers/            # auth, users, documents, reports, shares, chat,
                            #   dashboard, alerts, api_keys
    services/
      rag/                  # ingest, chunk, embed  (ported from prototype)
      llm/                  # LLMProvider abstraction + implementations
      export/               # layout.py (one document model) + pdf_writer + docx_writer
      report.py             # parallel section generation, validation, retry
      analytics.py          # dashboard aggregation — GROUP BY in SQL, never ORM loops
      severity.py           # the free-text severity ladder, defined once
      chatbot.py            # chat over ingested docs
      integrity.py          # SHA-256 sealing + safe upload-path resolution
      share.py              # share-link rules: creation, expiry, revocation, classification
  alembic/                  # migrations
  tests/                    # pytest
frontend/
  public/video/             # optimized background clips + posters (see manifest.md)
  eslint.config.js          # flat config; react-hooks rules are the ones that matter
  vite.config.js            # app build *and* Vitest, so both resolve `@/` identically
  src/
    index.css               # @theme tokens — the whole design system lives here
    App.jsx                 # routes only
    components/charts/      # Recharts wrappers; ChartGrid is lazy-loaded — see below
    components/motion/      # CSS/SVG feature animations (no deps)
    components/ui/          # design system primitives (Radix behaviour, own styling)
    components/layout/      # AppShell, Sidebar, Topbar
    components/common/      # PageHeader, SeveritySpine, AmbientVideo, IntroSequence
    components/report/      # section renderers, ReportBody (shared with the public
                            #   share view), ExportMenu, ShareDialog, classification
    context/AuthContext.jsx # token + current user; the only source of "who am I"
    hooks/queries.js        # every TanStack Query hook and its query keys
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
pytest
ruff check app tests               # lint; config in backend/ruff.toml

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

**Phases 0–6 complete; Phase 7 part 1 (reproducibility, tests, CI, cleanup) complete — README and
screenshots deliberately not written yet.** See `AIPCC_CLAUDE_CODE_PROMPTS.md` for the phase
sequence and
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
**and a one-command `docker compose up` verified from empty volumes, 30 Vitest/Testing-Library
frontend tests, and a GitHub Actions pipeline running backend lint + migrations + pytest against a
Postgres service container alongside frontend lint + tests + build.** 318 backend tests and 30
frontend tests pass; `ruff check` and `npm run lint` are both clean with no warnings.

Not yet written: the README and screenshots (Phase 7 part 2), held back until the project has been
verified manually. The n8n workflow JSONs are corrected and their
endpoint contracts are covered by tests and verified against a running backend with a real service
key, but the workflows themselves have not been executed inside n8n — that needs live Groq,
AbuseIPDB and VirusTotal credentials. See `n8n/IMPORT.md` > Verification status.

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

**Update this section at the end of every phase.**
