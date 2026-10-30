"""Pick a subject, or one of its study points, as the place for a picture."""
from __future__ import annotations

from typing import Container, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from ..controller import AppController

TARGET_ROLE = Qt.ItemDataRole.UserRole
Target = tuple[str, Optional[str]]  # (subject id, study point id or None for the subject itself)


class TargetPickerDialog(QDialog):
    def __init__(
        self,
        controller: AppController,
        title: str,
        label: str,
        taken: Container[Target] = (),
        ok_text: str = "OK",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(420, 420)
        prompt = QLabel(label)
        prompt.setWordWrap(True)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(18)
        self.tree.setObjectName("targetTree")
        for subject in sorted(controller.subjects(), key=lambda s: s.name.casefold()):
            top = self._item(subject.name, (subject.id, None), taken)
            self.tree.addTopLevelItem(top)
            for point in subject.points:
                top.addChild(self._item(point.title, (subject.id, point.id), taken))
            top.setExpanded(True)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setText(ok_text)
        self.ok_button.setDefault(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)
        layout.addWidget(prompt)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.buttons)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.tree.currentItemChanged.connect(self._on_current_changed)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self._update_ok()

    @staticmethod
    def _item(text: str, target: Target, taken: Container[Target]) -> QTreeWidgetItem:
        item = QTreeWidgetItem([text + ("   (already here)" if target in taken else "")])
        item.setData(0, TARGET_ROLE, target)
        if target in taken:
            item.setFlags(Qt.ItemFlag.NoItemFlags)  # shown, but cannot be picked
        return item

    def selected(self) -> Optional[Target]:
        item = self.tree.currentItem()
        return item.data(0, TARGET_ROLE) if item is not None and item.flags() & Qt.ItemFlag.ItemIsSelectable else None

    def _update_ok(self) -> None:
        self.ok_button.setEnabled(self.selected() is not None)

    def _on_current_changed(self, _current, _previous) -> None:
        self._update_ok()

    def _on_double_click(self, _item, _column) -> None:
        if self.selected() is not None:
            self.accept()

    @staticmethod
    def ask(parent, controller: AppController, title: str, label: str, taken: Container[Target] = (), ok_text: str = "OK") -> Optional[Target]:
        dialog = TargetPickerDialog(controller, title, label, taken, ok_text, parent)
        return dialog.selected() if dialog.exec() == QDialog.DialogCode.Accepted else None
