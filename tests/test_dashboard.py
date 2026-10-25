from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from studyflow import PlanSettings, Status, StorageError, UserManager  # noqa: E402
from studyflow.ui import style, util  # noqa: E402
from studyflow.ui.controller import AppController  # noqa: E402
from studyflow.ui.main_window import PAGE_DASHBOARD, PAGE_SUBJECT, MainWindow  # noqa: E402
from studyflow.ui.pages.dashboard_page import DashboardPage  # noqa: E402
from studyflow.ui.widgets import ranking_table as rt  # noqa: E402
from studyflow.ui.widgets.ranking_table import (  # noqa: E402
    COL_EFFORT,
    COL_LEFT,
    COL_RANK,
    COL_START,
    COL_STATUS,
    COL_TITLE,
    STATUS_ROLE,
    SUBJECT_ROLE,
    RankingModel,
)

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)
D, H = timedelta(days=1), timedelta(hours=1)
DISPLAY = Qt.ItemDataRole.DisplayRole


@pytest.fixture
def clock():
    return {"now": NOW}


@pytest.fixture
def ctrl(qapp, tmp_path, clock):
    c = AppController(tmp_path / "root", now=lambda: clock["now"])
    c.create_user("Saurabh")
    return c


@pytest.fixture
def world(ctrl):
    """Seven points whose ranking at NOW (2 study hours a day) is known:
    1 overdue, 2 start now, 3 soon, 4 soon, 5 on track, 6 no deadline  (+ a finished one that is never listed)."""
    os_, dbms, maths = ctrl.add_subject("Operating Systems"), ctrl.add_subject("DBMS"), ctrl.add_subject("Maths")
    pts = {
        "sched": ctrl.add_point(os_.id, "Process scheduling", deadline=NOW - 5 * H, effort_hours=1),
        "norm": ctrl.add_point(dbms.id, "Normalisation", deadline=NOW + 20 * H, effort_hours=3),
        "prob": ctrl.add_point(maths.id, "Probability", deadline=NOW + 2 * D),  # no estimate: default 1 h
        "dead": ctrl.add_point(os_.id, "Deadlocks", deadline=NOW + 3 * D + 4 * H, effort_hours=2.5),
        "alg": ctrl.add_point(maths.id, "Linear algebra", deadline=NOW + 9 * D, effort_hours=6),
        "er": ctrl.add_point(dbms.id, "ER diagrams"),
    }
    done = ctrl.add_point(os_.id, "Introduction", effort_hours=1)
    ctrl.set_point_done(os_.id, done.id, True)
    return {"os": os_, "dbms": dbms, "maths": maths, **pts}


@pytest.fixture
def page(qapp, ctrl, world):
    return DashboardPage(ctrl)


def titles(page):
    return [page.model.data(page.model.index(r, COL_TITLE)) for r in range(page.model.rowCount())]


def cell(model, row, col, role=DISPLAY):
    return model.data(model.index(row, col), role)


def spy(signal):
    count = {"n": 0}
    signal.connect(lambda: count.__setitem__("n", count["n"] + 1))
    return count


# ================================================================== small helpers
def test_status_colours_cover_every_status_in_both_themes(qapp):
    for theme in (style.LIGHT, style.DARK):
        style._current = theme
        pairs = {s.value: style.status_colors(s) for s in Status}
        assert len(pairs) == 6 and all(len(set(p)) == 2 for p in pairs.values())  # text and background differ
        assert len({pairs[k] for k in ("overdue", "start_now", "soon", "on_track")}) == 4  # the four urgent ones are distinct
        assert style.status_colors(Status.OVERDUE) == style.status_colors("overdue")
        assert style.status_colors("nonsense") == style.status_colors("no_deadline")
    assert style._STATUS_LIGHT["overdue"] != style._STATUS_DARK["overdue"]
    style.apply_theme(qapp, "light")


