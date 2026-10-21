"""StudyFlow data model.

Everything the user creates lives in one `Database` object that is saved as a single JSON file.
Images are NOT stored inside the JSON; only a record with a relative file path and tags is kept,
the picture itself sits in an images/ folder.

An image does not belong to any subject or point. It is a standalone record, and subjects and
study points LIST the images they use (many-to-many), so one photo can appear in several places.

JSON layout (schemaVersion 2)
-----------------------------
{
  "schemaVersion": 2,
  "subjects": [
    {
      "id": "…", "name": "Operating Systems", "notes": "…", "createdAt": "…",
      "imageIds": ["<image id>", …],                      # images shown on the subject itself
      "points": [
        {
          "id": "…", "title": "Deadlocks", "notes": "…", "done": false,
          "deadline": "2026-11-02T18:30:00+00:00" | null,
          "effortHours": 2.5 | null,
          "imageIds": ["<image id>", …],                  # images shown on this study point
          "createdAt": "…"
        }
      ]
    }
  ],
  "images": [
    { "id": "…", "file": "images/<id>.jpg", "originalName": "IMG_0412.jpg",
      "tags": ["blackboard"], "addedAt": "…" }
  ]
}

Rules: every id in an imageIds list must exist in "images"; an image that nothing lists any more
is deleted (see Database.unlink_image). All timestamps are ISO 8601 in UTC.

Schema history: 1 = images carried subjectId/pointId (one owner each). 2 = the layout above.
"""
from __future__ import annotations

import copy
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

SCHEMA_VERSION = 2


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


def _id_list(value: Any) -> list[str]:
    return [str(i) for i in (value or [])]


# --------------------------------------------------------------------------- records
@dataclass
class ImageRecord:
    file: str  # path relative to the data folder, always with "/" separators
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
            "tags": list(self.tags),
            "addedAt": dt_to_str(self.added_at),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ImageRecord":
        return cls(
            id=str(d["id"]),
            file=str(d["file"]),
            original_name=str(d.get("originalName", "")),
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
    image_ids: list[str] = field(default_factory=list)
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
            "imageIds": list(self.image_ids),
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
            image_ids=_id_list(d.get("imageIds")),
            created_at=str_to_dt(d.get("createdAt")) or utc_now(),
        )


@dataclass
class Subject:
    name: str
    notes: str = ""
    points: list[StudyPoint] = field(default_factory=list)
    image_ids: list[str] = field(default_factory=list)
    id: str = field(default_factory=new_id)
    created_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "notes": self.notes,
            "createdAt": dt_to_str(self.created_at),
            "imageIds": list(self.image_ids),
            "points": [p.to_dict() for p in self.points],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Subject":
        return cls(
            id=str(d["id"]),
            name=str(d["name"]),
            notes=str(d.get("notes", "")),
            created_at=str_to_dt(d.get("createdAt")) or utc_now(),
            image_ids=_id_list(d.get("imageIds")),
            points=[StudyPoint.from_dict(p) for p in d.get("points", [])],
        )


# --------------------------------------------------------------------------- database

@dataclass(frozen=True)
class SearchHit:
    """One search result. kind is "subject", "point" or "image"; the ids say where to jump to."""

    kind: str
    field: str  # which field matched: "name", "title", "notes", "tag" or "file name"
    snippet: str  # a short piece of the matching text
    subject_id: Optional[str] = None  # set for subjects and points
    point_id: Optional[str] = None  # set for points
    image_id: Optional[str] = None  # set for images (see Database.usage for where it is used)


