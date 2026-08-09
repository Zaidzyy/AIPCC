# n8n workflows

Three workflows. Import each via **n8n → Workflows → Import from File**.

n8n runs at http://localhost:5678 (`docker compose up n8n`).

---

## Backend base URL

Every HTTP node targets `http://host.docker.internal:8000`. That resolves from
inside the n8n container to the host, which is correct when the backend runs on
your machine. If you run the backend via `docker compose`, change it to
`http://backend:8000` so it resolves over the compose network.

## Authentication (required since Phase 2)

Every backend endpoint except `/` and `/health/db` now requires a bearer token.
The workflows as exported send no `Authorization` header, so **each HTTP node
that calls the backend must be given one** or it will get a 401.

Get a token:

```bash
curl -X POST http://localhost:8000/auth/login \
  -d "username=admin@aipcc.io&password=admin"
```

Add it in n8n as a **Header Auth** credential — name `Authorization`, value
`Bearer <token>` — and attach it to each backend HTTP node.

Reports are attributed to whoever the token belongs to, and non-admins only see
their own. Use an admin token if a workflow needs to read across all users, as
the FIM engine does when it polls `/get_all_reports`.

Tokens expire after `ACCESS_TOKEN_EXPIRE_MINUTES` (default 60), which is fine
for testing but not for a scheduled workflow. A long-lived service-account
token is a Phase 5 task.

---

## 1. Simple Report Generator (3 nodes)

Webhook `POST /generate-docx` → JS → DOCX response. Self-contained; calls no
backend endpoint. Superseded by backend export in Phase 6, kept as reference.

**Credentials:** none.

---

## 2. AI Security Report Orchestrator (16 nodes)

`POST /analyze-report` webhook → fetch logs → Groq agent → risk scoring → IOC
classification → AbuseIPDB reputation → threat-intel merge → DOCX → store.

**Backend endpoints it calls**

| Endpoint | Status |
|---|---|
| `GET /get_latest_document_content` | ✅ built in Phase 1 |
| `POST /store_generated_report` | ✅ built in Phase 1 |
| `POST /upload_file` | ✅ built in Phase 1 |

**Credentials:** Groq API key, AbuseIPDB API key.

`/store_generated_report` takes the canonical `ReportSections` shape, the same
one the Python generator produces, so an n8n-driven report and an app-driven
report land in identical tables. The section keys are `attack_types`,
`general_risk_assessment`, `vulnerabilities`, `anomalies`, `timeline` — the
workflow's agent output must be mapped to those names.

---

## 3. Automated File Integrity Monitoring (FIM) & Audit Engine (19 nodes)

Scheduled → fetch reports → hash stored file → compare to stored hash →
VirusTotal lookup → SEALED / TAMPERED state → security alert.

**Backend endpoints it calls**

| Endpoint | Status |
|---|---|
| `GET /get_all_reports` | ✅ built in Phase 1 |
| `GET /get_report_by_id/{report_id}` | ✅ built in Phase 1 |
| `GET /uploads/{document_name}` | ❌ Phase 5 — static file serving |
| `GET /documents/{document_id}/download` | ❌ Phase 5 |
| `PATCH /api/report/integrity/{report_id}` | ❌ Phase 5 |
| `POST /api/security/alert` | ❌ Phase 5 |

**Credentials:** VirusTotal API key.

Four of its six endpoints do not exist yet — this workflow cannot run end to
end until Phase 5. The two report-reading endpoints work today.

---

## Provenance

These JSONs were never committed to the prototype repository; they were
exported from a live n8n instance. The rebuild plan described them from
memory. Treat the files here as the source of truth.

Related: prototype commits `c836a19` ("Added file_hash column and PATCH
endpoint for n8n auditing") and `bd55a3f` ("added security alert receiver for
workflow 3") added partial backend support that is absent from the prototype's
final tree. `git show <sha>` in the prototype clone recovers it as reference
for Phase 5.
