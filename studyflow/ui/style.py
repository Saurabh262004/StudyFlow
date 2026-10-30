"""Look of the app: a clean custom theme, light or dark, that follows the system or is chosen by the user.

How it works, and why (this module was rewritten after dark mode turned out to hide checkbox outlines, disabled
state, popups and scrollbars):

* The QPalette is COMPLETE, including the Disabled group. Qt's Fusion style derives outlines, bevels and arrows from
  palette roles we used to leave unset, which is what made them vanish on a dark background.
* Every control that matters is styled explicitly in the stylesheet, in EVERY state (normal, hover, focus, pressed,
  checked, disabled, selected), and always with the foreground AND the background together. Setting only one of the two
  for a state lets Qt fill in the other from the palette, which is how a hovered combo-box item became dark text on a
  dark background.
* Checkmarks, radio dots and arrows are small images drawn at start-up in the theme's colours.
* tests/test_theme.py checks contrast numerically and renders every control in both themes, including hover.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QPointF, Qt, QTemporaryDir
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPalette, QPen
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Colors:
    window: str  # background of windows and pages
    surface: str  # background of inputs, cards and tables
    sidebar: str
    text: str
    muted: str  # secondary text (still readable: >= 4.5:1 on every background it is used on)
    accent: str
    accent_text: str  # text and tick marks on top of `accent`
    border: str  # soft separators and frames
    control_border: str  # outlines of inputs and check boxes: at least 3:1 against the surface they sit on
    hover: str  # background of a hovered row, menu item or button
    disabled_text: str  # dimmer than muted, but still readable
    banner_bg: str
    banner_border: str
    banner_text: str
    danger: str


LIGHT = Colors(
    window="#f6f7f9", surface="#ffffff", sidebar="#eceef3", text="#1f2430", muted="#5c667a",
    accent="#2f60e2", accent_text="#ffffff", border="#d9dde6", control_border="#8089a0", hover="#dde3f0",
    disabled_text="#7f879b",
    banner_bg="#fff4d6", banner_border="#f0d48a", banner_text="#5a4300", danger="#c0392b",
)
DARK = Colors(
    window="#171a21", surface="#1f232d", sidebar="#1b1f28", text="#e6e8ee", muted="#9aa3b5",
    accent="#6d8cff", accent_text="#10131a", border="#2d3340", control_border="#7b849a", hover="#363f58",
    disabled_text="#6f788d",
    banner_bg="#3a3115", banner_border="#6b5a1e", banner_text="#f3e2a8", danger="#ff7b6b",
)


def system_is_dark(app: QGuiApplication) -> bool:
    return app.styleHints().colorScheme() == Qt.ColorScheme.Dark  # "Unknown" counts as light


# --------------------------------------------------------------------------- palette
def build_palette(c: Colors) -> QPalette:
    """A complete palette: every role, for the active, inactive AND disabled groups."""
    p = QPalette()
    roles = QPalette.ColorRole
    everywhere = {
        roles.Window: c.window, roles.WindowText: c.text,
        roles.Base: c.surface, roles.AlternateBase: c.sidebar,
        roles.Text: c.text, roles.PlaceholderText: c.muted,
        roles.Button: c.surface, roles.ButtonText: c.text, roles.BrightText: c.text,
        roles.Light: c.surface, roles.Midlight: c.hover, roles.Mid: c.control_border, roles.Dark: c.border,
        roles.Shadow: c.window,
        roles.Highlight: c.accent, roles.HighlightedText: c.accent_text,
        roles.Link: c.accent, roles.LinkVisited: c.muted,
        roles.ToolTipBase: c.surface, roles.ToolTipText: c.text,
    }
    if hasattr(roles, "Accent"):  # Qt 6.6+
        everywhere[roles.Accent] = c.accent
    for role, color in everywhere.items():
        p.setColor(role, QColor(color))  # sets the colour for all three groups
    disabled = QPalette.ColorGroup.Disabled
    for role, color in {
        roles.WindowText: c.disabled_text, roles.Text: c.disabled_text, roles.ButtonText: c.disabled_text,
        roles.PlaceholderText: c.disabled_text, roles.Button: c.window, roles.Base: c.window,
        roles.Highlight: c.border, roles.HighlightedText: c.disabled_text,
    }.items():
        p.setColor(disabled, role, QColor(color))
    return p


# --------------------------------------------------------------------------- icons (tick marks, arrows)
_icon_dir: Optional[QTemporaryDir] = None
_icon_serial = 0


def _polyline(painter: QPainter, points, scale: float) -> None:
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        painter.drawLine(QPointF(x1 * scale, y1 * scale), QPointF(x2 * scale, y2 * scale))


def make_icons(c: Colors) -> dict[str, str]:
    """Draw the small images the stylesheet needs (in this theme's colours) and return name -> file path.
    Every call writes new files, so switching themes at run time never shows a cached picture of the old theme."""
    global _icon_dir, _icon_serial
    if _icon_dir is None:
        _icon_dir = QTemporaryDir()  # removed again when the program ends
    if not _icon_dir.isValid():
        return {}
    _icon_serial += 1
    shapes = {
        "check": (c.accent_text, [[(3.5, 8.6), (6.6, 11.6), (12.6, 4.8)]], 2.0),
        "dash": (c.accent_text, [[(4.0, 8.0), (12.0, 8.0)]], 2.0),
        "arrow_down": (c.text, [[(4.0, 6.2), (8.0, 10.0), (12.0, 6.2)]], 1.8),
        "arrow_up": (c.text, [[(4.0, 9.8), (8.0, 6.0), (12.0, 9.8)]], 1.8),
        "arrow_down_disabled": (c.disabled_text, [[(4.0, 6.2), (8.0, 10.0), (12.0, 6.2)]], 1.8),
        "arrow_up_disabled": (c.disabled_text, [[(4.0, 9.8), (8.0, 6.0), (12.0, 9.8)]], 1.8),
        "chevron_left": (c.text, [[(10.0, 3.5), (5.5, 8.0), (10.0, 12.5)]], 1.9),
        "chevron_right": (c.text, [[(6.0, 3.5), (10.5, 8.0), (6.0, 12.5)]], 1.9),
    }
    paths: dict[str, str] = {}
    for name, (color, lines, width) in shapes.items():
        for scale, suffix in ((1, ""), (2, "@2x")):  # Qt picks the @2x file on high-DPI screens
            image = QImage(16 * scale, 16 * scale, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor(color), width * scale)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            for line in lines:
                _polyline(painter, line, scale)
            painter.end()
            path = Path(_icon_dir.path()) / f"{name}-{_icon_serial}{suffix}.png"
            image.save(str(path), "PNG")
        paths[name] = (Path(_icon_dir.path()) / f"{name}-{_icon_serial}.png").as_posix()
    # the radio button's dot is a filled circle
    for scale, suffix in ((1, ""), (2, "@2x")):
        image = QImage(16 * scale, 16 * scale, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(c.accent_text))
        painter.drawEllipse(QPointF(8 * scale, 8 * scale), 3.2 * scale, 3.2 * scale)
        painter.end()
        image.save(str(Path(_icon_dir.path()) / f"dot-{_icon_serial}{suffix}.png"), "PNG")
    paths["dot"] = (Path(_icon_dir.path()) / f"dot-{_icon_serial}.png").as_posix()
    return paths


# --------------------------------------------------------------------------- stylesheet
# Written with @token@ placeholders (see build_stylesheet) so CSS braces need no escaping and a typo raises an error.
_QSS = """
* { font-size: 10.5pt; }
QMainWindow, QDialog { background: @window@; }
QToolBar { background: @window@; border: none; border-bottom: 1px solid @border@; padding: 6px 10px; spacing: 8px; }
QStatusBar { background: @window@; color: @muted@; border-top: 1px solid @border@; }
QMenuBar { background: @window@; color: @text@; }
QMenuBar::item { padding: 4px 10px; background: transparent; border-radius: 4px; }
QMenuBar::item:selected { background: @hover@; color: @text@; }

/* ---- menus and tool tips */
QMenu { background: @surface@; color: @text@; border: 1px solid @control_border@; padding: 4px; }
QMenu::item { padding: 6px 22px; border-radius: 4px; background: transparent; color: @text@; }
QMenu::item:selected { background: @accent@; color: @accent_text@; }
QMenu::item:disabled { color: @disabled_text@; background: transparent; }
QMenu::separator { height: 1px; background: @border@; margin: 4px 8px; }
QToolTip { background: @surface@; color: @text@; border: 1px solid @control_border@; padding: 4px 6px; }

/* ---- plain list views (also the pop-up of auto-complete); more specific rules below override this */
QListView { background: @surface@; color: @text@; border: 1px solid @control_border@; outline: 0; selection-background-color: @accent@; selection-color: @accent_text@; }
QListView::item:hover { background: @hover@; color: @text@; }
QListView::item:selected { background: @accent@; color: @accent_text@; }

/* ---- sidebar */
#sidebar { background: @sidebar@; border-right: 1px solid @border@; }
#sidebarHeading { color: @muted@; font-size: 9pt; font-weight: 600; padding: 10px 14px 4px 14px; }
QListWidget { background: transparent; color: @text@; border: none; outline: 0; }
#sidebar QListWidget::item { padding: 7px 12px; margin: 1px 8px; border-radius: 6px; color: @text@; background: transparent; }
#sidebar QListWidget::item:hover:!selected { background: @hover@; color: @text@; }
#sidebar QListWidget::item:selected { background: @accent@; color: @accent_text@; }

/* ---- plain text styles */
#pageTitle { font-size: 20pt; font-weight: 600; }
#muted { color: @muted@; }
#errorText { color: @danger@; }
#sectionLabel { color: @muted@; font-size: 9pt; font-weight: 600; }
#cardTitle { font-size: 16pt; font-weight: 600; }
QLabel:disabled { color: @disabled_text@; }

/* ---- banners and cards */
#banner, #riskBanner { background: @banner_bg@; border: 1px solid @banner_border@; border-radius: 8px; }
#banner QLabel, #riskBanner QLabel { color: @banner_text@; background: transparent; }
#nextCard { background: @surface@; border: 1px solid @border@; border-radius: 12px; }

/* ---- buttons */
QPushButton, QToolButton { background: @surface@; color: @text@; border: 1px solid @control_border@; border-radius: 6px; padding: 6px 14px; }
QPushButton:hover, QToolButton:hover { border-color: @accent@; background: @hover@; color: @text@; }
QPushButton:pressed, QToolButton:pressed { background: @border@; color: @text@; }
QPushButton:disabled, QToolButton:disabled { background: @window@; color: @disabled_text@; border-color: @border@; }
QPushButton:default { background: @accent@; color: @accent_text@; border-color: @accent@; }
QPushButton:default:hover { background: @accent@; color: @accent_text@; border-color: @text@; }
QPushButton:default:disabled { background: @window@; color: @disabled_text@; border-color: @border@; }
QToolButton::menu-indicator { image: none; width: 0; }

/* ---- check boxes and radio buttons (also the check boxes inside tables) */
QCheckBox, QRadioButton { spacing: 8px; color: @text@; background: transparent; }
QCheckBox:disabled, QRadioButton:disabled { color: @disabled_text@; }
QCheckBox::indicator, QAbstractItemView::indicator { width: 16px; height: 16px; border: 1px solid @control_border@; border-radius: 4px; background: @surface@; }
QCheckBox::indicator:hover, QAbstractItemView::indicator:hover { border-color: @accent@; }
QCheckBox::indicator:checked, QAbstractItemView::indicator:checked { background: @accent@; border-color: @accent@; image: url("@icon_check@"); }
QCheckBox::indicator:indeterminate { background: @accent@; border-color: @accent@; image: url("@icon_dash@"); }
QCheckBox::indicator:disabled { background: @window@; border-color: @border@; }
QCheckBox::indicator:checked:disabled, QCheckBox::indicator:indeterminate:disabled { background: @control_border@; border-color: @control_border@; }
QRadioButton::indicator { width: 16px; height: 16px; border: 1px solid @control_border@; border-radius: 9px; background: @surface@; }
QRadioButton::indicator:hover { border-color: @accent@; }
QRadioButton::indicator:checked { background: @accent@; border-color: @accent@; image: url("@icon_dot@"); }
QRadioButton::indicator:disabled { background: @window@; border-color: @border@; }
QRadioButton::indicator:checked:disabled { background: @control_border@; border-color: @control_border@; }

/* ---- text inputs */
QLineEdit, QPlainTextEdit, QTextEdit { background: @surface@; color: @text@; border: 1px solid @control_border@; border-radius: 6px; padding: 7px 10px;
                                       selection-background-color: @accent@; selection-color: @accent_text@; placeholder-text-color: @muted@; }
QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover { border-color: @muted@; }
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus { border-color: @accent@; }
QLineEdit:disabled, QPlainTextEdit:disabled, QTextEdit:disabled { background: @window@; color: @disabled_text@; border-color: @border@; }

/* ---- spin boxes and date/time editors */
QAbstractSpinBox { background: @surface@; color: @text@; border: 1px solid @control_border@; border-radius: 6px; padding: 6px 28px 6px 10px; min-height: 20px;
                   selection-background-color: @accent@; selection-color: @accent_text@; }
QAbstractSpinBox:hover { border-color: @muted@; }
QAbstractSpinBox:focus { border-color: @accent@; }
QAbstractSpinBox:disabled { background: @window@; color: @disabled_text@; border-color: @border@; }
QAbstractSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 24px; border: none; border-left: 1px solid @border@;
                              border-top-right-radius: 5px; background: transparent; margin-top: 1px; margin-right: 1px; }
QAbstractSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 24px; border: none; border-left: 1px solid @border@;
                                border-bottom-right-radius: 5px; background: transparent; margin-bottom: 1px; margin-right: 1px; }
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover { background: @hover@; }
QAbstractSpinBox::up-arrow { image: url("@icon_arrow_up@"); width: 10px; height: 10px; }
QAbstractSpinBox::down-arrow { image: url("@icon_arrow_down@"); width: 10px; height: 10px; }
QAbstractSpinBox::up-arrow:disabled, QAbstractSpinBox::up-arrow:off { image: url("@icon_arrow_up_disabled@"); }
QAbstractSpinBox::down-arrow:disabled, QAbstractSpinBox::down-arrow:off { image: url("@icon_arrow_down_disabled@"); }
QDateTimeEdit::drop-down { subcontrol-origin: border; subcontrol-position: center right; width: 26px; border: none; border-left: 1px solid @border@;
                           border-top-right-radius: 5px; border-bottom-right-radius: 5px; background: transparent; margin: 1px; }
QDateTimeEdit::drop-down:hover { background: @hover@; }
QDateTimeEdit::down-arrow { image: url("@icon_arrow_down@"); width: 10px; height: 10px; }
QDateTimeEdit::down-arrow:disabled { image: url("@icon_arrow_down_disabled@"); }

