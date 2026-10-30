"""Choose pictures that are already in StudyFlow (to show them in one more place)."""
from __future__ import annotations

from typing import Container, Optional

from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from ..controller import AppController
from ..widgets.image_list import ImageListModel, ImageListView


def filter_images(images, tag: Optional[str], text: str):
    """Pictures carrying `tag` (any if None) whose file name or tags contain every word of `text`."""
    words = text.casefold().split()
    chosen = []
    for image in images:
        haystack = (image.original_name + " " + " ".join(image.tags)).casefold()
        if (tag is None or tag in image.tags) and all(w in haystack for w in words):
            chosen.append(image)
    return chosen


class ImagePickerDialog(QDialog):
    def __init__(
        self,
        controller: AppController,
        exclude_ids: Container[str] = (),
        title: str = "Show existing pictures",
        label: str = "Pick pictures to show here:",
        ok_text: str = "Show here",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle(title)
        self.setMinimumSize(640, 480)
        self._all = sorted((i for i in controller.all_images() if i.id not in exclude_ids), key=lambda i: i.added_at, reverse=True)

        prompt = QLabel(label)
        self.tag_filter = QComboBox()
        self.tag_filter.addItem("All pictures", None)
        for tag, count in controller.tag_counts().items():
            self.tag_filter.addItem(f"{tag}  ({count})", tag)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by file name or tag")
        self.empty = QLabel("There are no other pictures to choose from.\nAdd pictures to a subject or study point first.")
        self.empty.setObjectName("muted")
        self.model = ImageListModel(controller, parent=self)
        self.view = ImageListView(self.model)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setText(ok_text)
        self.ok_button.setDefault(True)

        top = QHBoxLayout()
        top.addWidget(self.search, 1)
        top.addWidget(self.tag_filter)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)
        layout.addWidget(prompt)
        layout.addLayout(top)
        layout.addWidget(self.view, 1)
        layout.addWidget(self.empty, 1)
        layout.addWidget(self.buttons)

        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.search.textChanged.connect(self._on_filter_changed)
        self.tag_filter.currentIndexChanged.connect(self._on_filter_index_changed)
        self.view.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.view.imageActivated.connect(self._on_activated)
        self._apply_filter()

    def _apply_filter(self) -> None:
        shown = filter_images(self._all, self.tag_filter.currentData(), self.search.text())
        self.model.set_images(shown)
        self.view.setVisible(bool(self._all))
        self.empty.setVisible(not self._all)
        self._update_ok()

    def _on_filter_changed(self, _text: str) -> None:
        self._apply_filter()

    def _on_filter_index_changed(self, _index: int) -> None:
        self._apply_filter()

    def _on_selection_changed(self, _selected, _deselected) -> None:
        self._update_ok()

    def _on_activated(self, image_id: str) -> None:
        self.accept()

    def _update_ok(self) -> None:
        self.ok_button.setEnabled(bool(self.selected_ids()))

    def selected_ids(self) -> list[str]:
        return self.view.selected_ids()

    @staticmethod
    def ask(parent, controller: AppController, exclude_ids: Container[str] = (), **kwargs) -> list[str]:
        dialog = ImagePickerDialog(controller, exclude_ids, parent=parent, **kwargs)
        return dialog.selected_ids() if dialog.exec() == QDialog.DialogCode.Accepted else []