def test_text_helpers(qapp, ctrl, world):
    rows = {r.point.title: r for r in ctrl.ranking(include_done=True)}
    assert rt.status_label(Status.START_NOW) == "Start now" and rt.status_label(Status.NO_DEADLINE) == "No deadline"
    assert rt.start_by_text(rows["Process scheduling"]) == "now" and rt.start_by_text(rows["Normalisation"]) == "now"
    assert rt.start_by_text(rows["ER diagrams"]) == "\u2014"
    assert rt.start_by_text(rows["Linear algebra"]) == rows["Linear algebra"].start_by.astimezone().strftime("%d %b, %H:%M")
    assert rt.effort_text(rows["Probability"]) == "1 h" and rt.effort_text(rows["Probability"], mark_default=True) == "1 h (default)"
    assert rt.effort_text(rows["Deadlocks"], mark_default=True) == "2.5 h"
    assert rt.time_left_text(rows["Normalisation"]).endswith("at risk")
    assert rt.time_left_text(rows["Process scheduling"]) == "overdue by 5h 0m"  # overdue is already red: no "at risk" noise
    assert rt.time_left_text(rows["Linear algebra"]) == "9d 0h left" and rt.time_left_text(rows["ER diagrams"]) == "\u2014"


# ================================================================== the model
def test_model_rows_columns_and_roles(qapp, ctrl, world):
    m = RankingModel()
    m.set_rows(ctrl.ranking())
    assert m.rowCount() == 6 and m.columnCount() == 6
    assert [cell(m, r, COL_TITLE) for r in range(6)] == [
        "Process scheduling", "Normalisation", "Probability", "Deadlocks", "Linear algebra", "ER diagrams"]
    assert [cell(m, r, COL_RANK) for r in range(6)] == ["1", "2", "3", "4", "5", "6"]
    assert [cell(m, r, COL_STATUS, STATUS_ROLE) for r in range(6)] == ["overdue", "start_now", "soon", "soon", "on_track", "no_deadline"]
    assert [cell(m, r, COL_STATUS) for r in range(6)] == ["Overdue", "Start now", "Soon", "Soon", "On track", "No deadline"]
    assert cell(m, 1, COL_TITLE, SUBJECT_ROLE) == "DBMS" and cell(m, 3, COL_TITLE, SUBJECT_ROLE) == "Operating Systems"
    assert cell(m, 0, COL_LEFT) == "overdue by 5h 0m" and cell(m, 1, COL_LEFT) == "20h 0m left  \u00b7  at risk"
    assert cell(m, 4, COL_LEFT) == "9d 0h left"
    assert [cell(m, r, COL_EFFORT) for r in range(6)] == ["1 h", "3 h", "1 h", "2.5 h", "6 h", "1 h"]
    assert cell(m, 0, COL_START) == "now" and cell(m, 5, COL_START) == "\u2014"
    assert m.row_of(world["dbms"].id, world["norm"].id) == 1 and m.row_of("x", "y") == -1
    assert m.row_at(2).point.id == world["prob"].id
    assert m.data(m.index(99, 0)) is None


def test_model_marks_default_efforts_and_risk(qapp, ctrl, world):
    m = RankingModel()
    m.set_rows(ctrl.ranking())
    assert cell(m, 2, COL_EFFORT, Qt.ItemDataRole.FontRole).italic()  # Probability has no estimate
    assert cell(m, 3, COL_EFFORT, Qt.ItemDataRole.FontRole) is None
    assert "default" in cell(m, 2, COL_EFFORT, Qt.ItemDataRole.ToolTipRole)
    danger = style.current().danger
    assert cell(m, 0, COL_LEFT, Qt.ItemDataRole.ForegroundRole).color().name() == danger  # overdue
    assert cell(m, 1, COL_LEFT, Qt.ItemDataRole.ForegroundRole).color().name() == danger  # at risk
    assert cell(m, 4, COL_LEFT, Qt.ItemDataRole.ForegroundRole) is None  # on track
    assert "study hours" in cell(m, 1, COL_LEFT, Qt.ItemDataRole.ToolTipRole)
    assert cell(m, 3, COL_TITLE, Qt.ItemDataRole.ToolTipRole) == "Deadlocks\nOperating Systems"


