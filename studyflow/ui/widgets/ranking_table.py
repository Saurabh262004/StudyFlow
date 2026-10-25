"""The priority list: every unfinished study point, most urgent first, with a coloured status pill."""
from __future__ import annotations

from typing import Iterable, Optional

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRect, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QWidget,
)

from ...priority import PointPriority, Status
from .. import style

COL_RANK, COL_STATUS, COL_TITLE, COL_LEFT, COL_EFFORT, COL_START = range(6)
HEADERS = ["#", "Status", "Study point", "Time left", "Effort", "Start by"]
STATUS_LABELS = {
    "overdue": "Overdue", "start_now": "Start now", "soon": "Soon",
    "on_track": "On track", "no_deadline": "No deadline", "done": "Done",
}
STATUS_ROLE = Qt.ItemDataRole.UserRole
SUBJECT_ROLE = Qt.ItemDataRole.UserRole + 1  # the subject's name, drawn under the title
DASH = "\u2014"


def status_label(status: Status) -> str:
    return STATUS_LABELS[status.value]


def start_by_text(row: PointPriority) -> str:
    if row.status in (Status.OVERDUE, Status.START_NOW):
        return "now"
    if row.start_by is None:
        return DASH
    return row.start_by.astimezone().strftime("%d %b, %H:%M")


def effort_text(row: PointPriority, mark_default: bool = False) -> str:
    """"2.5 h"; with mark_default, an assumed (not estimated) effort reads "1 h (default)"."""
    return f"{row.effort_hours:g} h" + (" (default)" if mark_default and not row.effort_estimated else "")


def time_left_text(row: PointPriority) -> str:
    text = row.remaining_text if row.time_remaining is not None else DASH
    return text + ("  \u00b7  at risk" if row.at_risk and row.status is not Status.OVERDUE else "")


class RankingModel(QAbstractTableModel):
    """Plain table of PointPriority rows (the page computes them with controller.ranking())."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._rows: list[PointPriority] = []

    def set_rows(self, rows: Iterable[PointPriority]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def row_at(self, row: int) -> PointPriority:
        return self._rows[row]

    def row_of(self, subject_id: str, point_id: str) -> int:
        return next((i for i, r in enumerate(self._rows) if r.subject_id == subject_id and r.point.id == point_id), -1)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return HEADERS[section]
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        r, col = self._rows[index.row()], index.column()
        if role == STATUS_ROLE:
            return r.status.value
        if role == SUBJECT_ROLE:
            return r.subject_name
        if role == Qt.ItemDataRole.DisplayRole:
            return {
                COL_RANK: str(index.row() + 1),
                COL_STATUS: status_label(r.status),
                COL_TITLE: r.point.title,
                COL_LEFT: time_left_text(r),
                COL_EFFORT: effort_text(r),
                COL_START: start_by_text(r),
            }[col]
        if role == Qt.ItemDataRole.ForegroundRole:
            colors = style.current()
            if col == COL_LEFT and (r.status is Status.OVERDUE or r.at_risk):
                return QBrush(QColor(colors.danger))
            if col == COL_RANK:
                return QBrush(QColor(colors.muted))
        if role == Qt.ItemDataRole.TextAlignmentRole and col == COL_RANK:
            return int(Qt.AlignmentFlag.AlignCenter)
        if role == Qt.ItemDataRole.FontRole and col == COL_EFFORT and not r.effort_estimated:
            font = QFont()
            font.setItalic(True)  # an assumed effort looks different from one you estimated
            return font
        if role == Qt.ItemDataRole.ToolTipRole:
            if col == COL_LEFT and r.at_risk and r.status is not Status.OVERDUE:
                return "More work is due by this deadline than the study hours you have before it."
            if col == COL_EFFORT and not r.effort_estimated:
                return "No estimate was set, so the default effort is assumed."
            if col == COL_TITLE:
                return f"{r.point.title}\n{r.subject_name}"
        return None


class StatusDelegate(QStyledItemDelegate):
    """Paints the status as a rounded, coloured pill."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        label, opt.text = opt.text, ""
        widget_style = opt.widget.style() if opt.widget is not None else QApplication.style()
        widget_style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)  # row background / selection
        fg, bg = style.status_colors(index.data(STATUS_ROLE))
        height = opt.fontMetrics.height() + 6
        width = opt.fontMetrics.horizontalAdvance(label) + 22
        pill = QRect(opt.rect.left() + 6, opt.rect.center().y() - height // 2, width, height)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(bg))
        painter.drawRoundedRect(pill, height / 2, height / 2)
        font = QFont(opt.font)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(fg))
        painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, label)
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # noqa: N802
        base = super().sizeHint(option, index)
        return QSize(option.fontMetrics.horizontalAdvance(str(index.data())) + 34, max(base.height(), 32))


class TitleDelegate(QStyledItemDelegate):
    """The study point's title with its subject in small muted text underneath."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        title, opt.text = opt.text, ""
        widget_style = opt.widget.style() if opt.widget is not None else QApplication.style()
        widget_style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        palette = opt.palette
        main = palette.color(QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text)
        muted = palette.color(QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.PlaceholderText)

        small = QFont(opt.font)
        small.setPointSizeF(max(7.0, opt.font.pointSizeF() * 0.85))
        small_metrics = QFontMetrics(small)
        area = opt.rect.adjusted(8, 0, -8, 0)
        block = opt.fontMetrics.height() + 2 + small_metrics.height()
        top = area.top() + (area.height() - block) // 2
        painter.save()
        painter.setPen(main)
        painter.setFont(opt.font)
        painter.drawText(QRect(area.left(), top, area.width(), opt.fontMetrics.height()), Qt.AlignmentFlag.AlignVCenter,
                         opt.fontMetrics.elidedText(title, Qt.TextElideMode.ElideRight, area.width()))
        painter.setPen(muted)
        painter.setFont(small)
        painter.drawText(QRect(area.left(), top + opt.fontMetrics.height() + 2, area.width(), small_metrics.height()),
                         Qt.AlignmentFlag.AlignVCenter,
                         small_metrics.elidedText(str(index.data(SUBJECT_ROLE)), Qt.TextElideMode.ElideRight, area.width()))
        painter.restore()


class RankingTable(QTableView):
    rowActivated = Signal(int)  # double-click or Enter on a row

    def __init__(self, model: RankingModel, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setModel(model)
        self.setItemDelegateForColumn(COL_STATUS, StatusDelegate(self))
        self.setItemDelegateForColumn(COL_TITLE, TitleDelegate(self))
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setShowGrid(False)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(46)
        header = self.horizontalHeader()
        header.setHighlightSections(False)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setSectionResizeMode(COL_RANK, QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(COL_RANK, 44)
        header.setMinimumSectionSize(40)
        header.setSectionResizeMode(COL_TITLE, QHeaderView.ResizeMode.Stretch)  # the title gets whatever is left
        for col in (COL_STATUS, COL_LEFT, COL_EFFORT, COL_START):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.doubleClicked.connect(self._on_double_click)

    def _on_double_click(self, index: QModelIndex) -> None:
        self.rowActivated.emit(index.row())

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt name)
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.currentIndex().isValid():
            self.rowActivated.emit(self.currentIndex().row())
            return
        super().keyPressEvent(event)
