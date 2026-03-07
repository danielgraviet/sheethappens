# Phase 06: Multi-Tenant OAuth and Scalable Student Deployment Blueprint

## Objective
Evolve SheetHappens from a single-tenant cron sync service into a secure, multi-tenant platform where each student can connect Canvas + Google once and receive automatic, reliable assignment sync into their own Google Sheet at institutional scale.

## Why This Phase Exists
Current implementation is intentionally simple and single-tenant:
- One global Canvas token (`CANVAS_TOKEN`).
- One global Google credential (`GOOGLE_CREDS_JSON`) using service account auth.
- One global target sheet (`SPREADSHEET_ID`).
- Public `/sync` endpoint that runs full sync in request path.
- Idempotency keying based only on `assignment_id`.

To support thousands of students with low-friction onboarding, we need per-user identity, per-user OAuth credentials, per-user sheets, async job processing, tenant isolation, and stronger security/operations.

---

## Scope
This phase delivers architecture and implementation for:
- Multi-tenant account model.
- OAuth-based Google authorization per student.
- Canvas identity and access model suitable for broad campus rollout.
- One-click-ish onboarding flow (subject to institution consent policy).
- Async sync orchestration with queue workers.
- Rate limiting, retries, idempotency, and observability at scale.
- Deployment topology for reliable growth.

Out of scope for this phase:
- Advanced analytics dashboards.
- Billing/subscription features.
- Full admin portal UX polish.

---

## Product Constraints and UX Reality
"One click" depends on institutional setup:
- If institution admins pre-approve Canvas tool + Google OAuth app scopes, students can have near one-click onboarding.
- Without pre-approval, students must complete at least one consent prompt per provider.

Pragmatic target UX:
1. Student launches tool from Canvas (LTI).
2. Student taps "Connect Google".
3. Student picks Gmail account and consents.
4. App auto-creates/links Google Sheet and begins sync.

---

## Architecture Decision Summary

### 1) Canvas Integration Mode
Preferred: LTI 1.3 tool launch for identity bootstrapping.
- Reason: Better institutional fit, cleaner student launch path from Canvas, simpler roster/course context.
- Fallback: Canvas OAuth2 per student if LTI install is not possible.

### 2) Google Integration Mode
Use OAuth 2.0 authorization code flow per student.
- Request offline access (refresh token).
- Minimal scopes required for first version:
  - `openid`, `email`, `profile`
  - `https://www.googleapis.com/auth/spreadsheets`
  - `https://www.googleapis.com/auth/drive.file`

### 3) Processing Model
Move sync processing off request path.
- API handles auth/session/job creation.
- Workers execute Canvas fetch -> adapt -> write -> mark seen.
- Queue decouples spikes from user-facing latency.

### 4) Data Stores
- Postgres: source of truth for users, connections, sheets, jobs.
- Redis: cache, short-lived locks, distributed rate-limit counters.
- Optional object storage: audit exports or raw event archives.

### 5) Deployment Topology
- Web/API service (stateless).
- Worker service(s) for queue consumers.
- Managed Postgres + managed Redis.
- Scheduled orchestrator for periodic sync dispatch.

---

## Target System Design

### Components
1. API Service (FastAPI)
- Handles LTI/OAuth callbacks, session management, API endpoints.
- Issues and validates signed JWT sessions.
- Enqueues sync jobs.

2. Auth Service Module
- OAuth start/callback handlers.
- Token refresh logic and secure token storage.

3. Sync Worker
- Pulls user-specific jobs from queue.
- Fetches Canvas assignments for that user.
- Writes rows to that user’s target Google Sheet.
- Updates sync state and emits metrics/events.

4. Scheduler/Dispatcher
- Periodically finds active users needing sync.
- Enqueues per-user jobs with backpressure controls.

5. Data Layer
- Postgres for durable relational state.
- Redis for lock/rate/idempotency acceleration.

