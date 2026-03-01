# Phase 05: Deployment, CRON, and Operations

## Objective
Deploy the service to Railway, automate sync cadence, and add operational safeguards.

## Explanatory Section
After core functionality is complete, production readiness depends on stable deployment and observability. This phase configures Railway runtime, scheduled triggering, and operational checks so the pipeline runs unattended every 6 hours.

## Deliverables
- Railway deployment configuration:
  - build/start commands
  - environment variables configured in Railway
- CRON job setup to hit `GET /sync` every 6 hours.
- Operational logging standards:
  - request-level logs for `/sync`
  - sync summary logs (fetched/skipped/inserted/errors)
- Alerting baseline (at minimum):
  - failed sync detection
  - repeated upstream API failures
- Runbook document for:
  - rotating Canvas token / Google credentials
  - recovering from Redis or Sheets outages
  - validating service health

## Design Choices and Tradeoffs
- **Choice:** Use Railway CRON calling HTTP endpoint.
  - **Why:** Keeps scheduling external to app process; simple architecture.
  - **Tradeoff:** Depends on endpoint availability and network path.
- **Choice:** Centralized env-var management in Railway.
  - **Why:** Cleaner secrets handling than local file-based secrets in production.
  - **Tradeoff:** More manual setup steps in the deployment platform.
- **Choice:** Start with lightweight alerting.
  - **Why:** Fast to implement and enough for MVP reliability.
  - **Tradeoff:** Less granular diagnostics than full monitoring stack.

## Exit Criteria
- Service is reachable in Railway and `/health` is green.
- CRON runs every 6 hours and successfully triggers sync.
- At least one full unattended sync cycle succeeds and logs expected metrics.
- Runbook exists and is usable for common operational incidents.
