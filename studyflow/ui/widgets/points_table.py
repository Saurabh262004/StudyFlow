"""The table of a subject's study points: done checkbox, title, deadline, effort, time left."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableView, QWidget

from ...models import NotFoundError, StudyPoint
from ...priority import format_remaining
from ...storage import StorageError
from .. import style
from ..controller import AppController, NoUserOpenError

COL_DONE, COL_TITLE, COL_DEADLINE, COL_EFFORT, COL_LEFT = range(5)
HEADERS = ["", "Study point", "Deadline", "Effort", "Time left"]
DASH = "\u2014"


class PointsModel(QAbstractTableModel):
    """Read-only view of one subject's points; only the Done checkbox can be changed (through the controller)."""

    errorRaised = Signal(str)

    def __init__(self, controller: AppController, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.subject_id: Optional[str] = None
        self._points: list[StudyPoint] = []

    # ------------------------------------------------------------------ loading
    def set_subject(self, subject_id: Optional[str]) -> None:
        self.beginResetModel()
        self.subject_id = subject_id
        self._points = self._read()
        self.endResetModel()

    def refresh(self) -> None:
        """Re-read the points. If only values changed (same points, same order) the rows are updated in
        place, which is safe even while the view is in the middle of handling a click."""
        points = self._read()
        if [p.id for p in points] == [p.id for p in self._points]:
            self._points = points
            if points:
                self.dataChanged.emit(self.index(0, 0), self.index(len(points) - 1, len(HEADERS) - 1))
            return
        self.beginResetModel()
        self._points = points
        self.endResetModel()

    def refresh_times(self) -> None:
        """The clock ticked: only the "Time left" column can have changed."""
        if self._points:
            self.dataChanged.emit(self.index(0, COL_LEFT), self.index(len(self._points) - 1, COL_LEFT))

    def _read(self) -> list[StudyPoint]:
        if self.subject_id is None or not self.controller.is_open:
            return []
        try:
            return list(self.controller.get_subject(self.subject_id).points)
        except (NotFoundError, NoUserOpenError):
            self.subject_id = None
            return []

    def point_at(self, row: int) -> StudyPoint:
        return self._points[row]

    def row_of(self, point_id: str) -> int:
        return next((i for i, p in enumerate(self._points) if p.id == point_id), -1)

    # ------------------------------------------------------------------ Qt model interface
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._points)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return HEADERS[section]
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == COL_DONE:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def time_left_text(self, point: StudyPoint) -> str:
        if point.done:
            return "done"
        if point.deadline is None:
            return DASH
        return format_remaining(point.deadline - self.controller.now())

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._points):
            return None
        p, col = self._points[index.row()], index.column()
        if role == Qt.ItemDataRole.CheckStateRole and col == COL_DONE:
            return Qt.CheckState.Checked if p.done else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.DisplayRole:
            if col == COL_TITLE:
                return p.title
            if col == COL_DEADLINE:
                return DASH if p.deadline is None else p.deadline.astimezone().strftime("%d %b %Y, %H:%M")
            if col == COL_EFFORT:
                return DASH if p.effort_hours is None else f"{p.effort_hours:g} h"
            if col == COL_LEFT:
                return self.time_left_text(p)
        elif role == Qt.ItemDataRole.FontRole and p.done and col != COL_DONE:
            font = QFont()  # only "strike out" is set, the rest (family, size) comes from the table itself
            font.setStrikeOut(True)
            return font
        elif role == Qt.ItemDataRole.ForegroundRole:
            colors = style.current()
            if p.done and col != COL_DONE:
                return QBrush(QColor(colors.muted))
            if col == COL_LEFT and p.deadline is not None and p.deadline <= self.controller.now():
                return QBrush(QColor(colors.danger))
        elif role == Qt.ItemDataRole.ToolTipRole and col == COL_TITLE:
            return p.title
        return None

    def setData(self, index: QModelIndex, value, role: int = Qt.ItemDataRole.EditRole) -> bool:  # noqa: N802
        if role != Qt.ItemDataRole.CheckStateRole or index.column() != COL_DONE or not index.isValid():
            return False
        done = Qt.CheckState(value) == Qt.CheckState.Checked
        try:
            self.controller.set_point_done(self.subject_id, self._points[index.row()].id, done)
        except (ValueError, NotFoundError, StorageError, NoUserOpenError) as exc:
            self.errorRaised.emit(str(exc))
            return False
        return True


class PointsTable(QTableView):
    deleteRequested = Signal()

    def __init__(self, model: PointsModel, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setModel(model)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setShowGrid(False)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(32)
        header = self.horizontalHeader()
        header.setHighlightSections(False)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setSectionResizeMode(COL_DONE, QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(COL_DONE, 44)
        header.setSectionResizeMode(COL_TITLE, QHeaderView.ResizeMode.Stretch)
        for col in (COL_DEADLINE, COL_EFFORT, COL_LEFT):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt name)
        if event.key() == Qt.Key.Key_Delete and self.currentIndex().isValid():
            self.deleteRequested.emit()
            return
        super().keyPressEvent(event)