### High-Level Sequence
1. Student authenticates via Canvas launch (LTI) or Canvas OAuth.
2. Student connects Google account through OAuth.
3. App stores encrypted Google refresh token and creates/links sheet.
4. API enqueues initial sync job.
5. Worker executes sync with tenant-scoped idempotency.
6. Scheduler triggers subsequent periodic jobs.

---

## Data Model (Postgres)

### `users`
- `id` (uuid, pk)
- `email` (text, unique)
- `name` (text)
- `created_at`, `updated_at`
- `status` (`active`, `paused`, `deleted`)

### `canvas_accounts`
- `id` (uuid, pk)
- `user_id` (fk users)
- `canvas_user_id` (text)
- `canvas_domain` (text)
- `auth_mode` (`lti`, `oauth`)
- `oauth_access_token_encrypted` (nullable)
- `oauth_refresh_token_encrypted` (nullable)
- `oauth_token_expires_at` (nullable)
- `created_at`, `updated_at`
- unique `(canvas_domain, canvas_user_id)`

### `google_accounts`
- `id` (uuid, pk)
- `user_id` (fk users, unique)
- `google_sub` (text, unique)
- `email` (text)
- `access_token_encrypted` (nullable)
- `refresh_token_encrypted` (text)
- `token_expires_at` (timestamp)
- `scopes` (text[])
- `created_at`, `updated_at`

### `sheets`
- `id` (uuid, pk)
- `user_id` (fk users)
- `spreadsheet_id` (text)
- `sheet_name` (text default `Sheet1`)
- `is_primary` (bool)
- `created_at`, `updated_at`
- unique `(user_id, spreadsheet_id)`

### `sync_jobs`
- `id` (uuid, pk)
- `user_id` (fk users)
- `trigger_type` (`onboarding`, `manual`, `scheduled`, `retry`)
- `status` (`queued`, `running`, `succeeded`, `failed`, `dead_letter`)
- `days_window` (int)
- `attempt_count` (int)
- `scheduled_for` (timestamp)
- `started_at`, `finished_at`
- `error_code`, `error_message` (nullable)
- `created_at`, `updated_at`

### `sync_items` (idempotency ledger)
- `id` (uuid, pk)
- `user_id` (fk users)
- `assignment_id` (text)
- `first_synced_at` (timestamp)
- unique `(user_id, assignment_id)`

### `oauth_states`
- `id` (uuid, pk)
- `provider` (`google`, `canvas`)
- `state` (text, unique)
- `pkce_verifier` (nullable)
- `user_hint_id` (nullable)
- `expires_at` (timestamp)

---

## Security Model

### Secret and Token Handling
- Encrypt all refresh/access tokens at rest using envelope encryption.
- Use cloud KMS-managed key for data encryption keys.
- Never log token payloads.
- Rotate encryption keys and re-encrypt on schedule.

### API Security
- Protect manual sync endpoints with authenticated session/JWT.
- Use CSRF/state validation for OAuth callbacks.
- Validate LTI `id_token` signatures and nonce strictly.
- Add request rate limits per IP + per user.

### Tenant Isolation
- Every query/job path requires `user_id` scope.
- Idempotency keys include tenant scope (`user_id:assignment_id`).
- Prevent cross-tenant sheet writes by ownership checks before append.

### Compliance and Privacy
- Maintain least-privilege OAuth scopes.
- Add explicit disconnect/revoke path for Google and Canvas.
- Support account deletion with cascading token purge.

---

## API and Auth Endpoints

### Session and Status
- `GET /v1/me`
- `GET /v1/integrations/status`

### Google OAuth
- `GET /v1/auth/google/start`
- `GET /v1/auth/google/callback`
- `POST /v1/auth/google/disconnect`

### Canvas/LTI
- `POST /v1/auth/lti/launch`
- `POST /v1/auth/lti/callback` (if needed by platform flow)
- Optional Canvas OAuth fallback:
  - `GET /v1/auth/canvas/start`
  - `GET /v1/auth/canvas/callback`

