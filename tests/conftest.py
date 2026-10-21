import gc
import os
import sys
import traceback

import pytest

# Qt must not need a screen when the tests run (set before any Qt object exists)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole test run (a QApplication is also a QCoreApplication)."""
    widgets = pytest.importorskip("PySide6.QtWidgets")
    app = widgets.QApplication.instance() or widgets.QApplication([])
    yield app
    _delete_all_widgets(app)


def _delete_all_widgets(app) -> None:
    """Destroy every window while the QApplication still exists. Widgets that are only freed at interpreter
    exit (after Qt itself is gone) crash the process on shutdown."""
    from PySide6.QtCore import QCoreApplication, QEvent

    for w in app.topLevelWidgets():
        w.close()
        w.deleteLater()
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()


@pytest.fixture(autouse=True)
def _fail_on_exceptions_in_qt_slots():
    """PySide6 only PRINTS an exception raised inside a slot and carries on, so a test would still pass.
    Collect them instead and fail the test."""
    caught = []
    previous = sys.excepthook
    sys.excepthook = lambda kind, value, tb: caught.append("".join(traceback.format_exception(kind, value, tb)))
    yield
    sys.excepthook = previous
    if caught:
        pytest.fail(f"{len(caught)} exception(s) were raised inside Qt slots:\n\n" + "\n".join(caught[:2]), pytrace=False)


@pytest.fixture(autouse=True)
def _tidy_qt_after_each_test(_fail_on_exceptions_in_qt_slots):
    yield
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:  # the data-layer tests run fine without PySide6
        return
    app = QApplication.instance()
    if app is not None:
        _delete_all_widgets(app)
