"""Several StudyFlow users on one computer, without logging in as a different OS user.

Everything lives under one persistent root folder (see default_data_dir()):

    <root>/
      app.json                 {"lastUser": "<id>"}        (optional, only a convenience)
      users/
        <user id>/             32 hex characters, never the user's name
          user.json            {"name": "...", "createdAt": "..."}
          data.json            that user's subjects, points, notes ...   (see Storage)
          data.json.bak
          images/

* The folder name is a random id, so any display name is allowed (spaces, Hindi, "/", ...)
  and renaming a user never moves files.
* user.json is the only source of truth for a user's name. There is no central index that
  could get out of sync: list_users() simply looks at the folders.
* Users are separate data spaces, NOT a security boundary. Anyone who can open the folder
  with a file manager can read every user's files. (Use OS accounts if you need that.)
"""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import NotFoundError, dt_to_str, new_id, str_to_dt, utc_now
from .storage import PathLike, Storage, StorageError, atomic_write, default_data_dir

USERS_DIR = "users"
USER_FILE = "user.json"
APP_FILE = "app.json"
MAX_NAME_LENGTH = 50
_ID_RE = re.compile(r"^[0-9a-f]{32}$")


@dataclass(frozen=True)
class UserInfo:
    id: str
    name: str
    created_at: datetime


class UserManager:
    def __init__(self, root: Optional[PathLike] = None) -> None:
        self.root = Path(root) if root is not None else default_data_dir()
        self.users_dir = self.root / USERS_DIR
        self.users_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ helpers
    def _user_dir(self, user_id: str) -> Path:
        """Folder of an existing user. The id check also blocks path tricks like '../x'."""
        if not isinstance(user_id, str) or not _ID_RE.match(user_id):
            raise NotFoundError(f"user {user_id!r} not found")
        path = self.users_dir / user_id
        if not path.is_dir():
            raise NotFoundError(f"user {user_id!r} not found")
        return path

    @staticmethod
    def _clean_name(name: str) -> str:
        name = (name or "").strip()
        if not name:
            raise ValueError("user name cannot be empty")
        if len(name) > MAX_NAME_LENGTH:
            raise ValueError(f"user name cannot be longer than {MAX_NAME_LENGTH} characters")
        if not name.isprintable():
            raise ValueError("user name contains invalid characters")
        return name

    def _read_info(self, path: Path) -> UserInfo:
        """Never fails: a missing or damaged user.json must not hide the user's data."""
        name, created = None, None
        try:
            raw = json.loads((path / USER_FILE).read_text(encoding="utf-8"))
            if isinstance(raw.get("name"), str) and raw["name"].strip():
                name = raw["name"].strip()
            created = str_to_dt(raw.get("createdAt"))
        except (OSError, ValueError, AttributeError):
            pass
        if created is None:
            try:
                created = datetime.fromtimestamp(path.stat().st_ctime, tz=timezone.utc)
            except OSError:
                created = utc_now()
        return UserInfo(id=path.name, name=name or f"Unnamed user ({path.name[:6]})", created_at=created)

    def _write_info(self, user_id: str, name: str, created_at: datetime) -> None:
        payload = {"name": name, "createdAt": dt_to_str(created_at)}
        atomic_write(
            self.users_dir / user_id / USER_FILE,
            json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8"),
        )

    def _check_unique(self, name: str, ignore_id: Optional[str] = None) -> None:
        wanted = name.casefold()
        for u in self.list_users():
            if u.id != ignore_id and u.name.casefold() == wanted:
                raise ValueError(f"a user named {u.name!r} already exists")

    # ------------------------------------------------------------------ users
    def list_users(self) -> list[UserInfo]:
        users = [
            self._read_info(p)
            for p in self.users_dir.iterdir()
            if p.is_dir() and _ID_RE.match(p.name)
        ]
        return sorted(users, key=lambda u: (u.name.casefold(), u.created_at))

    def get_user(self, user_id: str) -> UserInfo:
        return self._read_info(self._user_dir(user_id))

    def create_user(self, name: str) -> UserInfo:
        name = self._clean_name(name)
        self._check_unique(name)
        user_id, created = new_id(), utc_now()
        (self.users_dir / user_id).mkdir()
        self._write_info(user_id, name, created)
        return UserInfo(id=user_id, name=name, created_at=created)

    def rename_user(self, user_id: str, new_name: str) -> UserInfo:
        info = self.get_user(user_id)
        new_name = self._clean_name(new_name)
        self._check_unique(new_name, ignore_id=user_id)
        self._write_info(user_id, new_name, info.created_at)
        return UserInfo(id=user_id, name=new_name, created_at=info.created_at)

    def delete_user(self, user_id: str) -> None:
        """Permanently delete a user and ALL their data. The UI must ask for confirmation first
        (and can offer Storage.export_backup() beforehand)."""
        path = self._user_dir(user_id)
        try:
            shutil.rmtree(path)
        except OSError as exc:
            raise StorageError(f"Could not delete the user's data: {exc}") from exc
        if self._read_last_id() == user_id:
            self._write_last_id(None)

    # ------------------------------------------------------------------ switching
    def open_user(self, user_id: str) -> Storage:
        """Select a user. Returns that user's Storage; call .load() on it to get their Database.

        Switching users in the app is just: save (already done after every action),
        call open_user(other_id), load(), and show the new data.
        """
        path = self._user_dir(user_id)
        self._write_last_id(user_id)
        return Storage(path)

    def last_user(self) -> Optional[UserInfo]:
        """The user who was active last time, or None (first run, or that user was deleted)."""
        user_id = self._read_last_id()
        if user_id is None:
            return None
        try:
            return self.get_user(user_id)
        except NotFoundError:
            return None

    def _read_last_id(self) -> Optional[str]:
        try:
            value = json.loads((self.root / APP_FILE).read_text(encoding="utf-8")).get("lastUser")
        except (OSError, ValueError, AttributeError):
            return None
        return value if isinstance(value, str) else None

    def _write_last_id(self, user_id: Optional[str]) -> None:
        try:
            atomic_write(
                self.root / APP_FILE,
                json.dumps({"lastUser": user_id}, indent=2).encode("utf-8"),
            )
        except StorageError:
            pass  # only a convenience; failing to remember the last user must never block the app
