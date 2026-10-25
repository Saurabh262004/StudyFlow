"""A gallery of every kind of control StudyFlow uses, for checking a theme by eye.

    python tools/theme_gallery.py                    # opens the gallery (follows the system theme)
    python tools/theme_gallery.py --theme dark       # or light / system
    python tools/theme_gallery.py --save out.png     # render to a picture instead of opening a window

The same builder is used by the tests (tests/test_theme.py), which render it in both themes and check that
text, outlines, hover states and popups are legible."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QDateTime, Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
)

from studyflow.ui import style  # noqa: E402


class Gallery(QDialog):
    """Every control in every state that matters. Attributes are public so tests can point at them.
    (A dialog, because lists inside dialogs get their own styling, as in the real user picker.)"""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("StudyFlow theme gallery")

        # ---- text
        self.label_normal = QLabel("Normal text")
        self.label_muted = QLabel("Muted text")
        self.label_muted.setObjectName("muted")
        self.label_error = QLabel("Error text")
        self.label_error.setObjectName("errorText")
        self.label_section = QLabel("SECTION LABEL")
        self.label_section.setObjectName("sectionLabel")

        # ---- buttons
        self.button = QPushButton("Button")
        self.button_default = QPushButton("Default")
        self.button_default.setDefault(True)
        self.button_disabled = QPushButton("Disabled")
        self.button_disabled.setEnabled(False)
        self.tool_button = QToolButton()
        self.tool_button.setText("Tool button  \u25be")
        self.tool_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.menu = QMenu(self.tool_button)
        self.menu.addAction("Menu item")
        self.menu.addAction("Another item")
        disabled_action = self.menu.addAction("Disabled item")
        disabled_action.setEnabled(False)
        self.menu.addSeparator()
        self.menu.addAction("Last item")
        self.tool_button.setMenu(self.menu)

        # ---- check boxes and radio buttons
        self.check_off = QCheckBox("Unchecked")
        self.check_on = QCheckBox("Checked")
        self.check_on.setChecked(True)
        self.check_partial = QCheckBox("Partly checked")
        self.check_partial.setTristate(True)
        self.check_partial.setCheckState(Qt.CheckState.PartiallyChecked)
        self.check_off_disabled = QCheckBox("Disabled")
        self.check_off_disabled.setEnabled(False)
        self.check_on_disabled = QCheckBox("Disabled, checked")
        self.check_on_disabled.setChecked(True)
        self.check_on_disabled.setEnabled(False)
        self.radio_off = QRadioButton("Radio off")
        self.radio_on = QRadioButton("Radio on")
        self.radio_on.setChecked(True)

        # ---- text input
        self.line = QLineEdit("Some typed text")
        self.line_placeholder = QLineEdit()
        self.line_placeholder.setPlaceholderText("Placeholder text")
        self.line_disabled = QLineEdit("Disabled input")
        self.line_disabled.setEnabled(False)
        self.notes = QPlainTextEdit("Plain text notes\nsecond line")
        self.notes.setFixedHeight(60)
        self.spin = QDoubleSpinBox()
        self.spin.setSuffix(" h/day")
        self.spin.setValue(2.5)
        style.pad_spin_box(self.spin)
        self.spin_disabled = QDoubleSpinBox()
        self.spin_disabled.setValue(1.0)
        style.pad_spin_box(self.spin_disabled)
        self.spin_disabled.setEnabled(False)
        self.datetime = QDateTimeEdit(QDateTime(2026, 10, 25, 18, 0, 0))
        self.datetime.setCalendarPopup(True)
        self.datetime.setDisplayFormat("dd MMM yyyy  HH:mm")
        style.plain_calendar(self.datetime)
        self.combo = QComboBox()
        self.combo.addItems(["All subjects", "DBMS", "Maths", "Operating Systems"])
        self.combo_disabled = QComboBox()
        self.combo_disabled.addItems(["Disabled combo"])
        self.combo_disabled.setEnabled(False)

        # ---- lists, tabs, group box
        self.list = QListWidget()
        self.list.setObjectName("galleryList")
        self.list.addItems(["Amit", "Guest", "Saurabh   (current)", "Another user", "Fifth user", "Sixth user", "Seventh user"])
        self.list.setCurrentRow(1)
        self.list.setFixedHeight(110)
        self.tabs = QTabWidget()
        self.tabs.addTab(QLabel("First tab content"), "Study points")
        self.tabs.addTab(QLabel("Second tab content"), "Notes \u2022")
        self.group = QGroupBox("Study point")
        group_layout = QVBoxLayout(self.group)
        group_layout.addWidget(QLabel("Label inside a group box"))
        self.group_disabled = QGroupBox("Disabled group")
        group_layout2 = QVBoxLayout(self.group_disabled)
        group_layout2.addWidget(QLabel("Label inside a disabled group box"))
        group_layout2.addWidget(QCheckBox("Check box in it"))
        self.group_disabled.setEnabled(False)

        # ---- banners
        self.banner = QFrame()
        self.banner.setObjectName("banner")
        QHBoxLayout(self.banner).addWidget(QLabel("A warning banner message"))
        self.risk = QFrame()
        self.risk.setObjectName("riskBanner")
        QHBoxLayout(self.risk).addWidget(QLabel("A risk banner message"))
        self.card = QFrame()
        self.card.setObjectName("nextCard")
        card_layout = QVBoxLayout(self.card)
        self.card_title = QLabel("Card title")
        self.card_title.setObjectName("cardTitle")
        card_layout.addWidget(self.card_title)

        grid = QGridLayout(self)
        grid.setSpacing(10)
        column1, column2, column3 = QVBoxLayout(), QVBoxLayout(), QVBoxLayout()
        for w in (self.label_normal, self.label_muted, self.label_error, self.label_section, self.button, self.button_default,
                  self.button_disabled, self.tool_button, self.check_off, self.check_on, self.check_partial,
                  self.check_off_disabled, self.check_on_disabled, self.radio_off, self.radio_on):
            column1.addWidget(w)
        column1.addStretch(1)
        for w in (self.line, self.line_placeholder, self.line_disabled, self.notes, self.spin, self.spin_disabled,
                  self.datetime, self.combo, self.combo_disabled, self.list):
            column2.addWidget(w)
        column2.addStretch(1)
        for w in (self.tabs, self.group, self.group_disabled, self.banner, self.risk, self.card):
            column3.addWidget(w)
        column3.addStretch(1)
        grid.addLayout(column1, 0, 0)
        grid.addLayout(column2, 0, 1)
        grid.addLayout(column3, 0, 2)
        self.resize(1000, 640)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--theme", choices=style.THEME_MODES, default="system")
    parser.add_argument("--save", metavar="PNG", help="render to this picture and exit")
    args = parser.parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    style.install(app, args.theme)
    gallery = Gallery()
    gallery.show()
    if args.save:
        app.processEvents()
        gallery.grab().save(args.save)
        return 0
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
