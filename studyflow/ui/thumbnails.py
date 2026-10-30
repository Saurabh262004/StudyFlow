"""Loading pictures for display: small thumbnails (cached) and large versions for the viewer.

Phone photos are big and usually stored "sideways" with a rotation note (EXIF orientation); QImageReader with
auto-transform turns them upright. Thumbnails are decoded at reduced size (JPEG can do that cheaply), so a folder of
12-megapixel blackboard photos is quick to show."""
from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QImage, QImageReader, QPainter, QPixmap

THUMB_SIZE = 96  # longest side, in device-independent pixels


def read_image(path: Path, max_side: int = 0) -> Optional[QImage]:
    """The picture upright, no larger than `max_side` on its longest side (0 = full size). None if unreadable."""
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    if not reader.canRead():
        return None
    if max_side:
        size = reader.size()  # the stored size; the reader turns the result upright after scaling
        if size.isValid() and max(size.width(), size.height()) > max_side:
            size.scale(max_side, max_side, Qt.AspectRatioMode.KeepAspectRatio)
            reader.setScaledSize(size)
    image = reader.read()
    if image.isNull():
        return None
    if max_side and max(image.width(), image.height()) > max_side:  # formats that cannot decode at reduced size
        image = image.scaled(max_side, max_side, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    return image


def square(image: QImage, side: int) -> QPixmap:
    """The picture centred on a transparent square, so portrait and landscape thumbnails take the same room
    (otherwise the caption of a tall picture is drawn over the picture itself).
    Drawn on a QImage with an explicit alpha format, so the transparent padding is guaranteed on every platform."""
    canvas = QImage(side, side, QImage.Format.Format_ARGB32_Premultiplied)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.drawImage((side - image.width()) // 2, (side - image.height()) // 2, image)
    painter.end()
    return QPixmap.fromImage(canvas)


def placeholder(size: int, text: str, dark_background: str = "#2a3040", ink: str = "#aab3c5") -> QPixmap:
    """A square stand-in for a picture that is missing or unreadable."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(dark_background))
    painter = QPainter(pixmap)
    painter.setPen(QColor(ink))
    font = QFont()
    font.setPixelSize(max(9, size // 8))
    painter.setFont(font)
    painter.drawText(QRect(0, 0, size, size), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, text)
    painter.end()
    return pixmap


class ThumbnailCache:
    """Remembers the most recent thumbnails. A picture file never changes once imported (its id is its name), so the
    cache can be keyed by file path; it is emptied explicitly with forget() when a picture is deleted."""

    def __init__(self, capacity: int = 400) -> None:
        self._capacity = capacity
        self._items: "OrderedDict[tuple[str, int], QPixmap]" = OrderedDict()

    def get(self, path: Path, size: int = THUMB_SIZE, dpr: float = 1.0) -> QPixmap:
        key = (str(path), round(size * dpr))
        cached = self._items.get(key)
        if cached is not None:
            self._items.move_to_end(key)
            return cached
        image = read_image(path, round(size * dpr))
        if image is None:
            pixmap = placeholder(round(size * dpr), "missing" if not path.exists() else "unreadable")
        else:
            pixmap = square(image, round(size * dpr))
        pixmap.setDevicePixelRatio(dpr)
        self._items[key] = pixmap
        while len(self._items) > self._capacity:
            self._items.popitem(last=False)
        return pixmap

    def forget(self, path: Path) -> None:
        for key in [k for k in self._items if k[0] == str(path)]:
            del self._items[key]

    def __len__(self) -> int:
        return len(self._items)


def fit(size: QSize, box: QSize) -> QSize:
    """`size` scaled down (never up) to fit in `box`, keeping its proportions."""
    if size.width() <= box.width() and size.height() <= box.height():
        return size
    scaled = QSize(size)
    scaled.scale(box, Qt.AspectRatioMode.KeepAspectRatio)
    return scaled


_shared: Optional[ThumbnailCache] = None


def shared_cache() -> ThumbnailCache:
    """One cache for the whole app (pictures of different users live in different folders, so paths never clash)."""
    global _shared
    if _shared is None:
        _shared = ThumbnailCache()
    return _shared