### Sync
- `POST /v1/sync/run` (enqueue manual sync)
- `GET /v1/sync/jobs/:job_id`
- `POST /v1/sync/webhook/scheduler` (internal, signed)

---

## Queue and Worker Design

### Queue Choice
Use Redis-backed queue initially (RQ/Celery/Arq) for speed of implementation.
- Later migrate to managed queue (Cloud Tasks/SQS/PubSub) if needed.

### Job Payload
- `job_id`
- `user_id`
- `days_window`
- `trigger_type`
- `requested_at`

### Worker Execution Contract
1. Acquire per-user lock (`sync:lock:{user_id}` with TTL).
2. Load user integrations and refresh tokens if expired.
3. Fetch Canvas assignments (bounded pages + retries/backoff).
4. Adapt and validate rows.
5. Upsert idempotency ledger (`user_id`, `assignment_id`).
6. Batch append new rows to user sheet.
7. Commit job status + metrics.

### Retry Policy
- Retry transient errors with exponential backoff + jitter.
- No retry for invalid_grant / revoked consent until user reconnects.
- Dead-letter after max attempts and notify user/admin.

---

## Google Sheets Strategy per Student

### Preferred onboarding behavior
- On first Google connect:
  - Create a spreadsheet named `SheetHappens - <Term/Year>` OR
  - Allow student to choose existing sheet from picker.
- Store resulting `spreadsheet_id` under user account.
- Ensure headers are present once per sheet.

### Write strategy
- Append rows in batches (e.g., 100-500 rows/request).
- Use value input mode consistent with existing formula/hyperlink conventions.
- Include stable machine-readable `assignment_id` column for audit/debug.

---

## Canvas Access Strategy

### LTI-first model
- Institution installs external tool once.
- Student launch creates/links local user account.
- Use launch context (`sub`, course context, domain) for identity.

### API data retrieval
- For user-specific assignment pulls, use either:
  - LTI + service token exchange pattern supported by institution, or
  - User-authorized Canvas OAuth access token.

Implementation should support both behind interface abstraction:
- `CanvasCredentialProvider.get_access_token(user_id)`

---

## Observability and Operations

### Metrics (minimum)
- `sync_jobs_queued_total`
- `sync_jobs_succeeded_total`
- `sync_jobs_failed_total`
- `sync_job_duration_seconds`
- `oauth_connect_success_total` (by provider)
- `oauth_connect_failure_total` (by provider, reason)
- `sheets_rows_written_total`
- `canvas_api_errors_total` (status/reason)

### Logging
- Structured JSON logs.
- Correlation IDs on each request and job.
- Include `user_id`, `job_id`, `provider`, `status` fields.

### Alerting
- Error-rate threshold for failed sync jobs.
- Stalled queue depth threshold.
- Token refresh failure spike alerts.

### Runbooks to add
- OAuth outage triage.
- Token encryption key rotation.
- Queue backlog incident response.
- Tenant-specific replay procedure.

---

## Scaling Strategy

### Horizontal scaling
- Scale API pods independently from worker pods.
- Increase worker concurrency based on queue latency target.

### Backpressure controls
- Per-tenant sync cooldown windows.
- Global and provider-specific QPS caps.
- Batch scheduler dispatch instead of all-user fanout at once.

### Data scaling
- Indexes:
  - `sync_jobs (status, scheduled_for)`
  - `sync_items (user_id, assignment_id)` unique
  - `google_accounts (user_id)`
- Partition `sync_jobs` by time if job history grows quickly.

---

## Implementation Plan (Milestones)

### Milestone 1: Foundation and Schema
- Add SQL migration system and Postgres connection.
- Introduce new tables listed above.
- Build token encryption utility with KMS adapter.
- Add typed repository layer for user/integration/job data.

### Milestone 2: Auth and Onboarding
- Implement session auth and `/v1/me`.
- Implement Google OAuth start/callback/disconnect.
- Implement LTI launch handler and user provisioning.
- Create onboarding API returning integration readiness state.

