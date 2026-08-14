# AIPCC — Claude Code Prompts

Copy-paste these into Claude Code **one phase at a time, in order.** Read `AIPCC_REBUILD_PLAN.md` alongside these.

## How to run this well
- **One phase = one branch = one session.** `git checkout -b phase-1-backend-core` before each. Commit when the phase's done-criteria pass. This keeps blast radius small and lets you roll back.
- **Start each session by pasting the "Standing context" block below, then the phase prompt.**
- After each phase, actually run the app and check the done-criteria before moving on. Don't stack broken phases.
- If Claude Code wants to change something outside the phase's scope, tell it to note it and stay in scope.

---

## Standing context (paste at the top of every session)

```
This is AIPCC, an AI-powered cybersecurity report generator: FastAPI + SQLAlchemy (Postgres) +
Chroma (HuggingFace MiniLM embeddings) + an LLM + React (Vite), with n8n workflows for automation.
It's a PORTFOLIO project — prioritize clean architecture, reproducibility, and tests over feature sprawl.

This repo is a ground-up rebuild of an incomplete internship prototype. PORTING.md says exactly
what to carry over and what to rewrite.

Ground rules:
- Read CLAUDE.md first, then AIPCC_REBUILD_PLAN.md for why the architecture is what it is.
- Work only within the scope of the phase I give you. If you spot other issues, list them at the end, don't fix them now.
- Keep every phase runnable. Don't leave the app in a broken state at the end of a session.
- Explain non-obvious decisions in commit messages. Update CLAUDE.md (including its status section) when architecture changes.
- Never reintroduce: on-startup DB drops, a hardcoded current_user, plaintext passwords, pages rendered
  without a router, or unvalidated LLM output reaching the database.
- Postgres runs in Docker locally. Never require an external managed DB to run the app.
```

---

## Day 0 — create the new repo (do this yourself, before Phase 0)

The rebuild lives in a **brand-new repo**, not the prototype. Five minutes of setup:

```bash
mkdir aipcc && cd aipcc
git init -b main
# copy in the planning docs from the old folder:
#   CLAUDE.md  AIPCC_REBUILD_PLAN.md  AIPCC_CLAUDE_CODE_PROMPTS.md  PORTING.md
# copy in the finished assets:
#   frontend/public/video/          (7 clips + posters + manifest.md)
#   frontend/src/components/motion/ (4 CSS/SVG components)
printf '.env\n__pycache__/\nnode_modules/\nchroma_langchain_db/\nuploads/\n.idea/\n' > .gitignore
git add -A && git commit -m "chore: planning docs and prepared motion assets"
# create the repo on GitHub under YOUR account, then:
# git remote add origin https://github.com/<you>/aipcc.git && git push -u origin main
```

**Do not copy `.env` or `.git/` from the prototype.** See `PORTING.md` — it has the full port/skip
list and a credentials warning.

---

## Phase 0 — Foundation

```
GOAL: Scaffold the new repo and port the salvageable prototype logic. No new features.

Context: This is a NEW, near-empty repo. The prototype lives elsewhere and is read-only reference.
PORTING.md lists exactly what to carry over and what to rewrite — follow it.

Tasks:
1. Scaffold the backend package exactly as CLAUDE.md describes:
   backend/app/{main.py, core/, db/, schemas/, api/routers/, services/} plus backend/tests/.
   FastAPI app factory in app/main.py, health endpoint at GET /.
2. Centralize configuration in app/core/config.py with pydantic-settings (DATABASE_URL, LLM_PROVIDER,
   GEMINI_API_KEY, CHROMA_DIR, JWT_SECRET, etc.). No bare os.getenv anywhere else.
   Write a complete .env.example with no real values.
3. docker-compose.yml with services: postgres (16), backend, frontend, n8n. Postgres is the DEFAULT
   local database — no external/Neon dependency. Include a named volume so data survives restarts.
4. SQLAlchemy models in app/db/models.py: Users, Document, Report, AttackType, RiskAssessment,
   Vulnerability, Anomaly, Timeline, Chat, Message. Keep the prototype's table shapes but use UUID
   primary keys instead of parsed sequential strings ("UR-1001"). Session factory in app/db/session.py
   that NEVER creates or drops schema at import time.
5. Alembic: initialize, generate the initial migration, confirm `alembic upgrade head` builds the schema.
   Add app/db/seed.py as an explicit manual script (an admin user + the sample dataset).
6. Port the RAG pipeline per PORTING.md into app/services/rag/ (ingest, chunk, embed, vectorstore).
   Remove the circular `from backend.main import *`. Move hardcoded paths/model names into config.
7. Frontend: scaffold Vite + React 19 + react-router-dom + Tailwind + TanStack Query. A single app
   shell with a placeholder route. Do NOT port any prototype pages. Leave the already-prepared
   frontend/public/video/ and frontend/src/components/motion/ untouched.
8. Verify: docker compose up starts postgres + backend; the backend connects; restarting the backend
   does NOT lose data; a CSV can be ingested and chunks land in Chroma.

DONE WHEN: `docker compose up` runs, `alembic upgrade head` builds the schema, data survives a restart,
a sample CSV ingests successfully, and `grep -r "drop_all" backend/` returns nothing.
```