def test_model_is_read_only(qapp, ctrl, world):
    m = RankingModel()
    m.set_rows(ctrl.ranking())
    assert not m.flags(m.index(0, 0)) & Qt.ItemFlag.ItemIsEditable
    m.set_rows([])
    assert m.rowCount() == 0


# ================================================================== the page
def test_empty_state(qapp, ctrl):
    page = DashboardPage(ctrl)
    assert page.summary.text() == "0 subject(s), 0 unfinished study point(s)"
    assert not page.empty_hint.isHidden() and page.table.isHidden() and page.risk_banner.isHidden()
    assert page.card_title.text() == "Nothing to study right now" and page.open_button.isHidden() and page.card_pill.isHidden()
    ctrl.add_subject("Only a subject")  # a subject without points is still "nothing to study"
    assert not page.empty_hint.isHidden() and "1 subject(s)" in page.summary.text()


def test_page_shows_the_plan(qapp, page, world):
    assert page.summary.text() == "3 subject(s), 6 unfinished study point(s)"
    assert titles(page) == ["Process scheduling", "Normalisation", "Probability", "Deadlocks", "Linear algebra", "ER diagrams"]
    assert page.empty_hint.isHidden() and not page.table.isHidden()
    assert page.card_title.text() == "Process scheduling" and page.card_subject.text() == "Operating Systems"
    assert page.card_pill.text() == "Overdue"
    assert page.card_details.text() == "overdue by 5h 0m   \u00b7   1 h effort   \u00b7   start by now"
    assert not page.open_button.isHidden()
    assert page.hours.value() == 2.0


def test_the_card_is_never_pushed_aside_by_the_filter(qapp, page, world):
    page.filter.setCurrentIndex(page.filter.findText("Maths"))
    assert titles(page) == ["Probability", "Linear algebra"]
    assert page.card_title.text() == "Process scheduling"  # "study next" is about everything you have to do


def test_the_card_marks_an_assumed_effort(qapp, ctrl, world, page):
    ctrl.set_point_done(world["os"].id, world["sched"].id, True)
    ctrl.set_point_done(world["dbms"].id, world["norm"].id, True)
    assert page.card_title.text() == "Probability" and "1 h (default) effort" in page.card_details.text()


def test_card_follows_the_data(qapp, ctrl, world, page):
    ctrl.set_point_done(world["os"].id, world["sched"].id, True)
    assert page.card_title.text() == "Normalisation" and page.card_pill.text() == "Start now"
    assert page.summary.text() == "3 subject(s), 5 unfinished study point(s)" and page.model.rowCount() == 5
    ctrl.update_point(world["dbms"].id, world["norm"].id, done=True)
    ctrl.update_point(world["maths"].id, world["prob"].id, done=True)
    ctrl.update_point(world["os"].id, world["dead"].id, done=True)
    ctrl.update_point(world["maths"].id, world["alg"].id, done=True)
    assert page.card_title.text() == "ER diagrams" and page.card_pill.text() == "No deadline"
    ctrl.update_point(world["dbms"].id, world["er"].id, done=True)
    assert page.card_title.text() == "Nothing to study right now" and not page.empty_hint.isHidden()


# ---------------------------------------------------------------- warning banner
def test_risk_banner(qapp, ctrl, world, page):
    assert not page.risk_banner.isHidden()
    assert page.risk_label.text().startswith("3 deadline(s) cannot be met with 2 study hour(s) per day")  # not the overdue one
    ctrl.set_settings(PlanSettings(hours_per_day=24))
    assert page.risk_banner.isHidden()
    ctrl.set_settings(PlanSettings(hours_per_day=1))
    assert "with 1 study hour(s)" in page.risk_label.text() and "4 deadline(s)" in page.risk_label.text()


