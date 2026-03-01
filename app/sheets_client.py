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
COLUMNS = ["assignment_id", "course_name", "assignment_name", "due_at", "url", "synced_at"]


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

        synced_at = datetime.now(timezone.utc).isoformat()
        rows = [self._to_row(a, synced_at) for a in assignments]

        if self._dry_run:
            logger.info(
                "[dry-run] Would append %d row(s) to %s:\n%s",
                len(rows),
                self._spreadsheet_id,
                rows,
            )
            return len(rows)

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

    @staticmethod
    def _to_row(assignment: Assignment, synced_at: str) -> list[str]:
        """Serialize an Assignment to a Sheets row following COLUMNS order."""
        return [
            assignment.assignment_id,
            assignment.course_name,
            assignment.assignment_name,
            assignment.due_at.isoformat() if assignment.due_at else "",
            assignment.url,
            synced_at,
        ]