---

## Phase 1 — Backend correctness

```
GOAL: Make one report generate AND store correctly, end to end. This is the most important phase.

Tasks:
1. Define ONE canonical Pydantic schema for a full report (attack_types, general_risk_assessment,
   vulnerabilities, anomalies, timeline) in app/schemas/. The generator and the DB-storage code must both
   use these exact field names so keys can never drift again.
2. Fix the key mismatch between report.py (name, mitre_attack_technique_id, nested risk_assessment, etc.)
   and store_report_data (attack_name, attack_mitre_technique_id, flat fields). Align both to the schema.
3. Fix the Report insert: report_id (primary key) must be passed into the Report(...) row.
4. Make LLM output parsing robust: validate each section against its Pydantic schema; on parse/validation
   failure, retry once with a repair instruction; if it still fails, return a typed error for that section
   (not a silent {"status":"error"}).
5. Run the 5 report sections in parallel with asyncio.gather instead of sequentially.
6. Create an LLMProvider abstraction in services/llm/ that selects the backend via env
   (LLM_PROVIDER=gemini|ollama|groq). Default gemini. Remove the dead commented-out model reassignments.
7. Add the endpoints the n8n workflows expect (stub the bodies if needed, but real routes):
   GET /get_latest_document_content, POST /store_generated_report. Add GET /reports/{id}/status for async
   generation.
8. Add pytest tests for: report schema validation, the key-alignment (a generated report stores and reads
   back with all fields populated), and the parse-retry path.

DONE WHEN: upload a log -> generate a report -> every section's fields are populated in the DB and returned
to the client. Tests pass. Report generation runs sections in parallel.
```

---

## Phase 2 — Auth + roles

```
GOAL: Real authentication and role-based access. Kill the hardcoded user.

Tasks:
1. app/core/security.py: bcrypt password hashing (hash on user create, verify on login). Migrate the
   password_hash column to store real hashes. JWT access-token create/verify.
2. OAuth2 password flow: POST /auth/login returns a JWT. get_current_user dependency decodes it.
   require_role("admin") dependency for admin-only routes.
3. Replace every use of the old hardcoded current_user (documents, reports, chat) with the authenticated
   user from the token.
4. Gate endpoints: user management is admin-only; a user only sees their own reports/chats unless admin.
5. Add a POST /auth/register (or admin-create-user) path with hashed passwords.
6. Tests: login success/failure, protected route without token -> 401, role enforcement -> 403.

DONE WHEN: you log in, get a token, and all data endpoints require it. Passwords are bcrypt-hashed. Admin
vs non-admin access is enforced and tested.
```

---

## Phase 3 — Frontend rewrite

```
GOAL: Full React rewrite. It should look like a real product, not stacked components.

Tasks:
1. Delete the current App.jsx approach (all pages stacked), the "DEBUG: App mounted" banner, and the
   Create-React-App leftovers (react-scripts). Vite only.
2. Add react-router-dom with routes: /login, /dashboard, /generate, /reports, /reports/:id, /chat,
   /users (admin), /profile, /settings. Add a ProtectedRoute wrapper that redirects to /login without a token.
3. Design system: Tailwind CSS + a component library (shadcn/ui or Radix primitives). Build one app shell
   (sidebar nav + topbar with user menu). Dark "security console" aesthetic, consistent spacing/typography.
4. Data layer: a typed apiClient (axios) with base URL from env and an interceptor that attaches the JWT and
   redirects to /login on 401. Use TanStack Query for all server state.
5. Auth context: store the token, expose login/logout, hydrate current user.
6. Rebuild each page cleanly against the real backend: Login, Report Generator (upload -> generate ->
   view), Report History (list), Report Detail (all sections rendered nicely), Chat (talk to data),
   Users (admin table), Profile, Settings.
7. Loading/empty/error states everywhere. No console-debug UI left in.

DONE WHEN: the app is a single routed SPA behind login, every page pulls real data through TanStack Query,
and it looks polished and consistent. No stacked pages, no debug banner.
```

