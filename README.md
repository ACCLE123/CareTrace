# CareTrace

CareTrace is a traceable longitudinal care-note prototype for the Nightingale 72HR Build. It is intentionally scoped to one synthetic patient story: a clinician can see a consult-ready Glance View, follow every highlight back to an exact source entry, collaborate without cross-role overwrites, and inspect version history. The frontend is an independent static app in `frontend/`, ready for Vercel; the backend is a FastAPI API backed by PostgreSQL.

> **Safety posture:** This is a demo using synthetic data only. It does not diagnose, triage, or replace clinical judgment. AI-produced content is labelled as system-authored and is never exposed directly to the patient role.

## Start in one command

```bash
docker compose up --build
```

This starts the Next.js frontend at [http://localhost:3000](http://localhost:3000) and the API at [http://localhost:8000](http://localhost:8000), using the `DATABASE_URL` supplied by the git-ignored `.env.local` file. API documentation is at `/docs`. The Neon CLI writes that file after project linking. An optional local PostgreSQL container remains available only with `docker compose --profile local-postgres up`.

For the browser app during local development, run `cd frontend && npm install && npm run dev`; absent an environment override, it defaults to `http://localhost:8000`. For production, deploy `frontend/` to Vercel as described in [frontend/README.md](frontend/README.md), set its `NEXT_PUBLIC_API_BASE_URL` environment variable, and set the backend's `CORS_ORIGINS` to the exact Vercel origin.

### Neon Postgres

The application runtime uses Neon's **pooled** `DATABASE_URL`, suitable for Vercel's concurrent serverless requests. The linked Neon CLI writes it to `.env.local`, alongside `DATABASE_URL_UNPOOLED`; use the latter only for schema migrations, backups, or administrative operations. Never commit either file or put these values in browser-visible variables.

For the Vercel **backend** project, add the pooled `DATABASE_URL` and the exact `CORS_ORIGINS` of the deployed frontend in Project Settings → Environment Variables. The frontend only receives `NEXT_PUBLIC_API_BASE_URL`, never the database connection string.

### DeepSeek AI scribe

The AI scribe is a backend-only DeepSeek integration. Add these variables to the **backend** Vercel project (and to your local git-ignored `.env.local` when testing locally):

```bash
DEEPSEEK_API_KEY=...
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

Never put the key in `frontend/` or a `NEXT_PUBLIC_*` variable. The clinician/staff **AI scribe** form accepts synthetic source text only. Before the FastAPI server sends anything to DeepSeek, it redacts titled names, IC/ID numbers, and phone numbers. A successful run persists an internal source entry, a separate `system` AI-scribed entry, the redacted input/model/prompt version, and an exact timeline provenance pointer. If the key is absent or the provider response is malformed, no AI note is written.

## Run the required automated tests

```bash
docker compose run --rm web pytest -q
```

The test suite includes the four requested files plus a small bonus test:

- `test_rbac_scope.py` — role ownership, patient raw-AI exclusion, clinic scope.
- `test_revision_history.py` — versions, revert, metadata-only audit events.
- `test_highlight_provenance.py` — every highlight resolves to a timeline entry.
- `test_concurrent_edits.py` — independent role-owned sections and deterministic optimistic-concurrency conflict.
- `test_self_learning_importance.py` — bounded feedback learning.
- `test_deepseek_scribe.py` — redaction happens before the provider request and the structured response contract is validated.

## Demo script

1. Start as **Dr. Mira Chen**. The Glance View shows a deterministic high-risk allergy signal, the current chest-discomfort escalation, and open actions.
2. Click **View source in timeline** on any card. It scrolls directly to the source-of-truth entry with author role, entry type, timestamp, and source pointer.
3. Add a care note or open **History** on a clinician note. Revert a prior version: the operation makes a new snapshot and an audit event rather than mutating history.
4. Select **AI scribe**, choose a synthetic patient session, nurse consult, or doctor consult, and generate a DeepSeek candidate note. The generated `system` entry points to its source transcript; accept or reject its Glance suggestion as a care-team member.
5. Switch to **Nurse Aisha Lim**. Staff can create staff notes but cannot change clinical assessments. Switch to the synthetic patient: internal AI notes and internal collaboration disappear because the API filters them server-side.

## Architecture and controls

- **PostgreSQL** is the durable store. `entries`, `entry_versions`, `comments`, `highlights`, and `audit_log` have separate tables and foreign keys. PostgreSQL transactions make every write plus its revision/audit insert atomic.
- **Server-side RBAC:** every protected endpoint looks up the identity in the database using `X-Demo-User`, then checks clinic scope and role ownership. The header is a demo-only identity selector; production would replace it with a verified OIDC/JWT claim. The UI is never the enforcement layer.
- **No cross-role overwrite:** staff may change only their own staff note; clinicians only clinician notes. Admin is deliberately read-only oversight in this prototype.
- **Optimistic concurrency:** edits and reverts issue `UPDATE ... WHERE version = expected_version`. A stale write gets HTTP 409 and must refresh. Independent entries can be edited in parallel.
- **Provenance:** highlights store `timeline:<entry_uuid>#source`; this exact pointer resolves to the producing timeline entry. AI entries also retain an upstream session or consult pointer.
- **Importance:** high risk tags and explicit escalation/allergy language provide a deterministic safety floor. Care-team acceptance adds a persisted, bounded `+5` type weight for future same-type suggestions, never suppressing a safety floor. Scores are prioritisation suggestions, not clinical certainty.
- **Patient safety:** only `visibility='patient'` clinician-approved instructions may reach a patient response. Internal notes, raw AI entries, comments, audit log, and highlights are excluded by the API.

## Redaction boundary

`app.policy.redact_for_llm()` removes Singapore/US-style IDs, phone numbers, and titled names before every DeepSeek request. The scribe endpoint stores a redacted provider-input record, never the outbound secret or prompt credentials. All seed data and demo inputs remain synthetic. Production would supplement this boundary with structured PII detectors, audit-safe logging, TLS, managed PostgreSQL encryption at rest, tenant isolation, and formal threat modelling.

## Warm-path latency

`GET /api/patients/{id}/glance` emits `Server-Timing: glance;dur=8` for the demo’s in-process query segment, below the 300 ms warm-path target. This is an approximation, not a production benchmark; a production measurement would use load testing against an authenticated warm connection pool and report P95 end-to-end latency.

## Project layout

```text
app/main.py        API, role and clinic enforcement
app/db.py          PostgreSQL schema and synthetic demo seed
app/policy.py      pure policy, redaction, and test model
frontend/          Next.js + TypeScript frontend, independently deployable to Vercel
tests/             required micro-tests
docs/TECHNICAL_BRIEF.md
```
