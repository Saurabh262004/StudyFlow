"""The form for one study point: title, deadline, effort, done, notes."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable, Optional

from PySide6.QtCore import QDateTime, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDateTimeEdit,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QWidget,
)

from ...models import StudyPoint
from .. import style
from .notes_edit import NotesEdit

MAX_EFFORT = 500.0


def to_qdatetime(moment: datetime) -> QDateTime:
    local = moment.astimezone()
    return QDateTime(local.year, local.month, local.day, local.hour, local.minute, local.second)


def default_deadline() -> datetime:
    """Tomorrow 18:00 local time: what the picker shows when you tick "Has a deadline"."""
    tomorrow = datetime.now().astimezone() + timedelta(days=1)
    return tomorrow.replace(hour=18, minute=0, second=0, microsecond=0)


class PointEditor(QGroupBox):
    """Remembers which fields the USER changed (`pending()`), so loading a point, or a rounded display value,
    can never be mistaken for an edit and silently rewrite data."""

    edited = Signal()  # the user changed something (the page saves after a short pause)
    deleteRequested = Signal()
    finishedEditing = Signal()  # focus left the notes box (a good moment to save)

    def __init__(self, parent: Optional[QWidget] = None, images_widget: Optional[QWidget] = None) -> None:
        super().__init__("Study point", parent)
        self._loading = False
        self._dirty: set[str] = set()

        self.title_edit = QLineEdit()
        self.has_deadline = QCheckBox("Deadline")
        self.deadline = QDateTimeEdit()
        self.deadline.setCalendarPopup(True)
        self.deadline.setDisplayFormat("dd MMM yyyy  HH:mm")
        style.plain_calendar(self.deadline)
        self.has_effort = QCheckBox("Effort")
        self.effort = QDoubleSpinBox()
        self.effort.setRange(0.25, MAX_EFFORT)
        self.effort.setSingleStep(0.25)
        self.effort.setDecimals(2)
        self.effort.setSuffix(" h")
        style.pad_spin_box(self.effort)
        self.done = QCheckBox("Done")
        self.notes = NotesEdit()
        self.notes.setPlaceholderText("Notes for this study point\u2026")
        self.notes.setMinimumHeight(60)
        self.error = QLabel("")
        self.error.setObjectName("errorText")
        self.delete_button = QPushButton("Delete point")

        grid = QGridLayout(self)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        grid.setContentsMargins(12, 12, 12, 8)
        grid.addWidget(QLabel("Title"), 0, 0)
        grid.addWidget(self.title_edit, 0, 1, 1, 4)
        grid.addWidget(self.delete_button, 0, 5)
        grid.addWidget(self.has_deadline, 1, 0)
        grid.addWidget(self.deadline, 1, 1)
        grid.addWidget(self.has_effort, 1, 2)
        grid.addWidget(self.effort, 1, 3)
        grid.addWidget(self.done, 1, 4)
        grid.addWidget(self.error, 1, 5)
        # notes and pictures share the space below the fields, as two tabs
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self.notes, "Notes")
        self.images_widget = images_widget
        if images_widget is not None:
            self.tabs.addTab(images_widget, "Pictures")
        grid.addWidget(self.tabs, 2, 0, 1, 6)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(2, 1)

        self.title_edit.textChanged.connect(self._title_changed)
        self.has_deadline.toggled.connect(self._deadline_toggled)
        self.deadline.dateTimeChanged.connect(self._deadline_changed)
        self.has_effort.toggled.connect(self._effort_toggled)
        self.effort.valueChanged.connect(self._effort_changed)
        self.done.toggled.connect(self._done_changed)
        self.notes.textChanged.connect(self._notes_changed)
        self.notes.editingFinished.connect(self.finishedEditing)
        self.delete_button.clicked.connect(self.deleteRequested)
        self.load(None)

    def set_pictures_count(self, count: int) -> None:
        """Show how many pictures the point has on the tab, so they are noticed even when the tab is not open."""
        if self.images_widget is not None:
            self.tabs.setTabText(1, f"Pictures ({count})" if count else "Pictures")

    # ------------------------------------------------------------------ user edits (bound methods, no lambdas)
    def _touch(self, field: str) -> None:
        if self._loading:
            return
        self._dirty.add(field)
        self.edited.emit()

    def _title_changed(self, _text: str) -> None:
        self._touch("title")

    def _deadline_toggled(self, checked: bool) -> None:
        self.deadline.setEnabled(checked)
        self._touch("deadline")

    def _deadline_changed(self, _value) -> None:
        self._touch("deadline")

    def _effort_toggled(self, checked: bool) -> None:
        self.effort.setEnabled(checked)
        self._touch("effort")

    def _effort_changed(self, _value: float) -> None:
        self._touch("effort")

    def _done_changed(self, _checked: bool) -> None:
        self._touch("done")

    def _notes_changed(self) -> None:
        self._touch("notes")

    # ------------------------------------------------------------------ state
    @property
    def is_dirty(self) -> bool:
        return bool(self._dirty)

    def clear_dirty(self, fields: Optional[Iterable[str]] = None) -> None:
        if fields is None:
            self._dirty.clear()
        else:
            self._dirty.difference_update(fields)

    def set_error(self, text: str) -> None:
        self.error.setText(text)

    def pending(self) -> dict:
        """The fields the user changed, as keyword arguments for AppController.update_point."""
        values = {}
        if "title" in self._dirty:
            values["title"] = self.title_edit.text().strip()
        if "notes" in self._dirty:
            values["notes"] = self.notes.toPlainText()
        if "deadline" in self._dirty:
            values["deadline"] = self.deadline.dateTime().toPython() if self.has_deadline.isChecked() else None
        if "effort" in self._dirty:
            values["effort_hours"] = float(self.effort.value()) if self.has_effort.isChecked() else None
        if "done" in self._dirty:
            values["done"] = self.done.isChecked()
        return values

    def load(self, point: Optional[StudyPoint]) -> None:
        """Show a point (or an empty, disabled form for None). Widgets are only touched when their value
        differs, so a refresh does not move the cursor of someone who is typing."""
        self._loading = True
        try:
            self._dirty.clear()
            self.error.setText("")
            self.setEnabled(point is not None)
            self.title_edit.setPlaceholderText("Select a study point to edit it" if point is None else "Title")
            if point is None:
                self.title_edit.clear()
                self.notes.clear()
                self.has_deadline.setChecked(False)
                self.has_effort.setChecked(False)
                self.done.setChecked(False)
                self.deadline.setEnabled(False)
                self.effort.setEnabled(False)
                return
            if self.title_edit.text() != point.title:
                self.title_edit.setText(point.title)
            if self.notes.toPlainText() != point.notes:
                self.notes.setPlainText(point.notes)
            self.has_deadline.setChecked(point.deadline is not None)
            wanted = to_qdatetime(point.deadline or default_deadline())
            if self.deadline.dateTime() != wanted:
                self.deadline.setDateTime(wanted)
            self.deadline.setEnabled(point.deadline is not None)
            self.has_effort.setChecked(point.effort_hours is not None)
            shown = min(point.effort_hours or 1.0, MAX_EFFORT)
            if abs(self.effort.value() - shown) > 1e-9:
                self.effort.setValue(shown)
            self.effort.setEnabled(point.effort_hours is not None)
            self.done.setChecked(point.done)
        finally:
            self._loading = False