---

## Phase 4 — Dashboard / analytics

```
GOAL: A dashboard that makes the app feel substantial.

Tasks:
1. Backend aggregation endpoints under /dashboard: reports over time, count by severity, top attack types,
   anomaly volume over time, open vs resolved. Efficient SQL aggregation, not per-row Python loops.
2. Frontend /dashboard page using Recharts: a KPI row (total reports, critical count, etc.) plus 3-4 charts
   bound to the endpoints above. Respect the design system.
3. Sensible empty states when there's no data yet.

DONE WHEN: /dashboard shows live aggregates and charts driven entirely by backend data.
```

---

## Phase 5 — n8n integration (Orchestrator + FIM)

```
GOAL: Wire the two orphaned n8n workflows into the real backend and surface their output in the UI.

Context: The AI Security Report Orchestrator and FIM & Audit Engine call backend endpoints that don't
exist. Some overlap with Python report.py. Decide per-feature whether n8n or the backend owns it, and
document the choice in CLAUDE.md.

Tasks:
1. Create a /n8n folder; move the three workflow JSONs there with an IMPORT.md explaining how to import
   and which env/credentials each needs (Groq, AbuseIPDB, VirusTotal).
2. Orchestrator: implement the endpoints it calls (/get_latest_document_content, /store_generated_report,
   /upload_file already exists). Update the workflow so it runs end to end: log fetch -> analysis ->
   risk scoring -> IOC classification -> AbuseIPDB reputation -> threat-intel merge -> store. Advance it
   where useful. Surface the threat-intel enrichment (IP reputation, IOC classes) in the Report Detail page.
3. FIM engine: add integrity endpoints (store SHA-256 hash on report creation; GET stored hash; update
   integrity state SEALED/TAMPERED; POST security alert). Wire the workflow's VirusTotal + tamper-alert
   path to them. Add an Alerts view in the frontend and an integrity badge on reports.
4. Make sure a report generated via the app and one driven via n8n land in the same schema/tables.

DONE WHEN: importing the workflows and running them produces reports/alerts stored via real endpoints,
and the threat-intel + integrity data shows up in the UI.
```

---

## Phase 6 — Export + sharing

```
GOAL: Report export and controlled sharing.

Tasks:
1. Backend: generate a polished DOCX and PDF for a report (reuse the n8n docx logic or a Python lib like
   python-docx + a PDF renderer). Endpoints: GET /reports/{id}/export?format=pdf|docx.
2. Classification levels on reports (e.g., Public / Internal / Confidential) enforced in the UI and API.
3. Shareable links: a tokenized, optionally-expiring read-only report view. Respect classification.
4. Frontend: export buttons on Report Detail, a share dialog, classification selector.

DONE WHEN: a report exports to clean PDF/DOCX and can be shared via a read-only link that honors
classification.
```

---

## Phase 7 — Polish (portfolio finish)

```
GOAL: Make it obviously the work of someone who ships.

Tasks:
1. Finalize docker-compose so `docker compose up` brings up backend + frontend + postgres + n8n (+ optional
   ollama) and the app is reachable. One-command run.
2. Expand tests: backend coverage on report/auth/dashboard; a few frontend component/integration tests.
   Add a GitHub Actions CI workflow running lint + tests on push.
3. Rewrite README to be honest and impressive: accurate stack, architecture diagram, feature list,
   one-command run instructions, screenshots/GIFs of the dashboard, report, and chat.
4. Add a seed script producing a realistic demo dataset so a reviewer sees a populated app immediately.
5. Remove dead code, TODOs, and the CRA/leftover files.

DONE WHEN: a stranger can clone, run `docker compose up`, log in with seed creds, and see a populated,
good-looking app. CI is green. README sells it.
```

---

## Optional first move
Before Phase 0, you can hand Claude Code the whole repo with just: *"Read AIPCC_REBUILD_PLAN.md and the
codebase, then confirm the broken-items list is accurate and flag anything I missed."* A quick reality-check
pass catches drift between this plan and the actual current state before you start changing things.
