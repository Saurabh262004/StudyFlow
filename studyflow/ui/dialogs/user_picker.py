"""Choose, create, rename or delete a user."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...models import NotFoundError
from ...storage import StorageError
from .. import util
from ..controller import AppController
from .name_dialog import NameDialog


class UserPickerDialog(QDialog):
    """Accepted (result Accepted) when a user was opened. Cancel/close leaves the current user as it was."""

    def __init__(self, controller: AppController, error: Optional[str] = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("Choose user")
        self.setMinimumSize(440, 420)

        heading = QLabel("Who is studying?")
        heading.setObjectName("pageTitle")
        hint = QLabel("Everyone has their own subjects, notes, pictures and settings.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        self.error = QLabel("")
        self.error.setObjectName("errorText")
        self.error.setWordWrap(True)
        self.users = QListWidget()

        self.open_button = QPushButton("Open")
        self.open_button.setDefault(True)
        self.new_button = QPushButton("New user\u2026")
        self.rename_button = QPushButton("Rename\u2026")
        self.delete_button = QPushButton("Delete\u2026")
        self.close_button = QPushButton("Close")

        side = QVBoxLayout()
        for b in (self.open_button, self.new_button, self.rename_button, self.delete_button):
            side.addWidget(b)
        side.addStretch(1)
        side.addWidget(self.close_button)
        body = QHBoxLayout()
        body.addWidget(self.users, 1)
        body.addLayout(side)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)
        layout.addWidget(heading)
        layout.addWidget(hint)
        layout.addWidget(self.error)
        layout.addLayout(body, 1)

        self.open_button.clicked.connect(self.open_selected)
        self.new_button.clicked.connect(self.new_user)
        self.rename_button.clicked.connect(self.rename_user)
        self.delete_button.clicked.connect(self.delete_user)
        self.close_button.clicked.connect(self.reject)
        self.users.itemDoubleClicked.connect(self._on_double_click)
        self.users.currentItemChanged.connect(self._on_current_changed)
        controller.usersChanged.connect(self.refresh)

        self.error.setText(error or "")
        self.refresh()

    # (bound methods rather than lambdas: a lambda holding `self` makes a reference cycle that Python only
    # frees at exit, when Qt is already gone)
    def _on_double_click(self, _item: QListWidgetItem) -> None:
        self.open_selected()

    def _on_current_changed(self, _current, _previous) -> None:
        self._update_buttons()

    # ------------------------------------------------------------------ list
    def refresh(self) -> None:
        selected = self.selected_id()
        current = self.controller.current_user.id if self.controller.current_user else None
        self.users.clear()
        for user in self.controller.users():
            item = QListWidgetItem(user.name + ("   (current)" if user.id == current else ""))
            item.setData(Qt.ItemDataRole.UserRole, user.id)
            item.setToolTip(f"Created {user.created_at.astimezone():%d %b %Y}")
            self.users.addItem(item)
        row = next((i for i in range(self.users.count()) if self.users.item(i).data(Qt.ItemDataRole.UserRole) == (selected or current)), 0)
        if self.users.count():
            self.users.setCurrentRow(row)
        self._update_buttons()

    def selected_id(self) -> Optional[str]:
        item = self.users.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _selected_user(self):
        user_id = self.selected_id()
        return next((u for u in self.controller.users() if u.id == user_id), None)

    def _update_buttons(self) -> None:
        has = self.selected_id() is not None
        for b in (self.open_button, self.rename_button, self.delete_button):
            b.setEnabled(has)

    # ------------------------------------------------------------------ actions
    def open_selected(self) -> None:
        user_id = self.selected_id()
        if user_id is None:
            return
        current = self.controller.current_user
        if current is not None and current.id == user_id:
            self.accept()
            return
        try:
            self.controller.open_user(user_id)
        except (StorageError, NotFoundError) as exc:
            self.error.setText(str(exc))  # shown here, the dialog stays open so another user can be picked
            return
        self.accept()

    def new_user(self) -> None:
        name = NameDialog.ask(self, "New user", "Name of the new user:", self.controller.validate_user_name, ok_text="Create")
        if name is None:
            return
        try:
            self.controller.create_user(name)  # also opens the new user
        except (ValueError, StorageError) as exc:
            util.show_error(self, str(exc))
            return
        self.accept()

    def rename_user(self) -> None:
        user = self._selected_user()
        if user is None:
            return
        name = NameDialog.ask(
            self, "Rename user", f"New name for {user.name}:",
            lambda text: self.controller.validate_user_name(text, ignore_id=user.id), initial=user.name, ok_text="Rename",
        )
        if name is None or name == user.name:
            return
        try:
            self.controller.rename_user(user.id, name)
        except (ValueError, StorageError, NotFoundError) as exc:
            util.show_error(self, str(exc))

    def delete_user(self) -> None:
        user = self._selected_user()
        if user is None:
            return
        answer = util.confirm(
            self, "Delete user", f"Delete \u201c{user.name}\u201d and ALL their data?",
            ok_text="Delete user",
            detail="Their subjects, notes, pictures and settings will be permanently removed. This cannot be undone.",
            checkbox_text="Save a backup first",
        )
        if answer is None:
            return
        if answer:  # the "Save a backup first" box was ticked
            path = util.ask_save_path(self, "Save backup", f"StudyFlow backup {user.name}.zip")
            if path is None:
                return  # no place chosen: do not delete
            try:
                self.controller.export_user_backup(user.id, path)
            except StorageError as exc:
                util.show_error(self, f"The backup failed, so nothing was deleted.\n\n{exc}")
                return
        try:
            self.controller.delete_user(user.id)
        except (StorageError, NotFoundError) as exc:
            util.show_error(self, str(exc))
