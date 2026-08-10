# Evaluation

> How do you know the output is any good?

Most "AI-powered" projects cannot answer that. This one measures it, against
real published reference data, and fails the build when it regresses.

```bash
python -m app.eval.run                  # replay the recorded fixtures
python -m app.eval.run --gate           # ...and exit non-zero on a regression
python -m app.eval.run --live           # call the configured provider for real
python -m app.eval.run --live --record  # ...and save its responses as fixtures
python -m app.eval.vendor               # refresh the ATT&CK and CWE catalogues
```

Results land in `app/eval/results/latest.json` (committed) and as a summary on
stdout. The latest committed run is also visible in the app, on **Settings →
Evaluation**.

---

## What is measured

| Metric | Definition | Why it is the one that matters |
|---|---|---|
| **Hallucination rate** | invalid identifiers ÷ identifiers emitted | A MITRE technique id that does not exist, or a real id under a name that is not its own. The second is the dangerous one: it passes every format check and reads perfectly plausibly. |
| **Grounding rate** | findings citing real retrieved content ÷ findings | A finding the model could not source. |
| **Fabricated citations** | citations that resolve to nothing ÷ citations made | The model claiming to have read log content it was never given. |
| **Recall (coverage)** | golden labels appearing anywhere ÷ labels | Did it see the events at all. |
| **Recall (distinct)** | golden labels with a finding of their own ÷ labels | Did it report them as separate findings, or bundle them into one narrative. |
| **Precision** | attack findings that are not labelled-benign ÷ attack findings | A report that flags routine activity is one an analyst stops reading. |
| **MITRE agreement** | techniques matching the labeller's choice ÷ labelled | **Reported, never enforced** — see below. |
| **Section success rate** | sections that produced output ÷ 5 | Pipeline health. |
| **Retry rate** | calls with attempt > 1 ÷ calls | How often the repair prompt was needed. |
| **Cost, tokens, p95 latency** | from Phase 9's per-call accounting | What a run costs to produce. |

**A zero denominator gives `None`, never `0.0`.** A model that emitted no
identifiers has a hallucination rate of "not measured", not "perfect" — and the
gate has an explicit rule that refusing to answer is not a passing grade.

---

## The reference data is real

`app/eval/data/` holds MITRE ATT&CK Enterprise (823 techniques) and CWE (969
weaknesses), **derived from the publishers' own releases** by
`app/eval/vendor.py`, pinned to a version, checksummed and attributed in
[`data/SOURCES.md`](app/eval/data/SOURCES.md). Nothing in it is hand-written.

That is not a detail. A hand-typed approximation of the technique list would
make every hallucination number here a fiction — worse than reporting none —
and `tests/test_eval.py::TestCatalogue` spot-checks the files against known
facts so a truncated or invented catalogue fails the suite.

**Deprecated and revoked techniques are kept and flagged, not dropped.** A
model naming `T1022` has not invented an identifier — ATT&CK retired it — and
scoring that as a hallucination would make the rate climb with the calendar
rather than with model behaviour.

**CVE existence is deliberately not checked.** The list is unbounded and grows
daily, so verifying it needs a network call, and a gate that needs the internet
fails on a bad day and gets deleted on the next. The harness checks CVE
*format* and says that is what it checked. CWE and ATT&CK are checked for
existence because they are finite and vendorable.

---

## The golden dataset

`app/eval/golden/golden_log.csv` — 35 rows describing one intrusion end to end:
SSH password guessing, a successful login, bulk reads of finance and HR files,
three large uploads to an external host, encoded PowerShell, Run-key and
service persistence, an SMB `admin$` sweep, a fixed-interval C2 beacon, and the
Security event log being cleared. Interleaved with ordinary user activity that
**must not** be reported as an attack.

`golden_labels.json` carries the expected findings, each with the rows that
justify it and a written reason. It is small on purpose: every label has to be
defensible by reading the log, and a label set nobody can check by hand is one
nobody will maintain.

**What it does not cover**, stated plainly: one synthetic CSV with a
deliberately unambiguous story. It says nothing about noisy production data,
about formats other than CSV, or about attacks not represented in it.

### Why MITRE agreement is reported but not enforced

On the first live run the model scored **14.3%** agreement with the labeller —
and was arguably right more often than the label was. It chose `T1567.002`
(*Exfiltration to Cloud Storage*) where the label said `T1041`
(*Exfiltration Over C2 Channel*) for an upload to a CDN, and `T1543.003`
(*Windows Service*) where the label said `T1547` (*Boot or Logon Autostart*)
for a log containing both a Run key and a service.

Both of those are defensible readings. Enforcing agreement would measure how
closely the model matches one labeller's opinion, not whether it is correct —
so agreement is reported as information and **validity** (does the id exist,
does the name match) is what the gate acts on.

---

## The CI gate replays; it does not call a model

`python -m app.eval.run --gate` runs in CI on every push, with **no database,
no vector store, no embedding model, no network and no API key**. It chunks the
committed golden log with the same `chunk_logs` the real ingest uses, retrieves
deterministically over those chunks, and replays provider responses recorded
once from a real Gemini call.

**Why not live.** A gate that makes LLM calls on every push needs a secret in
CI, costs money per push, and is flaky by construction — the same prompt does
not return the same text twice. A flaky quality gate gets marked
`continue-on-error` within a week and deleted within a month, and then the
project has a quality gate in name only.

### What the replayed gate proves

- The validators genuinely reject bad output — an invented technique id, a real
  id under the wrong name, a malformed CVE, a non-existent CWE, a citation
  pointing at a chunk that was never retrieved.
- The parser, repair retry, citation resolver, golden matcher and metric
  arithmetic behave as claimed, and a change to any of them moves the numbers.
- The thresholds trip. `tests/test_eval.py::TestGate` fires each one.
- The prompt has not silently drifted away from the recorded responses:
  fixtures are keyed by the SHA-256 of the exact prompt, so changing the prompt
  makes replay miss and the run fail loudly telling you to re-record.

### What it does not prove

- **Anything about the current model.** Those responses are frozen at the
  moment they were recorded. Only `--live` produces numbers that describe a
  model, and every result file and printed summary carries its `mode` so the
  two can never be read as the same thing.
- **Retrieval quality.** Golden retrieval is a fixed selection over a 35-row
  log, not a similarity search, so a change that makes the retriever pick worse
  chunks will not move these numbers. Evaluating retrieval needs a larger
  corpus with relevance judgements, and that is future work rather than
  something quietly implied here.
- **Generalisation.** One log, one scenario. See above.

---

## Thresholds

In `app/core/config.py`, because a quality bar is a project decision that
changes as the system improves, and one buried in code is one nobody raises:

```
EVAL_MAX_HALLUCINATION_RATE=0.10
EVAL_MIN_GROUNDING_RATE=0.80
EVAL_MIN_SECTION_SUCCESS_RATE=0.80
```

They are deliberately not set to perfection. A gate that demands 0% on its
first honest run fails immediately and gets deleted; these sit where the
recorded baseline sits, so a **regression** trips them and normal variation
does not. Raise them as the numbers improve.

---

## Re-recording fixtures

Needed whenever a prompt changes — which the harness will tell you, because
replay will miss:

```bash
# with a real key in .env
python -m app.eval.run --live --record
git add app/eval/fixtures/golden_run.json app/eval/results/latest.json
```

Review the diff. A fixture is a record of what a model actually said, and it
should change only when you intended a prompt change.
