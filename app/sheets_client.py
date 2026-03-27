import json
import logging
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import settings
from app.models import Assignment

OAUTH_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_RANGE = "Sheet1!A1"

# Column A is a checkbox (Done); data columns start at B.
COLUMNS = ["done", "course_name", "assignment_name", "due_at", "days_left", "url", "source"]
HEADERS = ["Done", "Course", "Assignment", "Due Date", "Days Left", "Link", "Source"]

# Last synced timestamp is written here — outside the data table
_LAST_SYNCED_CELL = "Sheet1!H1"

# Column indices (0-based)
_DUE_DATE_COL_INDEX = 3
_DAYS_LEFT_COL_INDEX = 4

# Palette of pastel colors for dynamic course coloring (RGB 0-1 scale)
_COLOR_PALETTE = [
    {"red": 0.68, "green": 0.85, "blue": 0.95},  # sky blue
    {"red": 0.71, "green": 0.90, "blue": 0.72},  # mint green
    {"red": 0.99, "green": 0.88, "blue": 0.68},  # warm amber
    {"red": 0.85, "green": 0.73, "blue": 0.95},  # lavender
    {"red": 0.99, "green": 0.75, "blue": 0.80},  # rose
    {"red": 0.68, "green": 0.93, "blue": 0.93},  # aqua
    {"red": 0.98, "green": 0.93, "blue": 0.68},  # pale yellow
    {"red": 0.80, "green": 0.90, "blue": 0.78},  # sage
]


def _color_for_course(name: str) -> dict:
    """Deterministically pick a palette color from the course name."""
    return _COLOR_PALETTE[hash(name) % len(_COLOR_PALETTE)]


class SheetsAuthError(Exception):
    pass


class SheetsAPIError(Exception):
    pass


