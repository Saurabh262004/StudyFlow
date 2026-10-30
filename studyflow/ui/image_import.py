"""Getting pictures into the app (file picker, drag-and-drop, clipboard) and taking them out of a place.

Shared by the picture strips, the gallery and the viewer so they all behave and word things the same way."""
from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Iterable, Optional

from PySide6.QtCore import QMimeData
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget

from ..models import ImageRecord, NotFoundError
from ..storage import IMAGE_EXTENSIONS, StorageError
from . import util
from .controller import AppController, NoUserOpenError
from .dialogs.tags_dialog import TagsDialog

PICTURE_FILTER = "Pictures (" + " ".join(f"*{ext}" for ext in sorted(IMAGE_EXTENSIONS)) + ");;All files (*)"


def picture_paths_from_mime(mime: QMimeData) -> tuple[list[Path], int]:
    """Local picture files in dropped / pasted data, and how many other items were ignored."""
    paths, ignored = [], 0
    for url in mime.urls() if mime.hasUrls() else []:
        if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in IMAGE_EXTENSIONS and Path(url.toLocalFile()).is_file():
            paths.append(Path(url.toLocalFile()))
        else:
            ignored += 1
    return paths, ignored


def can_accept(mime: QMimeData) -> bool:
    paths, _ = picture_paths_from_mime(mime)
    return bool(paths)


def import_pictures(
    controller: AppController,
    parent: Optional[QWidget],
    paths: Iterable[Path],
    subject_id: str,
    point_id: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> list[ImageRecord]:
    """Add pictures to a subject or study point. Asks once for tags for the whole batch (unless `tags` is given).
    Pictures that cannot be added are reported together at the end; the rest are still added."""
    paths = list(paths)
    if not paths:
        return []
    if tags is None:
        label = f"Tags for {'this picture' if len(paths) == 1 else f'these {len(paths)} pictures'} (optional):"
        tags = TagsDialog.ask(parent, "Add pictures", label, list(controller.tag_counts()), ok_text="Add")
        if tags is None:
            return []
    added, failures = [], []
    for path in paths:
        try:
            added.append(controller.import_image(path, subject_id, point_id, tags))
        except (StorageError, ValueError, NotFoundError, NoUserOpenError) as exc:
            failures.append(f"{path.name}: {exc}")
    if failures:
        util.show_error(parent, "Some pictures could not be added:\n\n" + "\n".join(failures))
    return added


def paste_picture(
    controller: AppController, parent: Optional[QWidget], subject_id: str, point_id: Optional[str] = None
) -> list[ImageRecord]:
    """Add whatever picture is on the clipboard: a copied image (e.g. a screenshot) or copied picture files."""
    mime = QGuiApplication.clipboard().mimeData()
    if mime is None:
        util.show_error(parent, "There is no picture on the clipboard.")
        return []
    files, _ = picture_paths_from_mime(mime)
    if files:
        return import_pictures(controller, parent, files, subject_id, point_id)
    image = QGuiApplication.clipboard().image()
    if image.isNull():
        util.show_error(parent, "There is no picture on the clipboard.")
        return []
    with tempfile.TemporaryDirectory() as folder:  # the app keeps its own copy, so the temporary file can go
        path = Path(folder) / f"Pasted picture {time.strftime('%Y-%m-%d %H.%M.%S')}.png"
        if not image.save(str(path), "PNG"):
            util.show_error(parent, "The pasted picture could not be read.")
            return []
        return import_pictures(controller, parent, [path], subject_id, point_id)


def remove_from_place(
    controller: AppController, parent: Optional[QWidget], image_ids: Iterable[str], subject_id: str, point_id: Optional[str] = None
) -> int:
    """Stop showing pictures on a subject / study point. A picture that is shown nowhere else would be deleted, so
    that asks first. Returns how many pictures were removed from this place."""
    removed = 0
    for image_id in list(image_ids):
        try:
            if len(controller.usage(image_id)) <= 1:
                answer = util.confirm(
                    parent, "Remove picture", "Remove this picture?", ok_text="Remove and delete",
                    detail="This is the only place the picture is used, so removing it deletes the picture from StudyFlow.",
                )
                if answer is None:
                    continue
            controller.unlink_image(image_id, subject_id, point_id)
            removed += 1
        except (StorageError, NotFoundError, ValueError, NoUserOpenError) as exc:
            util.show_error(parent, str(exc))
    return removed


def delete_everywhere(controller: AppController, parent: Optional[QWidget], image_ids: Iterable[str]) -> int:
    """Delete pictures from every place they are used (after asking). Returns how many were deleted."""
    ids = list(image_ids)
    if not ids:
        return 0
    places = sum(len(controller.usage(i)) for i in ids)
    what = "this picture" if len(ids) == 1 else f"these {len(ids)} pictures"
    answer = util.confirm(
        parent, "Delete pictures", f"Delete {what}?", ok_text="Delete",
        detail=f"It is shown in {places} place(s). It will be removed from all of them and deleted from StudyFlow. This cannot be undone.",
    )
    if answer is None:
        return 0
    deleted = 0
    for image_id in ids:
        try:
            controller.delete_image(image_id)
            deleted += 1
        except (StorageError, NotFoundError, ValueError, NoUserOpenError) as exc:
            util.show_error(parent, str(exc))
    return deleted
