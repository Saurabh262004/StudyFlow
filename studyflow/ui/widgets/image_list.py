"""A list of pictures as thumbnails: the model and view used by the picture strips, the gallery and the pickers."""
from __future__ import annotations

from typing import Iterable, Optional

from PySide6.QtCore import QAbstractListModel, QModelIndex, QSize, Qt, Signal
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QAbstractItemView, QListView, QWidget

from ...models import ImageRecord
from .. import thumbnails
from ..controller import AppController

ID_ROLE = Qt.ItemDataRole.UserRole


def caption_for(record: ImageRecord) -> str:
    return ", ".join(record.tags)


class ImageListModel(QAbstractListModel):
    """Pictures of the open user. Thumbnails are loaded when the view first asks for them (so only what is on
    screen is ever decoded) and kept in a shared cache."""

    def __init__(self, controller: AppController, icon_size: int = thumbnails.THUMB_SIZE, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.icon_size = icon_size
        self._records: list[ImageRecord] = []

    def set_images(self, records: Iterable[ImageRecord]) -> None:
        self.beginResetModel()
        self._records = list(records)
        self.endResetModel()

    def image_at(self, row: int) -> ImageRecord:
        return self._records[row]

    def image_ids(self) -> list[str]:
        return [r.id for r in self._records]

    def row_of(self, image_id: str) -> int:
        return next((i for i, r in enumerate(self._records) if r.id == image_id), -1)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._records)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._records):
            return None
        record = self._records[index.row()]
        if role == Qt.ItemDataRole.DecorationRole:
            screen = QGuiApplication.primaryScreen()
            pixmap = thumbnails.shared_cache().get(self.controller.image_path(record), self.icon_size, screen.devicePixelRatio() if screen else 1.0)
            return QIcon(pixmap)
        if role == Qt.ItemDataRole.DisplayRole:
            return caption_for(record)
        if role == ID_ROLE:
            return record.id
        if role == Qt.ItemDataRole.ToolTipRole:
            places = len(self.controller.usage(record.id))
            tags = ", ".join(record.tags) or "none"
            return f"{record.original_name}\nTags: {tags}\nShown in {places} place(s)"
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable


class ImageListView(QListView):
    """Thumbnails in a wrapping grid, or in a single scrolling row (`row=True`)."""

    imageActivated = Signal(str)  # double click or Enter on a picture
    deleteRequested = Signal()  # the Delete key

    def __init__(self, model: ImageListModel, row: bool = False, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("imageView")
        self.setModel(model)
        size = model.icon_size
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setIconSize(QSize(size, size))
        self.setGridSize(QSize(size + 26, size + 44))
        self.setMovement(QListView.Movement.Static)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setUniformItemSizes(True)
        self.setSpacing(4)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setAcceptDrops(False)  # drops go to the strip around us (see ImageStrip)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        if row:
            self.setFlow(QListView.Flow.LeftToRight)
            self.setWrapping(False)
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.setFixedHeight(size + 44 + 18)
        self.doubleClicked.connect(self._on_double_click)

    def selected_ids(self) -> list[str]:
        model = self.model()
        return [model.data(i, ID_ROLE) for i in sorted(self.selectionModel().selectedIndexes(), key=lambda i: i.row())]

    def _on_double_click(self, index: QModelIndex) -> None:
        self.imageActivated.emit(self.model().data(index, ID_ROLE))

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt name)
        index = self.currentIndex()
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and index.isValid():
            self.imageActivated.emit(self.model().data(index, ID_ROLE))
            return
        if event.key() == Qt.Key.Key_Delete and self.selectionModel().hasSelection():
            self.deleteRequested.emit()
            return
        super().keyPressEvent(event)
