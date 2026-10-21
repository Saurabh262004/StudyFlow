"""A small "type a name" dialog that checks the text while you type."""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QLineEdit, QVBoxLayout, QWidget


class NameDialog(QDialog):
    """`validator(text)` returns None when the text is fine, or a message saying what is wrong.
    OK stays disabled until the text is non-empty and valid; the message appears as soon as you type."""

    def __init__(
        self,
        title: str,
        label: str,
        validator: Callable[[str], Optional[str]],
        initial: str = "",
        ok_text: str = "OK",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(380)
        self._validator = validator

        self.prompt = QLabel(label)
        self.prompt.setWordWrap(True)
        self.edit = QLineEdit(initial)
        self.error = QLabel("")
        self.error.setObjectName("errorText")
        self.error.setWordWrap(True)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setText(ok_text)
        self.ok_button.setDefault(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 18, 20, 16)
        for w in (self.prompt, self.edit, self.error, self.buttons):
            layout.addWidget(w)

        self.edit.textChanged.connect(self._check)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self._check(initial, quiet=True)
        self.edit.selectAll()
        self.edit.setFocus()

    def _check(self, text: str, quiet: bool = False) -> None:
        text = text.strip()
        problem = self._validator(text) if text else None
        self.error.setText(problem or "")
        self.ok_button.setEnabled(bool(text) and problem is None)

    def value(self) -> str:
        return self.edit.text().strip()

    @staticmethod
    def ask(
        parent: Optional[QWidget],
        title: str,
        label: str,
        validator: Callable[[str], Optional[str]],
        initial: str = "",
        ok_text: str = "OK",
    ) -> Optional[str]:
        """Show the dialog; returns the name, or None if cancelled."""
        dialog = NameDialog(title, label, validator, initial, ok_text, parent)
        return dialog.value() if dialog.exec() == QDialog.DialogCode.Accepted else None
