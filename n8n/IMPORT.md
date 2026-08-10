# n8n workflows

Three workflows. Import each via **n8n → Workflows → Import from File**.

n8n runs at http://localhost:5678 (`docker compose up n8n`).

---

## 1. Authentication — do this first

Every backend endpoint except `/` and `/health/db` requires a bearer credential.

**Do not use a login token.** Access tokens expire after
`ACCESS_TOKEN_EXPIRE_MINUTES` (60 by default), so a scheduled workflow
authenticated with one stops working an hour after somebody last pasted it in.
Raising that lifetime to suit a workflow would weaken every human session too.
Machines get a separate credential instead:

```bash
cd backend
python -m app.db.seed --service-token
```

That creates the `n8n@aipcc.io` service account and prints an API key **once**:

```
aipcc_9d8b1f8f0b02_VrHcSMh9NSpyDnNEY-nC5EWgsJUonUPPuarmqxq6_bU
```

Only the SHA-256 of that value is stored, so there is no way to read it back.
Re-running the command mints a new key and revokes the old ones.

### Add it to n8n

**Credentials → New → Header Auth**, named exactly **`AIPCC API Key`** (the
workflow JSONs reference that name):

| Field | Value |
|---|---|
| Name | `Authorization` |
| Value | `Bearer aipcc_...` |

Every backend node in both workflows is already set to Header Auth and points
at this credential. After import, open one node and confirm the credential
resolved; if n8n created a placeholder, pick the real one and it applies to the
rest.

### What the service account can and cannot do

| | |
|---|---|
| Role | `admin` — the FIM engine polls `/get_all_reports`, which is owner-scoped, so a non-admin service account would only ever audit its own reports |
| Password login | Impossible. The account's password hash is a random value nobody holds. |
| Can | Read and write reports, documents, integrity state, alerts |
| **Cannot** | Touch `/users` or `/api-keys` — API-key callers are refused there (`require_human`) |

That last row is the point. A key pasted into a workflow lives in a credential
store and is long-lived by design; if one leaks it must not be able to mint a
second credential or create an admin. It can do the workflow's job and nothing
beyond it.

Keys can also be managed over the API by an admin holding a **session** token:
`POST /api-keys`, `GET /api-keys`, `DELETE /api-keys/{key_id}` (revoke).

---

## 2. Backend base URL

Every HTTP node targets `http://host.docker.internal:8000`, which resolves from
inside the n8n container to the host — correct when the backend runs on your
machine. If the backend runs under `docker compose`, change it to
`http://backend:8000` so it resolves over the compose network.

---

## Workflow 1 — Simple Report Generator (3 nodes)

Webhook `POST /generate-docx` → JS → DOCX response. Self-contained; calls no
backend endpoint. Superseded by backend export in Phase 6, kept as reference.

**Credentials:** none.

---

## Workflow 2 — AI Security Report Orchestrator (16 nodes)

`POST /analyze-report` webhook → fetch logs → Groq agent → risk scoring → IOC
classification → AbuseIPDB reputation → threat-intel merge → DOCX → store.

**Backend endpoints**

| Endpoint | |
|---|---|
| `GET /get_latest_document_content` | ✅ |
| `POST /upload_file` | ✅ |
| `POST /store_generated_report` | ✅ |

**Credentials:** `AIPCC API Key` (Header Auth), Groq API key, AbuseIPDB API key.

### The store body

`/store_generated_report` accepts the canonical shape — the same Pydantic
schema the Python generator produces, so a report from n8n and one from the app
land in identical tables:

```json
{
  "document_id": "uuid",
  "report_name": "string",
  "classification": "Internal",
  "sections": {
    "attack_types": [], "general_risk_assessment": [],
    "vulnerabilities": [], "anomalies": [], "timeline": []
  },
  "threat_intel": [
    {
      "indicator": "203.0.113.44", "indicator_type": "ip",
      "category": "External Infrastructure", "source": "abuseipdb",
      "reputation_score": 94, "risk_level": "CRITICAL",
      "country": "RU", "usage_type": "Data Center/Web Hosting"
    }
  ]
}
```

The exported workflow sent `report_json`, `user_id` and `generated_filename`,
none of which exist on that endpoint. The committed JSON has been corrected:

- **`user_id` is gone and is not coming back.** A report is attributed to the
  owner of the document it analyses, resolved server-side. A body field naming
  the owner would be a hard-rule #2 violation wearing a disguise.
- **`document_id` is now carried through** from `GET /get_latest_document_content`
  by the `Normalize Input Data` node. It was being dropped, and it is the one
  field the store endpoint cannot infer.
- **`threat_intel`** is built from the workflow's own `classified_iocs` plus the
  AbuseIPDB fields. The reputation score is attached only to the IP AbuseIPDB
  was actually asked about — a domain nobody looked up does not inherit an IP's
  score.

Reports land under the **document owner**, not under `n8n@aipcc.io`, so they
appear in that analyst's `/reports` list and on their dashboard.

---

## Workflow 3 — File Integrity Monitoring (FIM) & Audit Engine (14 nodes)

Scheduled (every 15 min) → fetch reports → skip unsealed ones → download the
source document → SHA-256 → compare against the hash sealed at generation time
→ SEALED, or VirusTotal lookup → TAMPERED + security alert.

**Backend endpoints — all six now exist**

