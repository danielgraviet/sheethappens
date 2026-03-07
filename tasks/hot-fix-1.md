# Hot-Fix 1: Shorten Course Names

## Status: Ready to implement

## Problem
Canvas `context_name` values are long and noisy (e.g. `"Foundations of the Restoration (REL C 225, sections 12, 16, 37. 40)"`). The sheet "Course" column should display a compact, human-readable label (e.g. `"REL 225"`).

## Chosen Approach: Regex-based extraction (no LLM needed)
A regex pattern extracts the department code + course number from the raw name. This is fast, free, deterministic, and works for standard BYU course name formats. An LLM fallback is described at the bottom if edge cases arise.

## Examples
| Raw `context_name` | Shortened |
|---|---|
| `Foundations of the Restoration (REL C 225, sections 12, 16, 37. 40)` | `REL C 225` |
| `MATH 112-026: Winter 2026 Snellman` | `MATH 112` |
| `C S 180-001: Intro to Data Science` | `CS 180` |

## Files to Create/Modify

### 1. Create `app/course_shortener.py` (new file)

```python
import re

# Ordered list of regex patterns. First match wins.
# Each pattern must produce a named group `short`.
_PATTERNS = [
    # Parenthetical course code: "Foundations of the Restoration (REL C 225, ...)"
    # Captures the dept + number inside parens before the first comma or close-paren.
    re.compile(r"\((?P<short>[A-Z][A-Z &]+\d{3}[A-Z]?)[\s,\)]", re.IGNORECASE),

    # Prefix code with section: "MATH 112-026: ..." or "C S 180-001: ..."
    # Captures dept code + course number, strips the section (-026).
    re.compile(r"^(?P<short>[A-Z][A-Z &]*\d{3}[A-Z]?)-\d+", re.IGNORECASE),

    # Plain "DEPT NNN: Title" with no section number
    re.compile(r"^(?P<short>[A-Z][A-Z &]*\d{3}[A-Z]?)\b", re.IGNORECASE),
]


def shorten_course_name(name: str) -> str:
    """Return a compact course label, e.g. 'MATH 112'. Falls back to the
    original name (truncated to 30 chars) if no pattern matches."""
    for pattern in _PATTERNS:
        match = pattern.search(name)
        if match:
            # Normalise internal whitespace (e.g. "C S" → "CS" is intentional BYU style;
            # keep as-is so "C S 180" remains "CS 180" after strip only)
            short = match.group("short").strip()
            # Collapse multiple spaces (e.g. "C  S 180" → "C S 180")
            short = re.sub(r" {2,}", " ", short)
            return short
    # Fallback: truncate raw name
    return name[:30].rstrip()
```

### 2. Modify `app/adapter.py`

**Add import at the top:**
```python
from app.course_shortener import shorten_course_name
```

**In the `adapt` method, change the `course_name` line:**
```python
# OLD:
course_name = (raw.get("context_name") or "Unknown Course").strip()

# NEW:
course_name = shorten_course_name(
    (raw.get("context_name") or "Unknown Course").strip()
)
```

No other changes needed — `course_name` is already stored on the `Assignment` model and flows through to the sheet.

### 3. Create `tests/test_course_shortener.py` (new file)

```python
from app.course_shortener import shorten_course_name

def test_parenthetical_dept_code():
    assert shorten_course_name(
        "Foundations of the Restoration (REL C 225, sections 12, 16, 37. 40)"
    ) == "REL C 225"

def test_prefix_with_section():
    assert shorten_course_name("MATH 112-026: Winter 2026 Snellman") == "MATH 112"

def test_spaced_dept_with_section():
    assert shorten_course_name("C S 180-001: Intro to Data Science") == "C S 180"

def test_plain_dept_no_section():
    assert shorten_course_name("ECON 110: Principles of Economics") == "ECON 110"

def test_fallback_unknown_format():
    result = shorten_course_name("Some totally unknown course format here and beyond")
    assert len(result) <= 30

def test_empty_string_fallback():
    result = shorten_course_name("")
    assert result == ""
```

## Verification
```
uv run pytest tests/test_course_shortener.py -v
uv run pytest -v
```

## Optional LLM Fallback (not required for MVP)
If a course name doesn't match any regex pattern (fallback path), you could call a cheap LLM (e.g. `claude-haiku-4-5`) with a prompt like:
> "Shorten this university course name to just the department code and number (e.g. 'MATH 112'). Return only the short form, nothing else. Course: {name}"

This would require adding `anthropic` as a dependency (`uv add anthropic`) and handling the API call in `course_shortener.py`. Only worth doing if the regex fallback produces ugly results in practice.

## Notes
- The `Assignment` model field `course_name` is a plain `str` — no model changes needed.
- Idempotency is keyed by `assignment_id`, so changing the displayed course name does not affect deduplication.
- After deploying, a re-sync is NOT required for existing rows — only newly synced assignments will show the shortened name. To backfill, clear the sheet and Redis and re-sync (see hot-fix-4 notes).
