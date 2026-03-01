import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.canvas import (
    AssignmentAdapter,
    CanvasAPIError,
    CanvasAuthError,
    CanvasClient,
    CanvasMalformedResponseError,
    CanvasTimeoutError,
)
from app.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="SheetHappens", version="0.1.0")


@app.get("/health")
def health() -> dict:
    logger.info("Health check requested")
    return {"status": "ok", "service": "sheethappens"}


@app.get("/sync")
def sync() -> JSONResponse:
    logger.info("Sync requested")
    try:
        with CanvasClient(
            domain=settings.canvas_domain,
            token=settings.canvas_token,
        ) as canvas_client:
            upcoming_rows = canvas_client.fetch_upcoming_assignments()
    except CanvasAuthError as exc:
        logger.exception("Canvas auth error during sync")
        return JSONResponse(status_code=401, content={"status": "error", "message": str(exc)})
    except CanvasTimeoutError as exc:
        logger.exception("Canvas timeout during sync")
        return JSONResponse(status_code=504, content={"status": "error", "message": str(exc)})
    except (CanvasMalformedResponseError, CanvasAPIError) as exc:
        logger.exception("Canvas API error during sync")
        return JSONResponse(status_code=502, content={"status": "error", "message": str(exc)})

    assignments = [AssignmentAdapter.adapt(row) for row in upcoming_rows]
    return JSONResponse(
        status_code=200,
        content={
            "status": "ok",
            "fetched": len(upcoming_rows),
            "assignments": [assignment.model_dump(mode="json") for assignment in assignments],
        },
    )