/* ---- combo boxes and their pop-up list */
QComboBox { background: @surface@; color: @text@; border: 1px solid @control_border@; border-radius: 6px; padding: 6px 28px 6px 10px; min-height: 20px; }
QComboBox:hover { border-color: @muted@; }
QComboBox:focus, QComboBox:on { border-color: @accent@; }
QComboBox:disabled { background: @window@; color: @disabled_text@; border-color: @border@; }
QComboBox::drop-down { subcontrol-origin: border; subcontrol-position: center right; width: 26px; border: none; border-left: 1px solid @border@;
                       border-top-right-radius: 5px; border-bottom-right-radius: 5px; background: transparent; margin: 1px; }
QComboBox::drop-down:hover { background: @hover@; }
QComboBox::down-arrow { image: url("@icon_arrow_down@"); width: 10px; height: 10px; }
QComboBox::down-arrow:disabled { image: url("@icon_arrow_down_disabled@"); }
QComboBox QAbstractItemView { background: @surface@; color: @text@; border: 1px solid @control_border@; outline: 0; padding: 4px;
                              selection-background-color: @accent@; selection-color: @accent_text@; }
QComboBox QAbstractItemView::item { padding: 6px 10px; min-height: 22px; border-radius: 4px; background: transparent; color: @text@; }
QComboBox QAbstractItemView::item:hover { background: @hover@; color: @text@; }
QComboBox QAbstractItemView::item:selected { background: @accent@; color: @accent_text@; }

