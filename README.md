# SheetHappens

Lightweight Canvas-to-Google-Sheets automation service.

## Prerequisites

- `uv` installed
- Python `3.13` (managed via `.python-version`)

## Quickstart (uv)

```bash
# create/update virtualenv and install dependencies from pyproject.toml
uv sync

# run the FastAPI service (with reload)
uv run python main.py
# or directly with uvicorn
uv run uvicorn app.main:app --reload
```

## Environment Variables

Create `.env` and set:

- `CANVAS_TOKEN`
- `CANVAS_DOMAIN`
- `SPREADSHEET_ID`
- `REDIS_URL`
- `GOOGLE_CREDS_JSON`

## Dependency Management (uv)

```bash
# add packages
uv add fastapi uvicorn redis httpx google-api-python-client google-auth

# remove a package
uv remove <package>
```

## Project Goal

The service will:

1. Fetch upcoming assignments from Canvas.
2. Normalize payloads through an adapter layer.
3. Deduplicate by `assignment_id` using Upstash Redis.
4. Append new rows to Google Sheets.
5. Run automatically on a Railway CRON schedule.
