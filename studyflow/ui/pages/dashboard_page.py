"""The Dashboard: what to study next, and every unfinished study point ranked by urgency.

Everything shown here is computed by the priority engine (priority.py) through controller.ranking(); this
page only displays it. It refreshes whenever data or settings change and once a minute (the clock tick)."""
from __future__ import annotations

from dataclasses import replace
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...models import NotFoundError
from ...priority import PointPriority, Status
from ...storage import StorageError
from .. import style, util
from ..controller import AppController, NoUserOpenError
from ..widgets.ranking_table import (
    RankingModel,
    RankingTable,
    effort_text,
    start_by_text,
    status_label,
)

MAX_HOURS_PER_DAY = 24.0


class DashboardPage(QWidget):
    openPointRequested = Signal(str, str)  # subject id, study point id

    def __init__(self, controller: AppController, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._next: Optional[PointPriority] = None
        self._syncing = False

        # ---- header: title, summary, and the one setting the plan depends on most
        self.title = QLabel("Dashboard")
        self.title.setObjectName("pageTitle")
        self.summary = QLabel()
        self.summary.setObjectName("muted")
        self.hours = QDoubleSpinBox()
        self.hours.setRange(0.5, MAX_HOURS_PER_DAY)
        self.hours.setSingleStep(0.5)
        self.hours.setDecimals(2)
        self.hours.setSuffix(" h/day")
        style.pad_spin_box(self.hours)
        self.hours.setKeyboardTracking(False)  # saves when you press Enter or click away, not on every digit
        self.hours.setToolTip("How many hours you can really study per day. The plan is built from this.")
        header = QHBoxLayout()
        header.addWidget(self.title, 1)
        header.addWidget(QLabel("I can study"))
        header.addWidget(self.hours)

        # ---- warning: more work than time
        self.risk_banner = QFrame()
        self.risk_banner.setObjectName("riskBanner")
        self.risk_label = QLabel()
        self.risk_label.setWordWrap(True)
        risk_layout = QHBoxLayout(self.risk_banner)
        risk_layout.setContentsMargins(14, 10, 14, 10)
        risk_layout.addWidget(self.risk_label)

        # ---- the "study next" card
        self.card = QFrame()
        self.card.setObjectName("nextCard")
        card_caption = QLabel("STUDY NEXT")
        card_caption.setObjectName("sectionLabel")
        self.card_title = QLabel()
        self.card_title.setObjectName("cardTitle")
        self.card_title.setWordWrap(True)
        self.card_subject = QLabel()
        self.card_subject.setObjectName("muted")
        self.card_pill = QLabel()
        self.card_details = QLabel()
        self.open_button = QPushButton("Open")
        self.open_button.setDefault(True)
        pill_row = QHBoxLayout()
        pill_row.addWidget(self.card_pill)
        pill_row.addWidget(self.card_details, 1)
        text_column = QVBoxLayout()
        text_column.setSpacing(4)
        for item in (card_caption, self.card_title, self.card_subject):
            text_column.addWidget(item)
        text_column.addLayout(pill_row)
        card_layout = QHBoxLayout(self.card)
        card_layout.setContentsMargins(20, 16, 20, 16)
        card_layout.addLayout(text_column, 1)
        card_layout.addWidget(self.open_button, 0, Qt.AlignmentFlag.AlignVCenter)

        # ---- the ranked list
        list_caption = QLabel("PRIORITY LIST")
        list_caption.setObjectName("sectionLabel")
        self.filter = QComboBox()
        self.filter.setMinimumWidth(180)
        list_header = QHBoxLayout()
        list_header.addWidget(list_caption, 1)
        list_header.addWidget(self.filter)
        self.model = RankingModel(self)
        self.table = RankingTable(self.model)
        self.empty_hint = QLabel(
            "Nothing to show yet.\n\nCreate a subject, add study points to it, and give them deadlines and effort "
            "estimates. The most urgent ones appear here."
        )
        self.empty_hint.setObjectName("muted")
        self.empty_hint.setWordWrap(True)
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 18, 28, 14)
        layout.setSpacing(10)
        layout.addLayout(header)
        layout.addWidget(self.summary)
        layout.addWidget(self.risk_banner)
        layout.addWidget(self.card)
        layout.addLayout(list_header)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.empty_hint, 1)

        self.hours.valueChanged.connect(self._on_hours_changed)
        self.filter.currentIndexChanged.connect(self._on_filter_changed)
        self.table.rowActivated.connect(self._on_row_activated)
        self.open_button.clicked.connect(self._open_next)
        for signal in (controller.dataChanged, controller.settingsChanged, controller.userChanged, controller.tick):
            signal.connect(self.refresh)
        self.refresh()

    # ------------------------------------------------------------------ refreshing
    def refresh(self) -> None:
        if not self.controller.is_open:
            self._show_nothing()
            return
        subjects = sorted(self.controller.subjects(), key=lambda s: s.name.casefold())
        self._fill_filter(subjects)
        everything = self.controller.ranking()  # the whole plan: the card and the warning always look at all subjects
        wanted = self._filter_id()
        shown = [r for r in everything if wanted is None or r.subject_id == wanted]

        keep = self._selected_key()
        self.model.set_rows(shown)
        if keep is not None:
            row = self.model.row_of(*keep)
            if row >= 0:
                self.table.selectRow(row)

        self.summary.setText(f"{len(subjects)} subject(s), {len(everything)} unfinished study point(s)")
        self._update_card(everything[0] if everything else None)
        self._update_risk(everything)
        self._sync_hours()
        has_rows = bool(shown)
        self.table.setVisible(has_rows)
        self.empty_hint.setVisible(not has_rows)

    def _show_nothing(self) -> None:
        self.model.set_rows([])
        self.summary.setText("")
        self._update_card(None)
        self.risk_banner.setVisible(False)
        self.table.setVisible(False)
        self.empty_hint.setVisible(True)

    def _fill_filter(self, subjects) -> None:
        keep = self._filter_id()
        self.filter.blockSignals(True)
        self.filter.clear()
        self.filter.addItem("All subjects", None)
        for s in subjects:
            self.filter.addItem(s.name, s.id)
        index = next((i for i in range(self.filter.count()) if self.filter.itemData(i) == keep), 0)
        self.filter.setCurrentIndex(index)
        self.filter.blockSignals(False)

    def _filter_id(self) -> Optional[str]:
        return self.filter.currentData() if self.filter.count() else None

    def _selected_key(self) -> Optional[tuple[str, str]]:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        r = self.model.row_at(rows[0].row())
        return r.subject_id, r.point.id

    def _update_card(self, top: Optional[PointPriority]) -> None:
        self._next = top
        if top is None:
            self.card_title.setText("Nothing to study right now")
            self.card_subject.setText("Add study points with deadlines and they will be ranked here.")
            self.card_pill.setVisible(False)
            self.card_details.setVisible(False)
            self.open_button.setVisible(False)
            return
        fg, bg = style.status_colors(top.status)
        self.card_title.setText(top.point.title)
        self.card_subject.setText(top.subject_name)
        self.card_pill.setText(status_label(top.status))
        self.card_pill.setStyleSheet(
            f"background: {bg}; color: {fg}; border-radius: 11px; padding: 3px 12px; font-weight: 600;"
        )
        self.card_details.setText(f"{top.remaining_text}   \u00b7   {effort_text(top, mark_default=True)} effort   \u00b7   start by {start_by_text(top)}")
        for w in (self.card_pill, self.card_details, self.open_button):
            w.setVisible(True)

    def _update_risk(self, everything: list[PointPriority]) -> None:
        # points that are already overdue are shown in red in the list; this warning is about deadlines still ahead
        risky = [r for r in everything if r.at_risk and r.status is not Status.OVERDUE]
        hours = self.controller.settings.hours_per_day
        self.risk_banner.setVisible(bool(risky))
        if risky:
            self.risk_label.setText(
                f"{len(risky)} deadline(s) cannot be met with {hours:g} study hour(s) per day: more work is due "
                "by then than you have time for. Study more per day, or move or drop something."
            )

    def _sync_hours(self) -> None:
        wanted = self.controller.settings.hours_per_day
        if abs(self.hours.value() - wanted) > 1e-9:
            self._syncing = True
            self.hours.setValue(wanted)
            self._syncing = False

    # ------------------------------------------------------------------ user actions
    def _on_hours_changed(self, value: float) -> None:
        if self._syncing or not self.controller.is_open:
            return
        try:
            self.controller.set_settings(replace(self.controller.settings, hours_per_day=value))
        except (ValueError, StorageError, NoUserOpenError) as exc:
            util.show_error(self, str(exc))
            self._sync_hours()

    def _on_filter_changed(self, _index: int) -> None:
        self.refresh()

    def _on_row_activated(self, row: int) -> None:
        if 0 <= row < self.model.rowCount():
            r = self.model.row_at(row)
            self.openPointRequested.emit(r.subject_id, r.point.id)

    def _open_next(self) -> None:
        if self._next is not None:
            self.openPointRequested.emit(self._next.subject_id, self._next.point.id)