def _snippet(value: str, patterns: list, width: int = 40) -> str:
    flat = " ".join(value.split())  # newlines and runs of spaces become single spaces
    for pattern in patterns:
        m = pattern.search(flat)
        if m:
            start, end = max(0, m.start() - width), min(len(flat), m.end() + width)
            return ("\u2026" if start > 0 else "") + flat[start:end] + ("\u2026" if end < len(flat) else "")
    return flat[: 2 * width]

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

    def _target(self, subject_id: str, point_id: Optional[str]):
        """The subject, or the study point inside it when point_id is given."""
        return self.get_subject(subject_id) if point_id is None else self.get_point(subject_id, point_id)

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

    # ---- images: a many-to-many link between images and subjects / study points
    def link_image(self, image_id: str, subject_id: str, point_id: Optional[str] = None) -> None:
        """Show an existing image on a subject (or on one of its study points). Linking twice is harmless."""
        self.get_image(image_id)
        target = self._target(subject_id, point_id)
        if image_id not in target.image_ids:
            target.image_ids.append(image_id)

    def unlink_image(self, image_id: str, subject_id: str, point_id: Optional[str] = None) -> Optional[ImageRecord]:
        """Stop showing an image there. If nothing else uses it, the record is removed from the
        database and returned so the caller can delete the file; otherwise returns None."""
        self.get_image(image_id)
        target = self._target(subject_id, point_id)
        if image_id not in target.image_ids:
            raise NotFoundError(f"image {image_id!r} is not linked there")
        target.image_ids.remove(image_id)
        return self._drop_if_unused(image_id)

    def remove_image(self, image_id: str) -> ImageRecord:
        """Delete an image everywhere: its record and every link to it."""
        record = self.get_image(image_id)
        self.images.remove(record)
        for s in self.subjects:
            if image_id in s.image_ids:
                s.image_ids.remove(image_id)
            for p in s.points:
                if image_id in p.image_ids:
                    p.image_ids.remove(image_id)
        return record

    def images_of(self, subject_id: str, point_id: Optional[str] = None) -> list[ImageRecord]:
        """Images shown on a subject (or on one study point), in the order they were added."""
        by_id = {i.id: i for i in self.images}
        return [by_id[i] for i in self._target(subject_id, point_id).image_ids if i in by_id]

    def usage(self, image_id: str) -> list[tuple[str, Optional[str]]]:
        """Where an image is used: (subject_id, None) for a subject, (subject_id, point_id) for a point."""
        found: list[tuple[str, Optional[str]]] = []
        for s in self.subjects:
            if image_id in s.image_ids:
                found.append((s.id, None))
            found.extend((s.id, p.id) for p in s.points if image_id in p.image_ids)
        return found

    def _referenced_ids(self) -> set[str]:
        ids: set[str] = set()
        for s in self.subjects:
            ids.update(s.image_ids)
            for p in s.points:
                ids.update(p.image_ids)
        return ids

    def _drop_if_unused(self, image_id: str) -> Optional[ImageRecord]:
        if image_id in self._referenced_ids():
            return None
        for record in self.images:
            if record.id == image_id:
                self.images.remove(record)
                return record
        return None

    # ---- remove (they return the images that are no longer used so the caller can delete the files;
    #      an image that is also used somewhere else is kept)
    def remove_subject(self, subject_id: str) -> list[ImageRecord]:
        subject = self.get_subject(subject_id)
        candidates = list(subject.image_ids)
        for p in subject.points:
            candidates.extend(p.image_ids)
        self.subjects.remove(subject)
        return self._drop_all_unused(candidates)

    def remove_point(self, subject_id: str, point_id: str) -> list[ImageRecord]:
        point = self.get_point(subject_id, point_id)
        self.get_subject(subject_id).points.remove(point)
        return self._drop_all_unused(point.image_ids)

    def _drop_all_unused(self, image_ids: Iterable[str]) -> list[ImageRecord]:
        removed = []
        for image_id in dict.fromkeys(image_ids):  # unique, in order
            record = self._drop_if_unused(image_id)
            if record is not None:
                removed.append(record)
        return removed

    # ---- search
    def find_images(
        self,
        subject_id: Optional[str] = None,
        point_id: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> list[ImageRecord]:
        """Filter images. subject_id: used on that subject or any of its points; point_id: used on that
        point; tag: has that tag (any letter case). All given filters must match."""
        wanted: Optional[set[str]] = None
        if subject_id is not None or point_id is not None:
            wanted = set()
            for s in self.subjects:
                if subject_id is not None and s.id != subject_id:
                    continue
                if point_id is None:
                    wanted.update(s.image_ids)
                for p in s.points:
                    if point_id is None or p.id == point_id:
                        wanted.update(p.image_ids)
        tag = tag.strip().lower() if tag else None
        return [i for i in self.images if (wanted is None or i.id in wanted) and (tag is None or tag in i.tags)]

    def search(self, text: str, subject_id: Optional[str] = None, limit: Optional[int] = None) -> list[SearchHit]:
        """Find subjects, study points and images. Case-insensitive; every word of `text` must appear.

        * subject: in its name or notes.
        * study point: in its title or notes. Words may also come from the subject's name
          ("os deadlocks" finds the point Deadlocks of OS), but at least one must be in the point itself.
        * image: in its tags or original file name.
        Results with a hit in a name/title/tag come before those in notes or file names.
        subject_id limits the search to that subject, its points and the images used there.
        """
        words = text.split()
        if not words:
            return []
        patterns = [re.compile(re.escape(w), re.IGNORECASE) for w in words]

        def all_words_in(*texts: str) -> bool:
            blob = " ".join(texts)
            return all(p.search(blob) for p in patterns)

        def first_field(fields):
            for name, value in fields:
                if any(p.search(value) for p in patterns):
                    return name, value
            return None

        found: list[tuple[tuple[int, int, int], SearchHit]] = []

        def add(kind_order: int, name: str, value: str, hit_kwargs: dict, kind: str) -> None:
            rank = 0 if name in ("name", "title", "tag") else 1
            hit = SearchHit(kind=kind, field=name, snippet=_snippet(value, patterns), **hit_kwargs)
            found.append(((rank, kind_order, len(found)), hit))

        for s in self.subjects:
            if subject_id is not None and s.id != subject_id:
                continue
            fields = [("name", s.name), ("notes", s.notes)]
            match = first_field(fields)
            if match and all_words_in(s.name, s.notes):
                add(0, match[0], match[1], {"subject_id": s.id}, "subject")
            for p in s.points:
                fields = [("title", p.title), ("notes", p.notes)]
                match = first_field(fields)
                if match and all_words_in(s.name, p.title, p.notes):
                    add(1, match[0], match[1], {"subject_id": s.id, "point_id": p.id}, "point")

        allowed = None if subject_id is None else {i.id for i in self.find_images(subject_id=subject_id)}
        for image in self.images:
            if allowed is not None and image.id not in allowed:
                continue
            fields = [("tag", " ".join(image.tags)), ("file name", image.original_name)]
            match = first_field(fields)
            if match and all_words_in(*[v for _n, v in fields]):
                add(2, match[0], match[1], {"image_id": image.id}, "image")

        found.sort(key=lambda t: t[0])
        hits = [hit for _key, hit in found]
        return hits if limit is None else hits[:limit]

    # ---- consistency
    def integrity_problems(self) -> list[str]:
        """Things that must never be true of a saved database (the JSON Schema cannot check these)."""
        problems, seen = [], set()
        for i in self.images:
            if i.id in seen:
                problems.append(f"image id {i.id} appears twice")
            seen.add(i.id)
        for s in self.subjects:
            for image_id in s.image_ids:
                if image_id not in seen:
                    problems.append(f"subject {s.name!r} lists the missing image {image_id}")
            for p in s.points:
                for image_id in p.image_ids:
                    if image_id not in seen:
                        problems.append(f"study point {p.title!r} lists the missing image {image_id}")
        return problems

    # ---- (de)serialisation
    def to_dict(self) -> dict:
        return {
            "schemaVersion": self.schema_version,
            "subjects": [s.to_dict() for s in self.subjects],
            "images": [i.to_dict() for i in self.images],
        }

    @classmethod
    def from_dict(cls, raw: Any) -> "Database":
        raw = upgrade(raw)
        try:
            return cls(
                subjects=[Subject.from_dict(s) for s in raw.get("subjects", [])],
                images=[ImageRecord.from_dict(i) for i in raw.get("images", [])],
                schema_version=SCHEMA_VERSION,
            )
        except (KeyError, TypeError, AttributeError, ValueError) as exc:
            raise DataFormatError(f"damaged data: {exc!r}") from exc


# --------------------------------------------------------------------------- upgrading old files
def upgrade(raw: Any) -> dict:
    """Return `raw` as a dict in the current schema, migrating older layouts.

    Raises NewerSchemaError for data from a newer app (never to be touched) and DataFormatError
    for anything that is not a usable database. Calling it on current data changes nothing.
    """
    if not isinstance(raw, dict):
        raise DataFormatError("top level of the data file must be an object")
    version = raw.get("schemaVersion", 1)
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise DataFormatError("schemaVersion must be a whole number of at least 1")
    if version > SCHEMA_VERSION:
        raise NewerSchemaError(
            f"data was saved by a newer StudyFlow (schema {version}, this app knows {SCHEMA_VERSION})"
        )
    try:
        if version < 2:
            raw = _v1_to_v2(raw)
    except (KeyError, TypeError, AttributeError) as exc:
        raise DataFormatError(f"damaged data: {exc!r}") from exc
    return raw


def _v1_to_v2(raw: dict) -> dict:
    """v1: every image said which subject/point it belonged to. v2: subjects and points list their images."""
    raw = copy.deepcopy(raw)
    subjects = {s["id"]: s for s in raw.get("subjects", [])}
    points = {}
    for s in subjects.values():
        s.setdefault("imageIds", [])
        for p in s.get("points", []):
            p.setdefault("imageIds", [])
            points[p["id"]] = p
    for image in raw.get("images", []):
        subject_id, point_id = image.pop("subjectId", None), image.pop("pointId", None)
        target = points.get(point_id) or subjects.get(subject_id)
        if target is not None and image["id"] not in target["imageIds"]:
            target["imageIds"].append(image["id"])
    raw["schemaVersion"] = 2
    return raw
