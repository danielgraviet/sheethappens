# Hot-Fix 4: Remove the "Synced At" column

## Status: Ready to implement

## Problem
The `synced_at` column (last column in the sheet) is internal metadata that is not useful to the end user. It should be removed from the sheet output.

## Files to Modify

### 1. `app/sheets_client.py`

**Current state (lines 20–21):**
```python
COLUMNS = ["course_name", "assignment_name", "due_at", "url", "assignment_id", "synced_at"]
HEADERS = ["Course", "Assignment", "Due Date", "Link", "Assignment ID", "Synced At"]
```

**Change 1** — remove `synced_at` from both lists:
```python
COLUMNS = ["course_name", "assignment_name", "due_at", "url", "assignment_id"]
HEADERS = ["Course", "Assignment", "Due Date", "Link", "Assignment ID"]
```

**Change 2** — in `append_rows`, remove the `synced_at` variable:
```python
# DELETE this line:
synced_at = datetime.now(timezone.utc)
# DELETE this line:
rows = [self._to_row(a, synced_at) for a in assignments]

# REPLACE with:
rows = [self._to_row(a) for a in assignments]
```

Also remove the unused `datetime` import if it's no longer used elsewhere. Check: `datetime` is still used in the `_to_row` type hint for `due_at`, so keep the import.

**Change 3** — update `_to_row` signature and body:
```python
# OLD signature:
def _to_row(self, assignment: Assignment, synced_at: datetime) -> list[str]:

# NEW signature:
def _to_row(self, assignment: Assignment) -> list[str]:
```

Remove the `synced_str` block entirely:
```python
# DELETE these lines:
synced_str = (
    f"{synced_at.strftime('%b')} {synced_at.day}, {synced_at.year} "
    f"{synced_at.strftime('%-I:%M %p')} UTC"
)
```

Remove `synced_str` from the return list:
```python
# OLD return:
return [
    assignment.course_name,
    assignment.assignment_name,
    due_str,
    link,
    assignment.assignment_id,
    synced_str,
]

# NEW return:
return [
    assignment.course_name,
    assignment.assignment_name,
    due_str,
    link,
    assignment.assignment_id,
]
```

Also update `_ensure_headers` — the range `"Sheet1!A1:F1"` should become `"Sheet1!A1:E1"` since there are now only 5 columns.

### 2. `tests/test_sheets_client.py`

**Change 1** — update `test_columns_order`:
```python
def test_columns_order() -> None:
    assert COLUMNS == [
        "course_name",
        "assignment_name",
        "due_at",
        "url",
        "assignment_id",
    ]
```

**Change 2** — update `test_headers_match_columns_length`:
```python
def test_headers_match_columns_length() -> None:
    assert len(HEADERS) == len(COLUMNS)
    assert HEADERS == ["Course", "Assignment", "Due Date", "Link", "Assignment ID"]
```

**Change 3** — update `test_to_row_with_due_at`: remove the `synced_at` argument from the `_to_row` call and drop the assertion about `row[5]` (synced string). The row now has 5 elements.

**Change 4** — update `test_to_row_without_due_at`: same — remove `synced_at` argument.

**Change 5** — update `test_to_row_relative_url`: same — remove `synced_at` argument.

## Verification
Run `uv run pytest tests/test_sheets_client.py -v` — all tests should pass.
Then run `uv run pytest -v` to confirm the full suite is green.

## Notes
- After deploying, clear the sheet and re-sync once so the header row is rewritten without the "Synced At" column. The Redis keys do NOT need to be cleared since idempotency is keyed by `assignment_id`, not column layout.
