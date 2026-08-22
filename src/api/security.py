"""Input sanitization for path-shaped API parameters. Every route that turns
a request value into a filesystem path (data_dir -> corpus files, run_id /
decision_id -> runs/{run_id}/audit.jsonl) goes through here first — found by
code review: none of them validated their input before it hit Path()/open().
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import HTTPException

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DATA_ROOT = (_PROJECT_ROOT / "data").resolve()

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def safe_data_dir(data_dir: str) -> str:
    """Resolves data_dir and rejects anything outside the project's data/
    directory — blocks `../../etc` style traversal via the /run and
    /compare request bodies."""
    candidate = (_PROJECT_ROOT / data_dir).resolve()
    if not candidate.is_relative_to(_DATA_ROOT):
        raise HTTPException(400, f"data_dir must be inside data/: {data_dir!r}")
    return str(candidate)


def safe_id(value: str, field_name: str) -> str:
    """run_id / decision_id must match the charset the system itself
    generates them with (see audit/trail.py, eval/harness.py, redteam/
    generator.py) — anything else is rejected before it reaches a path."""
    if not _SAFE_ID_RE.match(value):
        raise HTTPException(400, f"invalid {field_name}: {value!r}")
    return value