class SheetsClient:
    def __init__(self, dry_run: bool = False) -> None:
        self._spreadsheet_id = settings.spreadsheet_id
        self._dry_run = dry_run
        self._canvas_domain = settings.canvas_domain
        self._service = self._build_service()

    def _build_service(self) -> Any:
        try:
            creds_value = settings.google_creds_json.strip()
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
        rows = [self._to_row(a) for a in assignments]

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
            # Use column B (Course) to find the last row with data — column A is
            # always an empty checkbox, so it can't be used for table detection.
            col_b = self._service.spreadsheets().values().get(
                spreadsheetId=self._spreadsheet_id,
                range="Sheet1!B:B",
            ).execute()
            next_row = len(col_b.get("values", [])) + 1

            self._service.spreadsheets().values().update(
                spreadsheetId=self._spreadsheet_id,
                range=f"Sheet1!A{next_row}",
                valueInputOption="USER_ENTERED",
                body={"values": rows},
            ).execute()
        except HttpError as exc:
            raise SheetsAPIError(
                f"Google Sheets API error ({exc.status_code}): {exc.reason}"
            ) from exc
        except Exception as exc:
            raise SheetsAPIError(f"Unexpected Sheets error: {exc}") from exc

        # Update the single "Last synced" timestamp in G1
        synced_label = (
            f"Last synced: {synced_at.strftime('%b')} {synced_at.day}, "
            f"{synced_at.year} {synced_at.strftime('%-I:%M %p')} UTC"
        )
        try:
            self._service.spreadsheets().values().update(
                spreadsheetId=self._spreadsheet_id,
                range=_LAST_SYNCED_CELL,
                valueInputOption="RAW",
                body={"values": [[synced_label]]},
            ).execute()
        except HttpError:
            pass  # non-fatal

        logger.info("Appended %d row(s) to spreadsheet %s.", len(rows), self._spreadsheet_id)

        # Ensure every course in this batch has a color rule
        unique_courses = list({a.course_name for a in assignments})
        self._update_course_colors(unique_courses)

        return len(rows)

    def _ensure_headers(self) -> None:
        """Write the header row to A1 if the sheet is empty, then apply formatting."""
        try:
            last_col = chr(ord("A") + len(HEADERS) - 1)
            result = self._service.spreadsheets().values().get(
                spreadsheetId=self._spreadsheet_id,
                range=f"Sheet1!A1:{last_col}1",
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
            self._apply_formatting()
        except HttpError as exc:
            raise SheetsAPIError(f"Failed to write headers: {exc}") from exc

    def _get_sheet_id(self) -> int:
        """Return the numeric sheetId for Sheet1 (needed for batchUpdate requests)."""
        result = self._service.spreadsheets().get(
            spreadsheetId=self._spreadsheet_id,
            fields="sheets.properties",
        ).execute()
        for sheet in result.get("sheets", []):
            props = sheet.get("properties", {})
            if props.get("title") == "Sheet1":
                return props["sheetId"]
        return 0  # fallback: first sheet is always 0

    def reapply_formatting(self) -> None:
        """Clear all conditional format rules on Sheet1 then reapply full formatting."""
        sheet_id = self._get_sheet_id()

        # Fetch existing conditional format rules so we can delete them first
        result = self._service.spreadsheets().get(
            spreadsheetId=self._spreadsheet_id,
            fields="sheets.conditionalFormats,sheets.properties",
        ).execute()

        delete_requests: list[dict] = []
        for sheet in result.get("sheets", []):
            if sheet.get("properties", {}).get("sheetId") == sheet_id:
                rules = sheet.get("conditionalFormats", [])
                # Delete in reverse order so indices stay valid
                for i in range(len(rules) - 1, -1, -1):
                    delete_requests.append({
                        "deleteConditionalFormatRule": {
                            "sheetId": sheet_id,
                            "index": i,
                        }
                    })

        if delete_requests:
            self._service.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={"requests": delete_requests},
            ).execute()

        self._apply_formatting()

        # Recolor all courses currently in the sheet
        col_b = self._service.spreadsheets().values().get(
            spreadsheetId=self._spreadsheet_id,
            range="Sheet1!B2:B",
        ).execute()
        courses = list({
            row[0] for row in col_b.get("values", [])
            if row and row[0] and row[0] != "Course"
        })
        self._update_course_colors(courses)

    def _apply_formatting(self) -> None:
        """
        Apply one-time formatting after headers are written:
        - Bold/large/dark header row, frozen
        - Checkbox data validation on column A
        - Conditional format: strikethrough + grey when Done is checked
        - Conditional format: row color per course name
        """
        sheet_id = self._get_sheet_id()
        num_cols = len(HEADERS)

        data_range = {
            "sheetId": sheet_id,
            "startRowIndex": 1,
            "endRowIndex": 100,
            "startColumnIndex": 0,
            "endColumnIndex": num_cols,
        }

        requests: list[dict] = [
            # Style the header row: dark bg, white bold text, centered, larger font
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": 1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {"red": 0.15, "green": 0.15, "blue": 0.15},
                            "textFormat": {
                                "bold": True,
                                "fontSize": 12,
                                "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                            },
                            "horizontalAlignment": "CENTER",
                            "verticalAlignment": "MIDDLE",
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)",
                }
            },
            # Freeze the header row
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": sheet_id,
                        "gridProperties": {"frozenRowCount": 1},
                    },
                    "fields": "gridProperties.frozenRowCount",
                }
            },
            # Checkbox data validation for column A (rows 2-1000)
            {
                "setDataValidation": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "endRowIndex": 100,
                        "startColumnIndex": 0,
                        "endColumnIndex": 1,
                    },
                    "rule": {
                        "condition": {"type": "BOOLEAN"},
                        "strict": True,
                    },
                }
            },
            # Date number format for Due Date column (col D) — shows calendar picker on click
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "endRowIndex": 100,
                        "startColumnIndex": _DUE_DATE_COL_INDEX,
                        "endColumnIndex": _DUE_DATE_COL_INDEX + 1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "numberFormat": {"type": "DATE", "pattern": "mmm d, yyyy"},
                        }
                    },
                    "fields": "userEnteredFormat.numberFormat",
                }
            },
            # Date data validation for Due Date column — enforces calendar picker
            {
                "setDataValidation": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "endRowIndex": 100,
                        "startColumnIndex": _DUE_DATE_COL_INDEX,
                        "endColumnIndex": _DUE_DATE_COL_INDEX + 1,
                    },
                    "rule": {
                        "condition": {"type": "DATE_IS_VALID"},
                        "strict": False,
                        "showCustomUi": True,
                    },
                }
            },
        ]

        # Number format for Days Left column (col E) — plain integer, not a date
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 1,
                    "endRowIndex": 100,
                    "startColumnIndex": _DAYS_LEFT_COL_INDEX,
                    "endColumnIndex": _DAYS_LEFT_COL_INDEX + 1,
                },
                "cell": {
                    "userEnteredFormat": {
                        "numberFormat": {"type": "NUMBER", "pattern": "0"},
                        "horizontalAlignment": "CENTER",
                    }
                },
                "fields": "userEnteredFormat(numberFormat,horizontalAlignment)",
            }
        })

        # Days Left color rules — applied only to col E, highest priority first
        days_left_range = {
            "sheetId": sheet_id,
            "startRowIndex": 1,
            "endRowIndex": 100,
            "startColumnIndex": _DAYS_LEFT_COL_INDEX,
            "endColumnIndex": _DAYS_LEFT_COL_INDEX + 1,
        }
        urgency_rules = [
            # Overdue or due today — deep red
            ('=AND($E2<>"",$E2<=0)',  {"red": 0.90, "green": 0.18, "blue": 0.18}),
            # 1–2 days — red-orange
            ('=AND($E2<>"",$E2<=2)',  {"red": 0.96, "green": 0.42, "blue": 0.26}),
            # 3–5 days — amber
            ('=AND($E2<>"",$E2<=5)',  {"red": 0.98, "green": 0.75, "blue": 0.18}),
            # 6+ days — green
            ('=AND($E2<>"",$E2>5)',   {"red": 0.42, "green": 0.78, "blue": 0.42}),
        ]
        # Urgency rules on col E only — insert in reverse so highest priority ends up at index 0
        for formula, color in reversed(urgency_rules):
            requests.append({
                "addConditionalFormatRule": {
                    "rule": {
                        "ranges": [days_left_range],
                        "booleanRule": {
                            "condition": {
                                "type": "CUSTOM_FORMULA",
                                "values": [{"userEnteredValue": formula}],
                            },
                            "format": {"backgroundColor": color},
                        },
                    },
                    "index": 0,
                }
            })

        # Strikethrough rule — added LAST so it inserts at index 0 = highest priority.
        # Uses =$A2 (truthy check) which reliably matches Sheets boolean checkbox values.
        requests.append({
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [data_range],
                    "booleanRule": {
                        "condition": {
                            "type": "CUSTOM_FORMULA",
                            "values": [{"userEnteredValue": "=$A2"}],
                        },
                        "format": {
                            "textFormat": {
                                "strikethrough": True,
                                "foregroundColor": {"red": 0.6, "green": 0.6, "blue": 0.6},
                            },
                            "backgroundColor": {"red": 0.92, "green": 0.92, "blue": 0.92},
                        },
                    },
                },
                "index": 0,
            }
        })

        try:
            self._service.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={"requests": requests},
            ).execute()
            logger.info("Applied sheet formatting (headers, checkboxes, conditional formats).")
        except HttpError as exc:
            # Non-fatal: formatting is cosmetic, log and continue
            logger.warning("Failed to apply sheet formatting: %s", exc)

    def _update_course_colors(self, courses: list[str]) -> None:
        """Add conditional format rules for any courses not yet colored."""
        if not courses:
            return

        sheet_id = self._get_sheet_id()

        # Find courses that already have a color rule
        result = self._service.spreadsheets().get(
            spreadsheetId=self._spreadsheet_id,
            fields="sheets.conditionalFormats,sheets.properties",
        ).execute()

        existing: set[str] = set()
        for sheet in result.get("sheets", []):
            if sheet.get("properties", {}).get("sheetId") == sheet_id:
                for rule in sheet.get("conditionalFormats", []):
                    for val in (
                        rule.get("booleanRule", {})
                            .get("condition", {})
                            .get("values", [])
                    ):
                        formula = val.get("userEnteredValue", "")
                        if formula.startswith('=$B2="') and formula.endswith('"'):
                            existing.add(formula[6:-1])

        new_courses = [c for c in courses if c not in existing]
        if not new_courses:
            return

        requests = []
        for course in new_courses:
            color = _color_for_course(course)
            course_ranges = [
                {
                    "sheetId": sheet_id,
                    "startRowIndex": 1,
                    "endRowIndex": 1000,
                    "startColumnIndex": 0,
                    "endColumnIndex": _DAYS_LEFT_COL_INDEX,
                },
                {
                    "sheetId": sheet_id,
                    "startRowIndex": 1,
                    "endRowIndex": 1000,
                    "startColumnIndex": _DAYS_LEFT_COL_INDEX + 1,
                    "endColumnIndex": len(HEADERS),
                },
            ]
            requests.append({
                "addConditionalFormatRule": {
                    "rule": {
                        "ranges": course_ranges,
                        "booleanRule": {
                            "condition": {
                                "type": "CUSTOM_FORMULA",
                                "values": [{"userEnteredValue": f'=$B2="{course}"'}],
                            },
                            "format": {"backgroundColor": color},
                        },
                    },
                    "index": 999,
                }
            })

        try:
            self._service.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={"requests": requests},
            ).execute()
            logger.info("Applied course colors for: %s", new_courses)
        except HttpError as exc:
            logger.warning("Failed to apply course colors: %s", exc)

    def _to_row(self, assignment: Assignment) -> list[str]:
        """Serialize an Assignment to a Sheets row following COLUMNS order."""
        # Convert UTC → local timezone before formatting so the displayed date
        # matches the calendar date in the user's timezone, not UTC.
        if assignment.due_at:
            local_tz = ZoneInfo(settings.local_timezone)
            due_local = assignment.due_at.astimezone(local_tz)
            due_str = due_local.strftime("%Y-%m-%d")
        else:
            due_str = ""

        url = assignment.url
        if url and url.startswith("/"):
            domain = self._canvas_domain.rstrip("/")
            if not domain.startswith("http"):
                domain = f"https://{domain}"
            url = f"{domain}{url}"
        link = f'=HYPERLINK("{url}", "Open →")' if url else ""

        return [
            "",  # Done — checkbox managed by data validation in col A
            assignment.course_name,
            assignment.assignment_name,
            due_str,
            '=IF(INDIRECT("D"&ROW())="","",INDIRECT("D"&ROW())-TODAY())',  # Days Left — blank if no due date
            link,
            assignment.source,
        ]