/* ---- lists, tables */
QDialog QListWidget { background: @surface@; color: @text@; border: 1px solid @control_border@; border-radius: 8px; }
QDialog QListWidget::item { padding: 9px 12px; background: transparent; color: @text@; }
QDialog QListWidget::item:hover:!selected { background: @hover@; color: @text@; }
QDialog QListWidget::item:selected { background: @accent@; color: @accent_text@; }
QTableView { background: @surface@; color: @text@; border: 1px solid @border@; border-radius: 8px; gridline-color: transparent; outline: 0;
             selection-background-color: @accent@; selection-color: @accent_text@; }
QTableView::item { padding: 4px 8px; }
QHeaderView::section { background: @surface@; color: @muted@; border: none; border-bottom: 1px solid @border@; padding: 6px 8px; font-weight: 600; }

/* ---- tree (the "pick a subject or study point" dialog) */
QTreeView { background: @surface@; color: @text@; border: 1px solid @control_border@; border-radius: 8px; outline: 0; selection-background-color: @accent@; selection-color: @accent_text@; }
QTreeView::item { padding: 6px 4px; background: transparent; color: @text@; }
QTreeView::item:hover { background: @hover@; color: @text@; }
QTreeView::item:selected { background: @accent@; color: @accent_text@; }
QTreeView::item:disabled { background: transparent; color: @disabled_text@; }