def test_an_overdue_point_alone_is_not_a_warning(qapp, ctrl):
    s = ctrl.add_subject("S")
    ctrl.add_point(s.id, "Late", deadline=NOW - H, effort_hours=1)
    page = DashboardPage(ctrl)
    assert page.risk_banner.isHidden() and page.model.rowCount() == 1


# ---------------------------------------------------------------- study hours per day
def test_changing_study_hours_replans_and_is_saved(qapp, ctrl, world, page, tmp_path):
    changed = spy(ctrl.settingsChanged)
    assert page.card_pill.text() == "Overdue"
    assert cell(page.model, 1, COL_STATUS) == "Start now"
    page.hours.setValue(24)
    assert changed["n"] == 1 and ctrl.settings.hours_per_day == 24
    assert cell(page.model, 1, COL_STATUS) != "Start now"  # with 24 study hours a day Normalisation is no longer late to start
    again = AppController(tmp_path / "root", now=lambda: NOW)
    again.start()
    assert again.settings.hours_per_day == 24  # persisted for this user


def test_outside_settings_changes_update_the_box_without_saving_again(qapp, ctrl, world, page, monkeypatch):
    calls = []
    real = ctrl.set_settings
    monkeypatch.setattr(ctrl, "set_settings", lambda s: (calls.append(s), real(s))[1])
    real(PlanSettings(hours_per_day=5))
    assert page.hours.value() == 5 and calls == []


def test_a_failed_settings_save_is_reported_and_the_box_reverts(qapp, ctrl, world, page, monkeypatch):
    shown = []
    monkeypatch.setattr(util, "show_error", lambda parent, message: shown.append(message))
    monkeypatch.setattr(ctrl.store, "save_settings", lambda s: (_ for _ in ()).throw(StorageError("disk full")))
    page.hours.setValue(9)
    assert shown == ["disk full"] and page.hours.value() == 2.0 and ctrl.settings.hours_per_day == 2.0


def test_each_user_has_their_own_study_hours(qapp, ctrl, world, page):
    ctrl.set_settings(PlanSettings(hours_per_day=6))
    ctrl.create_user("Amit")
    assert page.hours.value() == 2.0 and page.model.rowCount() == 0 and not page.empty_hint.isHidden()
    ctrl.open_user(next(u for u in ctrl.users() if u.name == "Saurabh").id)
    assert page.hours.value() == 6.0 and page.model.rowCount() == 6


# ---------------------------------------------------------------- subject filter
def test_filter_lists_subjects_and_limits_the_list(qapp, page, world):
    assert [page.filter.itemText(i) for i in range(page.filter.count())] == ["All subjects", "DBMS", "Maths", "Operating Systems"]
    page.filter.setCurrentIndex(page.filter.findText("DBMS"))
    assert titles(page) == ["Normalisation", "ER diagrams"]
    assert [cell(page.model, r, COL_RANK) for r in range(2)] == ["1", "2"]  # numbered within the filtered list
    page.filter.setCurrentIndex(0)
    assert page.model.rowCount() == 6


def test_filter_survives_changes_and_resets_when_its_subject_goes(qapp, ctrl, world, page):
    page.filter.setCurrentIndex(page.filter.findText("DBMS"))
    ctrl.rename_subject(world["dbms"].id, "Databases")
    assert page.filter.currentText() == "Databases" and titles(page) == ["Normalisation", "ER diagrams"]
    ctrl.add_point(world["dbms"].id, "Joins", deadline=NOW + 30 * D, effort_hours=1)
    assert page.filter.currentText() == "Databases" and "Joins" in titles(page) and "Deadlocks" not in titles(page)
    ctrl.delete_subject(world["dbms"].id)
    assert page.filter.currentText() == "All subjects" and page.model.rowCount() == 4


