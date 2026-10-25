"""One subject: name, notes, its study points, and an editor for the selected point.

Saving model: there is no Save button. Edits are written to disk by the controller

  * after a short pause in typing (debounce),
  * when focus leaves a notes box,
  * when another point or subject is selected, or the window is about to close or switch user
    (the main window calls flush() first),

and only the fields the user actually changed are sent, so nothing is rewritten by accident."""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...models import NotFoundError
from ...storage import StorageError
from .. import util
from ..controller import AppController, NoUserOpenError
from ..dialogs.name_dialog import NameDialog
from ..widgets.notes_edit import NotesEdit
from ..widgets.point_editor import PointEditor
from ..widgets.points_table import PointsModel, PointsTable

SAVE_DELAY_MS = 700


class SubjectPage(QWidget):
    def __init__(self, controller: AppController, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._subject_id: Optional[str] = None
        self._point_id: Optional[str] = None
        self._notes_dirty = False
        self._loading_notes = False
        self._restoring_selection = False
        self._flushing = False

        # ---- header
        self.title = QLabel()
        self.title.setObjectName("pageTitle")
        self.summary = QLabel()
        self.summary.setObjectName("muted")
        self.rename_button = QPushButton("Rename\u2026")
        self.delete_button = QPushButton("Delete subject\u2026")
        header = QHBoxLayout()
        header.addWidget(self.title, 1)
        header.addWidget(self.rename_button)
        header.addWidget(self.delete_button)

        # ---- notes
        self.notes = NotesEdit()
        self.notes.setPlaceholderText("Write notes for this subject\u2026")

        # ---- points
        self.model = PointsModel(controller, self)
        self.table = PointsTable(self.model)
        self.quick_add = QLineEdit()
        self.quick_add.setPlaceholderText("Add a study point and press Enter")
        points_box = QWidget()
        points_layout = QVBoxLayout(points_box)
        points_layout.setContentsMargins(0, 0, 0, 0)
        points_layout.setSpacing(8)
        points_layout.addWidget(self.table, 1)
        points_layout.addWidget(self.quick_add)
        self.editor = PointEditor()
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(points_box)
        splitter.addWidget(self.editor)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 4)
        splitter.setChildrenCollapsible(False)
        splitter.setSizes([250, 230])
        splitter.setHandleWidth(10)

        # Two tabs ("Images" joins them later) so that the points table and the editor get the whole height
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(splitter, "Study points")
        self.tabs.addTab(self.notes, "Notes")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 18, 28, 14)
        layout.setSpacing(6)
        layout.addLayout(header)
        layout.addWidget(self.summary)
        layout.addWidget(self.tabs, 1)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SAVE_DELAY_MS)

        self._save_timer.timeout.connect(self._on_save_timer)
        self.rename_button.clicked.connect(self.rename_subject)
        self.delete_button.clicked.connect(self.delete_subject)
        self.notes.textChanged.connect(self._on_notes_changed)
        self.notes.editingFinished.connect(self.flush)
        self.editor.finishedEditing.connect(self.flush)
        self.editor.edited.connect(self._save_timer.start)
        self.editor.deleteRequested.connect(self.delete_point)
        self.table.deleteRequested.connect(self.delete_point)
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.quick_add.returnPressed.connect(self.add_point)
        self.model.errorRaised.connect(self._show_error)
        controller.dataChanged.connect(self.refresh)
        controller.tick.connect(self.model.refresh_times)
        self.clear()

    # ------------------------------------------------------------------ showing a subject
    def show_subject(self, subject_id: str) -> None:
        self.flush()
        self._subject_id, self._point_id = subject_id, None
        self._restoring_selection = True
        self.model.set_subject(subject_id)
        self.table.clearSelection()
        self._restoring_selection = False
        self.quick_add.clear()
        self._load_header_and_notes(force=True)
        self.editor.load(None)

    def clear(self) -> None:
        """Show nothing. Pending edits are DISCARDED (call flush() first if they should be kept)."""
        self._save_timer.stop()
        self._notes_dirty = False
        self._subject_id = self._point_id = None
        self._restoring_selection = True
        self.model.set_subject(None)
        self._restoring_selection = False
        self.editor.load(None)
        self.title.setText("")
        self.summary.setText("")
        self._set_notes_text("")

    def refresh(self) -> None:
        """The data changed (anywhere): bring the page in line, without disturbing what the user is typing."""
        if self._subject_id is None:
            return
        try:
            self.controller.get_subject(self._subject_id)
        except (NotFoundError, NoUserOpenError):
            self.clear()  # the subject was deleted
            return
        self._load_header_and_notes(force=False)
        # Keep what is selected in the table RIGHT NOW. (self._point_id can be stale: saving the point we are
        # leaving triggers this refresh in the middle of a click on another row, which must not be undone.)
        keep = self._selected_point_id() or self._point_id
        self._restoring_selection = True
        self.model.refresh()
        row = self.model.row_of(keep) if keep else -1
        if row >= 0:
            self.table.selectRow(row)
        else:
            self.table.clearSelection()
            self._point_id = None
        self._restoring_selection = False
        self._reload_editor(force=False)

    def _load_header_and_notes(self, force: bool) -> None:
        subject = self.controller.get_subject(self._subject_id)
        done = sum(1 for p in subject.points if p.done)
        self.title.setText(subject.name)
        self.summary.setText(f"{len(subject.points)} study point(s), {done} done")
        if force or not self._notes_dirty:
            self._set_notes_text(subject.notes)
            self._notes_dirty = False

    def _set_notes_text(self, text: str) -> None:
        if self.notes.toPlainText() != text:
            self._loading_notes = True
            self.notes.setPlainText(text)
            self._loading_notes = False
        self._update_notes_tab()

    def _update_notes_tab(self) -> None:
        """A dot on the "Notes" tab when the subject has notes, so notes in a hidden tab are still discoverable."""
        self.tabs.setTabText(1, "Notes \u2022" if self.notes.toPlainText().strip() else "Notes")

    def _reload_editor(self, force: bool) -> None:
        if self._point_id is None:
            self.editor.load(None)
            return
        if self.editor.is_dirty and not force:
            return  # keep what the user is typing
        try:
            point = self.controller.get_point(self._subject_id, self._point_id)
        except (NotFoundError, NoUserOpenError):
            self._point_id = None
            self.editor.load(None)
            return
        self.editor.load(point)

    def select_point(self, point_id: str) -> None:
        """Show the "Study points" tab with this point selected and its editor open."""
        self.tabs.setCurrentIndex(0)
        row = self.model.row_of(point_id)
        if row >= 0:
            self.table.selectRow(row)
            self.table.scrollTo(self.model.index(row, 0))

    # ------------------------------------------------------------------ selection
    def _on_selection_changed(self, _selected, _deselected) -> None:
        if self._restoring_selection:
            return
        self.flush()  # first save the edits made on the point we are leaving
        self._point_id = self._selected_point_id()
        self._reload_editor(force=True)

    def _selected_point_id(self) -> Optional[str]:
        rows = self.table.selectionModel().selectedRows()
        return self.model.point_at(rows[0].row()).id if rows else None

    # ------------------------------------------------------------------ saving
    def _call(self, action: Callable[[], object]):
        """Run a controller call. Returns (True, result), or (False, None) after showing the problem.
        A subject or point that has vanished in the meantime is not worth a dialog."""
        try:
            return True, action()
        except NotFoundError:
            return False, None
        except (ValueError, StorageError, NoUserOpenError) as exc:
            self._show_error(str(exc))
            return False, None

    def _show_error(self, message: str) -> None:
        util.show_error(self, message)

    def _on_notes_changed(self) -> None:
        self._update_notes_tab()
        if self._loading_notes:
            return
        self._notes_dirty = True
        self._save_timer.start()

    def _on_save_timer(self) -> None:
        """The user paused typing: save, but do not scold about a half-typed (still empty) title."""
        self._commit_notes()
        self._commit_point(final=False)

    def flush(self) -> None:
        """Save everything pending right now (before changing selection, switching user, closing ...)."""
        if self._flushing:  # saving emits dataChanged, which must never lead back into saving
            return
        self._flushing = True
        try:
            self._save_timer.stop()
            self._commit_notes()
            self._commit_point(final=True)
        finally:
            self._flushing = False

    def _commit_notes(self) -> None:
        if not self._notes_dirty or self._subject_id is None:
            self._notes_dirty = False
            return
        text, subject_id = self.notes.toPlainText(), self._subject_id
        self._notes_dirty = False
        self._call(lambda: self.controller.set_subject_notes(subject_id, text))

    def _commit_point(self, final: bool) -> None:
        if self._subject_id is None or self._point_id is None or not self.editor.is_dirty:
            return
        subject_id, point_id = self._subject_id, self._point_id
        changes = self.editor.pending()
        if "title" in changes and not changes["title"]:
            del changes["title"]  # an empty title is never saved
            if final:
                self.editor.clear_dirty(["title"])  # the edit is dropped; the old title comes back on reload
            else:
                self.editor.set_error("The title cannot be empty.")
        if changes:
            # Mark these fields as saved BEFORE calling the controller: the call emits dataChanged, and anything
            # reacting to that must not find them still "pending" and save them a second time.
            self.editor.clear_dirty(changes.keys())
            ok, _ = self._call(lambda: self.controller.update_point(subject_id, point_id, **changes))
            if ok:
                if "title" in changes:
                    self.editor.set_error("")
            else:
                self.editor.clear_dirty()
                self._reload_editor(force=True)  # show what is really saved
        if final:
            self.editor.clear_dirty()

    # ------------------------------------------------------------------ actions
    def add_point(self) -> None:
        title = self.quick_add.text().strip()
        if not title or self._subject_id is None:
            return
        ok, point = self._call(lambda: self.controller.add_point(self._subject_id, title))
        if not ok:
            return
        self.quick_add.clear()
        row = self.model.row_of(point.id)
        if row >= 0:
            self.table.selectRow(row)  # shows the new point in the editor; focus stays here for rapid entry

    def delete_point(self) -> None:
        if self._subject_id is None or self._point_id is None:
            return
        subject_id, point_id = self._subject_id, self._point_id
        self._save_timer.stop()
        self.editor.clear_dirty()  # edits to a point that is about to disappear are pointless
        self._call(lambda: self.controller.delete_point(subject_id, point_id))

    def rename_subject(self) -> None:
        if self._subject_id is None:
            return
        self.flush()
        subject = self.controller.get_subject(self._subject_id)
        name = NameDialog.ask(self, "Rename subject", "New name for the subject:", _accept_anything, initial=subject.name, ok_text="Rename")
        if name is None or name == subject.name:
            return
        self._call(lambda: self.controller.rename_subject(subject.id, name))

    def delete_subject(self) -> None:
        if self._subject_id is None:
            return
        self.flush()
        subject = self.controller.get_subject(self._subject_id)
        answer = util.confirm(
            self, "Delete subject", f"Delete \u201c{subject.name}\u201d?", ok_text="Delete subject",
            detail=f"Its {len(subject.points)} study point(s) and notes will be removed, and so will any picture "
                   "that is not used anywhere else. This cannot be undone.",
        )
        if answer is None:
            return
        self._call(lambda: self.controller.delete_subject(subject.id))


def _accept_anything(_text: str) -> Optional[str]:
    return None