/* ---- pictures: thumbnails and the strip that accepts dropped files */
QListView#imageView { background: transparent; color: @text@; border: none; outline: 0; }
QListView#imageView::item { padding: 6px; border-radius: 8px; background: transparent; color: @text@; }
QListView#imageView::item:hover { background: @hover@; color: @text@; }
QListView#imageView::item:selected { background: @accent@; color: @accent_text@; }
QFrame#imageStrip { border: 2px dashed transparent; border-radius: 10px; background: transparent; }
QFrame#imageStrip[dropActive="true"] { border: 2px dashed @accent@; background: @hover@; }

/* ---- group boxes, tabs, splitters */
QGroupBox { background: @surface@; color: @text@; border: 1px solid @border@; border-radius: 8px; margin-top: 10px; padding: 8px 0 0 0; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: @muted@; font-weight: 600; }
QGroupBox:disabled::title { color: @disabled_text@; }
QSplitter::handle { background: transparent; }
QSplitter::handle:hover { background: @border@; border-radius: 3px; }
QTabWidget::pane { border: none; border-top: 1px solid @border@; }
QTabBar::tab { background: transparent; color: @muted@; padding: 9px 18px; margin-right: 4px; border: none; border-bottom: 2px solid transparent; font-weight: 600; }
QTabBar::tab:selected { color: @text@; border-bottom: 2px solid @accent@; }
QTabBar::tab:hover:!selected { color: @text@; background: @hover@; }

