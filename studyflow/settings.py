"""Per-user settings. They are exactly the numbers the priority engine plans with (PlanSettings),
saved as settings.json in the user's own folder (see Storage.load_settings / save_settings).

    {"schemaVersion": 1, "hoursPerDay": 2.0, "defaultEffortHours": 1.0, "soonDays": 2.0}
"""
from __future__ import annotations

from typing import Any

from .priority import PlanSettings
from .schemas import describe_errors, load_validator

SETTINGS_SCHEMA_VERSION = 1
_VALIDATOR = load_validator("settings.schema.json")


def settings_to_dict(settings: PlanSettings) -> dict:
    return {
        "schemaVersion": SETTINGS_SCHEMA_VERSION,
        "hoursPerDay": settings.hours_per_day,
        "defaultEffortHours": settings.default_effort_hours,
        "soonDays": settings.soon_days,
    }


def settings_errors(data: Any) -> list[str]:
    return describe_errors(_VALIDATOR, data)


def settings_from_dict(raw: Any) -> PlanSettings:
    """Validate against the JSON Schema, then build PlanSettings. Raises ValueError if anything is wrong."""
    problems = settings_errors(raw)
    if problems:
        raise ValueError("; ".join(problems[:3]))
    return PlanSettings(
        hours_per_day=float(raw["hoursPerDay"]),
        default_effort_hours=float(raw["defaultEffortHours"]),
        soon_days=float(raw["soonDays"]),
    )
