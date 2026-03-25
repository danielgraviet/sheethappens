import logging
import time
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

import redis
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.adapter import AssignmentAdapter
from app.auth_router import router as auth_router
from app.canvas_client import CanvasAuthError, CanvasAPIError, CanvasClient
from app.config import settings
from app.database import close_pool
from app.idempotency import IdempotencyService
from app.ls_adapter import LearningSuiteAdapter
from app.multi_sync import sync_canvas, sync_learning_suite
from app.sheets_client import SheetsAPIError, SheetsAuthError, SheetsClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN001
    yield
    await close_pool()


app = FastAPI(title="OhSheet", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://learningsuite.byu.edu",
        "https://byu.instructure.com",
        settings.app_base_url,
    ],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
    allow_credentials=True,
)

app.include_router(auth_router)


# ── Setup page ────────────────────────────────────────────────────────────────

_STATIC = Path(__file__).parent / "static"


@app.get("/", response_class=FileResponse)
def root() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


@app.get("/setup", response_class=FileResponse)
def setup_page() -> FileResponse:
    return FileResponse(_STATIC / "setup.html")


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "ohsheet"}


# ── Multi-tenant sync endpoints ───────────────────────────────────────────────

class SyncResult(BaseModel):
    status: str
    total_fetched: int
    skipped_duplicates: int
    newly_inserted: int
    failures: int


@app.get("/api/sync/canvas", response_model=SyncResult)
async def api_sync_canvas(
    token: str = Query(..., description="Your OhSheet sync token"),
    days: int = Query(default=30, ge=1, le=365),
) -> SyncResult:
    result = await sync_canvas(token, days)
    return SyncResult(**result)


class MultiLSSyncRequest(BaseModel):
    token: str
    courses: list[dict]
    page_url: str = ""


class LSSyncResult(BaseModel):
    status: str
    synced: int
    skipped: int
    failures: int


@app.post("/api/sync/learning-suite", response_model=LSSyncResult)
async def api_sync_ls(payload: MultiLSSyncRequest) -> LSSyncResult:
    result = await sync_learning_suite(payload.token, payload.courses, payload.page_url)
    return LSSyncResult(**result)


# ── Legacy single-tenant endpoints (CRON / backward compat) ──────────────────

def _days_until_end_of_week() -> int:
    today = date.today()
    days_left = 6 - today.weekday()
    return max(days_left, 1)


@app.get("/format")
def format_sheet() -> dict:
    if not settings.google_creds_json or not settings.spreadsheet_id:
        return {"status": "error", "message": "Single-tenant credentials not configured."}
    try:
        sheets = SheetsClient()
        sheets.reapply_formatting()
        return {"status": "ok", "message": "Formatting reapplied successfully."}
    except (SheetsAuthError, SheetsAPIError) as exc:
        logger.error("Failed to reapply formatting: %s", exc)
        return {"status": "error", "message": str(exc)}


@app.get("/sync", response_model=SyncResult)
def sync(
    days: int = Query(default=None, ge=1, le=365),
) -> SyncResult:
    if not settings.canvas_token or not settings.google_creds_json:
        return SyncResult(status="error", total_fetched=0, skipped_duplicates=0,
                          newly_inserted=0, failures=1)
    if days is None:
        days = _days_until_end_of_week()
    started_at = time.monotonic()
    logger.info("Legacy sync started (window: %d days).", days)

    try:
        canvas = CanvasClient()
        adapter = AssignmentAdapter()
        sheets = SheetsClient()
        redis_client = redis.from_url(settings.redis_url, decode_responses=True)
        idempotency = IdempotencyService(redis_client)
    except Exception as exc:
        logger.error("ALERT: Failed to initialise clients: %s", exc)
        return SyncResult(status="error", total_fetched=0, skipped_duplicates=0,
                          newly_inserted=0, failures=1)

    try:
        raw = canvas.fetch_upcoming_assignments(days=days)
    except CanvasAuthError as exc:
        logger.error("ALERT: Canvas auth failure: %s", exc)
        return SyncResult(status="error", total_fetched=0, skipped_duplicates=0,
                          newly_inserted=0, failures=1)
    except CanvasAPIError as exc:
        logger.error("ALERT: Canvas API unreachable: %s", exc)
        return SyncResult(status="error", total_fetched=0, skipped_duplicates=0,
                          newly_inserted=0, failures=1)

    assignments = adapter.adapt_many(raw)
    total_fetched = len(assignments)
    skipped = inserted = failures = 0

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
            logger.error("Unexpected error for %s: %s", assignment.assignment_id, exc)
            failures += 1

    elapsed = time.monotonic() - started_at
    logger.info(
        "Legacy sync complete in %.2fs — fetched=%d skipped=%d inserted=%d failures=%d",
        elapsed, total_fetched, skipped, inserted, failures,
    )
    return SyncResult(status="ok", total_fetched=total_fetched, skipped_duplicates=skipped,
                      newly_inserted=inserted, failures=failures)


class LearningSuiteSyncRequest(BaseModel):
    courses: list[dict]
    page_url: str = ""


class LearningSuiteSyncResult(BaseModel):
    status: str
    synced: int
    skipped: int
    failures: int


@app.post("/sync/learning-suite", response_model=LearningSuiteSyncResult)
def sync_learning_suite_legacy(payload: LearningSuiteSyncRequest) -> LearningSuiteSyncResult:
    """Legacy single-tenant LS sync (no token required — uses global sheet)."""
    if not settings.google_creds_json:
        return LearningSuiteSyncResult(status="error", synced=0, skipped=0, failures=1)

    logger.info("Legacy LS sync started (%d course(s)).", len(payload.courses))

    try:
        sheets = SheetsClient()
        redis_client = redis.from_url(settings.redis_url, decode_responses=True)
        idempotency = IdempotencyService(redis_client)
    except Exception as exc:
        logger.error("Failed to initialise clients for LS sync: %s", exc)
        return LearningSuiteSyncResult(status="error", synced=0, skipped=0, failures=1)

    assignments = LearningSuiteAdapter().adapt_many(payload.courses, page_url=payload.page_url)
    synced = skipped = failures = 0

    for assignment in assignments:
        try:
            if idempotency.seen(assignment.assignment_id):
                skipped += 1
                continue
            sheets.append_rows([assignment])
            idempotency.mark_seen(assignment.assignment_id)
            synced += 1
        except (SheetsAPIError, SheetsAuthError) as exc:
            logger.error("Failed to write LS assignment %s: %s", assignment.assignment_id, exc)
            failures += 1
        except Exception as exc:
            logger.error("Unexpected error for LS assignment %s: %s", assignment.assignment_id, exc)
            failures += 1

    logger.info("Legacy LS sync complete — synced=%d skipped=%d failures=%d", synced, skipped, failures)
    return LearningSuiteSyncResult(status="ok", synced=synced, skipped=skipped, failures=failures)