/* ---- scroll bars */
QScrollBar:vertical { background: transparent; width: 14px; margin: 0; }
QScrollBar:horizontal { background: transparent; height: 14px; margin: 0; }
QScrollBar::handle:vertical { background: @control_border@; border-radius: 4px; min-height: 30px; margin: 2px 3px; }
QScrollBar::handle:horizontal { background: @control_border@; border-radius: 4px; min-width: 30px; margin: 3px 2px; }
QScrollBar::handle:hover { background: @muted@; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; border: none; background: none; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
QAbstractScrollArea::corner { background: transparent; }

/* ---- the calendar that pops up from a date field */
QCalendarWidget { background: @surface@; }
QCalendarWidget #qt_calendar_navigationbar { background: @surface@; border: none; border-bottom: 1px solid @border@; padding: 2px; }
QCalendarWidget QToolButton { color: @text@; background: transparent; border: none; border-radius: 4px; padding: 4px 8px; icon-size: 16px; }
QCalendarWidget QToolButton:hover { background: @hover@; color: @text@; }
QCalendarWidget QToolButton::menu-indicator { image: none; width: 0; }
QCalendarWidget QToolButton#qt_calendar_prevmonth { qproperty-icon: url("@icon_chevron_left@"); }
QCalendarWidget QToolButton#qt_calendar_nextmonth { qproperty-icon: url("@icon_chevron_right@"); }
QCalendarWidget QAbstractItemView:enabled { background: @surface@; color: @text@; selection-background-color: @accent@; selection-color: @accent_text@; outline: 0; }
QCalendarWidget QAbstractItemView:disabled { color: @muted@; }
"""


def build_stylesheet(c: Colors, icons: Optional[dict[str, str]] = None) -> str:
    """The stylesheet for a theme. `icons` (name -> file path from make_icons) is drawn on demand when not given."""
    if icons is None:
        icons = make_icons(c)
    values = {name: getattr(c, name) for name in c.__dataclass_fields__}
    values.update({f"icon_{name}": path for name, path in icons.items()})

    def substitute(match: re.Match) -> str:
        token = match.group(1)
        if token not in values:
            if token.startswith("icon_"):  # no image files could be written: the rule just gets an empty url
                return ""
            raise KeyError(f"unknown style token @{token}@")
        return values[token]

    return re.sub(r"@(\w+)@", substitute, _QSS)


# (text colour, background colour) of the status pills, one table per theme
_STATUS_LIGHT = {
    "overdue": ("#b42318", "#fde7e4"), "start_now": ("#b54708", "#feebd3"), "soon": ("#946200", "#fff3c4"),
    "on_track": ("#1c7c43", "#dcf5e5"), "no_deadline": ("#5b6475", "#e8ebf1"), "done": ("#5b6475", "#e8ebf1"),
}
_STATUS_DARK = {
    "overdue": ("#ffb4a9", "#4a1f1a"), "start_now": ("#ffcf99", "#4a3010"), "soon": ("#f6dd8a", "#463a10"),
    "on_track": ("#9be3b3", "#12361f"), "no_deadline": ("#aab3c5", "#2a3040"), "done": ("#aab3c5", "#2a3040"),
}


def status_colors(status) -> tuple[str, str]:
    """(text colour, background colour) for a priority status (a Status member or its value) in the current theme."""
    key = getattr(status, "value", status)
    table = _STATUS_DARK if _current is DARK else _STATUS_LIGHT
    return table.get(key, table["no_deadline"])


# --------------------------------------------------------------------------- two small fixes Qt's stylesheets cannot do
def pad_spin_box(spin) -> None:
    """A stylesheet's left padding is ignored by the text field inside a spin box (a Qt quirk), so give the text
    a left margin directly. Call this on every QSpinBox / QDoubleSpinBox."""
    spin.lineEdit().setTextMargins(8, 0, 0, 0)


def plain_calendar(date_edit) -> None:
    """Make a date field's pop-up calendar show weekends like other days. Qt paints them pure red, which is too
    dim on a dark background; this also keeps the calendar correct when the theme changes."""
    from PySide6.QtGui import QTextCharFormat

    calendar = date_edit.calendarWidget()
    if calendar is not None:
        for day in (Qt.DayOfWeek.Saturday, Qt.DayOfWeek.Sunday):
            calendar.setWeekdayTextFormat(day, QTextCharFormat())


THEME_MODES = ("system", "light", "dark")
_mode = "system"
_current = LIGHT


def current() -> Colors:
    """The colours of the theme that is applied right now (for code that paints or colours things itself)."""
    return _current


def apply_theme(app: QApplication, mode: str = "system") -> None:
    """Apply a theme. mode: "system" (follow the OS light/dark setting), "light" or "dark".
    The settings screen will call this with the user's choice."""
    global _mode, _current
    if mode not in THEME_MODES:
        raise ValueError(f"theme mode must be one of {THEME_MODES}")
    _mode = mode
    dark = system_is_dark(app) if mode == "system" else mode == "dark"
    _current = DARK if dark else LIGHT
    app.setStyle("Fusion")
    app.setPalette(build_palette(_current))
    app.setStyleSheet(build_stylesheet(_current))


def install(app: QApplication, mode: str = "system") -> None:
    apply_theme(app, mode)
    # while the mode is "system" the app follows the OS when it switches between light and dark
    app.styleHints().colorSchemeChanged.connect(lambda _scheme: apply_theme(app, _mode) if _mode == "system" else None)
