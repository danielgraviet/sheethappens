import logging

import redis
from fastapi import FastAPI
from pydantic import BaseModel

from app.adapter import AssignmentAdapter
from app.canvas_client import CanvasAuthError, CanvasAPIError, CanvasClient
from app.config import settings
from app.idempotency import IdempotencyService
from app.sheets_client import SheetsAPIError, SheetsAuthError, SheetsClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="SheetHappens", version="0.1.0")


class SyncResult(BaseModel):
    status: str
    total_fetched: int
    skipped_duplicates: int
    newly_inserted: int
    failures: int


@app.get("/health")
def health() -> dict:
    logger.info("Health check requested")
    return {"status": "ok", "service": "sheethappens"}


@app.get("/sync", response_model=SyncResult)
def sync() -> SyncResult:
    logger.info("Sync started.")

    # --- bootstrap clients ---
    try:
        canvas = CanvasClient()
        adapter = AssignmentAdapter()
        sheets = SheetsClient()
        redis_client = redis.from_url(settings.redis_url, decode_responses=True)
        idempotency = IdempotencyService(redis_client)
    except (SheetsAuthError, Exception) as exc:
        logger.error("Failed to initialise clients: %s", exc)
        return SyncResult(
            status="error",
            total_fetched=0,
            skipped_duplicates=0,
            newly_inserted=0,
            failures=1,
        )

    # --- fetch & adapt ---
    try:
        raw = canvas.fetch_upcoming_assignments()
    except (CanvasAuthError, CanvasAPIError) as exc:
        logger.error("Canvas fetch failed: %s", exc)
        return SyncResult(
            status="error",
            total_fetched=0,
            skipped_duplicates=0,
            newly_inserted=0,
            failures=1,
        )

    assignments = adapter.adapt_many(raw)
    total_fetched = len(assignments)
    logger.info("Fetched and adapted %d assignments.", total_fetched)

    # --- deduplicate, write, mark ---
    skipped = 0
    inserted = 0
    failures = 0

    for assignment in assignments:
        try:
            if idempotency.seen(assignment.assignment_id):
                skipped += 1
                continue

            sheets.append_rows([assignment])
            idempotency.mark_seen(assignment.assignment_id)
            inserted += 1

        except (SheetsAPIError, SheetsAuthError) as exc:
            logger.error("Failed to write assignment %s: %s", assignment.assignment_id, exc)
            failures += 1
        except Exception as exc:
            logger.error("Unexpected error for assignment %s: %s", assignment.assignment_id, exc)
            failures += 1

    logger.info(
        "Sync complete — fetched=%d skipped=%d inserted=%d failures=%d",
        total_fetched, skipped, inserted, failures,
    )

    return SyncResult(
        status="ok",
        total_fetched=total_fetched,
        skipped_duplicates=skipped,
        newly_inserted=inserted,
        failures=failures,
    )
