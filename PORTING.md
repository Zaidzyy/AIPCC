# PORTING.md — what moves from the prototype to the new repo

The prototype lives at `github.com/ahmed2bassam/AIPCC` (university group project, 7 contributors,
dormant since 2026-03-06). The new repo is a ground-up rebuild. This is the complete list of what
crosses over.

---

## ⚠️ Before anything

1. **Do not copy `.env`.** It contains a live `GEMINI_API_KEY`, `DATABASE_URL` and `HF_TOKEN`.
   Copy `.env.example` instead and fill in fresh values. **If the prototype repo is public, rotate
   those three credentials now** — they may already be exposed in history.
2. **Do not copy `.git/`.** New repo, new history.
3. **Do not copy** `__pycache__/`, `chroma_langchain_db/`, `uploads/`, `.idea/`, `node_modules/`.
4. **Credit the prototype** in the new README: it was a team project, and the rebuild is yours. One
   honest line — "Rebuilt from a university group prototype (link); this repo is a ground-up
   reimplementation" — protects you and is the accurate story.

---

## PORT — carry these over

| From (prototype) | To (new repo) | Notes |
|---|---|---|
| `backend/ai/rag/ingest_data.py` | `backend/app/services/rag/ingest.py` | Loaders for csv/json/txt/log + metadata extraction. **Remove the `from backend.main import *` circular import.** |
| `backend/ai/rag/chunk_data.py` | `backend/app/services/rag/chunk.py` | RecursiveCharacterTextSplitter logic. Sound as-is. |
| `backend/ai/rag/embed_data.py` | `backend/app/services/rag/embed.py` | MiniLM embeddings. Move the model name into config. |
| `backend/apicc_databases/chroma_db/` | `backend/app/services/rag/vectorstore.py` | Chroma setup. Move `persist_directory` into config. |
| `backend/ai/report.py` — **prompts only** | `backend/app/services/report.py` | The 5 section prompts are genuinely good. **Rewrite the surrounding code**: shared Pydantic schemas, parallel execution, validation + retry. Do not port the `json.loads(output.content[0]["text"])` pattern or the bare excepts. |
| `backend/ai/chatbot.py` — **prompt + history approach** | `backend/app/services/chatbot.py` | Keep the system prompts and the doc-scoped retrieval idea. Rewrite session/DB handling. |
| SQLAlchemy **table shapes** in `postgressql_database.py` | `backend/app/db/models.py` | Users, Document, Report, AttackType, RiskAssessment, Vulnerability, Anomaly, Timeline, Chat, Message. Keep the shapes; drop `run_query()`, the ID-generator functions, and the module-level `run_query("create")`. |
| `uploads/synthetic_pegasus_dataset.csv` | `backend/tests/fixtures/` or `seed/` | Useful demo/test data. |
| The 3 n8n workflow JSONs | `n8n/` | Rewire to real endpoints in Phase 5. |
| `frontend/public/video/` | same path | **Already built.** Copy as-is with `manifest.md`. |
| `frontend/src/components/motion/` | same path | **Already built.** Copy as-is. |
| `AIPCC_REBUILD_PLAN.md`, `AIPCC_CLAUDE_CODE_PROMPTS.md`, `CLAUDE.md`, `PORTING.md` | repo root | The planning docs. |

---

## DO NOT PORT — rewrite from scratch

| Prototype file | Why |
|---|---|
| `backend/main.py` | 439 lines, all routes in one file, hardcoded `current_user`, plaintext passwords, no auth. Rewrite as routers. |
| `postgressql_database.py` — the `run_query()` layer | Generic string-dispatch wrapper that swallows exceptions and drops all tables on `"create"`. Use SQLAlchemy directly. |
| `generate_user_id` / `generate_document_id` / … | String-parsing sequential IDs (`UR-1001` → `UR-1002`) with race conditions. Use UUIDs or DB sequences. |
| `store_report_data()` | The field names disagree with what `report.py` produces, so rows save mostly-null. Replaced by shared schemas. |
| `frontend/src/App.jsx` | Renders every page stacked, plus a debug banner. Full rewrite with a router. |
| `frontend/src/Pages/*` | CRA-era, no design system, inconsistent naming (`Report generator.jsx` with a space). Rebuild in Phase 3. |
| `frontend/src/Pages/CSS_Filess/*` | Superseded by Tailwind + the design system. |
| `backend/test.py`, `TestingPage.jsx` | Scratch files. |
| `requirements.txt` | 130+ pinned lines including unused packages. Regenerate from actual imports. |
| `README.md` | Claims local Ollama + AES-256/SHA-256 that the code never implemented. Write an honest one. |

---

## Sanity check after porting

Before starting Phase 1, confirm:

- [ ] `docker compose up postgres -d` works and the backend connects
- [ ] Backend starts and **the database still has data after a restart** (the prototype's fatal bug)
- [ ] A CSV can be ingested and chunks land in Chroma
- [ ] No `from backend.main import *` anywhere
- [ ] `.env` is gitignored; `.env.example` is committed with no real values
- [ ] `grep -r "drop_all" backend/` returns nothing
