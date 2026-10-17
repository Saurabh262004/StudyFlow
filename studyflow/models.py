"""StudyFlow data model.

Everything the user creates lives in one `Database` object that is saved as a
single JSON file. Images are NOT stored inside the JSON; only a record with a
relative file path and tags is kept, the picture itself sits in an images/ folder.

JSON layout (schemaVersion 1)
-----------------------------
{
  "schemaVersion": 1,
  "subjects": [
    {
      "id": "…", "name": "Operating Systems", "notes": "…", "createdAt": "…Z",
      "points": [
        {
          "id": "…", "title": "Deadlocks", "notes": "…", "done": false,
          "deadline": "2026-11-02T18:30:00+00:00" | null,
          "effortHours": 2.5 | null,
          "createdAt": "…"
        }
      ]
    }
  ],
  "images": [
    {
      "id": "…", "file": "images/<id>.jpg", "originalName": "IMG_0412.jpg",
      "subjectId": "…", "pointId": "…" | null, "tags": ["blackboard"],
      "addedAt": "…"
    }
  ]
}

All timestamps are stored as ISO 8601 in UTC. The UI converts to local time.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

SCHEMA_VERSION = 1


# --------------------------------------------------------------------------- errors
class DataFormatError(ValueError):
    """The data is damaged or does not look like a StudyFlow database."""


class NewerSchemaError(Exception):
    """The data was written by a newer version of StudyFlow. Never overwrite it."""


class NotFoundError(LookupError):
    """A subject, study point or image with the given id does not exist."""


# --------------------------------------------------------------------------- helpers
def new_id() -> str:
    return uuid.uuid4().hex


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_utc(dt: datetime) -> datetime:
    """Return dt as an aware UTC datetime. Naive datetimes are treated as local time."""
    if dt.tzinfo is None:
        dt = dt.astimezone()  # attaches the system's local timezone
    return dt.astimezone(timezone.utc)


def dt_to_str(dt: Optional[datetime]) -> Optional[str]:
    return None if dt is None else to_utc(dt).isoformat()


def str_to_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return to_utc(datetime.fromisoformat(value))
    except (ValueError, TypeError):
        return None


def normalise_tags(tags: Iterable[str]) -> list[str]:
    """Lower-case, trimmed, de-duplicated, sorted. Empty tags are dropped."""
    return sorted({t.strip().lower() for t in tags if isinstance(t, str) and t.strip()})


def _clean_name(value: str, what: str) -> str:
    value = (value or "").strip()
    if not value:
        raise ValueError(f"{what} cannot be empty")
    return value


def _check_effort(hours: Optional[float]) -> Optional[float]:
    if hours is None:
        return None
    hours = float(hours)
    if hours <= 0:
        raise ValueError("estimated effort must be greater than 0 hours")
    return hours


# --------------------------------------------------------------------------- records
@dataclass
class ImageRecord:
    file: str  # path relative to the data folder, always with "/" separators
    subject_id: str
    point_id: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    original_name: str = ""
    id: str = field(default_factory=new_id)
    added_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.tags = normalise_tags(self.tags)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "file": self.file,
            "originalName": self.original_name,
            "subjectId": self.subject_id,
            "pointId": self.point_id,
            "tags": list(self.tags),
            "addedAt": dt_to_str(self.added_at),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ImageRecord":
        return cls(
            id=str(d["id"]),
            file=str(d["file"]),
            original_name=str(d.get("originalName", "")),
            subject_id=str(d["subjectId"]),
            point_id=d.get("pointId"),
            tags=d.get("tags") or [],
            added_at=str_to_dt(d.get("addedAt")) or utc_now(),
        )


@dataclass
class StudyPoint:
    title: str
    notes: str = ""
    done: bool = False
    deadline: Optional[datetime] = None
    effort_hours: Optional[float] = None
    id: str = field(default_factory=new_id)
    created_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "notes": self.notes,
            "done": self.done,
            "deadline": dt_to_str(self.deadline),
            "effortHours": self.effort_hours,
            "createdAt": dt_to_str(self.created_at),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "StudyPoint":
        effort = d.get("effortHours")
        return cls(
            id=str(d["id"]),
            title=str(d["title"]),
            notes=str(d.get("notes", "")),
            done=bool(d.get("done", False)),
            deadline=str_to_dt(d.get("deadline")),
            effort_hours=None if effort is None else float(effort),
            created_at=str_to_dt(d.get("createdAt")) or utc_now(),
        )


@dataclass
class Subject:
    name: str
    notes: str = ""
    points: list[StudyPoint] = field(default_factory=list)
    id: str = field(default_factory=new_id)
    created_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "notes": self.notes,
            "createdAt": dt_to_str(self.created_at),
            "points": [p.to_dict() for p in self.points],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Subject":
        return cls(
            id=str(d["id"]),
            name=str(d["name"]),
            notes=str(d.get("notes", "")),
            created_at=str_to_dt(d.get("createdAt")) or utc_now(),
            points=[StudyPoint.from_dict(p) for p in d.get("points", [])],
        )


# --------------------------------------------------------------------------- database
@dataclass
class Database:
    subjects: list[Subject] = field(default_factory=list)
    images: list[ImageRecord] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION

    # ---- lookups
    def get_subject(self, subject_id: str) -> Subject:
        for s in self.subjects:
            if s.id == subject_id:
                return s
        raise NotFoundError(f"subject {subject_id!r} not found")

    def get_point(self, subject_id: str, point_id: str) -> StudyPoint:
        for p in self.get_subject(subject_id).points:
            if p.id == point_id:
                return p
        raise NotFoundError(f"study point {point_id!r} not found")

    def get_image(self, image_id: str) -> ImageRecord:
        for i in self.images:
            if i.id == image_id:
                return i
        raise NotFoundError(f"image {image_id!r} not found")

    # ---- create
    def add_subject(self, name: str, notes: str = "") -> Subject:
        subject = Subject(name=_clean_name(name, "subject name"), notes=notes)
        self.subjects.append(subject)
        return subject

    def add_point(
        self,
        subject_id: str,
        title: str,
        notes: str = "",
        deadline: Optional[datetime] = None,
        effort_hours: Optional[float] = None,
    ) -> StudyPoint:
        subject = self.get_subject(subject_id)
        point = StudyPoint(
            title=_clean_name(title, "study point title"),
            notes=notes,
            deadline=None if deadline is None else to_utc(deadline),
            effort_hours=_check_effort(effort_hours),
        )
        subject.points.append(point)
        return point

    # ---- remove (they return the removed images so the caller can delete the files)
    def remove_subject(self, subject_id: str) -> list[ImageRecord]:
        subject = self.get_subject(subject_id)
        self.subjects.remove(subject)
        removed = [i for i in self.images if i.subject_id == subject_id]
        self.images = [i for i in self.images if i.subject_id != subject_id]
        return removed

    def remove_point(self, subject_id: str, point_id: str) -> list[ImageRecord]:
        subject = self.get_subject(subject_id)
        subject.points.remove(self.get_point(subject_id, point_id))
        removed = [i for i in self.images if i.point_id == point_id]
        self.images = [i for i in self.images if i.point_id != point_id]
        return removed

    # ---- search
    def find_images(
        self,
        subject_id: Optional[str] = None,
        point_id: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> list[ImageRecord]:
        tag = tag.strip().lower() if tag else None
        return [
            i
            for i in self.images
            if (subject_id is None or i.subject_id == subject_id)
            and (point_id is None or i.point_id == point_id)
            and (tag is None or tag in i.tags)
        ]

    # ---- (de)serialisation
    def to_dict(self) -> dict:
        return {
            "schemaVersion": self.schema_version,
            "subjects": [s.to_dict() for s in self.subjects],
            "images": [i.to_dict() for i in self.images],
        }

    @classmethod
    def from_dict(cls, raw: Any) -> "Database":
        if not isinstance(raw, dict):
            raise DataFormatError("top level of the data file must be an object")
        version = raw.get("schemaVersion", 1)
        if not isinstance(version, int):
            raise DataFormatError("schemaVersion must be a number")
        if version > SCHEMA_VERSION:
            raise NewerSchemaError(
                f"data was saved by a newer StudyFlow (schema {version}, this app knows {SCHEMA_VERSION})"
            )
        raw = _migrate(raw, version)
        try:
            return cls(
                subjects=[Subject.from_dict(s) for s in raw.get("subjects", [])],
                images=[ImageRecord.from_dict(i) for i in raw.get("images", [])],
                schema_version=SCHEMA_VERSION,
            )
        except (KeyError, TypeError, AttributeError, ValueError) as exc:
            raise DataFormatError(f"damaged data: {exc!r}") from exc


def _migrate(raw: dict, version: int) -> dict:
    """Upgrade old data layouts to the current one. Nothing to do yet (only schema 1 exists)."""
    return raw
