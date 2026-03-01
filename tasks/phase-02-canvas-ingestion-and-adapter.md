# Phase 02: Canvas Ingestion and Adapter

## Objective
Implement Canvas assignment retrieval and normalize Canvas payloads into the project’s internal assignment schema.

## Explanatory Section
Canvas responses are nested and platform-specific. This phase isolates Canvas complexity behind an adapter layer so downstream logic consumes a consistent model. This keeps the rest of the system decoupled from Canvas schema changes.

## Deliverables
- Canvas client module that:
  - Authenticates with `CANVAS_TOKEN`.
  - Requests upcoming assignments from `CANVAS_DOMAIN`.
  - Handles pagination and basic retry for transient failures.
- `AssignmentAdapter` that maps Canvas JSON to internal model fields.
- Filtering rules for "upcoming" assignments (time-based).
- Unit tests for adapter mapping with sample Canvas payloads.
- Error handling for:
  - token/auth errors
  - malformed Canvas response fields
  - network timeout behavior

## Design Choices and Tradeoffs
- **Choice:** Dedicated Canvas client class + adapter class.
  - **Why:** Clear separation between transport and transformation.
  - **Tradeoff:** More files/abstraction now, easier maintenance later.
- **Choice:** Keep adapter output strict and flat.
  - **Why:** Google Sheets writing and dedup logic become simpler.
  - **Tradeoff:** Some Canvas fields are intentionally dropped; less raw detail.
- **Choice:** Add retry for 5xx/timeouts only.
  - **Why:** Improves reliability without retrying invalid requests.
  - **Tradeoff:** Does not solve persistent upstream outages.

## Exit Criteria
- Canvas assignments can be fetched in local/dev environments.
- Adapter returns validated internal assignment objects.
- Adapter tests pass with edge-case payloads (missing due date, null fields, etc.).
