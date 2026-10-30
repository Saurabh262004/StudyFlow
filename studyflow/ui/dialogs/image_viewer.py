"""Look at one picture large, browse the others, and manage it: tags, where it is shown, remove, delete."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...models import NotFoundError
from ...storage import StorageError
from .. import image_import, thumbnails, util
from ..controller import AppController, NoUserOpenError
from .tags_dialog import TagsDialog, parse_tags
from .target_picker import TargetPickerDialog

MAX_SIDE = 2600  # pictures are shown at most this big (a 12-megapixel photo is ~4000 px)


class ImageViewerDialog(QDialog):
    locationRequested = Signal(str, str)  # subject id, study point id ("" = the subject itself): "take me there"

    def __init__(
        self,
        controller: AppController,
        image_ids: list[str],
        index: int = 0,
        subject_id: Optional[str] = None,
        point_id: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.subject_id, self.point_id = subject_id, point_id  # the place we were opened from, if any
        self._ids = list(image_ids)
        self._index = max(0, min(index, len(self._ids) - 1))
        self._full: Optional[QPixmap] = None
        self._info = ""
        self._tags_dirty = False  # true only after the USER typed in the tags field (loading a picture is not an edit)
        self._fit = True
        self.setWindowTitle("Picture")
        self.resize(1040, 680)
        self.setMinimumSize(760, 480)

        # ---- the picture
        self.picture = QLabel()
        self.picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.picture)
        self.scroll.setWidgetResizable(False)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._viewport = self.scroll.viewport()  # (our own reference: the scroll area may already be gone while we shut down)
        self._viewport.installEventFilter(self)
        self.previous_button = QPushButton("\u2039  Previous")
        self.next_button = QPushButton("Next  \u203a")
        self.position = QLabel()
        self.position.setObjectName("muted")
        self.fit_button = QPushButton("Actual size")
        navigation = QHBoxLayout()
        navigation.addWidget(self.previous_button)
        navigation.addWidget(self.position, 1, Qt.AlignmentFlag.AlignCenter)
        navigation.addWidget(self.fit_button)
        navigation.addWidget(self.next_button)
        left = QVBoxLayout()
        left.addWidget(self.scroll, 1)
        left.addLayout(navigation)

        # ---- the details
        self.name = QLabel()
        self.name.setObjectName("cardTitle")
        self.name.setStyleSheet("font-size: 13pt;")
        self.name.setWordWrap(True)
        self.meta = QLabel()
        self.meta.setObjectName("muted")
        self.meta.setWordWrap(True)
        tags_label = QLabel("TAGS")
        tags_label.setObjectName("sectionLabel")
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("Separate tags with commas")
        used_label = QLabel("SHOWN IN")
        used_label.setObjectName("sectionLabel")
        self.used = QListWidget()
        self.used.setToolTip("Double-click a place to go there")
        self.also_button = QPushButton("Also show in\u2026")
        self.remove_button = QPushButton("Remove from here")
        self.delete_button = QPushButton("Delete everywhere\u2026")
        self.close_button = QPushButton("Close")
        side = QVBoxLayout()
        side.setSpacing(8)
        for widget in (self.name, self.meta, tags_label, self.tags_edit, used_label):
            side.addWidget(widget)
        side.addWidget(self.used, 1)
        for widget in (self.also_button, self.remove_button, self.delete_button, self.close_button):
            side.addWidget(widget)
        panel = QWidget()
        panel.setFixedWidth(290)
        panel.setLayout(side)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 14)
        layout.setSpacing(16)
        layout.addLayout(left, 1)
        layout.addWidget(panel)

        self.previous_button.clicked.connect(self.show_previous)
        self.next_button.clicked.connect(self.show_next)
        self.fit_button.clicked.connect(self.toggle_fit)
        self.tags_edit.textEdited.connect(self._on_tags_edited)
        self.tags_edit.editingFinished.connect(self.save_tags)
        self.also_button.clicked.connect(self.also_show_in)
        self.remove_button.clicked.connect(self.remove_from_here)
        self.delete_button.clicked.connect(self.delete_everywhere)
        self.close_button.clicked.connect(self.accept)
        self.used.itemDoubleClicked.connect(self._on_place_double_clicked)
        controller.dataChanged.connect(self._on_data_changed)
        self.show_index(self._index)

    # ------------------------------------------------------------------ showing
    @property
    def current_id(self) -> Optional[str]:
        return self._ids[self._index] if self._ids else None

    def show_index(self, index: int) -> None:
        self.save_tags()  # do not lose tags typed for the picture we are leaving
        if not self._ids:
            return
        self._index = max(0, min(index, len(self._ids) - 1))
        record = self.controller.get_image(self._ids[self._index])
        image = thumbnails.read_image(self.controller.image_path(record), MAX_SIDE)
        self._full = QPixmap.fromImage(image) if image is not None else None
        self._info = f"{image.width()} \u00d7 {image.height()} pixels" if image is not None else "The picture file is missing or cannot be read"
        self._update_details()
        self._update_picture()

    def _update_details(self) -> None:
        record = self.controller.get_image(self._ids[self._index])
        self.name.setText(record.original_name or "Picture")
        self.meta.setText(f"Added {record.added_at.astimezone():%d %b %Y, %H:%M}\n{self._info}")
        if not self._tags_dirty:  # never overwrite what the user is in the middle of typing
            self.tags_edit.setText(", ".join(record.tags))
        self.used.clear()
        for place in self.controller.describe_usage(record.id):
            self.used.addItem(place)
        usage = self.controller.usage(record.id)
        for row, (subject_id, point_id) in enumerate(usage):
            self.used.item(row).setData(Qt.ItemDataRole.UserRole, (subject_id, point_id or ""))
        here = self.subject_id is not None and (self.subject_id, self.point_id) in usage
        self.remove_button.setVisible(here)
        self.position.setText(f"{self._index + 1} of {len(self._ids)}")
        self.previous_button.setEnabled(self._index > 0)
        self.next_button.setEnabled(self._index < len(self._ids) - 1)

    def _update_picture(self) -> None:
        if self._full is None:
            self.picture.setPixmap(QPixmap())
            self.picture.setText(self._info)
            self.picture.resize(self.scroll.viewport().size())
            return
        self.picture.setText("")
        if self._fit:
            box = self.scroll.viewport().size() - QSize(4, 4)
            shown = self._full.scaled(box, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation) if (
                self._full.width() > box.width() or self._full.height() > box.height()) else self._full
        else:
            shown = self._full
        self.picture.setPixmap(shown)
        self.picture.resize(max(shown.width(), self.scroll.viewport().width()), max(shown.height(), self.scroll.viewport().height()))
        self.fit_button.setText("Actual size" if self._fit else "Fit to window")

    # ------------------------------------------------------------------ navigation
    def show_next(self) -> None:
        if self._index < len(self._ids) - 1:
            self.show_index(self._index + 1)

    def show_previous(self) -> None:
        if self._index > 0:
            self.show_index(self._index - 1)

    def toggle_fit(self) -> None:
        self._fit = not self._fit
        self._update_picture()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 (Qt name)
        """Re-fit the picture whenever the area it is shown in changes size. (A dialog resize event is not enough:
        the first layout when the dialog is shown changes that area without resizing the dialog.)"""
        if watched is self._viewport and event.type() == QEvent.Type.Resize and self._fit and self._full is not None:
            self._update_picture()
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt name)
        if not self.tags_edit.hasFocus():
            if event.key() == Qt.Key.Key_Right:
                self.show_next()
                return
            if event.key() == Qt.Key.Key_Left:
                self.show_previous()
                return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------ actions
    def _on_tags_edited(self, _text: str) -> None:
        self._tags_dirty = True

    def save_tags(self) -> None:
        """Save the tags the user typed. Does nothing unless they typed something: an untouched (or still empty)
        field must never be mistaken for "remove all tags"."""
        image_id = self.current_id
        if not self._tags_dirty or image_id is None:
            return
        self._tags_dirty = False
        try:
            record = self.controller.get_image(image_id)
        except (NotFoundError, NoUserOpenError):
            return
        tags = parse_tags(self.tags_edit.text())
        if tags != record.tags:
            try:
                self.controller.set_image_tags(image_id, tags)
            except (StorageError, ValueError, NotFoundError) as exc:
                util.show_error(self, str(exc))
        if not self.tags_edit.hasFocus():
            self.tags_edit.setText(", ".join(self.controller.get_image(image_id).tags))  # tidy spacing / case; shows what is saved

    def also_show_in(self) -> None:
        image_id = self.current_id
        if image_id is None:
            return
        taken = set(self.controller.usage(image_id))
        target = TargetPickerDialog.ask(self, self.controller, "Also show in\u2026", "Show this picture in:", taken, ok_text="Show there")
        if target is None:
            return
        try:
            self.controller.link_image(image_id, target[0], target[1])
        except (StorageError, ValueError, NotFoundError) as exc:
            util.show_error(self, str(exc))

    def remove_from_here(self) -> None:
        if self.current_id is not None and self.subject_id is not None:
            image_import.remove_from_place(self.controller, self, [self.current_id], self.subject_id, self.point_id)

    def delete_everywhere(self) -> None:
        if self.current_id is not None:
            image_import.delete_everywhere(self.controller, self, [self.current_id])

    def _on_place_double_clicked(self, item: QListWidgetItem) -> None:
        subject_id, point_id = item.data(Qt.ItemDataRole.UserRole)
        self.save_tags()
        self.locationRequested.emit(subject_id, point_id)
        self.accept()

    def _on_data_changed(self) -> None:
        """Something changed (maybe this very picture was deleted or removed): keep the viewer in line."""
        current = self.current_id
        existing = {r.id for r in self.controller.all_images()}
        self._ids = [i for i in self._ids if i in existing]
        if not self._ids:
            self.reject()
            return
        if current in existing:
            self._index = self._ids.index(current)
            self._update_details()
        else:
            self._index = min(self._index, len(self._ids) - 1)
            self._tags_dirty = False  # whatever was typed belonged to the picture that is gone
            self.show_index(self._index)

    def done(self, result: int) -> None:  # noqa: N802 (Qt name)
        self.save_tags()
        try:
            self._viewport.removeEventFilter(self)
        except RuntimeError:
            pass
        try:
            self.controller.dataChanged.disconnect(self._on_data_changed)
        except (RuntimeError, TypeError):
            pass
        super().done(result)
