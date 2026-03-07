# Hot-Fix 2: Color Coding the Sheet

## Status: Ready to implement

## Problem
The sheet is plain text with no visual hierarchy. We want:
1. A styled header row (bold, dark background, white text)
2. Each course to have a consistent highlight color — every row belonging to the same course gets the same background color, making it easy to visually group assignments by class.

## Approach: Google Sheets batchUpdate formatting API
After appending rows, call `spreadsheets.batchUpdate` with formatting requests. This uses the existing `SheetsClient._service` — no new auth or dependencies needed.

## Color Palette
Define a fixed palette of soft colors (one per course slot). Courses are assigned colors in the order they are first encountered during a sync run. The mapping is NOT persisted across syncs — colors are re-applied every time `append_rows` is called.

Suggested palette (RGB 0–1 scale for the Sheets API):
```python
COURSE_COLORS = [
    {"red": 0.78, "green": 0.89, "blue": 1.0},   # light blue
    {"red": 0.85, "green": 1.0,  "blue": 0.85},  # light green
    {"red": 1.0,  "green": 0.95, "blue": 0.78},  # light yellow
    {"red": 1.0,  "green": 0.82, "blue": 0.86},  # light pink
    {"red": 0.90, "green": 0.82, "blue": 1.0},   # light purple
    {"red": 0.80, "green": 0.95, "blue": 0.95},  # light teal
]
HEADER_BG   = {"red": 0.20, "green": 0.20, "blue": 0.20}  # dark grey
HEADER_TEXT = {"red": 1.0,  "green": 1.0,  "blue": 1.0}   # white
```

## Files to Modify

### 1. `app/sheets_client.py`

**Add the color palette constants** after the `HEADERS` line:
```python
COURSE_COLORS = [
    {"red": 0.78, "green": 0.89, "blue": 1.0},
    {"red": 0.85, "green": 1.0,  "blue": 0.85},
    {"red": 1.0,  "green": 0.95, "blue": 0.78},
    {"red": 1.0,  "green": 0.82, "blue": 0.86},
    {"red": 0.90, "green": 0.82, "blue": 1.0},
    {"red": 0.80, "green": 0.95, "blue": 0.95},
]
HEADER_BG   = {"red": 0.20, "green": 0.20, "blue": 0.20}
HEADER_TEXT = {"red": 1.0,  "green": 1.0,  "blue": 1.0}
```

**Add two new private methods to `SheetsClient`:**

```python
def _format_header_row(self) -> None:
    """Apply bold + dark background to row 1 (the header row)."""
    requests = [{
        "repeatCell": {
            "range": {
                "sheetId": 0,
                "startRowIndex": 0,
                "endRowIndex": 1,
            },
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": HEADER_BG,
                    "textFormat": {
                        "bold": True,
                        "foregroundColor": HEADER_TEXT,
                    },
                }
            },
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }
    }]
    try:
        self._service.spreadsheets().batchUpdate(
            spreadsheetId=self._spreadsheet_id,
            body={"requests": requests},
        ).execute()
    except HttpError as exc:
        raise SheetsAPIError(f"Failed to format header row: {exc}") from exc


def _format_data_rows(
    self,
    start_row: int,
    assignments: list[Assignment],
    course_color_map: dict[str, dict],
) -> None:
    """Apply per-course background colors to the newly appended rows.

    Args:
        start_row: 0-indexed row index of the first data row to format
                   (i.e. the row immediately after the last existing row).
        assignments: The assignments that were just appended, in order.
        course_color_map: Maps course_name → color dict (built by caller).
    """
    requests = []
    for i, assignment in enumerate(assignments):
        color = course_color_map.get(assignment.course_name, COURSE_COLORS[0])
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": 0,
                    "startRowIndex": start_row + i,
                    "endRowIndex": start_row + i + 1,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": color,
                    }
                },
                "fields": "userEnteredFormat.backgroundColor",
            }
        })
    if not requests:
        return
    try:
        self._service.spreadsheets().batchUpdate(
            spreadsheetId=self._spreadsheet_id,
            body={"requests": requests},
        ).execute()
    except HttpError as exc:
        raise SheetsAPIError(f"Failed to format data rows: {exc}") from exc
```

**Update `append_rows`** to call formatting after writing data:

The current `append_rows` calls `_ensure_headers()` then appends rows. Extend it to:

1. Before appending, get the current number of rows in the sheet so we know where the new rows will land:
```python
result = self._service.spreadsheets().values().get(
    spreadsheetId=self._spreadsheet_id,
    range="Sheet1",
).execute()
existing_rows = len(result.get("values") or [])
# existing_rows is the 0-indexed start of the new rows after append
```

2. Build a `course_color_map` from the assignments being written:
```python
course_color_map: dict[str, dict] = {}
for assignment in assignments:
    if assignment.course_name not in course_color_map:
        idx = len(course_color_map) % len(COURSE_COLORS)
        course_color_map[assignment.course_name] = COURSE_COLORS[idx]
```

3. After the append API call succeeds, call:
```python
self._format_header_row()
self._format_data_rows(existing_rows, assignments, course_color_map)
```

**Important:** The `_ensure_headers()` call must happen before the row count is fetched, so that the header row is included in `existing_rows`. The order in `append_rows` should be:
1. `_ensure_headers()`
2. Get current row count (`existing_rows`)
3. Append data rows
4. `_format_header_row()`
5. `_format_data_rows(...)`

## Caveats & Decisions

**Color persistence across syncs:** Course → color assignments are rebuilt fresh each sync run based on the order courses appear in the fetched assignments. This means the color for "MATH 112" might change between syncs if the course order changes. To make colors stable, persist the `course_color_map` in Redis (serialize as JSON under key `sheethappens:course_colors`). This is optional for MVP.

**Sheet ID:** The `sheetId: 0` in the batchUpdate requests assumes the target is the first sheet in the spreadsheet. If the spreadsheet has multiple sheets, this needs to be dynamic — call `spreadsheets.get()` and find the sheet by name (`"Sheet1"`).

**Dry run mode:** Skip all formatting calls when `self._dry_run` is True.

## Verification
- Run `uv run pytest -v` (formatting methods don't require new unit tests since they call live APIs, but you should mock them similarly to existing `test_append_rows_calls_api`)
- Visually inspect the sheet after a sync — header row should be dark with white bold text; each course should have a consistent pastel row color.