# ── Per-user OAuth-based client ──────────────────────────────────────────────

def _build_user_service(access_token: str, refresh_token: str, token_expires_at: Any) -> tuple[Any, Any]:
    """Build a Sheets service using per-user OAuth credentials. Returns (service, credentials)."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_oauth_client_id,
        client_secret=settings.google_oauth_client_secret,
        scopes=OAUTH_SCOPES,
        expiry=token_expires_at,
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("sheets", "v4", credentials=creds), creds


def create_user_spreadsheet(
    access_token: str, refresh_token: str, token_expires_at: Any = None
) -> tuple[str, Any]:
    """Create an OhSheet spreadsheet for a user. Returns (spreadsheet_id, credentials)."""
    service, creds = _build_user_service(access_token, refresh_token, token_expires_at)
    year = datetime.now(timezone.utc).year
    result = (
        service.spreadsheets()
        .create(body={"properties": {"title": f"OhSheet {year}"}}, fields="spreadsheetId")
        .execute()
    )
    spreadsheet_id = result["spreadsheetId"]
    logger.info("Created spreadsheet %s for new user.", spreadsheet_id)
    return spreadsheet_id, creds


class UserSheetsClient(SheetsClient):
    """SheetsClient backed by per-user OAuth credentials instead of a service account."""

    def __init__(
        self,
        spreadsheet_id: str,
        access_token: str,
        refresh_token: str,
        token_expires_at: Any = None,
        canvas_domain: str = "",
    ) -> None:
        self._spreadsheet_id = spreadsheet_id
        self._dry_run = False
        self._canvas_domain = canvas_domain or settings.canvas_domain
        self._service, self.refreshed_creds = _build_user_service(
            access_token, refresh_token, token_expires_at
        )

    # Override _build_service so the parent __init__ is not called.
    def _build_service(self) -> Any:  # pragma: no cover
        raise NotImplementedError("UserSheetsClient uses _build_user_service")
