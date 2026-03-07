# Hot-Fix 3: Checkbox Column with Strikethrough

## Status: Ready to implement

## Decision: Template sheet approach (recommended)
The user raised two options. **Use the template approach.** Reason: formatting (checkboxes, strikethrough conditional format, column widths, colors) is a one-time manual setup. The sync code only needs to inject data into specific columns, leaving the template structure untouched. This is more maintainable than having the API rebuild formatting on every sync.

## Architecture

```
Sheet layout (left to right):
| A (Done ✓) | B (Course) | C (Assignment) | D (Due Date) | E (Link) | F (Assignment ID) |
```

Column A contains checkboxes. A conditional formatting rule applies strikethrough to the entire row when A is checked (`TRUE`).

The API writes to columns B–F only. Column A is never touched by the sync code — the user checks boxes manually.

## Part 1: One-time manual template setup (user does this once in the sheet)

1. **Add checkbox data validation to column A:**
   - Select the entire column A (below row 1)
   - Insert → Checkbox (this writes `FALSE` to all selected cells and applies boolean data validation)
   - Or: Data → Data validation → Criteria: Checkbox

2. **Add conditional formatting rule for strikethrough:**
   - Format → Conditional formatting
   - Apply to range: `A2:F1000` (or however many rows you expect)
   - Format rules: Custom formula → `=$A2=TRUE`
   - Formatting style: Strikethrough ✓
   - Save

3. **Set column A header** in A1: `"Done"`

Once this template is set up, the sync code should never overwrite column A or touch formatting.

## Part 2: Code changes

The sync currently writes to `Sheet1!A1` using `append` with `INSERT_ROWS`. This will shift column A checkboxes if rows are inserted above existing data. We need to change the write target to columns B–F.

### 1. `app/sheets_client.py`

**Change `SHEET_RANGE`** to target column B onward:
```python
# OLD:
SHEET_RANGE = "Sheet1!A1"

# NEW:
SHEET_RANGE = "Sheet1!B1"
```

**Change `_ensure_headers`** to write headers to B1:F1 instead of A1:
```python
# Check range:
range="Sheet1!B1:F1"   # was "Sheet1!A1:F1"

# Write range:
range="Sheet1!B1"      # was "Sheet1!A1"
```

**Change `COLUMNS` and `HEADERS`** — column A ("Done") is owned by the template, not the sync code. No change needed to COLUMNS/HEADERS since they already describe B–F content. The `SHEET_RANGE = "Sheet1!B1"` change handles targeting correctly.

**No change to `_to_row`** — it still returns 5 values (or 6 if hot-fix-4 has not been applied yet). The Sheets API `append` call starting at B1 will write them into B, C, D, E, F automatically.

**Update `_ensure_headers`** range check to match the new column range:
```python
def _ensure_headers(self) -> None:
    try:
        result = self._service.spreadsheets().values().get(
            spreadsheetId=self._spreadsheet_id,
            range="Sheet1!B1:F1",   # <-- was A1:F1
        ).execute()
        if result.get("values"):
            return
        self._service.spreadsheets().values().update(
            spreadsheetId=self._spreadsheet_id,
            range="Sheet1!B1",      # <-- was Sheet1!A1
            valueInputOption="USER_ENTERED",
            body={"values": [HEADERS]},
        ).execute()
        logger.info("Wrote header row to spreadsheet.")
    except HttpError as exc:
        raise SheetsAPIError(f"Failed to write headers: {exc}") from exc
```

### 2. `tests/test_sheets_client.py`

Update `test_append_rows_calls_api` — check that the `range` in the append call is `"Sheet1!B1"` instead of `"Sheet1!A1"`.

Update any test that asserts on `SHEET_RANGE` or the header write range.

## Part 3: Checkbox auto-population via API (optional enhancement)

If you want the sync code to automatically write checkboxes into column A for each new row (so the user doesn't need to pre-populate column A in the template), add this to `SheetsClient`:

```python
def _write_checkboxes(self, start_row: int, count: int) -> None:
    """Write FALSE (unchecked) checkboxes into column A for `count` rows starting at `start_row`."""
    # start_row is 1-indexed (row 2 = first data row, since row 1 is the header)
    end_row = start_row + count - 1
    requests = [{
        "repeatCell": {
            "range": {
                "sheetId": 0,
                "startRowIndex": start_row - 1,  # API is 0-indexed
                "endRowIndex": end_row,
                "startColumnIndex": 0,
                "endColumnIndex": 1,
            },
            "cell": {
                "dataValidation": {
                    "condition": {"type": "BOOLEAN"},
                    "showCustomUi": True,
                },
                "userEnteredValue": {"boolValue": False},
            },
            "fields": "dataValidation,userEnteredValue",
        }
    }]
    try:
        self._service.spreadsheets().batchUpdate(
            spreadsheetId=self._spreadsheet_id,
            body={"requests": requests},
        ).execute()
    except HttpError as exc:
        raise SheetsAPIError(f"Failed to write checkboxes: {exc}") from exc
```

Call `_write_checkboxes(start_row=existing_rows + 1, count=len(assignments))` after the append succeeds. `existing_rows` is the count fetched before appending (same as in hot-fix-2).

## Ordering of hot-fixes
Hot-fix-3 and hot-fix-4 are compatible. Apply hot-fix-4 (remove synced_at) first so the final column layout is stable before setting up the template.

If hot-fix-2 (color coding) is also applied, the `batchUpdate` for colors should target columns B–F (startColumnIndex: 1) to leave column A (the checkbox) uncolored.

## Verification
1. Manually set up the template sheet (Part 1 above)
2. Clear the sheet data (keep the template formatting) and re-sync
3. Confirm:
   - New rows appear in columns B–F
   - Column A shows unchecked checkboxes
   - Checking a box in column A applies strikethrough to the entire row
   - The header in row 1 is not overwritten
