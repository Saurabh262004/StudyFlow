"""Entry point:  python -m studyflow  [--data-dir FOLDER]

The data folder can also be set with the STUDYFLOW_HOME environment variable. It is handy for trying the
app out without touching your real data."""
from __future__ import annotations

import argparse
import os
import sys
from typing import Optional, Sequence

from PySide6.QtWidgets import QApplication

from . import style
from .controller import AppController
from .main_window import MainWindow
from .startup import run_startup


def parse_args(argv: Sequence[str]):
    """Our own options; everything else is passed on to Qt. Returns (args, qt_args)."""
    parser = argparse.ArgumentParser(prog="studyflow", description="StudyFlow: subject-wise study organiser.")
    parser.add_argument("--data-dir", default=os.environ.get("STUDYFLOW_HOME"), help="where all users' data is kept")
    return parser.parse_known_args(list(argv))


def main(argv: Optional[Sequence[str]] = None) -> int:
    args, qt_args = parse_args(sys.argv[1:] if argv is None else argv)

    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName("StudyFlow")
    style.install(app)

    controller = AppController(args.data_dir)
    if not run_startup(controller):
        return 0
    window = MainWindow(controller)
    window.show()
    controller.start_clock()
    return app.exec()