# ---------------------------------------------------------------- opening a point
def test_activating_a_row_asks_to_open_that_point(qapp, page, world):
    got = []
    page.openPointRequested.connect(lambda s, p: got.append((s, p)))
    page.table.rowActivated.emit(1)
    page.table.rowActivated.emit(99)  # ignored
    assert got == [(world["dbms"].id, world["norm"].id)]


def test_double_click_and_enter_open_the_point(qapp, page, world):
    got = []
    page.openPointRequested.connect(lambda s, p: got.append((s, p)))
    page.resize(1000, 700)
    page.show()
    qapp.processEvents()
    pos = page.table.visualRect(page.model.index(2, COL_TITLE)).center()
    # a real double-click is press, release, double-click; Qt's item view needs that first press to recognise it
    QTest.mouseClick(page.table.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    QTest.mouseDClick(page.table.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    assert got == [(world["maths"].id, world["prob"].id)]  # exactly once
    page.table.setCurrentIndex(page.model.index(3, COL_TITLE))
    QTest.keyClick(page.table, Qt.Key.Key_Return)
    assert got[-1] == (world["os"].id, world["dead"].id) and len(got) == 2


def test_the_open_button_opens_the_study_next_point(qapp, page, world):
    got = []
    page.openPointRequested.connect(lambda s, p: got.append((s, p)))
    page.open_button.click()
    assert got == [(world["os"].id, world["sched"].id)]


# ---------------------------------------------------------------- staying current
def test_the_clock_tick_updates_times_and_keeps_the_selection(qapp, ctrl, world, page, clock):
    page.table.selectRow(3)
    before = cell(page.model, 3, COL_LEFT)
    clock["now"] = NOW + D
    ctrl.tick.emit()
    selected = page.table.selectionModel().selectedRows()
    assert [i.row() for i in selected] == [3] and cell(page.model, 3, COL_TITLE) == "Deadlocks"
    assert cell(page.model, 3, COL_LEFT) != before and cell(page.model, 3, COL_LEFT).startswith("2d 4h left")


def test_time_passing_changes_the_order_and_statuses(qapp, ctrl, world, page, clock):
    clock["now"] = NOW + 3 * D  # Normalisation, Probability are now overdue
    ctrl.tick.emit()
    assert [cell(page.model, r, COL_STATUS) for r in range(2)] == ["Overdue", "Overdue"]
    assert set(titles(page)[:3]) == {"Normalisation", "Probability", "Process scheduling"}


def test_selection_follows_the_point_when_the_ranking_reorders(qapp, ctrl, world, page):
    page.table.selectRow(4)  # Linear algebra
    ctrl.update_point(world["maths"].id, world["alg"].id, deadline=NOW + 1 * D, effort_hours=1.5)  # now far more urgent
    row = [i.row() for i in page.table.selectionModel().selectedRows()]
    assert row and cell(page.model, row[0], COL_TITLE) == "Linear algebra" and row[0] < 4


# ================================================================== painting
def painted_colours(widget):
    image = widget.grab().toImage()
    return {image.pixel(x, y) for x in range(0, image.width(), 2) for y in range(0, image.height(), 2)}


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_status_pills_are_painted_in_their_colours(qapp, ctrl, world, mode):
    style.apply_theme(qapp, mode)
    page = DashboardPage(ctrl)
    page.resize(1000, 700)
    page.show()
    page.table.clearSelection()
    qapp.processEvents()
    seen = painted_colours(page.table.viewport())
    for status in ("overdue", "start_now", "soon", "on_track", "no_deadline"):
        background = QColor(style.status_colors(status)[1]).rgb()
        assert background in seen, f"{status} pill missing in {mode}"
    style.apply_theme(qapp, "light")


# ================================================================== inside the main window
def test_the_dashboard_is_the_first_page(qapp, ctrl, world):
    w = MainWindow(ctrl)
    assert w.pages.currentIndex() == PAGE_DASHBOARD and w.pages.currentWidget() is w.dashboard_page
    assert w.dashboard_page.summary.text() == "3 subject(s), 6 unfinished study point(s)"


def test_opening_a_point_from_the_dashboard(qapp, ctrl, world):
    w = MainWindow(ctrl)
    w.show()
    w.dashboard_page.table.rowActivated.emit(3)  # Deadlocks, Operating Systems
    assert w.pages.currentIndex() == PAGE_SUBJECT and w.subject_page.title.text() == "Operating Systems"
    assert w.subject_page.tabs.currentIndex() == 0
    assert w.subject_page.editor.title_edit.text() == "Deadlocks" and w.subject_page.editor.isEnabled()
    assert [i.row() for i in w.subject_page.table.selectionModel().selectedRows()] == [world["os"].points.index(world["dead"])]
    assert w.subject_list.currentItem().text() == "Operating Systems" and w.nav.currentRow() == -1


def test_the_study_next_card_opens_its_point(qapp, ctrl, world):
    w = MainWindow(ctrl)
    w.dashboard_page.open_button.click()
    assert w.subject_page.title.text() == "Operating Systems" and w.subject_page.editor.title_edit.text() == "Process scheduling"


def test_opening_a_point_from_the_notes_tab_shows_the_points_tab(qapp, ctrl, world):
    w = MainWindow(ctrl)
    w.dashboard_page.table.rowActivated.emit(1)  # Normalisation, DBMS
    w.subject_page.tabs.setCurrentIndex(1)
    w.nav.setCurrentRow(0)
    w.dashboard_page.table.rowActivated.emit(1)
    assert w.subject_page.tabs.currentIndex() == 0 and w.subject_page.editor.title_edit.text() == "Normalisation"


def test_edits_are_saved_before_jumping_to_another_point(qapp, ctrl, world):
    w = MainWindow(ctrl)
    w.dashboard_page.table.rowActivated.emit(3)  # Deadlocks
    w.subject_page.editor.title_edit.setText("Deadlock avoidance")
    w.open_point(world["dbms"].id, world["norm"].id)  # jump to a different subject without leaving the page first
    assert ctrl.get_point(world["os"].id, world["dead"].id).title == "Deadlock avoidance"
    assert w.subject_page.title.text() == "DBMS" and w.subject_page.editor.title_edit.text() == "Normalisation"


def test_opening_an_unknown_point_does_nothing(qapp, ctrl, world):
    w = MainWindow(ctrl)
    w.open_point("no-such-subject", "no-such-point")
    assert w.pages.currentIndex() == PAGE_DASHBOARD


def test_the_dashboard_follows_the_subject_page(qapp, ctrl, world):
    w = MainWindow(ctrl)
    w.open_point(world["os"].id, world["dead"].id)
    w.subject_page.editor.done.setChecked(True)
    w.subject_page.flush()
    assert "5 unfinished" in w.dashboard_page.summary.text() and "Deadlocks" not in titles(w.dashboard_page)
    w.nav.setCurrentRow(0)
    assert w.pages.currentIndex() == PAGE_DASHBOARD


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_the_dashboard_renders_in_the_window(qapp, ctrl, world, mode):
    style.apply_theme(qapp, mode)
    w = MainWindow(ctrl)
    w.resize(1120, 720)
    w.show()
    qapp.processEvents()
    image = w.grab().toImage()
    assert image.width() >= 880 and len({image.pixel(x, y) for x in range(0, 880, 6) for y in range(0, 560, 6)}) > 8
    page = w.dashboard_page
    assert page.title.isVisible() and page.card.isVisible() and page.table.isVisible() and page.hours.isVisible()
    assert page.table.columnWidth(COL_TITLE) >= 200  # the title column is no longer squeezed
    style.apply_theme(qapp, "light")