| Endpoint | |
|---|---|
| `GET /get_all_reports` | ✅ |
| `GET /get_report_by_id/{report_id}` | ✅ |
| `GET /documents/{document_id}/download` | ✅ Phase 5 |
| `GET /uploads/{document_name}` | ✅ Phase 5 |
| `PATCH /api/report/integrity/{report_id}` | ✅ Phase 5 |
| `POST /api/security/alert` | ✅ Phase 5 |

**Credentials:** `AIPCC API Key` (Header Auth), VirusTotal API key.

### What changed from the export

The exported graph could not have worked, and not only because of auth:

- It read `$json.report[0].document_name`. `GET /get_report_by_id/{id}` returns
  a **flat** report object — `document_id`, `file_hash`, `report_name` at the
  top level. Every downstream expression referenced a shape the API never had.
- It had two nodes fetching the same file (`/uploads/{name}` and
  `/documents/{id}/download`) and merged one of them with a hash of the other.
  The graph now downloads once, by id, and merges the observed hash against the
  sealed hash from the metadata call.
- It ran **every minute**. Re-hashing every document in the system sixty times
  an hour is not monitoring, it is a load test. Now every 15 minutes.
- **New:** a `Only Sealed Reports` filter. A report with a null `file_hash` was
  never sealable — its source file was already gone when it was generated.
  Comparing against a null hash would mark all of those TAMPERED, which is a
  false accusation, not a finding.
- The VirusTotal node is set to `continueRegularOutput`. A hash VirusTotal has
  never seen returns 404, which is a normal answer to the question — not a
  reason to abandon the tamper alert.

### Endpoint contracts

`PATCH /api/report/integrity/{report_id}`

```json
{ "integrity_state": "SEALED" }
{ "integrity_state": "TAMPERED", "observed_hash": "<64 hex chars>" }
```

`integrity_state` is a closed enum (`UNKNOWN` / `SEALED` / `TAMPERED`); anything
else is a 422 rather than a state the UI cannot render. `integrity_checked_at`
is stamped server-side — a caller cannot make a stale check look fresh.

`POST /api/security/alert`

```json
{
  "severity": "critical",
  "source": "FIM & Audit Engine",
  "message": "File integrity mismatch on ...",
  "report_id": "uuid",
  "document_id": "uuid"
}
```

`severity` is normalised onto the app's ladder, so `CRITICAL`, `Sev 1` and
`critical` all land in one bucket. An unrecognised value becomes `medium`
rather than being rejected — losing an alert is worse than filing it one notch
off. The alert is attributed to the **owner of the report it concerns**, not to
the poster, so it reaches the analyst rather than the service account.

### Path safety

`GET /uploads/{document_name}` takes a caller-supplied name, and `../../.env`
is a valid file name. The name is used **only as a database lookup key** — it
is never joined onto a directory. The matching row supplies the path, and that
path is then still checked to resolve inside the upload directory, because a
row written by older code is untrusted input too. `GET /documents/{id}/download`
takes no name at all.

Both return **410**, not 404, when the record exists but the bytes are gone.
Those are different problems and the FIM engine treats them differently.

---

## Verification status

The endpoint contracts above are covered by tests
(`backend/tests/test_integrations.py`) and were additionally exercised against a
running backend using a real service key — store, download-by-id,
download-by-name, integrity PATCH and alert POST all answer correctly on the
credential the workflows use, and `/users` correctly refuses it.

**All three workflows have since been executed inside n8n** against a running
backend, with live Groq, AbuseIPDB and VirusTotal credentials. Captures of those
runs are in `docs/images/` and are referenced from the README:

| Workflow | Run |
|---|---|
| Simple Report Generator | Produces a real `.docx` over the webhook — `generated-docx-report.png` |
| AI Security Report Orchestrator | Full graph green, succeeded in 2.082 s — `n8n-orchestrator-execution.png`, with the store node's input and stored output in `n8n-orchestrator-store-node.png` |
| FIM & Audit Engine | Swept 47 reports through hash → compare → SEALED — `n8n-fim-execution.png` |

These are still workflow runs, not a regression test: nothing in CI executes
them, and they will need re-checking after any change to the endpoints below.
What CI does guarantee is that the endpoint contracts still hold, and that no
committed workflow JSON carries an embedded credential
(`tests/test_foundation.py::TestNoEmbeddedCredentials`).

---

## Ownership: which system is authoritative?

The Orchestrator duplicates `backend/app/services/report.py`. They are not
peers:

| | |
|---|---|
| **Authoritative** | The **Python generator**. It owns the canonical schema, validation, the repair retry, and the section-error contract. |
| **The Orchestrator** | A *client* of that schema. It produces sections and hands them to `/store_generated_report`, which validates them exactly as the Python path does before anything reaches the database. |

The rule: **n8n orchestrates, the backend decides.** Anything that determines
what is stored — schema, validation, ownership, integrity state, severity
normalisation — lives in Python and is enforced at the endpoint. n8n owns
scheduling, third-party enrichment (Groq, AbuseIPDB, VirusTotal) and DOCX
rendering: work that is genuinely about *when* and *from where*, not about
*what is true*.

That is why `/store_generated_report` re-validates everything and why
`integrity_state` is an enum rather than a string. A workflow can be edited by
anyone with n8n access; the invariants cannot be edited from there at all.

---

## Provenance

These JSONs were never committed to the prototype repository; they were
exported from a live n8n instance, and the rebuild plan described them from
memory. The files here are the source of truth.

Related: prototype commits `c836a19` ("Added file_hash column and PATCH
endpoint for n8n auditing") and `bd55a3f` ("added security alert receiver for
workflow 3") added partial backend support that is absent from the prototype's
final tree. `git show <sha>` in the prototype clone recovers it.
