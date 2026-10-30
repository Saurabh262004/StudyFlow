"""The Images page: every picture of the open user, with a tag filter and search."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QVBoxLayout, QWidget

from ...storage import StorageError
from .. import image_import, util
from ..controller import AppController, NoUserOpenError
from ..dialogs.image_picker import filter_images
from ..dialogs.image_viewer import ImageViewerDialog
from ..dialogs.target_picker import TargetPickerDialog
from ..widgets.image_list import ImageListModel, ImageListView


class GalleryPage(QWidget):
    openLocationRequested = Signal(str, str)  # subject id, study point id ("" = the subject itself)

    def __init__(self, controller: AppController, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.title = QLabel("Images")
        self.title.setObjectName("pageTitle")
        self.summary = QLabel()
        self.summary.setObjectName("muted")
        self.add_button = QPushButton("Add pictures\u2026")
        self.add_button.setDefault(True)
        header = QHBoxLayout()
        header.addWidget(self.title, 1)
        header.addWidget(self.add_button)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by file name or tag")
        self.tag_filter = QComboBox()
        self.tag_filter.setMinimumWidth(190)
        filters = QHBoxLayout()
        filters.addWidget(self.search, 1)
        filters.addWidget(self.tag_filter)

        self.model = ImageListModel(controller, icon_size=128, parent=self)
        self.view = ImageListView(self.model)
        self.empty = QLabel()
        self.empty.setObjectName("muted")
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 18, 28, 14)
        layout.setSpacing(10)
        layout.addLayout(header)
        layout.addWidget(self.summary)
        layout.addLayout(filters)
        layout.addWidget(self.view, 1)
        layout.addWidget(self.empty, 1)

        self.add_button.clicked.connect(self.add_pictures)
        self.search.textChanged.connect(self._on_filter_text)
        self.tag_filter.currentIndexChanged.connect(self._on_filter_index)
        self.view.imageActivated.connect(self.open_viewer)
        self.view.deleteRequested.connect(self.delete_selected)
        self.view.customContextMenuRequested.connect(self._show_menu)
        for signal in (controller.dataChanged, controller.userChanged):
            signal.connect(self.refresh)
        self.refresh()

    # ------------------------------------------------------------------ showing
    def refresh(self) -> None:
        if not self.controller.is_open:
            self.model.set_images([])
            self.summary.setText("")
            self._show_empty("")
            return
        everything = sorted(self.controller.all_images(), key=lambda i: i.added_at, reverse=True)
        self._fill_tags()
        shown = filter_images(everything, self.tag_filter.currentData(), self.search.text())
        keep = self.view.selected_ids()
        self.model.set_images(shown)
        for image_id in keep:
            row = self.model.row_of(image_id)
            if row >= 0:
                self.view.selectionModel().select(self.model.index(row), self.view.selectionModel().SelectionFlag.Select)
        total = len(everything)
        self.summary.setText(f"{total} picture(s)" + (f", {len(shown)} shown" if len(shown) != total else ""))
        if not everything:
            self._show_empty("No pictures yet.\n\nAdd pictures here, or from any subject or study point: use its Pictures tab, "
                             "paste with Ctrl+V, or drop picture files onto it. Tag them (for example \u201cblackboard\u201d) so you can find them again.")
        elif not shown:
            self._show_empty("No picture matches this search or tag.")
        else:
            self._show_empty("")

    def _show_empty(self, text: str) -> None:
        self.empty.setText(text)
        self.empty.setVisible(bool(text))
        self.view.setVisible(not text)

    def _fill_tags(self) -> None:
        keep = self.tag_filter.currentData()
        self.tag_filter.blockSignals(True)
        self.tag_filter.clear()
        self.tag_filter.addItem("All pictures", None)
        for tag, count in self.controller.tag_counts().items():
            self.tag_filter.addItem(f"{tag}  ({count})", tag)
        index = next((i for i in range(self.tag_filter.count()) if self.tag_filter.itemData(i) == keep), 0)
        self.tag_filter.setCurrentIndex(index)
        self.tag_filter.blockSignals(False)

    def _on_filter_text(self, _text: str) -> None:
        self.refresh()

    def _on_filter_index(self, _index: int) -> None:
        self.refresh()

    # ------------------------------------------------------------------ actions
    def open_viewer(self, image_id: str) -> None:
        ids = self.model.image_ids()
        if image_id not in ids:
            return
        viewer = ImageViewerDialog(self.controller, ids, ids.index(image_id), parent=self)
        viewer.locationRequested.connect(self.openLocationRequested)
        viewer.exec()

    def add_pictures(self) -> None:
        """Pictures always belong somewhere, so after choosing files you choose the subject or study point."""
        if not self.controller.subjects():
            util.show_error(self, "Create a subject first: pictures are shown on a subject or on one of its study points.")
            return
        paths = util.ask_open_files(self, "Add pictures", image_import.PICTURE_FILTER)
        if not paths:
            return
        target = TargetPickerDialog.ask(self, self.controller, "Add pictures", "Show the pictures on:", ok_text="Add here")
        if target is not None:
            image_import.import_pictures(self.controller, self, paths, target[0], target[1])

    def delete_selected(self) -> None:
        image_import.delete_everywhere(self.controller, self, self.view.selected_ids())

    def _show_menu(self, position) -> None:
        index = self.view.indexAt(position)
        if not index.isValid():
            return
        if not self.view.selectionModel().isSelected(index):
            self.view.setCurrentIndex(index)
        menu = QMenu(self)
        open_action = menu.addAction("Open")
        also_action = menu.addAction("Also show in\u2026")
        delete_action = menu.addAction("Delete everywhere\u2026")
        chosen = util.exec_menu(menu, self.view.viewport().mapToGlobal(position))
        image_id = self.model.data(index, Qt.ItemDataRole.UserRole)
        if chosen is open_action:
            self.open_viewer(image_id)
        elif chosen is also_action:
            self._also_show_in(self.view.selected_ids())
        elif chosen is delete_action:
            self.delete_selected()

    def _also_show_in(self, image_ids: list[str]) -> None:
        taken = set.intersection(*(set(self.controller.usage(i)) for i in image_ids)) if image_ids else set()
        target = TargetPickerDialog.ask(self, self.controller, "Also show in\u2026", "Show the selected pictures in:", taken, ok_text="Show there")
        if target is None:
            return
        for image_id in image_ids:
            try:
                self.controller.link_image(image_id, target[0], target[1])
            except (StorageError, NoUserOpenError, ValueError) as exc:
                util.show_error(self, str(exc))
