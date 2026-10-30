"""The pictures of one subject or study point: thumbnails plus Add / Paste / Show existing, and drag-and-drop."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QVBoxLayout, QWidget

from ...models import NotFoundError
from ...storage import StorageError
from .. import image_import, util
from ..controller import AppController, NoUserOpenError
from ..dialogs.image_picker import ImagePickerDialog
from ..dialogs.image_viewer import ImageViewerDialog
from .image_list import ImageListModel, ImageListView


class ImageStrip(QFrame):
    """`row=True`: one scrolling row (for the point editor). `row=False`: a wrapping grid (the subject's Pictures tab)."""

    countChanged = Signal(int)
    locationRequested = Signal(str, str)  # passed on from the viewer: take me to (subject id, point id or "")

    def __init__(self, controller: AppController, row: bool = True, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setObjectName("imageStrip")
        self.setAcceptDrops(True)
        self._subject_id: Optional[str] = None
        self._point_id: Optional[str] = None
        self._count = 0

        self.add_button = QPushButton("Add pictures\u2026")
        self.paste_button = QPushButton("Paste")
        self.paste_button.setToolTip("Paste a picture or picture files from the clipboard (Ctrl+V)")
        self.link_button = QPushButton("Show existing\u2026")
        self.link_button.setToolTip("Show a picture that is already in StudyFlow here too")
        self.hint = QLabel("or drop picture files here")
        self.hint.setObjectName("muted")
        self.model = ImageListModel(controller, parent=self)
        self.view = ImageListView(self.model, row=row)
        self.empty = QLabel("No pictures yet.\nAdd them with the buttons above, paste, or drop files here.")
        self.empty.setObjectName("muted")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)

        buttons = QHBoxLayout()
        for widget in (self.add_button, self.paste_button, self.link_button):
            buttons.addWidget(widget)
        buttons.addWidget(self.hint, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(6)
        layout.addLayout(buttons)
        layout.addWidget(self.view, 0 if row else 1)
        layout.addWidget(self.empty, 0 if row else 1)

        self.add_button.clicked.connect(self.add_pictures)
        self.paste_button.clicked.connect(self.paste)
        self.link_button.clicked.connect(self.show_existing)
        self.view.imageActivated.connect(self.open_viewer)
        self.view.deleteRequested.connect(self.remove_selected)
        self.view.customContextMenuRequested.connect(self._show_menu)
        shortcut = QShortcut(QKeySequence.StandardKey.Paste, self)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(self.paste)
        controller.dataChanged.connect(self.refresh)
        self.refresh()

    # ------------------------------------------------------------------ what it shows
    def set_target(self, subject_id: Optional[str], point_id: Optional[str] = None) -> None:
        self._subject_id, self._point_id = subject_id, point_id
        self.refresh()

    @property
    def target(self) -> tuple[Optional[str], Optional[str]]:
        return self._subject_id, self._point_id

    def count(self) -> int:
        return self._count

    def refresh(self) -> None:
        images = []
        if self._subject_id is not None and self.controller.is_open:
            try:
                images = self.controller.images_of(self._subject_id, self._point_id)
            except (NotFoundError, NoUserOpenError):
                self._subject_id = self._point_id = None
        if images != self.model._records:  # (ImageRecord compares by value) only rebuild when something changed
            keep = self.view.selected_ids()
            self.model.set_images(images)
            for image_id in keep:
                row = self.model.row_of(image_id)
                if row >= 0:
                    self.view.selectionModel().select(self.model.index(row), self.view.selectionModel().SelectionFlag.Select)
        has_target = self._subject_id is not None
        for button in (self.add_button, self.paste_button, self.link_button):
            button.setEnabled(has_target)
        self.view.setVisible(bool(images))
        self.empty.setVisible(not images)
        self.empty.setText("No pictures yet.\nAdd them with the buttons above, paste, or drop files here." if has_target else "")
        if len(images) != self._count:
            self._count = len(images)
            self.countChanged.emit(self._count)

    # ------------------------------------------------------------------ adding
    def add_pictures(self) -> None:
        if self._subject_id is None:
            return
        paths = util.ask_open_files(self, "Add pictures", image_import.PICTURE_FILTER)
        image_import.import_pictures(self.controller, self, paths, self._subject_id, self._point_id)

    def paste(self) -> None:
        if self._subject_id is not None:
            image_import.paste_picture(self.controller, self, self._subject_id, self._point_id)

    def show_existing(self) -> None:
        if self._subject_id is None:
            return
        already = {i.id for i in self.controller.images_of(self._subject_id, self._point_id)}
        for image_id in ImagePickerDialog.ask(self, self.controller, already):
            try:
                self.controller.link_image(image_id, self._subject_id, self._point_id)
            except (StorageError, NotFoundError, ValueError) as exc:
                util.show_error(self, str(exc))

    # ------------------------------------------------------------------ drag and drop
    def _set_drop_highlight(self, active: bool) -> None:
        self.setProperty("dropActive", active)
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt name)
        if self._subject_id is not None and image_import.can_accept(event.mimeData()):
            event.acceptProposedAction()
            self._set_drop_highlight(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 (Qt name)
        if self._subject_id is not None and image_import.can_accept(event.mimeData()):
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802 (Qt name)
        self._set_drop_highlight(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt name)
        self._set_drop_highlight(False)
        paths, _ = image_import.picture_paths_from_mime(event.mimeData())
        if self._subject_id is None or not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        image_import.import_pictures(self.controller, self, paths, self._subject_id, self._point_id)

    # ------------------------------------------------------------------ looking and removing
    def open_viewer(self, image_id: str) -> None:
        ids = self.model.image_ids()
        if image_id not in ids:
            return
        viewer = ImageViewerDialog(self.controller, ids, ids.index(image_id), self._subject_id, self._point_id, self)
        viewer.locationRequested.connect(self.locationRequested)
        viewer.exec()

    def remove_selected(self) -> None:
        if self._subject_id is not None:
            image_import.remove_from_place(self.controller, self, self.view.selected_ids(), self._subject_id, self._point_id)

    def _show_menu(self, position) -> None:
        index = self.view.indexAt(position)
        if not index.isValid():
            return
        if not self.view.selectionModel().isSelected(index):
            self.view.setCurrentIndex(index)
        menu = QMenu(self)
        open_action = menu.addAction("Open")
        remove_action = menu.addAction("Remove from here")
        delete_action = menu.addAction("Delete everywhere\u2026")
        chosen = util.exec_menu(menu, self.view.viewport().mapToGlobal(position))
        if chosen is open_action:
            self.open_viewer(self.model.data(index, Qt.ItemDataRole.UserRole))
        elif chosen is remove_action:
            self.remove_selected()
        elif chosen is delete_action:
            image_import.delete_everywhere(self.controller, self, self.view.selected_ids())
