import json
import logging
from datetime import datetime, timezone
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import settings
from app.models import Assignment

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_RANGE = "Sheet1!A1"

# Column contract — order must stay stable.
COLUMNS = ["course_name", "assignment_name", "due_at", "url", "assignment_id", "synced_at"]
HEADERS = ["Course", "Assignment", "Due Date", "Link", "Assignment ID", "Synced At"]


class SheetsAuthError(Exception):
    pass


class SheetsAPIError(Exception):
    pass


class SheetsClient:
    def __init__(self, dry_run: bool = False) -> None:
        self._spreadsheet_id = settings.spreadsheet_id
        self._dry_run = dry_run
        self._service = self._build_service()

    def _build_service(self) -> Any:
        try:
            creds_value = settings.google_creds_json.strip()
            # Accept either a file path (e.g. "secret.json") or raw JSON string.
            if creds_value.endswith(".json") and not creds_value.startswith("{"):
                with open(creds_value) as f:
                    creds_dict = json.load(f)
            else:
                creds_dict = json.loads(creds_value)
        except (json.JSONDecodeError, ValueError) as exc:
            raise SheetsAuthError(
                f"GOOGLE_CREDS_JSON is not valid JSON: {exc}"
            ) from exc
        except OSError as exc:
            raise SheetsAuthError(
                f"Could not read credentials file: {exc}"
            ) from exc

        try:
            credentials = service_account.Credentials.from_service_account_info(
                creds_dict, scopes=SCOPES
            )
            return build("sheets", "v4", credentials=credentials)
        except Exception as exc:
            raise SheetsAuthError(
                f"Failed to build Google Sheets service: {exc}"
            ) from exc

    def append_rows(self, assignments: list[Assignment]) -> int:
        """Append assignments as rows. Returns the number of rows written."""
        if not assignments:
            logger.info("No assignments to write.")
            return 0

        synced_at = datetime.now(timezone.utc)
        rows = [self._to_row(a, synced_at) for a in assignments]

        if self._dry_run:
            logger.info(
                "[dry-run] Would append %d row(s) to %s:\n%s",
                len(rows),
                self._spreadsheet_id,
                rows,
            )
            return len(rows)

        self._ensure_headers()

        try:
            self._service.spreadsheets().values().append(
                spreadsheetId=self._spreadsheet_id,
                range=SHEET_RANGE,
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body={"values": rows},
            ).execute()
        except HttpError as exc:
            raise SheetsAPIError(
                f"Google Sheets API error ({exc.status_code}): {exc.reason}"
            ) from exc
        except Exception as exc:
            raise SheetsAPIError(f"Unexpected Sheets error: {exc}") from exc

        logger.info("Appended %d row(s) to spreadsheet %s.", len(rows), self._spreadsheet_id)
        return len(rows)

    def _ensure_headers(self) -> None:
        """Write the header row to A1 if the sheet is empty."""
        try:
            result = self._service.spreadsheets().values().get(
                spreadsheetId=self._spreadsheet_id,
                range="Sheet1!A1:F1",
            ).execute()
            if result.get("values"):
                return
            self._service.spreadsheets().values().update(
                spreadsheetId=self._spreadsheet_id,
                range="Sheet1!A1",
                valueInputOption="USER_ENTERED",
                body={"values": [HEADERS]},
            ).execute()
            logger.info("Wrote header row to spreadsheet.")
        except HttpError as exc:
            raise SheetsAPIError(f"Failed to write headers: {exc}") from exc

    def _to_row(self, assignment: Assignment, synced_at: datetime) -> list[str]:
        """Serialize an Assignment to a Sheets row following COLUMNS order."""
        # Human-readable due date
        if assignment.due_at:
            dt = assignment.due_at
            due_str = f"{dt.strftime('%b')} {dt.day}, {dt.year} {dt.strftime('%-I:%M %p')} UTC"
        else:
            due_str = ""

        # Full, clickable URL
        url = assignment.url
        if url and url.startswith("/"):
            domain = settings.canvas_domain.rstrip("/")
            if not domain.startswith("http"):
                domain = f"https://{domain}"
            url = f"{domain}{url}"
        link = f'=HYPERLINK("{url}", "Open →")' if url else ""

        # Human-readable synced timestamp
        synced_str = (
            f"{synced_at.strftime('%b')} {synced_at.day}, {synced_at.year} "
            f"{synced_at.strftime('%-I:%M %p')} UTC"
        )

        return [
            assignment.course_name,
            assignment.assignment_name,
            due_str,
            link,
            assignment.assignment_id,
            synced_str,
        ]
