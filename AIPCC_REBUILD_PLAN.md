# AIPCC Rebuild Plan

**Goal:** Portfolio / resume piece. Judged on *coherence, reproducibility, and depth* — not feature count.
**Strategy:** Ground-up rebuild in a **new repo** under your own account. Port the working RAG/report
logic from the prototype (see `PORTING.md`), rewrite everything else, wire the n8n workflows in
properly, add auth + dashboard + threat intel + export.

**Why a new repo:** the prototype is a 7-contributor intern-team codebase living on someone else's
account. Rebuilding there would flatten teammates' work and still read as someone else's project. In
a new repo the architecture is demonstrably yours, with the original credited as the prototype it was.
**How to execute:** Phase by phase. Each phase ends in something that runs and demos. Never sit on a big-bang half-broken rewrite.

---

## 1. What this project is

AIPCC ("AI-Powered Cybersecurity Co-Pilot") ingests security logs, runs a RAG pipeline over them, and produces structured security reports (attack types, risk assessment, vulnerabilities, anomalies, timeline). It also has a "talk to your data" chatbot. Three n8n workflows were meant to orchestrate report generation, DOCX export, and file-integrity monitoring.

**Current stack:** FastAPI + SQLAlchemy (Postgres/Neon) + Chroma (HuggingFace MiniLM embeddings) + Google Gemini + React 19 (Vite) + n8n.

---

## 2. What is actually broken (fix these first — they are the reason it feels incomplete)

### Backend — correctness blockers
- **The database wipes itself on every boot.** `postgressql_database.py` runs `run_query("create")` at import time, which calls `Base.metadata.drop_all(engine)` then `create_all`. Every restart destroys all data. This must become a one-time migration/seed, never an on-startup drop.
- **Report data silently fails to save.** `report.py` emits keys like `name`, `mitre_attack_technique_id`, `risk_assessment.*`. `store_report_data()` reads `attack_name`, `attack_mitre_technique_id`, flat `risk_name`, etc. The keys don't match, so attack/vulnerability/anomaly rows get inserted mostly-null. Reports *look* generated but the DB is half-empty.
- **`report_id` is generated but never passed into the `Report(...)` insert.** `report_id` is a not-null primary key — storage is fragile / order-dependent.
- **Fragile LLM JSON parsing.** Every report section does `json.loads(output.content[0]["text"])` with a bare `except` that swallows errors into `{"status":"error"}`. No schema validation, no retry, no repair. One malformed response = a broken section with no signal.
- **6 sequential LLM calls per report.** `generate_full_report()` runs attack/risk/vuln/anomaly/timeline back-to-back. Slow and serial. Should be parallel (`asyncio.gather`) or a background job with status polling.
- **`llm_models.py` reassigns `CURRENT_LLM_MODEL` several times** and ends on `gemini-2.5-flash-lite` regardless of intent. No provider abstraction. The README claims local Ollama "for data sovereignty" but the code calls the Gemini cloud API, and the orchestrator uses Groq — three conflicting LLM stories.

### Security
- **Passwords stored in plaintext** (`password_hash = new_user.password`), even though `bcrypt` is already in requirements.
- **No authentication at all.** `current_user` is hardcoded to `UR-1001`, inserted on every startup. No JWT, no sessions, no role enforcement despite a `role` column.
- The README advertises "AES-256 encryption + SHA-256 hashing" that does not exist in the code.

### Frontend — this is why the UI looks bad
- **No router.** `App.jsx` renders *every page stacked on top of each other* — `TestingPage`, `LoginPage`, `HomePage`, `ChatPage`, `ManageProfile`, `ManageUsers`, `ReportDisplay`, `ReportGenerator`, `ReportHistory` all at once.
- A literal green **`DEBUG: App mounted`** banner is hardcoded top-right.
- `package.json` is half-migrated from Create React App to Vite (still has `react-scripts test`).
- No design system, no shared components, no auth-gated routes, no data-fetching layer.

### n8n — the wiring is missing
- **Simple Report Generator** (webhook `/generate-docx`, 3 nodes) just turns report JSON into a DOCX. It works and is what the frontend currently calls.
- **AI Security Report Orchestrator** (16 nodes) is the intended real pipeline (Groq agent → risk scoring → IOC classification → AbuseIPDB reputation → threat-intel merge → DOCX → save). But it calls backend endpoints that **don't exist**: `/store_generated_report`, `/get_latest_document_content`. So it was never runnable end to end. It also *duplicates* the Python `report.py` logic — you have two competing report engines.
- **FIM & Audit Engine** (19 nodes) is fully orphaned: scheduled SHA-256 hashing, stored-hash comparison, VirusTotal lookup, tamper alerts, SEALED/TAMPERED state — all pointing at backend endpoints that don't exist.

---

## 3. Target architecture

