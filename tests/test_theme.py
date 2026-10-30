"""The theme must stay legible. These tests exist because dark mode once hid checkbox outlines, disabled states and
hovered list items: they check the colours numerically, lint the stylesheet, and render real controls in both
themes (including hover and pop-ups) to look at the pixels."""
import re
import sys
from collections import Counter
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QPoint, QRect, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPalette  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractButton,
    QStyle,
    QStyledItemDelegate,
    QAbstractSpinBox,
    QComboBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QWidget,
)

from studyflow.ui import style  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from theme_gallery import Gallery  # noqa: E402

THEMES = {"light": style.LIGHT, "dark": style.DARK}


# ================================================================== helpers
def luminance(rgb) -> float:
    c = QColor(rgb) if not isinstance(rgb, QColor) else rgb
    parts = []
    for v in (c.redF(), c.greenF(), c.blueF()):
        parts.append(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
    return 0.2126 * parts[0] + 0.7152 * parts[1] + 0.0722 * parts[2]


def contrast(a, b) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def colours(image: QImage) -> Counter:
    return Counter(image.pixel(x, y) for x in range(image.width()) for y in range(image.height()))


def legibility(image: QImage) -> float:
    """Contrast between the dominant (background) colour of a picture and the colour furthest from it (the text)."""
    counts = colours(image)
    background = counts.most_common(1)[0][0]
    ink = max(counts, key=lambda px: abs(luminance(px) - luminance(background)))
    return contrast(ink, background)


def crop_of(widget: QWidget, root: QWidget, picture: QImage, rect: QRect = None) -> QImage:
    top_left = widget.mapTo(root, QPoint(0, 0))
    area = rect if rect is not None else widget.rect()
    return picture.copy(QRect(top_left + area.topLeft(), area.size()))


def rgb(name: str) -> int:
    return QColor(name).rgb()


def has_near(counts, wanted: int, tolerance: int = 20) -> bool:
    """Is there a pixel within `tolerance` (per channel) of the colour? Thin, rounded shapes are antialiased, so
    their exact colour may never appear."""
    r, g, b = QColor(wanted).red(), QColor(wanted).green(), QColor(wanted).blue()
    return any(abs(QColor(px).red() - r) <= tolerance and abs(QColor(px).green() - g) <= tolerance and abs(QColor(px).blue() - b) <= tolerance
               for px in counts)


def ink_contrast(image: QImage) -> float:
    return legibility(image)


@pytest.fixture(params=["light", "dark"])
def theme(request, qapp):
    style.apply_theme(qapp, request.param)
    yield THEMES[request.param]
    style.apply_theme(qapp, "light")


@pytest.fixture
def gallery(qapp, theme):
    g = Gallery()
    g.show()
    qapp.processEvents()
    return g, g.grab().toImage(), theme


# ================================================================== the colours themselves
@pytest.mark.parametrize("name", ["light", "dark"])
def test_text_colours_are_readable_on_every_background_they_are_used_on(name):
    c = THEMES[name]
    for text in (c.text, c.muted):
        for background in (c.window, c.surface, c.sidebar):
            assert contrast(text, background) >= 4.5, (name, text, background)
    assert contrast(c.text, c.hover) >= 4.5
    assert contrast(c.accent_text, c.accent) >= 4.5
    assert contrast(c.danger, c.surface) >= 4.5 and contrast(c.danger, c.window) >= 4.5
    assert contrast(c.banner_text, c.banner_bg) >= 4.5


@pytest.mark.parametrize("name", ["light", "dark"])
def test_outlines_and_dimmed_text_meet_the_non_text_minimum(name):
    c = THEMES[name]
    for background in (c.surface, c.window):
        assert contrast(c.control_border, background) >= 3, "check box / input outlines"
        assert contrast(c.disabled_text, background) >= 3, "disabled text must stay readable"
    for background in (c.surface, c.window, c.sidebar):
        assert contrast(c.accent, background) >= 3, "focus / checked colour"
    assert contrast(c.hover, c.surface) >= 1.2, "hover has to be noticeable"
    assert luminance(c.disabled_text) != luminance(c.text) and contrast(c.disabled_text, c.surface) < contrast(c.muted, c.surface)


@pytest.mark.parametrize("name", ["light", "dark"])
def test_status_pills_are_readable(name, qapp):
    style._current = THEMES[name]
    try:
        for status in ("overdue", "start_now", "soon", "on_track", "no_deadline", "done"):
            fg, bg = style.status_colors(status)
            assert contrast(fg, bg) >= 4.5, (name, status)
    finally:
        style.apply_theme(qapp, "light")


# ================================================================== the palette
@pytest.mark.parametrize("name", ["light", "dark"])
def test_the_palette_is_complete_and_readable_in_every_group(name):
    c, palette = THEMES[name], style.build_palette(THEMES[name])
    roles, groups = QPalette.ColorRole, QPalette.ColorGroup
    pairs = [(roles.WindowText, roles.Window), (roles.Text, roles.Base), (roles.ButtonText, roles.Button),
             (roles.HighlightedText, roles.Highlight), (roles.ToolTipText, roles.ToolTipBase), (roles.PlaceholderText, roles.Base)]
    for group in (groups.Active, groups.Inactive):
        for fg, bg in pairs:
            assert contrast(palette.color(group, fg), palette.color(group, bg)) >= 4.5, (name, group, fg, bg)
    for fg, bg in [(roles.WindowText, roles.Window), (roles.Text, roles.Base), (roles.ButtonText, roles.Button)]:
        assert contrast(palette.color(groups.Disabled, fg), palette.color(groups.Disabled, bg)) >= 3, (name, "disabled", fg)
    # disabled must look different from enabled
    assert palette.color(groups.Disabled, roles.Text) != palette.color(groups.Active, roles.Text)
    assert palette.color(roles.Mid) == QColor(c.control_border) and palette.color(roles.Highlight) == QColor(c.accent)


# ================================================================== the stylesheet
def test_the_stylesheet_has_no_unresolved_tokens_and_every_image_exists(qapp):
    for c in THEMES.values():
        sheet = style.build_stylesheet(c)
        assert "@" not in sheet
        images = re.findall(r'url\("([^"]+)"\)', sheet)
        assert len(images) >= 10
        for path in images:
            file = Path(path)
            assert file.exists() and file.stat().st_size > 0, path
            assert file.with_name(file.stem + "@2x.png").exists(), f"{path}: no @2x version for high-DPI screens"


def test_each_theme_draws_its_own_icons(qapp):
    """Tick marks and arrows are pictures; their colours must come from the theme (accent_text / text)."""
    for c in THEMES.values():
        icons = style.make_icons(c)
        assert rgb(c.accent_text) in colours(QImage(icons["check"])) and rgb(c.text) in colours(QImage(icons["arrow_down"]))
        assert rgb(c.disabled_text) in colours(QImage(icons["arrow_down_disabled"]))
    assert style.make_icons(style.DARK)["check"] != style.make_icons(style.DARK)["check"]  # fresh files each time: no stale cache


def test_stylesheet_lint_hover_selected_and_pressed_states_set_text_and_background_together(qapp):
    """The bug that made a hovered list item dark-on-dark: a state that sets only one of the two lets Qt fill in the
    other from the palette. Every item / menu / button state must set both."""
    sheet = style.build_stylesheet(style.DARK)
    rules = re.findall(r"([^{}/]+)\{([^{}]*)\}", sheet)
    checked = 0
    for selector, body in rules:
        selector = selector.strip()
        wants_both = any(state in selector for state in (":hover", ":selected", ":pressed", ":default"))
        is_widget_state = "::item" in selector or "QPushButton" in selector or "QToolButton" in selector or "QMenu::item" in selector
        if wants_both and is_widget_state and "::indicator" not in selector and "::drop-down" not in selector and "::up-button" not in selector:
            props = {p.split(":")[0].strip() for p in body.split(";") if ":" in p}
            assert "background" in props and "color" in props, f"state rule sets only one of text/background: {selector}"
            checked += 1
    assert checked >= 10


# ================================================================== rendered controls
TEXT_WIDGETS = ["label_normal", "label_muted", "label_error", "label_section", "button", "button_default", "tool_button",
                "line", "line_placeholder", "notes", "spin", "datetime", "combo", "check_off", "check_on", "check_partial",
                "radio_off", "radio_on", "group", "banner", "risk", "card_title"]
DISABLED_WIDGETS = ["button_disabled", "line_disabled", "spin_disabled", "combo_disabled", "check_off_disabled",
                    "check_on_disabled", "group_disabled"]


def test_every_control_in_the_gallery_is_legible(gallery):
    g, picture, _ = gallery
    for name in TEXT_WIDGETS:
        widget = getattr(g, name)
        ratio = legibility(crop_of(widget, g, picture))
        assert ratio >= 4.5, f"{name}: text/background contrast {ratio:.2f}"
    for name in DISABLED_WIDGETS:
        widget = getattr(g, name)
        ratio = legibility(crop_of(widget, g, picture))
        assert ratio >= 3, f"{name} (disabled): contrast {ratio:.2f}"


def test_disabled_controls_look_disabled(gallery):
    g, picture, theme = gallery
    for enabled, disabled in [("line", "line_disabled"), ("spin", "spin_disabled"), ("combo", "combo_disabled"), ("button", "button_disabled")]:
        crop_e, crop_d = crop_of(getattr(g, enabled), g, picture), crop_of(getattr(g, disabled), g, picture)
        assert contrast(max(colours(crop_e), key=lambda p: abs(luminance(p) - luminance(colours(crop_e).most_common(1)[0][0]))),
                        colours(crop_e).most_common(1)[0][0]) > legibility(crop_d), f"{disabled} is not dimmer than {enabled}"
    assert rgb(theme.disabled_text) in colours(crop_of(g.line_disabled, g, picture))


def check_box_indicator(g, picture, widget) -> QImage:
    return crop_of(widget, g, picture, QRect(0, 0, 22, widget.height()))


def test_check_box_outlines_ticks_and_dashes_are_visible(gallery):
    g, picture, theme = gallery
    off = colours(check_box_indicator(g, picture, g.check_off))
    assert rgb(theme.control_border) in off, "the unchecked box needs its outline"
    assert contrast(theme.control_border, theme.window) >= 3
    on = colours(check_box_indicator(g, picture, g.check_on))
    assert rgb(theme.accent) in on and rgb(theme.accent_text) in on, "checked: accent fill and a tick in the contrasting colour"
    partly = colours(check_box_indicator(g, picture, g.check_partial))
    assert rgb(theme.accent) in partly and rgb(theme.accent_text) in partly
    off_disabled = colours(check_box_indicator(g, picture, g.check_off_disabled))
    assert rgb(theme.border) in off_disabled and rgb(theme.control_border) not in off_disabled, "a disabled box looks different"
    on_disabled = colours(check_box_indicator(g, picture, g.check_on_disabled))
    assert rgb(theme.accent) not in on_disabled and rgb(theme.control_border) in on_disabled


def test_radio_buttons(gallery):
    g, picture, theme = gallery
    assert has_near(colours(check_box_indicator(g, picture, g.radio_off)), rgb(theme.control_border)), "the ring of an unselected radio"
    on = colours(check_box_indicator(g, picture, g.radio_on))
    assert rgb(theme.accent) in on and has_near(on, rgb(theme.accent_text)), "a selected radio has a filled disc and a dot"


def arrow_area(widget, g, picture) -> QImage:
    """The drop-down / spin button area without the outer outline (so only the arrow can be 'ink' in it)."""
    return crop_of(widget, g, picture, QRect(widget.width() - 20, 5, 14, widget.height() - 10))


def test_spin_box_and_combo_arrows_are_drawn(gallery):
    g, picture, theme = gallery
    for widget in (g.spin, g.datetime, g.combo):
        assert ink_contrast(arrow_area(widget, g, picture)) >= 3, f"{widget.__class__.__name__}: the arrow is missing or too faint"
    for enabled, disabled in ((g.spin, g.spin_disabled), (g.combo, g.combo_disabled)):
        assert ink_contrast(arrow_area(disabled, g, picture)) >= 2, "a disabled arrow is still visible"
        assert ink_contrast(arrow_area(disabled, g, picture)) < ink_contrast(arrow_area(enabled, g, picture)), "... but dimmer"


def test_inputs_have_a_visible_outline(gallery):
    g, picture, theme = gallery
    for widget in (g.line, g.notes, g.spin, g.combo, g.datetime, g.button):
        assert rgb(theme.control_border) in colours(crop_of(widget, g, picture)), widget.__class__.__name__


def test_spin_box_text_has_a_left_margin(gallery):
    g, *_ = gallery
    assert g.spin.lineEdit().textMargins().left() >= 6


def test_scroll_bars_are_not_black_blocks(gallery):
    g, picture, theme = gallery
    bar = g.list.verticalScrollBar()
    crop = crop_of(bar, g, picture)
    seen = colours(crop)
    assert rgb("#000000") not in seen, "a scroll bar part is painted black"
    assert rgb(theme.control_border) in seen, "the scroll bar handle is visible"


def test_list_selection_is_legible(gallery):
    g, picture, theme = gallery
    row = g.list.visualItemRect(g.list.item(1))
    crop = crop_of(g.list.viewport(), g, picture, row)
    assert legibility(crop) >= 4.5 and colours(crop).most_common(1)[0][0] == rgb(theme.accent)
    assert contrast(theme.accent_text, theme.accent) >= 4.5


# ================================================================== pop-ups and hover (the reported bug)
class StateProbe(QStyledItemDelegate):
    """Paints list items with an exact set of state flags (hover, selected ...) through the REAL view and
    stylesheet. A real mouse hover in a combo box pop-up selects the item instead of hovering it, so the states
    have to be forced to be tested all the time."""

    flags = QStyle.StateFlag.State_Enabled

    def paint(self, painter, option, index):
        option.state = StateProbe.flags | QStyle.StateFlag.State_Active
        super().paint(painter, option, index)


STATES = {
    "normal": (QStyle.StateFlag.State_Enabled, "surface"),
    "hover": (QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_MouseOver, "hover"),
    "selected": (QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_Selected, "accent"),
    "selected and hovered": (QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver, "accent"),
}


@pytest.mark.parametrize("state", list(STATES))
@pytest.mark.parametrize("which", ["combo popup", "user list"])
def test_list_items_are_legible_in_every_state(gallery, qapp, which, state):
    """Reported: a hovered item in the 'All subjects' drop-down had black text on a black background. Whatever the
    state, an item needs readable text on the colour that state is supposed to have."""
    g, _, theme = gallery
    if which == "combo popup":
        g.combo.showPopup()
        qapp.processEvents()
        view = g.combo.view()
    else:
        view = g.list
    probe = StateProbe(view)
    view.setItemDelegate(probe)
    flags, background = STATES[state]
    StateProbe.flags = flags
    view.viewport().update()
    qapp.processEvents()
    rect = view.visualRect(view.model().index(2, 0))
    picture = view.viewport().grab().toImage()
    crop = picture.copy(rect.intersected(picture.rect()))
    assert colours(crop).most_common(1)[0][0] == rgb(getattr(theme, background)), f"{which}, {state}: wrong background"
    assert legibility(crop) >= 4.5, f"{which}, {state}: text is not readable ({legibility(crop):.2f})"
    if which == "combo popup":
        g.combo.hidePopup()


def test_a_real_mouse_hover_over_the_combo_popup_keeps_everything_readable(gallery, qapp):
    g, _, _ = gallery
    g.combo.showPopup()
    qapp.processEvents()
    view = g.combo.view()
    for row in range(view.model().rowCount()):
        rect = view.visualRect(view.model().index(row, 0))
        QTest.mouseMove(view.viewport(), rect.center())
        qapp.processEvents()
        QTest.qWait(20)
        picture = view.viewport().grab().toImage()
        for other in range(view.model().rowCount()):
            r = view.visualRect(view.model().index(other, 0))
            assert legibility(picture.copy(r.intersected(picture.rect()))) >= 4.5, f"hovering row {row}, row {other} unreadable"
    g.combo.hidePopup()


def test_combo_popup_shows_the_current_item_clearly(gallery, qapp):
    g, _, theme = gallery
    g.combo.setCurrentIndex(1)
    g.combo.showPopup()
    qapp.processEvents()
    view = g.combo.view()
    picture = view.viewport().grab().toImage()
    rect = view.visualRect(view.model().index(1, 0))
    assert legibility(picture.copy(rect.intersected(picture.rect()))) >= 4.5
    g.combo.hidePopup()


def test_menu_items_selected_normal_and_disabled(gallery, qapp):
    g, _, theme = gallery
    g.menu.popup(g.mapToGlobal(QPoint(20, 300)))
    qapp.processEvents()
    g.menu.setActiveAction(g.menu.actions()[1])
    qapp.processEvents()
    picture = g.menu.grab().toImage()
    rects = [g.menu.actionGeometry(a) for a in g.menu.actions()]
    normal, active, disabled = picture.copy(rects[0]), picture.copy(rects[1]), picture.copy(rects[2])
    assert legibility(normal) >= 4.5
    assert legibility(active) >= 4.5 and colours(active).most_common(1)[0][0] == rgb(theme.accent)
    assert 3 <= legibility(disabled) < legibility(normal), "a disabled item is dimmer but still readable"
    g.menu.hide()


def test_calendar_popup(gallery, qapp):
    g, _, theme = gallery
    calendar = g.datetime.calendarWidget()
    calendar.setParent(None)
    calendar.show()
    qapp.processEvents()
    picture = calendar.grab().toImage()
    assert legibility(picture) >= 4.5
    navigation = calendar.findChild(QWidget, "qt_calendar_navigationbar")
    assert legibility(crop_of(navigation, calendar, picture)) >= 4.5, "month / year header"
    for day in (Qt.DayOfWeek.Saturday, Qt.DayOfWeek.Sunday):
        assert calendar.weekdayTextFormat(day).foreground().style() == Qt.BrushStyle.NoBrush, "weekends are not painted pure red"
    # the selected day is an accent square with readable text
    assert rgb(theme.accent) in colours(picture)
    calendar.hide()


# ================================================================== the real screens
INTERESTING = (QLabel, QAbstractButton, QLineEdit, QAbstractSpinBox, QComboBox, QPlainTextEdit)


def audit(root: QWidget, qapp, minimum=4.5, minimum_disabled=3.0) -> list[str]:
    """Render `root` and check the legibility of every visible control that shows text."""
    qapp.processEvents()
    picture = root.grab().toImage()
    problems = []
    for widget in root.findChildren(QWidget):
        if not isinstance(widget, INTERESTING) or not widget.isVisibleTo(root) or widget.width() < 12 or widget.height() < 10:
            continue
        if isinstance(widget, QLabel) and not widget.text().strip():
            continue
        if isinstance(widget, QAbstractSpinBox) and widget.objectName() == "qt_spinbox_lineedit":
            continue
        top_left = widget.mapTo(root, QPoint(0, 0))
        area = QRect(top_left, widget.size()).intersected(picture.rect())
        if area.width() < 12 or area.height() < 10:
            continue
        ratio = legibility(picture.copy(area))
        needed = minimum if widget.isEnabled() else minimum_disabled
        if ratio < needed:
            problems.append(f"{widget.__class__.__name__} {widget.objectName() or widget.property('text') or ''!r}: {ratio:.2f} < {needed}")
    return problems


def test_audit_of_the_gallery(gallery, qapp):
    g, *_ = gallery
    assert audit(g, qapp) == []


@pytest.fixture
def app_with_data(qapp, theme, tmp_path):
    from datetime import datetime, timedelta, timezone

    from studyflow.ui.controller import AppController

    now = datetime.now(timezone.utc)
    c = AppController(tmp_path / "root")
    c.create_user("Saurabh")
    os_, db = c.add_subject("Operating Systems", notes="Unit 3 and 4 are important."), c.add_subject("DBMS")
    c.add_point(os_.id, "Deadlocks", notes="Coffman conditions", deadline=now + timedelta(days=3), effort_hours=2.5)
    late = c.add_point(os_.id, "Process scheduling", deadline=now - timedelta(hours=5), effort_hours=1)
    c.add_point(db.id, "Normalisation", deadline=now + timedelta(hours=20), effort_hours=3)
    done = c.add_point(os_.id, "Introduction", effort_hours=1)
    c.set_point_done(os_.id, done.id, True)
    c.add_point(db.id, "ER diagrams")
    c.warnings = ["Your data file was damaged. A copy was kept."]
    from studyflow.ui import image_import
    from tests.pictures_support import make_picture

    folder = tmp_path / "photos"
    folder.mkdir()
    pictures = [make_picture(folder / f"IMG_{i}.jpg", 640, 480 - 60 * i, color) for i, color in enumerate(["#aa3333", "#33aa33", "#3333aa"])]
    image_import.import_pictures(c, None, pictures[:2], os_.id, late.id, tags=["blackboard", "unit 3"])
    image_import.import_pictures(c, None, pictures[2:], os_.id, None, tags=["slides"])
    return c, os_, late


def test_audit_of_the_main_window_pages(app_with_data, qapp):
    from studyflow.ui.main_window import MainWindow

    c, os_, late = app_with_data
    w = MainWindow(c)
    w.resize(1120, 760)
    w.show()
    c.warningsChanged.emit()
    qapp.processEvents()
    assert audit(w, qapp) == [], "dashboard"
    w.open_point(os_.id, late.id)
    qapp.processEvents()
    assert audit(w, qapp) == [], "subject page with the point editor open"
    w.subject_page.tabs.setCurrentIndex(1)
    qapp.processEvents()
    assert audit(w, qapp) == [], "subject notes tab"
    w.subject_page.tabs.setCurrentIndex(2)
    qapp.processEvents()
    assert audit(w, qapp) == [], "subject Pictures tab"
    w.subject_page.tabs.setCurrentIndex(0)
    w.subject_page.editor.tabs.setCurrentIndex(1)
    qapp.processEvents()
    assert audit(w, qapp) == [], "point editor Pictures tab"
    w.nav.setCurrentRow(1)
    qapp.processEvents()
    assert audit(w, qapp) == [], "images page"
    w.close()


def test_audit_of_the_point_editor_when_nothing_is_selected(app_with_data, qapp):
    from studyflow.ui.main_window import MainWindow

    c, os_, _ = app_with_data
    w = MainWindow(c)
    w.resize(1120, 760)
    w.show()
    w.subject_list.setCurrentRow(1)  # Operating Systems; no point selected, so the editor is disabled
    qapp.processEvents()
    assert not w.subject_page.editor.isEnabled()
    assert audit(w, qapp) == []
    w.close()


def test_audit_of_the_dialogs(app_with_data, qapp):
    from studyflow.ui.dialogs.name_dialog import NameDialog
    from studyflow.ui.dialogs.user_picker import UserPickerDialog

    c, *_ = app_with_data
    picker = UserPickerDialog(c, error="Could not open Amit's data: it was saved by a newer version.")
    picker.show()
    qapp.processEvents()
    assert audit(picker, qapp) == []
    name = NameDialog("New user", "Name of the new user:", c.validate_user_name, ok_text="Create")
    name.edit.setText("saurabh")  # duplicate: error text, OK disabled
    name.show()
    qapp.processEvents()
    assert name.error.text() and not name.ok_button.isEnabled()
    assert audit(name, qapp) == []


def test_table_check_boxes_have_outlines(app_with_data, qapp, theme):
    """Reported: the check boxes in the study-point table had no visible outline in dark mode."""
    from studyflow.ui.pages.subject_page import SubjectPage

    c, os_, _ = app_with_data
    page = SubjectPage(c)
    page.resize(900, 600)
    page.show()
    page.show_subject(os_.id)
    page.table.clearSelection()
    qapp.processEvents()
    picture = page.table.viewport().grab().toImage()
    column = picture.copy(QRect(0, 0, 44, picture.height()))
    seen = colours(column)
    assert rgb(theme.control_border) in seen, "unchecked boxes need an outline"
    assert rgb(theme.accent) in seen and rgb(theme.accent_text) in seen, "the checked box (done point) has a fill and a tick"


def test_point_editor_check_boxes_have_outlines(app_with_data, qapp, theme):
    from studyflow.ui.widgets.point_editor import PointEditor

    c, os_, late = app_with_data
    editor = PointEditor()
    editor.load(c.get_point(os_.id, late.id))
    editor.resize(700, 220)
    editor.show()
    qapp.processEvents()
    picture = editor.grab().toImage()
    for box in (editor.has_deadline, editor.has_effort, editor.done):
        indicator = crop_of(box, editor, picture, QRect(0, 0, 22, box.height()))
        assert rgb(theme.control_border) in colours(indicator) or rgb(theme.accent) in colours(indicator), box.text()
    assert audit(editor, qapp) == []


def test_every_theme_applies_without_errors_when_switching_repeatedly(qapp):
    for mode in ("dark", "light", "dark", "system", "light"):
        style.apply_theme(qapp, mode)
        w = Gallery()
        w.show()
        qapp.processEvents()
        assert not w.grab().isNull()
        w.close()


# ================================================================== picture screens
@pytest.mark.parametrize("state", list(STATES))
def test_picture_captions_are_legible_in_every_state(app_with_data, qapp, theme, state):
    from studyflow.ui.pages.gallery_page import GalleryPage

    c, *_ = app_with_data
    page = GalleryPage(c)
    page.resize(900, 520)
    page.show()
    view = page.view
    view.setItemDelegate(StateProbe(view))
    flags, background = STATES[state]
    StateProbe.flags = flags
    view.viewport().update()
    qapp.processEvents()
    rect = view.visualRect(view.model().index(0))
    top_left = view.viewport().mapTo(page, rect.topLeft())
    picture = page.grab().toImage()
    caption = picture.copy(QRect(top_left.x() + 4, top_left.y() + rect.height() - 24, rect.width() - 8, 20))
    assert legibility(caption) >= 4.5, f"{state}: caption not readable ({legibility(caption):.2f})"
    expected = {"surface": theme.window}.get(background, getattr(theme, background))  # a normal item shows the page behind it
    assert colours(caption).most_common(1)[0][0] == rgb(expected), f"{state}: wrong background"


@pytest.mark.parametrize("state", list(STATES))
def test_tree_picker_rows_are_legible_in_every_state(app_with_data, qapp, theme, state):
    from studyflow.ui.dialogs.target_picker import TargetPickerDialog

    c, os_, late = app_with_data
    dialog = TargetPickerDialog(c, "Also show in", "Show it in:", {(os_.id, late.id)})
    dialog.show()
    tree = dialog.tree
    tree.setItemDelegate(StateProbe(tree))
    flags, background = STATES[state]
    StateProbe.flags = flags
    tree.viewport().update()
    qapp.processEvents()
    item = tree.topLevelItem(0)
    rect = tree.visualItemRect(item)
    picture = tree.viewport().grab().toImage()
    row = picture.copy(rect.intersected(picture.rect()))
    assert legibility(row) >= 4.5, f"{state}: row not readable"
    assert colours(row).most_common(1)[0][0] == rgb(getattr(theme, background)), f"{state}: wrong background"


def test_taken_places_in_the_tree_picker_are_dimmed_but_readable(app_with_data, qapp, theme):
    from studyflow.ui.dialogs.target_picker import TargetPickerDialog

    c, os_, late = app_with_data
    dialog = TargetPickerDialog(c, "Also show in", "Show it in:", {(os_.id, late.id)})
    dialog.resize(420, 420)
    dialog.show()
    qapp.processEvents()
    top = [dialog.tree.topLevelItem(i) for i in range(dialog.tree.topLevelItemCount())]
    taken = next(child for item in top for child in (item.child(i) for i in range(item.childCount())) if "already here" in child.text(0))
    normal = next(child for item in top for child in (item.child(i) for i in range(item.childCount())) if "already here" not in child.text(0))
    picture = dialog.tree.viewport().grab().toImage()
    taken_row = picture.copy(dialog.tree.visualItemRect(taken).intersected(picture.rect()))
    normal_row = picture.copy(dialog.tree.visualItemRect(normal).intersected(picture.rect()))
    assert 3 <= legibility(taken_row) < legibility(normal_row)


def test_audit_of_the_picture_dialogs(app_with_data, qapp):
    from studyflow.ui.dialogs.image_picker import ImagePickerDialog
    from studyflow.ui.dialogs.image_viewer import ImageViewerDialog
    from studyflow.ui.dialogs.tags_dialog import TagsDialog
    from studyflow.ui.dialogs.target_picker import TargetPickerDialog

    c, os_, late = app_with_data
    ids = [i.id for i in c.all_images()]
    dialogs = {
        "tags": TagsDialog("Add pictures", "Tags for these 3 pictures (optional):", ["blackboard", "slides"], ok_text="Add"),
        "target": TargetPickerDialog(c, "Also show in", "Show it in:", {(os_.id, late.id)}, ok_text="Show there"),
        "picker": ImagePickerDialog(c, exclude_ids=set(ids[:1])),
        "viewer": ImageViewerDialog(c, ids, 1, os_.id, late.id),
    }
    for name, dialog in dialogs.items():
        dialog.resize(900, 600)
        dialog.show()
        qapp.processEvents()
        assert audit(dialog, qapp) == [], name
        dialog.close()
