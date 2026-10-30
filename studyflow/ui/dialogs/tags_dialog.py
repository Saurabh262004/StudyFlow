"""Ask for tags (comma separated), suggesting the ones you have used before."""
from __future__ import annotations

from typing import Iterable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCompleter, QDialog, QDialogButtonBox, QLabel, QLineEdit, QVBoxLayout, QWidget

from ...models import normalise_tags


def parse_tags(text: str) -> list[str]:
    """"Blackboard, unit 3,,blackboard" -> ["blackboard", "unit 3"]"""
    return normalise_tags(text.split(","))


class _TagCompleter(QCompleter):
    """Completes only the tag you are typing (the part after the last comma), keeping the rest of the line."""

    def splitPath(self, path: str) -> list[str]:  # noqa: N802 (Qt name)
        return [path.split(",")[-1].strip()]

    def pathFromIndex(self, index) -> str:  # noqa: N802 (Qt name)
        completed = super().pathFromIndex(index)
        line = self.widget().text()
        head = line[: line.rfind(",") + 1] if "," in line else ""
        return (head + " " if head else "") + completed


class TagsDialog(QDialog):
    def __init__(
        self,
        title: str,
        label: str,
        suggestions: Iterable[str] = (),
        initial: str = "",
        ok_text: str = "OK",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        suggestions = list(suggestions)

        prompt = QLabel(label)
        prompt.setWordWrap(True)
        self.edit = QLineEdit(initial)
        self.edit.setPlaceholderText("e.g. blackboard, unit 3")
        completer = _TagCompleter(suggestions, self.edit)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchStartsWith)
        self.edit.setCompleter(completer)
        self.completer = completer
        self.hint = QLabel(("Your tags: " + ", ".join(suggestions[:12]) + ("\u2026" if len(suggestions) > 12 else "")) if suggestions else "Separate tags with commas.")
        self.hint.setObjectName("muted")
        self.hint.setWordWrap(True)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setText(ok_text)
        self.ok_button.setDefault(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)
        for widget in (prompt, self.edit, self.hint, self.buttons):
            layout.addWidget(widget)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.edit.setFocus()

    def tags(self) -> list[str]:
        return parse_tags(self.edit.text())

    @staticmethod
    def ask(parent, title: str, label: str, suggestions: Iterable[str] = (), initial: str = "", ok_text: str = "OK") -> Optional[list[str]]:
        """Show the dialog. Returns the tags (possibly none), or None if it was cancelled."""
        dialog = TagsDialog(title, label, suggestions, initial, ok_text, parent)
        return dialog.tags() if dialog.exec() == QDialog.DialogCode.Accepted else None
