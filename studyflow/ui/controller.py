"""AppController: the one object the user interface talks to.

It owns the state of the running app (which user is open, their Database, their settings) and is the
ONLY place that changes data. Every change follows the same three steps:

    1. validate and apply the change to the Database      (models.py rules)
    2. save it to disk straight away                      (storage.py, atomic)
    3. emit a signal so every screen refreshes

so there is no Save button and nothing can be lost when the app closes.

Errors
------
Methods raise instead of showing dialogs (the UI decides how to show them):
  * ValueError     bad input (empty name, effort <= 0 ...). Nothing was changed.
  * NotFoundError  an id that does not exist. Nothing was changed.
  * StorageError   the disk (or an input file) was refused. If an unsaved change was left in memory, the
                   controller has already reloaded the data from disk and emitted dataChanged, so what the
                   screens show is what is really saved. For harmless errors nothing is refreshed.
  * NoUserOpenError  no user is open (before start(), or the open user was just deleted).

Signals
-------
  usersChanged     the list of users changed (created, renamed, deleted)
  userChanged      a different user was opened, or the open user went away: rebuild every screen
  dataChanged      subjects, study points, notes or images of the open user changed: refresh views
  settingsChanged  the planning settings changed: refresh the priority view
  warningsChanged  `warnings` changed: show or hide the banner
  tick             once a minute after start_clock(): refresh "time left" texts
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Optional

from PySide6.QtCore import QObject, QTimer, Signal

from ..models import (
    Database,
    ImageRecord,
    SearchHit,
    StudyPoint,
    Subject,
    _check_effort,
    _clean_name,
    normalise_tags,
    to_utc,
    utc_now,
)
from ..priority import PlanSettings, PointPriority, next_up, rank_points
from ..storage import PathLike, Storage, StorageError
from ..users import UserInfo, UserManager

START_READY = "ready"  # the last user was opened automatically
START_CHOOSE_USER = "choose_user"  # users exist but none could be opened: show the user picker
START_CREATE_FIRST_USER = "create_first_user"  # nobody exists yet: ask for a name

_UNSET = object()  # "leave this field alone" (None would mean "clear it")


class NoUserOpenError(RuntimeError):
    """An operation needs an open user but there is none."""


@dataclass(frozen=True)
class StartResult:
    state: str  # one of the START_* values
    error: Optional[str] = None  # why the last user could not be opened, if that was the reason


class AppController(QObject):
    usersChanged = Signal()
    userChanged = Signal()
    dataChanged = Signal()
    settingsChanged = Signal()
    warningsChanged = Signal()
    tick = Signal()

    def __init__(
        self,
        root: Optional[PathLike] = None,
        now: Callable[[], datetime] = utc_now,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.manager = UserManager(root)
        self._now = now  # injectable so the priority view can be tested with a fixed clock
        self.store: Optional[Storage] = None
        self.db: Optional[Database] = None
        self.current_user: Optional[UserInfo] = None
        self.settings = PlanSettings()
        self.warnings: list[str] = []  # messages the UI should show (restored from backup, upgraded format ...)
        self._store_warning_mark = 0
        self._timer: Optional[QTimer] = None

    # ================================================================== start-up and users
    def start(self) -> StartResult:
        """Call once when the app starts. Opens the last used user if there is one."""
        if not self.manager.list_users():
            return StartResult(START_CREATE_FIRST_USER)
        last = self.manager.last_user()
        if last is not None:
            try:
                self.open_user(last.id)
                return StartResult(START_READY)
            except StorageError as exc:
                return StartResult(START_CHOOSE_USER, str(exc))
        return StartResult(START_CHOOSE_USER)

    def users(self) -> list[UserInfo]:
        return self.manager.list_users()

    def now(self) -> datetime:
        """The current time (the injected clock in tests)."""
        return self._now()

    @property
    def is_open(self) -> bool:
        return self.db is not None

    def validate_user_name(self, name: str, ignore_id: Optional[str] = None) -> Optional[str]:
        """None if `name` is acceptable for a (new or renamed) user, else a message saying why not."""
        try:
            self.manager.validate_name(name, ignore_id)
        except ValueError as exc:
            message = str(exc)
            return message[:1].upper() + message[1:]
        return None

    def export_user_backup(self, user_id: str, destination: PathLike) -> Path:
        """Backup of any user's data, open or not (used before deleting a user)."""
        return self.manager.storage_for(user_id).export_backup(destination)

    def create_user(self, name: str, open_it: bool = True) -> UserInfo:
        info = self.manager.create_user(name)  # ValueError for a bad or duplicate name
        self.usersChanged.emit()
        if open_it:
            self.open_user(info.id)
        return info

    def rename_user(self, user_id: str, new_name: str) -> UserInfo:
        info = self.manager.rename_user(user_id, new_name)
        if self.current_user is not None and self.current_user.id == user_id:
            self.current_user = info
        self.usersChanged.emit()
        return info

    def delete_user(self, user_id: str) -> None:
        """Permanently delete a user and all their data. The UI must ask for confirmation first."""
        was_open = self.current_user is not None and self.current_user.id == user_id
        self.manager.delete_user(user_id)
        if was_open:
            self._close()
        self.usersChanged.emit()
        if was_open:
            self.userChanged.emit()

    def open_user(self, user_id: str) -> None:
        """Open (switch to) a user. If that fails the previously open user stays open, unchanged."""
        info = self.manager.get_user(user_id)
        store = self.manager.storage_for(user_id)
        db = store.load()  # StorageError e.g. for data saved by a newer version of the app
        settings = store.load_settings()
        self.manager.remember_user(user_id)  # only after loading worked
        self.store, self.db, self.settings, self.current_user = store, db, settings, info
        self.warnings = list(store.warnings)
        self._store_warning_mark = len(store.warnings)
        self.userChanged.emit()
        self.warningsChanged.emit()

    def _close(self) -> None:
        self.store = self.db = self.current_user = None
        self.settings = PlanSettings()
        self.warnings = []
        self._store_warning_mark = 0
        self.warningsChanged.emit()

    def dismiss_warnings(self) -> None:
        self.warnings = []
        self.warningsChanged.emit()

    # ================================================================== internals
    def _ensure_open(self) -> None:
        if self.db is None or self.store is None:
            raise NoUserOpenError("no user is open")

    def _change(self, action: Callable[[], object]):
        """Run `action` (which changes self.db and saves), then tell the views. On a disk error, put the
        in-memory data back in line with what is really on disk before re-raising."""
        self._ensure_open()
        try:
            result = action()
        except StorageError:
            self._resync_from_disk()
            raise
        self._pick_up_store_warnings()
        self.dataChanged.emit()
        return result

    def _resync_from_disk(self) -> None:
        """After a StorageError: if memory and disk now disagree (an unsaved change is still in memory), reload
        from disk and tell the views. If they agree (the error was harmless, e.g. 'file not found'), do nothing."""
        try:
            fresh = self.store.load()
        except StorageError:
            return  # keep what we have; the original error is the important one
        if self.store.warnings:  # e.g. the file on disk turned out to be damaged and was restored from backup
            self.warnings.extend(self.store.warnings)
            self._store_warning_mark = len(self.store.warnings)
            self.warningsChanged.emit()
        if fresh.to_dict() != self.db.to_dict():
            self.db = fresh
            self.dataChanged.emit()

    def _pick_up_store_warnings(self) -> None:
        new = self.store.warnings[self._store_warning_mark:]
        if new:
            self.warnings.extend(new)
            self._store_warning_mark = len(self.store.warnings)
            self.warningsChanged.emit()

    # ================================================================== subjects
    def add_subject(self, name: str, notes: str = "") -> Subject:
        def act():
            subject = self.db.add_subject(name, notes)
            self.store.save(self.db)
            return subject

        return self._change(act)

    def rename_subject(self, subject_id: str, name: str) -> None:
        def act():
            subject = self.db.get_subject(subject_id)
            subject.name = _clean_name(name, "subject name")
            self.store.save(self.db)

        self._change(act)

    def set_subject_notes(self, subject_id: str, notes: str) -> None:
        def act():
            self.db.get_subject(subject_id).notes = notes
            self.store.save(self.db)

        self._change(act)

    def delete_subject(self, subject_id: str) -> None:
        """Deletes the subject, its study points, and every picture nothing else uses."""
        self._change(lambda: self.store.delete_subject(self.db, subject_id))

    # ================================================================== study points
    def add_point(
        self,
        subject_id: str,
        title: str,
        notes: str = "",
        deadline: Optional[datetime] = None,
        effort_hours: Optional[float] = None,
    ) -> StudyPoint:
        def act():
            point = self.db.add_point(subject_id, title, notes, deadline, effort_hours)
            self.store.save(self.db)
            return point

        return self._change(act)

    def update_point(
        self,
        subject_id: str,
        point_id: str,
        *,
        title=_UNSET,
        notes=_UNSET,
        deadline=_UNSET,
        effort_hours=_UNSET,
        done=_UNSET,
    ) -> None:
        """Change only the fields you pass. deadline=None / effort_hours=None clear them.
        All values are checked before anything is changed, so a bad value changes nothing."""

        def act():
            point = self.db.get_point(subject_id, point_id)
            changes = {}
            if title is not _UNSET:
                changes["title"] = _clean_name(title, "study point title")
            if notes is not _UNSET:
                changes["notes"] = notes
            if deadline is not _UNSET:
                changes["deadline"] = None if deadline is None else to_utc(deadline)
            if effort_hours is not _UNSET:
                changes["effort_hours"] = _check_effort(effort_hours)
            if done is not _UNSET:
                changes["done"] = bool(done)
            for name, value in changes.items():
                setattr(point, name, value)
            self.store.save(self.db)

        self._change(act)

    def set_point_done(self, subject_id: str, point_id: str, done: bool) -> None:
        self.update_point(subject_id, point_id, done=done)

    def delete_point(self, subject_id: str, point_id: str) -> None:
        self._change(lambda: self.store.delete_point(self.db, subject_id, point_id))

    # ================================================================== images
    def import_image(
        self,
        source: PathLike,
        subject_id: str,
        point_id: Optional[str] = None,
        tags: Iterable[str] = (),
    ) -> ImageRecord:
        """Copy a picture into the app and show it on a subject or study point."""
        return self._change(lambda: self.store.attach_image(self.db, source, subject_id, point_id, tags))

    def link_image(self, image_id: str, subject_id: str, point_id: Optional[str] = None) -> None:
        """Show an already imported picture somewhere else too (no copy is made)."""
        self._change(lambda: self.store.link_image(self.db, image_id, subject_id, point_id))

    def unlink_image(self, image_id: str, subject_id: str, point_id: Optional[str] = None) -> bool:
        """Stop showing a picture there. Returns True if that was its last use and it was deleted,
        so the UI should ask for confirmation first when `len(usage(image_id)) == 1`."""
        return self._change(lambda: self.store.unlink_image(self.db, image_id, subject_id, point_id))

    def delete_image(self, image_id: str) -> None:
        """Delete a picture everywhere it is used."""
        self._change(lambda: self.store.delete_image(self.db, image_id))

    def set_image_tags(self, image_id: str, tags: Iterable[str]) -> None:
        def act():
            self.db.get_image(image_id).tags = normalise_tags(tags)
            self.store.save(self.db)

        self._change(act)

    # ================================================================== reading (never changes anything)
    def subjects(self) -> list[Subject]:
        """The open user's subjects. Treat the result as read-only: change things through this controller."""
        self._ensure_open()
        return self.db.subjects

    def get_subject(self, subject_id: str) -> Subject:
        self._ensure_open()
        return self.db.get_subject(subject_id)

    def get_point(self, subject_id: str, point_id: str) -> StudyPoint:
        self._ensure_open()
        return self.db.get_point(subject_id, point_id)

    def images_of(self, subject_id: str, point_id: Optional[str] = None) -> list[ImageRecord]:
        self._ensure_open()
        return self.db.images_of(subject_id, point_id)

    def all_images(self) -> list[ImageRecord]:
        self._ensure_open()
        return list(self.db.images)

    def usage(self, image_id: str) -> list[tuple[str, Optional[str]]]:
        self._ensure_open()
        return self.db.usage(image_id)

    def find_images(self, subject_id=None, point_id=None, tag=None) -> list[ImageRecord]:
        self._ensure_open()
        return self.db.find_images(subject_id, point_id, tag)

    def image_path(self, record: ImageRecord) -> Path:
        self._ensure_open()
        return self.store.image_path(record)

    def get_image(self, image_id: str) -> ImageRecord:
        self._ensure_open()
        return self.db.get_image(image_id)

    def tag_counts(self) -> dict[str, int]:
        """Every tag used on any picture, with how many pictures carry it, sorted by name."""
        self._ensure_open()
        counts: dict[str, int] = {}
        for image in self.db.images:
            for tag in image.tags:
                counts[tag] = counts.get(tag, 0) + 1
        return dict(sorted(counts.items()))

    def describe_usage(self, image_id: str) -> list[str]:
        """Where a picture is shown, in words: "Operating Systems" or "Operating Systems \u203a Deadlocks"."""
        self._ensure_open()
        places = []
        for subject_id, point_id in self.db.usage(image_id):
            subject = self.db.get_subject(subject_id)
            places.append(subject.name if point_id is None else f"{subject.name} \u203a {self.db.get_point(subject_id, point_id).title}")
        return places

    def search(self, text: str, subject_id: Optional[str] = None, limit: Optional[int] = None) -> list[SearchHit]:
        self._ensure_open()
        return self.db.search(text, subject_id=subject_id, limit=limit)

    def ranking(self, subject_id: Optional[str] = None, include_done: bool = False) -> list[PointPriority]:
        """The priority view: every unfinished study point, most urgent first."""
        self._ensure_open()
        return rank_points(self.db, now=self._now(), settings=self.settings, subject_id=subject_id, include_done=include_done)

    def next_up(self, subject_id: Optional[str] = None) -> Optional[PointPriority]:
        self._ensure_open()
        return next_up(self.db, now=self._now(), settings=self.settings, subject_id=subject_id)

    # ================================================================== settings, backup, clock
    def set_settings(self, settings: PlanSettings) -> None:
        self._ensure_open()
        self.store.save_settings(settings)  # StorageError propagates; self.settings stays as it was
        self.settings = settings
        self._pick_up_store_warnings()
        self.settingsChanged.emit()

    def export_backup(self, destination: PathLike) -> Path:
        """Write one .zip with all of the open user's data. Returns the real path (".zip" is added if missing)."""
        self._ensure_open()
        return self.store.export_backup(destination)

    def restore_backup(self, archive: PathLike) -> None:
        """Replace the open user's data with a backup. A snapshot of the current data is kept first.
        The UI must ask for confirmation first."""
        self._ensure_open()
        try:
            db = self.store.restore_backup(archive)
        except StorageError:
            self._resync_from_disk()
            raise
        self.db = db
        self.settings = self.store.load_settings()
        self._pick_up_store_warnings()
        self.dataChanged.emit()
        self.settingsChanged.emit()

    def start_clock(self, interval_ms: int = 60_000) -> None:
        """Emit `tick` every interval so "time left" texts stay current. Needs a running Qt event loop."""
        if self._timer is None:
            self._timer = QTimer(self)
            self._timer.timeout.connect(self.tick)
        self._timer.start(interval_ms)

    def stop_clock(self) -> None:
        if self._timer is not None:
            self._timer.stop()
