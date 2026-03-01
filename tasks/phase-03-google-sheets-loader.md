# Phase 03: Google Sheets Loader

## Objective
Write normalized assignments into Google Sheets reliably using a stable append contract.

## Explanatory Section
Once data is standardized, the next step is loading records into Sheets. This phase focuses on authentication, row formatting, and write behavior to ensure assignments appear consistently and are readable.

## Deliverables
- Google auth setup using `GOOGLE_CREDS_JSON` service account credentials.
- Sheets client module for appending assignment rows to `SPREADSHEET_ID`.
- Defined column ordering (for example):
  - `assignment_id`
  - `course_name`
  - `assignment_name`
  - `due_at`
  - `url`
  - `synced_at`
- Row serialization function from internal model to Sheets row array.
- Integration test or dry-run mode to validate row write behavior.

## Design Choices and Tradeoffs
- **Choice:** Use append-only writes.
  - **Why:** Simple and durable ingestion model.
  - **Tradeoff:** Requires external dedup guard (handled in next phase).
- **Choice:** Include `synced_at` timestamp in row.
  - **Why:** Useful for audits and troubleshooting.
  - **Tradeoff:** Adds one more column to maintain.
- **Choice:** Keep sheet schema fixed and explicit.
  - **Why:** Predictable analytics/reporting.
  - **Tradeoff:** Schema changes require coordinated code updates.

## Exit Criteria
- Service can authenticate and append rows to the target spreadsheet.
- Written rows match the defined column contract.
- Write failures return actionable errors without crashing the service process.
