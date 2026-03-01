# Phase 04: Idempotent Sync Orchestration

## Objective
Connect fetch, adapt, deduplicate, and load steps behind `/sync` with Redis-backed idempotency.

## Explanatory Section
This phase builds the core automation logic. It prevents duplicate rows by checking each `assignment_id` in Upstash Redis before writing to Sheets. Successful writes are then recorded in Redis so reruns remain safe.

## Deliverables
- Upstash Redis integration using `REDIS_URL`.
- Idempotency service with operations:
  - `seen(assignment_id) -> bool`
  - `mark_seen(assignment_id)`
- `/sync` endpoint fully implemented:
  - fetch from Canvas
  - adapt to internal model
  - deduplicate via Redis
  - append new rows to Sheets
  - mark synced IDs in Redis
- Structured sync result response:
  - total fetched
  - skipped duplicates
  - newly inserted
  - failures
- Tests for:
  - duplicate prevention
  - partial failure handling
  - rerun safety

## Design Choices and Tradeoffs
- **Choice:** Dedup key is only `assignment_id`.
  - **Why:** Matches source-of-truth uniqueness in overview architecture.
  - **Tradeoff:** Assignment edits are not treated as new records unless update logic is added later.
- **Choice:** Mark Redis only after successful Sheets write.
  - **Why:** Avoid false positives that could drop data.
  - **Tradeoff:** Slightly more complex error handling path.
- **Choice:** Endpoint returns sync stats.
  - **Why:** Easier monitoring and debugging.
  - **Tradeoff:** Slight increase in response payload complexity.

## Exit Criteria
- Repeated `/sync` calls do not create duplicate rows.
- New assignments are inserted and marked in Redis.
- Failures are surfaced with useful logs and sync response counts.
