"""StudyFlow storage: loads and saves the Database as JSON, and manages image files.

Design rules (the user's notes cannot be regenerated, so data safety comes first):
  * Saves are atomic: write a temp file, fsync it, then os.replace() it over data.json.
    A crash or power cut can never leave a half-written data.json.
  * The previous data.json is copied to data.json.bak before every replace.
  * A damaged data.json is NEVER overwritten. It is moved aside to
    data.corrupt-<time>.json and the .bak is tried instead.
  * Data written by a newer version of the app is never touched (NewerSchemaError).
  * studyflow.schema.json (JSON Schema) is checked on every load AND before every save.
    A save that would write invalid data is refused before the existing file is touched.
  * Database records are saved BEFORE image files are deleted, so a crash leaves a
    stray file at worst, never a record pointing at a missing picture.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Optional, Union

from jsonschema import Draft202012Validator

from .models import (
    Database,
    DataFormatError,
    ImageRecord,
    NewerSchemaError,
)

DATA_FILE = "data.json"
BACKUP_FILE = "data.json.bak"
IMAGE_DIR = "images"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}

PathLike = Union[str, os.PathLike]

SCHEMA_FILE = Path(__file__).with_name("studyflow.schema.json")
_VALIDATOR = Draft202012Validator(json.loads(SCHEMA_FILE.read_text(encoding="utf-8")))


def schema_errors(data: Any) -> list[str]:
    """Human-readable problems found when checking `data` against the JSON Schema (empty = valid)."""
    problems = []
    for err in sorted(_VALIDATOR.iter_errors(data), key=lambda e: list(map(str, e.absolute_path))):
        where = ""
        for part in err.absolute_path:
            where += f"[{part}]" if isinstance(part, int) else f".{part}"
        problems.append(f"{where.lstrip('.') or '(root)'}: {err.message}")
    return problems


class StorageError(Exception):
    """A storage operation failed. The message is safe to show to the user."""


def default_data_dir(app_name: str = "StudyFlow") -> Path:
    """Per-user data folder that works the same on Windows and Linux."""
    try:
        from platformdirs import user_data_dir

        return Path(user_data_dir(app_name, appauthor=False))
    except ImportError:  # platformdirs is optional
        return Path.home() / f".{app_name.lower()}"


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def atomic_write(path: Path, payload: bytes, backup: Optional[Path] = None) -> None:
    """Write `payload` to `path` so that a crash can never leave a half-written file.

    Writes a temp file next to it, fsyncs, optionally copies the old file to `backup`,
    then swaps the new file in with os.replace() (atomic on Windows and Linux).
    """
    tmp_name = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        if backup is not None and path.exists():
            shutil.copy2(path, backup)
        os.replace(tmp_name, path)
        tmp_name = None
    except OSError as exc:
        raise StorageError(f"Could not write {path.name}: {exc}") from exc
    finally:
        if tmp_name is not None:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


class Storage:
    """Data for ONE user, kept in `data_dir`. Use UserManager to get the right folder."""

    def __init__(self, data_dir: PathLike) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        # Messages from the last load() that the UI should show to the user.
        self.warnings: list[str] = []

    # ------------------------------------------------------------------ paths
    @property
    def data_file(self) -> Path:
        return self.data_dir / DATA_FILE

    @property
    def backup_file(self) -> Path:
        return self.data_dir / BACKUP_FILE

    @property
    def images_dir(self) -> Path:
        return self.data_dir / IMAGE_DIR

    def image_path(self, record: ImageRecord) -> Path:
        """Absolute path of an image, refusing anything that points outside the data folder."""
        path = (self.data_dir / record.file).resolve()
        if self.data_dir.resolve() not in path.parents:
            raise StorageError(f"image path escapes the data folder: {record.file!r}")
        return path

    # ------------------------------------------------------------------ load
    @staticmethod
    def _read(path: Path) -> Database:
        """Read one JSON file. Raises ValueError/DataFormatError if it is damaged."""
        with open(path, "rb") as f:
            raw = json.loads(f.read().decode("utf-8"))
        db = Database.from_dict(raw)  # raises NewerSchemaError first, so newer files are never judged by this schema
        # When migrations exist, validate the migrated dict here instead of `raw`.
        problems = schema_errors(raw)
        if problems:
            shown = "; ".join(problems[:3]) + (f" (+{len(problems) - 3} more)" if len(problems) > 3 else "")
            raise DataFormatError(f"data does not match the schema: {shown}")
        return db

    def load(self) -> Database:
        """Load the database. Check `self.warnings` afterwards and show them to the user."""
        self.warnings = []
        try:
            if self.data_file.exists():
                return self._read(self.data_file)
            if not self.backup_file.exists():
                return Database()  # first run
            db = self._restore_from_backup()
            if db is not None:
                self.warnings.append("data.json was missing; restored your data from the last backup.")
                return db
            self.warnings.append("data.json was missing and the backup could not be read; started empty.")
            return Database()
        except NewerSchemaError as exc:
            raise StorageError(f"{exc}. Please update StudyFlow.") from exc
        except OSError as exc:
            raise StorageError(f"Could not read your data: {exc}") from exc
        except ValueError:  # includes JSONDecodeError, UnicodeDecodeError and DataFormatError
            return self._recover_from_corruption()

    def _restore_from_backup(self) -> Optional[Database]:
        try:
            db = self._read(self.backup_file)
        except (ValueError, OSError):
            return None
        shutil.copy2(self.backup_file, self.data_file)
        return db

    def _recover_from_corruption(self) -> Database:
        quarantine = self.data_dir / f"data.corrupt-{_stamp()}.json"
        try:
            os.replace(self.data_file, quarantine)
        except OSError as exc:
            raise StorageError(f"Your data file is damaged and could not be moved aside: {exc}") from exc
        self.warnings.append(f"Your data file was damaged. A copy was kept as {quarantine.name}.")
        db = self._restore_from_backup() if self.backup_file.exists() else None
        if db is not None:
            self.warnings.append("Your data was restored from the last backup; recent changes may be missing.")
            return db
        self.warnings.append("No usable backup was found, so StudyFlow started with an empty database.")
        return Database()

    # ------------------------------------------------------------------ save
    def save(self, db: Database) -> None:
        data = db.to_dict()
        problems = schema_errors(data)
        if problems:  # a bug or bad value in memory: refuse BEFORE touching the saved file
            raise StorageError("Refusing to save invalid data (your saved file was not changed): " + "; ".join(problems[:3]))
        payload = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        atomic_write(self.data_file, payload, backup=self.backup_file)

    # ------------------------------------------------------------------ images
    def attach_image(
        self,
        db: Database,
        source: PathLike,
        subject_id: str,
        point_id: Optional[str] = None,
        tags: Iterable[str] = (),
    ) -> ImageRecord:
        """Copy a picture into the data folder, add its record to `db` and save."""
        source = Path(source)
        if not source.is_file():
            raise StorageError(f"File not found: {source}")
        ext = source.suffix.lower()
        if ext not in IMAGE_EXTENSIONS:
            raise StorageError(f"Unsupported image type {ext or '(none)'}. Use one of: {', '.join(sorted(IMAGE_EXTENSIONS))}")
        db.get_subject(subject_id)  # raises NotFoundError for bad ids
        if point_id is not None:
            db.get_point(subject_id, point_id)

        record = ImageRecord(file="", subject_id=subject_id, point_id=point_id, tags=list(tags), original_name=source.name)
        record.file = f"{IMAGE_DIR}/{record.id}{ext}"
        dest = self.image_path(record)
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
        except OSError as exc:
            raise StorageError(f"Could not copy the image: {exc}") from exc

        db.images.append(record)
        try:
            self.save(db)
        except Exception:
            db.images.remove(record)
            dest.unlink(missing_ok=True)
            raise
        return record

    def delete_image(self, db: Database, image_id: str) -> None:
        record = db.get_image(image_id)
        db.images.remove(record)
        self.save(db)
        self._delete_files([record])

    def delete_subject(self, db: Database, subject_id: str) -> None:
        removed = db.remove_subject(subject_id)
        self.save(db)
        self._delete_files(removed)

    def delete_point(self, db: Database, subject_id: str, point_id: str) -> None:
        removed = db.remove_point(subject_id, point_id)
        self.save(db)
        self._delete_files(removed)

    def _delete_files(self, records: Iterable[ImageRecord]) -> None:
        for record in records:
            try:
                self.image_path(record).unlink(missing_ok=True)
            except (OSError, StorageError) as exc:
                self.warnings.append(f"Could not delete {record.file}: {exc}")

    # ------------------------------------------------------------------ backup / restore
    def export_backup(self, destination: PathLike) -> Path:
        """Write data.json and all images into one .zip file the user can keep anywhere."""
        if not self.data_file.exists():
            raise StorageError("There is no data to back up yet.")
        destination = Path(destination)
        if destination.suffix.lower() != ".zip":
            destination = destination.with_suffix(".zip")
        try:
            with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(self.data_file, DATA_FILE)
                if self.images_dir.is_dir():
                    for file in sorted(self.images_dir.iterdir()):
                        if file.is_file():
                            zf.write(file, f"{IMAGE_DIR}/{file.name}")
        except OSError as exc:
            raise StorageError(f"Could not write the backup: {exc}") from exc
        return destination

    def restore_backup(self, archive: PathLike) -> Database:
        """Replace the current data with a backup made by export_backup().

        The current data is first saved as pre-restore-<time>.zip inside the data folder.
        """
        archive = Path(archive)
        try:
            zf = zipfile.ZipFile(archive)
        except (OSError, zipfile.BadZipFile) as exc:
            raise StorageError(f"Not a valid backup file: {exc}") from exc
        with zf:
            names = zf.namelist()
            if DATA_FILE not in names:
                raise StorageError("This zip file is not a StudyFlow backup (data.json is missing).")
            for name in names:
                posix = PurePosixPath(name)
                safe = (
                    "\\" not in name
                    and not posix.is_absolute()
                    and ".." not in posix.parts
                    and (name == DATA_FILE or posix.parts[0] == IMAGE_DIR)
                )
                if not safe:
                    raise StorageError(f"The backup contains an unexpected entry: {name!r}")

            with tempfile.TemporaryDirectory(dir=self.data_dir) as tmp:
                zf.extractall(tmp)
                try:
                    db = self._read(Path(tmp) / DATA_FILE)
                except NewerSchemaError as exc:
                    raise StorageError(f"{exc}. Please update StudyFlow.") from exc
                except ValueError as exc:
                    raise StorageError(f"The backup's data is damaged: {exc}") from exc

                if self.data_file.exists():
                    self.export_backup(self.data_dir / f"pre-restore-{_stamp()}.zip")

                new_images = Path(tmp) / IMAGE_DIR
                try:
                    if self.images_dir.exists():
                        shutil.rmtree(self.images_dir)
                    if new_images.is_dir():
                        shutil.move(str(new_images), str(self.images_dir))
                    else:
                        self.images_dir.mkdir()
                except OSError as exc:
                    raise StorageError(f"Could not replace the images folder: {exc}") from exc
        self.save(db)
        return db
