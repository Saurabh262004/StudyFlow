"""Tiny wrappers around Qt's standard dialogs. They live in one place so tests can replace them
(a real message box would wait for a click) and so every dialog looks and words things the same way."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import QCheckBox, QFileDialog, QMessageBox, QWidget


def show_error(parent: Optional[QWidget], message: str) -> None:
    QMessageBox.warning(parent, "StudyFlow", message)


def confirm(
    parent: Optional[QWidget],
    title: str,
    text: str,
    ok_text: str = "Delete",
    detail: str = "",
    checkbox_text: Optional[str] = None,
) -> Optional[bool]:
    """Ask before something destructive. Returns None if the user cancelled, otherwise the state of the
    optional checkbox (False when there is no checkbox). Cancel is the default button."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(title)
    box.setText(text)
    if detail:
        box.setInformativeText(detail)
    checkbox = None
    if checkbox_text:
        checkbox = QCheckBox(checkbox_text)
        box.setCheckBox(checkbox)
    ok = box.addButton(ok_text, QMessageBox.ButtonRole.DestructiveRole)
    cancel = box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(cancel)
    box.exec()
    if box.clickedButton() is not ok:
        return None
    return bool(checkbox.isChecked()) if checkbox is not None else False


def ask_save_path(parent: Optional[QWidget], title: str, default_name: str, file_filter: str = "Zip files (*.zip)") -> Optional[Path]:
    path, _ = QFileDialog.getSaveFileName(parent, title, default_name, file_filter)
    return Path(path) if path else None
