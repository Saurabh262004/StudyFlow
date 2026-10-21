"""Look of the app: a clean custom style that follows the system's light or dark setting."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Colors:
    window: str
    surface: str
    sidebar: str
    text: str
    muted: str
    accent: str
    accent_text: str
    border: str
    banner_bg: str
    banner_border: str
    banner_text: str
    danger: str


LIGHT = Colors(
    window="#f6f7f9", surface="#ffffff", sidebar="#eceef3", text="#1f2430", muted="#667085",
    accent="#3b6df0", accent_text="#ffffff", border="#d9dde6",
    banner_bg="#fff4d6", banner_border="#f0d48a", banner_text="#5a4300", danger="#c0392b",
)
DARK = Colors(
    window="#171a21", surface="#1f232d", sidebar="#1b1f28", text="#e6e8ee", muted="#9aa3b5",
    accent="#6d8cff", accent_text="#10131a", border="#2d3340",
    banner_bg="#3a3115", banner_border="#6b5a1e", banner_text="#f3e2a8", danger="#ff7b6b",
)


def system_is_dark(app: QGuiApplication) -> bool:
    return app.styleHints().colorScheme() == Qt.ColorScheme.Dark  # "Unknown" counts as light


def build_palette(c: Colors) -> QPalette:
    p = QPalette()
    for role, color in [
        (QPalette.ColorRole.Window, c.window), (QPalette.ColorRole.WindowText, c.text),
        (QPalette.ColorRole.Base, c.surface), (QPalette.ColorRole.AlternateBase, c.sidebar),
        (QPalette.ColorRole.Text, c.text), (QPalette.ColorRole.Button, c.surface),
        (QPalette.ColorRole.ButtonText, c.text), (QPalette.ColorRole.Highlight, c.accent),
        (QPalette.ColorRole.HighlightedText, c.accent_text), (QPalette.ColorRole.PlaceholderText, c.muted),
        (QPalette.ColorRole.ToolTipBase, c.surface), (QPalette.ColorRole.ToolTipText, c.text),
        (QPalette.ColorRole.Link, c.accent),
    ]:
        p.setColor(role, QColor(color))
    return p


def build_stylesheet(c: Colors) -> str:
    return f"""
    QWidget {{ font-size: 10.5pt; }}
    QMainWindow, QDialog {{ background: {c.window}; }}
    QToolBar {{ background: {c.window}; border: none; border-bottom: 1px solid {c.border}; padding: 6px 10px; spacing: 8px; }}
    QStatusBar {{ background: {c.window}; color: {c.muted}; border-top: 1px solid {c.border}; }}
    QMenuBar {{ background: {c.window}; }}
    QMenu {{ background: {c.surface}; border: 1px solid {c.border}; padding: 4px; }}
    QMenu::item {{ padding: 6px 22px; border-radius: 4px; }}
    QMenu::item:selected {{ background: {c.accent}; color: {c.accent_text}; }}

    #sidebar {{ background: {c.sidebar}; border-right: 1px solid {c.border}; }}
    #sidebarHeading {{ color: {c.muted}; font-size: 9pt; font-weight: 600; padding: 10px 14px 4px 14px; }}
    QListWidget {{ background: transparent; border: none; outline: 0; }}
    #sidebar QListWidget::item {{ padding: 7px 12px; margin: 1px 8px; border-radius: 6px; }}
    #sidebar QListWidget::item:selected {{ background: {c.accent}; color: {c.accent_text}; }}
    #sidebar QListWidget::item:hover:!selected {{ background: {c.border}; }}

    #pageTitle {{ font-size: 20pt; font-weight: 600; }}
    #muted {{ color: {c.muted}; }}
    #errorText {{ color: {c.danger}; }}

    #banner {{ background: {c.banner_bg}; border: 1px solid {c.banner_border}; border-radius: 8px; }}
    #banner QLabel {{ color: {c.banner_text}; }}

    QPushButton, QToolButton {{ background: {c.surface}; border: 1px solid {c.border}; border-radius: 6px; padding: 6px 14px; }}
    QPushButton:hover, QToolButton:hover {{ border-color: {c.accent}; }}
    QPushButton:disabled {{ color: {c.muted}; }}
    QPushButton:default {{ background: {c.accent}; color: {c.accent_text}; border-color: {c.accent}; }}
    QPushButton:default:disabled {{ background: {c.border}; color: {c.muted}; border-color: {c.border}; }}
    QToolButton::menu-indicator {{ image: none; width: 0; }}

    QLineEdit {{ background: {c.surface}; border: 1px solid {c.border}; border-radius: 6px; padding: 7px 10px; }}
    QLineEdit:focus {{ border-color: {c.accent}; }}
    QDialog QListWidget {{ background: {c.surface}; border: 1px solid {c.border}; border-radius: 8px; }}
    QDialog QListWidget::item {{ padding: 9px 12px; }}
    QDialog QListWidget::item:selected {{ background: {c.accent}; color: {c.accent_text}; }}

    #sectionLabel {{ color: {c.muted}; font-size: 9pt; font-weight: 600; }}
    QTableView {{ background: {c.surface}; border: 1px solid {c.border}; border-radius: 8px; gridline-color: transparent; outline: 0;
                  selection-background-color: {c.accent}; selection-color: {c.accent_text}; }}
    QTableView::item {{ padding: 4px 8px; }}
    QHeaderView::section {{ background: {c.surface}; color: {c.muted}; border: none; border-bottom: 1px solid {c.border};
                            padding: 6px 8px; font-weight: 600; }}
    QGroupBox {{ background: {c.surface}; border: 1px solid {c.border}; border-radius: 8px; margin-top: 10px; padding: 8px 0 0 0; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; color: {c.muted}; font-weight: 600; }}
    QPlainTextEdit, QDateTimeEdit, QDoubleSpinBox {{ background: {c.surface}; border: 1px solid {c.border}; border-radius: 6px; padding: 5px 8px; }}
    QPlainTextEdit:focus, QDateTimeEdit:focus, QDoubleSpinBox:focus {{ border-color: {c.accent}; }}
    QCheckBox {{ spacing: 8px; }}
    QSplitter::handle {{ background: transparent; }}
    """


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
