"""What happens when the app starts (and when the open user disappears): get a user opened."""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QWidget

from .controller import START_CREATE_FIRST_USER, START_READY, AppController
from .dialogs.name_dialog import NameDialog
from .dialogs.user_picker import UserPickerDialog
from . import util
from ..storage import StorageError


def run_startup(controller: AppController, parent: Optional[QWidget] = None) -> bool:
    """True when a user is open and the main window can be shown, False if the user gave up."""
    result = controller.start()
    if result.state == START_READY:
        return True
    if result.state == START_CREATE_FIRST_USER:
        return _create_first_user(controller, parent)
    return choose_user(controller, error=result.error, parent=parent)


def _create_first_user(controller: AppController, parent: Optional[QWidget]) -> bool:
    name = NameDialog.ask(
        parent, "Welcome to StudyFlow",
        "Welcome! What should we call you?\n(You can add more users later, each with their own data.)",
        controller.validate_user_name, ok_text="Get started",
    )
    if name is None:
        return False
    try:
        controller.create_user(name)
    except (ValueError, StorageError) as exc:
        util.show_error(parent, str(exc))
        return False
    return True


def choose_user(controller: AppController, error: Optional[str] = None, parent: Optional[QWidget] = None) -> bool:
    """Keep asking until a user is open. False if the user closes the dialogs without picking anyone."""
    while not controller.is_open:
        if not controller.users():  # everyone was deleted
            if not _create_first_user(controller, parent):
                return False
            continue
        UserPickerDialog(controller, error=error, parent=parent).exec()
        error = None
        if not controller.is_open and controller.users():
            return False  # closed the picker without choosing anyone (if nobody is left, we ask for a new user)
    return True
