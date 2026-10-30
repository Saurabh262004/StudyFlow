"""Helpers shared by the picture tests."""
from pathlib import Path

from PySide6.QtGui import QColor, QImage


def make_picture(path, width=320, height=240, color="#2a6f4e") -> Path:
    """A plain coloured picture file (format from the extension)."""
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    path = Path(path)
    assert image.save(str(path)), path
    return path