### Milestone 3: Multi-Tenant Sync Engine
- Refactor sync logic to `sync_service.sync_user(user_id, days)`.
- Replace global settings-based clients with user-scoped providers.
- Update idempotency to tenant-scoped ledger.
- Keep old `/sync` as internal admin endpoint only (or remove).

### Milestone 4: Queue + Worker + Scheduler
- Add queue producer/consumer and worker runtime.
- Add periodic dispatcher for active users.
- Add retry/dead-letter behavior and lock handling.

### Milestone 5: Observability + Hardening
- Add metrics and structured logging.
- Add rate limits and abuse protections.
- Add integration tests for OAuth and worker flows.
- Add operational runbook updates.

### Milestone 6: Pilot and Rollout
- Pilot with a small institution or course section.
- Monitor token failures, queue lag, API limits.
- Tune retries/concurrency.
- Gradually expand cohorts.

---

## Code Refactor Map (Current -> Target)

### `app/config.py`
Current: single-tenant required env vars.
Target: platform-level config only (DB URL, Redis URL, OAuth client IDs/secrets, KMS key ref, app base URL).

### `app/main.py`
Current: direct sync orchestration in route.
Target: route layer only; delegate to auth/sync/job modules.

### `app/canvas_client.py`
Current: global bearer token from env.
Target: injectable `access_token` per user; credential provider abstraction.

### `app/sheets_client.py`
Current: service account + one spreadsheet ID.
Target: OAuth credential object per user and per-user spreadsheet ID.

### `app/idempotency.py`
Current: Redis key on assignment only.
Target: durable `(user_id, assignment_id)` ledger in Postgres plus optional Redis cache.

---

## Required Configuration Changes

### New environment variables
- `DATABASE_URL`
- `REDIS_URL`
- `APP_BASE_URL`
- `SESSION_SIGNING_KEY`
- `GOOGLE_OAUTH_CLIENT_ID`
- `GOOGLE_OAUTH_CLIENT_SECRET`
- `GOOGLE_OAUTH_REDIRECT_URI`
- `CANVAS_LTI_JWKS_URL` (or per-institution mapping)
- `CANVAS_LTI_ISSUER`
- `CANVAS_LTI_CLIENT_ID`
- `KMS_KEY_ID` (or equivalent)

### Variables to deprecate
- `CANVAS_TOKEN`
- `SPREADSHEET_ID`
- `GOOGLE_CREDS_JSON`

---

## Testing Plan

### Unit tests
- OAuth state validation, callback parsing, token refresh behavior.
- Tenant-scoped idempotency and dedup correctness.
- Retry classifier (transient vs permanent failures).

### Integration tests
- Google OAuth happy path and reconnect path.
- LTI launch -> onboarding state -> sync enqueue.
- Worker sync success and partial failure handling.

### Load tests
- Simulate N concurrent student sync jobs.
- Validate queue latency and provider rate-limit behavior.

### Security tests
- Callback CSRF/state mismatch rejection.
- Cross-tenant access attempts.
- Token redaction verification in logs.

---

## Rollback Plan
- Keep legacy sync endpoint behind feature flag during migration.
- Enable new multi-tenant flow for pilot users only.
- If incident occurs, disable scheduler and worker consumption while preserving queued jobs.
- Re-enable legacy path temporarily for critical users if needed.

---

## Deliverables Checklist
- [ ] New DB schema and migrations.
- [ ] OAuth + LTI auth modules.
- [ ] Multi-tenant sync service and queue workers.
- [ ] Scheduler and retry/dead-letter handling.
- [ ] Updated deployment topology and env config.
- [ ] Updated runbook and incident procedures.
- [ ] Pilot rollout report with scale-readiness recommendations.

---

## Exit Criteria
- Students can onboard and sync using their own accounts end-to-end.
- System supports at least pilot-scale concurrent usage with acceptable latency.
- No cross-tenant data leakage in tests and audits.
- Failed jobs are observable, retryable, and operationally manageable.
- Legacy single-tenant credentials are fully removed from production path.
