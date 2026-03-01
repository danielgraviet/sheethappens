# Phase 01: Foundation and Contracts

## Objective
Establish the project skeleton, shared data contracts, and local development workflow so all later integration work is built on stable interfaces.

## Explanatory Section
This phase defines the "shape" of the system before external API calls are implemented. The goal is to reduce integration churn by locking core interfaces early:
- API surface (`/health`, `/sync` placeholder).
- Internal assignment schema used across adapters and loaders.
- Config loading for all required environment variables.

By doing this first, later phases can focus on behavior instead of reworking structure.

## Deliverables
- FastAPI app bootstrapped with:
  - `GET /health` returning service status.
  - `GET /sync` stub returning a not-implemented response.
- Configuration module that validates:
  - `CANVAS_TOKEN`
  - `CANVAS_DOMAIN`
  - `SPREADSHEET_ID`
  - `REDIS_URL`
  - `GOOGLE_CREDS_JSON`
- Typed internal assignment model (e.g., dataclass or Pydantic model) covering:
  - `assignment_id` (string)
  - `course_name`
  - `assignment_name`
  - `due_at`
  - `url`
- Basic logging setup and error response format.
- Minimal project docs:
  - local run instructions
  - environment variable setup

## Design Choices and Tradeoffs
- **Choice:** Use Pydantic models for internal contracts.
  - **Why:** Tight validation and clear error messages.
  - **Tradeoff:** Slight overhead vs plain dicts, but fewer downstream data bugs.
- **Choice:** Centralized config validation at startup.
  - **Why:** Fail fast when env vars are missing.
  - **Tradeoff:** App refuses to start on partial config, which is strict but safer.
- **Choice:** `/sync` exists early as a stub.
  - **Why:** Locks endpoint contract for CRON and tests.
  - **Tradeoff:** Early endpoint does little, but prevents interface drift later.

## Exit Criteria
- Service starts cleanly with valid environment variables.
- `/health` returns success.
- `/sync` route exists and returns a structured placeholder response.
- Assignment contract is defined and importable by future modules.
