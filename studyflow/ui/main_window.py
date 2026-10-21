"""The main window: sidebar (Dashboard, Images, subjects), the pages, a warning banner and a status bar.

In this build step the pages are placeholders; the shell, the user switching and the live wiring to the
controller are real."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..models import NotFoundError
from ..storage import StorageError
from . import util
from .controller import AppController, NoUserOpenError
from .dialogs.name_dialog import NameDialog
from .dialogs.user_picker import UserPickerDialog
from .pages.subject_page import SubjectPage
from .startup import choose_user

PAGE_DASHBOARD, PAGE_IMAGES, PAGE_SUBJECT = 0, 1, 2


class PlaceholderPage(QWidget):
    def __init__(self, title: str = "", body: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.title = QLabel(title)
        self.title.setObjectName("pageTitle")
        self.body = QLabel(body)
        self.body.setObjectName("muted")
        self.body.setWordWrap(True)
        self.body.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(10)
        layout.addWidget(self.title)
        layout.addWidget(self.body, 1)

    def set_text(self, title: str, body: str) -> None:
        self.title.setText(title)
        self.body.setText(body)


class WarningBanner(QFrame):
    """Shows the messages in controller.warnings (restored from backup, upgraded format ...) until dismissed."""

    def __init__(self, controller: AppController, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("banner")
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.dismiss = QPushButton("Dismiss")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 10, 10)
        layout.addWidget(self.label, 1)
        layout.addWidget(self.dismiss, 0, Qt.AlignmentFlag.AlignTop)
        self.dismiss.clicked.connect(controller.dismiss_warnings)
        self._controller = controller
        controller.warningsChanged.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        warnings = self._controller.warnings
        self.label.setText("\n".join(warnings))
        self.setVisible(bool(warnings))


class MainWindow(QMainWindow):
    def __init__(self, controller: AppController, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setMinimumSize(880, 560)
        self.resize(1120, 720)
        self._build_menu()
        self._build_toolbar()
        self._build_central()
        self.user_status = QLabel()
        self.statusBar().addWidget(self.user_status)
        self.statusBar().addPermanentWidget(QLabel("All changes are saved automatically"))

        c = controller
        c.userChanged.connect(self._on_user_changed)
        c.usersChanged.connect(self._refresh_user)
        c.dataChanged.connect(self._refresh_subjects)
        self._refresh_all()

    # ------------------------------------------------------------------ building
    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        self.switch_action = QAction("&Switch user\u2026", self)
        self.switch_action.setShortcut(QKeySequence("Ctrl+U"))
        self.switch_action.triggered.connect(self.switch_user)
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(self.switch_action)
        file_menu.addSeparator()
        file_menu.addAction(quit_action)

    def _build_toolbar(self) -> None:
        bar = QToolBar("Main")
        bar.setMovable(False)
        bar.setFloatable(False)
        title = QLabel("StudyFlow")
        title.setObjectName("pageTitle")
        title.setStyleSheet("font-size: 14pt;")
        bar.addWidget(title)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bar.addWidget(spacer)
        self.user_button = QToolButton()
        self.user_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.user_button)
        menu.addAction(self.switch_action)
        self.user_button.setMenu(menu)
        bar.addWidget(self.user_button)
        self.addToolBar(bar)

    def _build_central(self) -> None:
        self.sidebar = QWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(250)
        self.nav = QListWidget()
        for text in ("Dashboard", "Images"):
            self.nav.addItem(text)
        self.nav.setFixedHeight(2 * 38 + 6)
        self.subject_list = QListWidget()
        self.add_subject_button = QPushButton("+ New subject")
        heading_subjects = QLabel("SUBJECTS")
        heading_subjects.setObjectName("sidebarHeading")

        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(0, 8, 0, 12)
        side.setSpacing(0)
        side.addWidget(self.nav)
        side.addWidget(heading_subjects)
        side.addWidget(self.subject_list, 1)
        holder = QHBoxLayout()
        holder.setContentsMargins(12, 6, 12, 0)
        holder.addWidget(self.add_subject_button)
        side.addLayout(holder)

        self.pages = QStackedWidget()
        self.dashboard_page = PlaceholderPage("Dashboard")
        self.images_page = PlaceholderPage("Images", "Your picture gallery will appear here.")
        self.subject_page = SubjectPage(self.controller)
        for page in (self.dashboard_page, self.images_page, self.subject_page):
            self.pages.addWidget(page)

        self.banner = WarningBanner(self.controller)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        banner_holder = QVBoxLayout()
        banner_holder.setContentsMargins(16, 12, 16, 0)
        banner_holder.addWidget(self.banner)
        right_layout.addLayout(banner_holder)
        right_layout.addWidget(self.pages, 1)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.sidebar)
        layout.addWidget(right, 1)
        self.setCentralWidget(central)

        self.nav.currentRowChanged.connect(self._nav_selected)
        self.subject_list.currentRowChanged.connect(self._subject_selected)
        self.add_subject_button.clicked.connect(self.add_subject)

    # ------------------------------------------------------------------ refreshing
    def _refresh_all(self) -> None:
        self._refresh_user()
        self._refresh_subjects()

    def _refresh_user(self) -> None:
        user = self.controller.current_user
        name = user.name if user else "no user"
        self.setWindowTitle(f"{user.name} \u2014 StudyFlow" if user else "StudyFlow")
        self.user_button.setText(f"{name}  \u25be")
        self.user_status.setText(f"User: {name}")

    def _refresh_subjects(self) -> None:
        keep = self._selected_subject_id()
        self.subject_list.blockSignals(True)
        self.subject_list.clear()
        subjects = sorted(self.controller.subjects(), key=lambda s: s.name.casefold()) if self.controller.is_open else []
        for subject in subjects:
            item = QListWidgetItem(subject.name)
            item.setData(Qt.ItemDataRole.UserRole, subject.id)
            self.subject_list.addItem(item)
        self.subject_list.blockSignals(False)
        row = next((i for i, s in enumerate(subjects) if s.id == keep), -1)
        if row >= 0:
            self._select_subject_row(row)
        elif self.nav.currentRow() < 0 or keep is not None:
            self.nav.setCurrentRow(0)
        self._refresh_pages()

    def _refresh_pages(self) -> None:
        if not self.controller.is_open:
            return
        subjects = self.controller.subjects()
        points = sum(1 for s in subjects for p in s.points if not p.done)
        self.dashboard_page.set_text(
            "Dashboard",
            f"Your priority list will appear here.\n\nYou have {len(subjects)} subject(s) and {points} unfinished study point(s).",
        )

    def _selected_subject_id(self) -> Optional[str]:
        item = self.subject_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None and self.subject_list.currentRow() >= 0 else None

    def _select_subject_row(self, row: int) -> None:
        self.nav.blockSignals(True)
        self.nav.setCurrentRow(-1)
        self.nav.clearSelection()
        self.nav.blockSignals(False)
        # No signal here: this is called when a selection was just made, or when the list was rebuilt after a
        # data change. Announcing it again would re-run the "a subject was selected" handler (and its saving).
        self.subject_list.blockSignals(True)
        self.subject_list.setCurrentRow(row)
        self.subject_list.blockSignals(False)
        self.pages.setCurrentIndex(PAGE_SUBJECT)

    # ------------------------------------------------------------------ navigation
    def _nav_selected(self, row: int) -> None:
        if row < 0:
            return
        self.subject_page.flush()  # save pending edits before leaving the subject
        self.subject_page.clear()
        self.subject_list.blockSignals(True)
        self.subject_list.setCurrentRow(-1)
        self.subject_list.clearSelection()
        self.subject_list.blockSignals(False)
        self.pages.setCurrentIndex(PAGE_DASHBOARD if row == 0 else PAGE_IMAGES)

    def _subject_selected(self, row: int) -> None:
        if row < 0:
            return
        self.subject_page.flush()  # save pending edits of the subject we are leaving
        self._select_subject_row(row)
        self.subject_page.show_subject(self._selected_subject_id())

    # ------------------------------------------------------------------ actions
    def switch_user(self) -> None:
        self.subject_page.flush()  # edits belong to the CURRENT user: save them before anyone else is opened
        UserPickerDialog(self.controller, parent=self).exec()

    def add_subject(self) -> None:
        name = NameDialog.ask(self, "New subject", "Name of the subject:", lambda _t: None, ok_text="Add")
        if name is None:
            return
        try:
            subject = self.controller.add_subject(name)
        except (ValueError, StorageError, NoUserOpenError) as exc:
            util.show_error(self, str(exc))
            return
        for row in range(self.subject_list.count()):
            if self.subject_list.item(row).data(Qt.ItemDataRole.UserRole) == subject.id:
                self.subject_list.setCurrentRow(row)
                break

    def _on_user_changed(self) -> None:
        self.subject_page.clear()  # a different user: nothing on the page can be saved any more
        if not self.controller.is_open:  # the open user was deleted
            QTimer.singleShot(0, self._require_user)
            return
        self.nav.setCurrentRow(0)
        self._refresh_all()

    def _require_user(self) -> None:
        if not choose_user(self.controller, parent=self):
            self.close()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt name)
        self.subject_page.flush()
        self.controller.stop_clock()
        super().closeEvent(event)
