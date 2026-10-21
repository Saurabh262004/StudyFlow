from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QPlainTextEdit


class NotesEdit(QPlainTextEdit):
    """Plain-text notes box that also says when the user clicked or tabbed away (a good moment to save)."""

    editingFinished = Signal()

    def focusOutEvent(self, event) -> None:  # noqa: N802 (Qt name)
        super().focusOutEvent(event)
        self.editingFinished.emit()
