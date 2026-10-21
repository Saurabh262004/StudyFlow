"""Small helpers shared by everything that checks a JSON file against one of the bundled JSON Schemas."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


def load_validator(filename: str) -> Draft202012Validator:
    """Load a schema file that sits next to this module."""
    path = Path(__file__).with_name(filename)
    return Draft202012Validator(json.loads(path.read_text(encoding="utf-8")))


def describe_errors(validator: Draft202012Validator, data: Any) -> list[str]:
    """Human-readable problems, e.g. 'subjects[0].points[1].effortHours: -3 is less than ...' (empty = valid)."""
    problems = []
    for err in sorted(validator.iter_errors(data), key=lambda e: list(map(str, e.absolute_path))):
        where = ""
        for part in err.absolute_path:
            where += f"[{part}]" if isinstance(part, int) else f".{part}"
        problems.append(f"{where.lstrip('.') or '(root)'}: {err.message}")
    return problems