### Backend (FastAPI, restructured into a package)
```
backend/
  app/
    main.py                # app factory, router registration, CORS, middleware
    core/
      config.py            # pydantic-settings, all env in one place
      security.py          # bcrypt hashing, JWT create/verify, OAuth2 deps
    db/
      session.py           # engine + session, NO drop_all on import
      models.py            # SQLAlchemy models
      seed.py              # explicit, opt-in seed script (not on startup)
    schemas/               # pydantic request/response + LLM output schemas
    api/routers/
      auth.py  users.py  documents.py  reports.py  chat.py  dashboard.py  integrations.py
    services/
      rag/                 # ingest, chunk, embed (kept, cleaned)
      llm/                 # LLMProvider abstraction (gemini | ollama | groq via env)
      report.py            # parallel section generation + pydantic validation + retry
      chatbot.py
      threat_intel.py      # AbuseIPDB / VirusTotal enrichment
      integrity.py         # FIM hash storage + comparison
    alembic/               # migrations replace drop_all/create_all
  tests/                   # pytest: report parsing, auth, endpoints
```

Key backend changes:
- **Auth:** OAuth2 password flow, bcrypt hashing, JWT access tokens, `get_current_user` dependency, `require_role("admin")` dependency. Replace the hardcoded `UR-1001` everywhere.
- **Alembic migrations** instead of drop-all-on-boot. Seed via `python -m app.db.seed`.
- **Fix the report pipeline:** one canonical schema (Pydantic) shared by generator + storage so keys can't drift. Validate LLM output against it; retry/repair on failure. Run sections in parallel.
- **LLM provider abstraction:** `LLMProvider` interface; pick backend by env (`LLM_PROVIDER=gemini|ollama|groq`). Default Gemini so a reviewer can run it with just an API key; document Ollama as the "local / data-sovereignty" option to match the narrative.
- **Add the endpoints n8n needs:** `/get_latest_document_content`, `/store_generated_report`, plus integrity endpoints (`/integrity/hash`, `/integrity/state`) and an alerts endpoint. Async report generation with a `GET /reports/{id}/status`.

### Frontend (React + Vite, full rewrite)
- **Routing:** `react-router-dom` with real routes and a protected-route wrapper.
- **Design system:** Tailwind CSS + a component set (shadcn/ui or Radix). Dark "security console" aesthetic. One consistent layout shell (sidebar + topbar).
- **Data layer:** TanStack Query + a typed `apiClient` (axios), auth token in memory/context, 401 → redirect to login.
- **Pages:** Login, Dashboard (analytics), Report Generator, Report History, Report Detail, Chat ("talk to data"), Users (admin only), Profile, Settings.
- **Charts:** Recharts for the dashboard (severity trend, top attack types, anomaly volume, reports over time).
- Delete the stacked `App.jsx`, the debug banner, and the CRA leftovers.

### n8n
- Rewrite the **Orchestrator** to call the real backend endpoints; keep it as the automation layer. Surface its threat-intel output (AbuseIPDB / VT scores) in the report UI.
- Wire the **FIM engine** to real integrity endpoints; expose tamper alerts in the UI.
- Keep the **Simple Report Generator** as the DOCX export step (or fold export into the backend — see Phase 6).
- Ship the workflow JSONs in a `/n8n` folder with import instructions.

### Infra & portfolio polish (the disproportionate wins)
- **`docker-compose.yml`** bringing up backend + frontend + postgres + n8n (+ optional ollama) so the whole thing runs with `docker compose up`. This is the single biggest portfolio multiplier.
- **Complete `.env.example`**, honest **README** (accurate stack, screenshots, architecture diagram, one-command run).
- **Tests + CI:** pytest for the report-parsing and auth paths, a GitHub Actions workflow. A `tests/` dir and a green CI badge do a lot of the "this person is serious" work for you.

---

## 4. Phased roadmap (each phase is independently demo-able)

| Phase | Outcome | Depends on |
|---|---|---|
| **0 — Foundation** | New repo scaffolded, RAG ported, Alembic + Docker Postgres, config centralized. | — |
| **1 — Backend correctness** | One report generates *and stores correctly* end to end. Shared Pydantic schema, validation, parallel LLM calls, missing endpoints stubbed. | 0 |
| **2 — Auth + roles** | Real login, bcrypt, JWT, role-gated endpoints, `current_user` from token. | 0 |
| **3 — Frontend rewrite** | Router, design system, all pages, auth context, api client. Looks like a real product. | 1, 2 |
| **4 — Dashboard / analytics** | Aggregation endpoints + Recharts dashboard. | 3 |
| **5 — n8n integration** | Orchestrator + FIM wired to real endpoints; threat intel + tamper alerts in the UI. | 1, 3 |
| **6 — Export + sharing** | PDF/DOCX export, classification levels, shareable report links. | 3 |
| **7 — Polish** | Tests, CI, docker-compose finalized, honest README + screenshots, seed data. | all |

**Sequencing advice:** do 0 → 1 → 2 → 3 first. That alone is a coherent, runnable, good-looking portfolio app. Phases 4–7 are depth you can add and demo one at a time. Don't start Phase 5 (n8n) until Phase 1 endpoints exist, or you'll repeat the original mistake.

---

## 5. Decisions locked in from your answers
- **Rewrite scope:** full frontend rewrite; backend rewrite where needed (keep RAG/report logic, restructure everything around it).
- **Purpose:** portfolio — so clean architecture, reproducibility, and tests matter more than exhaustive features.
- **n8n:** wire Orchestrator + FIM into the backend; advance the workflows as needed.
- **Features:** auth + roles, dashboard/analytics, live threat intel + alerting, report export + sharing.

Open call to make during Phase 1: **one LLM story.** Recommended — provider abstraction, default Gemini (runnable with one key), Ollama documented as the local option. Pick and commit; don't leave three.
