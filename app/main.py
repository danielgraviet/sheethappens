import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse

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
    logger.info("Sync requested (stub)")
    return JSONResponse(
        status_code=501,
        content={
            "status": "not_implemented",
            "message": "Sync is not yet implemented.",
        },
    )
