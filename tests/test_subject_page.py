from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QDateTime, QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from studyflow import NotFoundError, StorageError, UserManager  # noqa: E402
from studyflow.models import to_utc  # noqa: E402
from studyflow.ui import main_window as mw_module  # noqa: E402
from studyflow.ui import style, util  # noqa: E402
from studyflow.ui.controller import AppController  # noqa: E402
from studyflow.ui.dialogs.name_dialog import NameDialog  # noqa: E402
from studyflow.ui.main_window import PAGE_DASHBOARD, PAGE_SUBJECT, MainWindow  # noqa: E402
from studyflow.ui.pages.subject_page import SubjectPage  # noqa: E402
from studyflow.ui.widgets.points_table import (  # noqa: E402
    COL_DEADLINE,
    COL_DONE,
    COL_EFFORT,
    COL_LEFT,
    COL_TITLE,
    PointsModel,
)

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)
CHECKED, UNCHECKED = Qt.CheckState.Checked, Qt.CheckState.Unchecked
DISPLAY, CHECK = Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.CheckStateRole


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
    """A subject with four points: scheduled, overdue, done, and bare."""
    s = ctrl.add_subject("OS", notes="subject notes")
    a = ctrl.add_point(s.id, "Deadlocks", notes="note a", deadline=NOW + timedelta(days=3), effort_hours=2.5)
    b = ctrl.add_point(s.id, "Scheduling", deadline=NOW - timedelta(hours=5), effort_hours=1)
    c = ctrl.add_point(s.id, "Intro", effort_hours=1)
    ctrl.set_point_done(s.id, c.id, True)
    d = ctrl.add_point(s.id, "Bare")
    return s, a, b, c, d


@pytest.fixture
def page(qapp, ctrl, world):
    p = SubjectPage(ctrl)
    p.show_subject(world[0].id)
    return p


def cell(model, row, col, role=DISPLAY):
    return model.data(model.index(row, col), role)


def select(page, row):
    page.table.selectRow(row)


def spy(ctrl):
    count = {"n": 0}
    ctrl.dataChanged.connect(lambda: count.__setitem__("n", count["n"] + 1))
    return count


def errors(monkeypatch):
    shown = []
    monkeypatch.setattr(util, "show_error", lambda parent, message: shown.append(message))
    return shown


# ================================================================== the table model
def test_model_columns(qapp, ctrl, world):
    s, a, b, c, d = world
    m = PointsModel(ctrl)
    m.set_subject(s.id)
    assert m.rowCount() == 4 and m.columnCount() == 5
    assert [cell(m, 0, col) for col in (COL_TITLE, COL_EFFORT, COL_LEFT)] == ["Deadlocks", "2.5 h", "3d 0h left"]
    assert cell(m, 0, COL_DEADLINE) == a.deadline.astimezone().strftime("%d %b %Y, %H:%M")
    assert cell(m, 1, COL_LEFT) == "overdue by 5h 0m"
    assert cell(m, 2, COL_LEFT) == "done" and cell(m, 3, COL_LEFT) == "\u2014"
    assert cell(m, 3, COL_DEADLINE) == "\u2014" and cell(m, 3, COL_EFFORT) == "\u2014"
    assert [cell(m, r, COL_DONE, CHECK) for r in range(4)] == [UNCHECKED, UNCHECKED, CHECKED, UNCHECKED]
    assert cell(m, 0, COL_DONE) is None  # the checkbox column shows no text


def test_done_rows_are_struck_through_and_overdue_is_red(qapp, ctrl, world):
    s, *_ = world
    m = PointsModel(ctrl)
    m.set_subject(s.id)
    assert cell(m, 2, COL_TITLE, Qt.ItemDataRole.FontRole).strikeOut()
    assert cell(m, 0, COL_TITLE, Qt.ItemDataRole.FontRole) is None
    assert cell(m, 1, COL_LEFT, Qt.ItemDataRole.ForegroundRole).color().name() == style.current().danger
    assert cell(m, 0, COL_LEFT, Qt.ItemDataRole.ForegroundRole) is None
    assert cell(m, 2, COL_TITLE, Qt.ItemDataRole.ForegroundRole).color().name() == style.current().muted


def test_only_the_done_column_is_checkable(qapp, ctrl, world):
    m = PointsModel(ctrl)
    m.set_subject(world[0].id)
    assert m.flags(m.index(0, COL_DONE)) & Qt.ItemFlag.ItemIsUserCheckable
    assert not m.flags(m.index(0, COL_TITLE)) & Qt.ItemFlag.ItemIsUserCheckable
    assert m.setData(m.index(0, COL_TITLE), "x", Qt.ItemDataRole.EditRole) is False


def test_ticking_the_box_marks_the_point_done(qapp, ctrl, world):
    s, a, *_ = world
    m = PointsModel(ctrl)
    m.set_subject(s.id)
    assert m.setData(m.index(0, COL_DONE), CHECKED, CHECK) is True
    assert ctrl.get_point(s.id, a.id).done is True
    assert m.setData(m.index(0, COL_DONE), 0, CHECK) is True  # plain ints are accepted too
    assert ctrl.get_point(s.id, a.id).done is False


def test_a_failed_tick_reports_the_error(qapp, ctrl, world, monkeypatch):
    m = PointsModel(ctrl)
    m.set_subject(world[0].id)
    got = []
    m.errorRaised.connect(got.append)
    monkeypatch.setattr(ctrl, "set_point_done", lambda *a: (_ for _ in ()).throw(StorageError("disk full")))
    assert m.setData(m.index(0, COL_DONE), CHECKED, CHECK) is False and got == ["disk full"]


def test_refresh_updates_in_place_or_resets(qapp, ctrl, world):
    s, a, *_ = world
    m = PointsModel(ctrl)
    m.set_subject(s.id)
    resets = []
    m.modelReset.connect(lambda: resets.append(1))
    ctrl.update_point(s.id, a.id, title="Renamed")
    m.refresh()
    assert cell(m, 0, COL_TITLE) == "Renamed" and resets == []  # same rows: updated in place
    ctrl.add_point(s.id, "New one")
    m.refresh()
    assert m.rowCount() == 5 and resets == [1] and m.row_of(a.id) == 0 and m.row_of("nope") == -1


def test_the_clock_tick_updates_only_the_time_left(qapp, ctrl, world, clock):
    s, *_ = world
    m = PointsModel(ctrl)
    m.set_subject(s.id)
    assert cell(m, 0, COL_LEFT) == "3d 0h left"
    clock["now"] = NOW + timedelta(days=1)
    changed = []
    m.dataChanged.connect(lambda tl, br, roles=None: changed.append((tl.column(), br.column())))
    m.refresh_times()
    assert cell(m, 0, COL_LEFT) == "2d 0h left" and changed == [(COL_LEFT, COL_LEFT)]


def test_model_without_a_subject_is_empty(qapp, ctrl):
    m = PointsModel(ctrl)
    assert m.rowCount() == 0 and m.data(m.index(0, 0)) is None
    m.set_subject("does-not-exist")
    assert m.rowCount() == 0 and m.subject_id is None


# ================================================================== the page: showing
def test_page_shows_the_subject(qapp, page):
    assert page.title.text() == "OS" and page.summary.text() == "4 study point(s), 1 done"
    assert page.notes.toPlainText() == "subject notes"
    assert page.model.rowCount() == 4
    assert not page.editor.isEnabled()  # nothing selected yet


def test_selecting_a_point_fills_the_editor(qapp, page, world):
    s, a, *_ = world
    select(page, 0)
    e = page.editor
    assert e.isEnabled() and e.title_edit.text() == "Deadlocks" and e.notes.toPlainText() == "note a"
    assert e.has_deadline.isChecked() and e.deadline.isEnabled()
    assert e.deadline.dateTime().toPython().astimezone() == a.deadline.astimezone()
    assert e.has_effort.isChecked() and e.effort.value() == 2.5 and not e.done.isChecked()
    select(page, 3)  # the bare point has neither deadline nor effort
    assert not e.has_deadline.isChecked() and not e.deadline.isEnabled()
    assert not e.has_effort.isChecked() and not e.effort.isEnabled()
    select(page, 2)
    assert e.done.isChecked()
    assert not e.is_dirty  # loading is never an edit


def test_the_default_deadline_is_tomorrow_evening(qapp, page):
    select(page, 3)
    shown = page.editor.deadline.dateTime().toPython()
    assert shown.hour == 18 and shown.minute == 0 and shown.date() > datetime.now().date()


# ================================================================== the page: adding and deleting points
def test_quick_add(qapp, page, world, ctrl):
    s = world[0]
    page.quick_add.setText("   ")
    page.quick_add.returnPressed.emit()
    assert page.model.rowCount() == 4  # blank input is ignored
    page.quick_add.setText("  New topic  ")
    page.quick_add.returnPressed.emit()
    assert page.quick_add.text() == "" and page.model.rowCount() == 5
    assert ctrl.get_subject(s.id).points[-1].title == "New topic"
    assert page.editor.title_edit.text() == "New topic" and page.editor.isEnabled()  # the new point is selected


def test_delete_with_the_button_and_with_the_key(qapp, page, world, ctrl):
    s, a, b, *_ = world
    select(page, 0)
    page.editor.delete_button.click()
    assert [p.id for p in ctrl.get_subject(s.id).points][0] == b.id and not page.editor.isEnabled()
    select(page, 0)
    QTest.keyClick(page.table, Qt.Key.Key_Delete)
    assert len(ctrl.get_subject(s.id).points) == 2 and page.model.rowCount() == 2
    QTest.keyClick(page.table, Qt.Key.Key_Delete)  # nothing selected any more: nothing happens
    assert page.model.rowCount() == 2


def test_deleting_a_point_discards_its_pending_edits(qapp, page, world, ctrl, monkeypatch):
    s, a, *_ = world
    shown = errors(monkeypatch)
    select(page, 0)
    page.editor.title_edit.setText("Edited but about to vanish")
    page.editor.delete_button.click()
    page.flush()
    assert shown == [] and a.id not in [p.id for p in ctrl.get_subject(s.id).points]


# ================================================================== the page: editing points
def test_editing_the_title_is_saved_on_flush_and_only_once(qapp, page, world, ctrl):
    s, a, *_ = world
    select(page, 0)
    page.editor.title_edit.setText("Deadlocks 2")
    assert page.editor.is_dirty and page._save_timer.isActive()
    count = spy(ctrl)
    page.flush()
    assert ctrl.get_point(s.id, a.id).title == "Deadlocks 2" and count["n"] == 1
    assert not page.editor.is_dirty and not page._save_timer.isActive()
    page.flush()  # nothing to save: no write, no signal
    assert count["n"] == 1
    assert cell(page.model, 0, COL_TITLE) == "Deadlocks 2"


def test_the_pause_in_typing_saves(qapp, page, world, ctrl):
    s, a, *_ = world
    select(page, 0)
    page.editor.notes.setPlainText("rewritten notes")
    assert page._save_timer.isActive() and ctrl.get_point(s.id, a.id).notes == "note a"  # not yet
    page._save_timer.timeout.emit()
    assert ctrl.get_point(s.id, a.id).notes == "rewritten notes"


def test_changing_deadline_effort_and_done(qapp, page, world, ctrl):
    s, a, *_ = world
    select(page, 0)
    e = page.editor
    e.deadline.setDateTime(QDateTime(2026, 12, 1, 9, 30, 0))
    e.effort.setValue(4.25)
    e.done.setChecked(True)
    page.flush()
    p = ctrl.get_point(s.id, a.id)
    assert p.deadline == to_utc(datetime(2026, 12, 1, 9, 30)) and p.effort_hours == 4.25 and p.done is True
    e.has_deadline.setChecked(False)
    e.has_effort.setChecked(False)
    page.flush()
    p = ctrl.get_point(s.id, a.id)
    assert p.deadline is None and p.effort_hours is None and p.done is True


def test_ticking_deadline_on_a_bare_point(qapp, page, world, ctrl):
    s, *_, d = world
    select(page, 3)
    page.editor.has_deadline.setChecked(True)
    page.editor.has_effort.setChecked(True)
    page.flush()
    p = ctrl.get_point(s.id, d.id)
    assert p.deadline is not None and p.deadline.astimezone().hour == 18 and p.effort_hours == 1.0


def test_only_fields_the_user_touched_are_written(qapp, page, world, ctrl):
    """A value the spin box cannot show exactly (2.345 -> 2.35) must not be rewritten by editing something else."""
    s, a, *_ = world
    ctrl.update_point(s.id, a.id, effort_hours=2.345)
    select(page, 3)
    select(page, 0)
    assert page.editor.effort.value() == 2.35
    page.editor.notes.setPlainText("only the notes changed")
    page.flush()
    p = ctrl.get_point(s.id, a.id)
    assert p.effort_hours == 2.345 and p.notes == "only the notes changed"


def test_an_empty_title_is_never_saved(qapp, page, world, ctrl):
    s, a, *_ = world
    select(page, 0)
    page.editor.title_edit.setText("")
    page.editor.notes.setPlainText("other change")
    page._save_timer.timeout.emit()  # the user paused: other fields are saved, the title complains
    assert ctrl.get_point(s.id, a.id).title == "Deadlocks" and ctrl.get_point(s.id, a.id).notes == "other change"
    assert "empty" in page.editor.error.text()
    page.editor.title_edit.setText("Fixed")
    page.flush()
    assert ctrl.get_point(s.id, a.id).title == "Fixed" and page.editor.error.text() == ""


def test_leaving_a_point_with_an_empty_title_restores_it(qapp, page, world, ctrl):
    s, a, b, *_ = world
    select(page, 0)
    page.editor.title_edit.setText("   ")
    select(page, 1)
    assert ctrl.get_point(s.id, a.id).title == "Deadlocks"
    select(page, 0)
    assert page.editor.title_edit.text() == "Deadlocks" and page.editor.error.text() == ""


def test_selecting_another_point_saves_the_previous_one(qapp, page, world, ctrl):
    s, a, b, *_ = world
    select(page, 0)
    page.editor.title_edit.setText("Edited A")
    select(page, 1)
    assert ctrl.get_point(s.id, a.id).title == "Edited A" and ctrl.get_point(s.id, b.id).title == "Scheduling"
    assert page.editor.title_edit.text() == "Scheduling"
    assert page._point_id == b.id and [i.row() for i in page.table.selectionModel().selectedRows()] == [1]  # the click was not undone


def test_an_outside_change_shows_up_unless_the_user_is_typing(qapp, page, world, ctrl):
    s, a, *_ = world
    select(page, 0)
    ctrl.update_point(s.id, a.id, title="Changed elsewhere")
    assert cell(page.model, 0, COL_TITLE) == "Changed elsewhere" and page.editor.title_edit.text() == "Changed elsewhere"
    page.editor.title_edit.setText("my half-typed title")
    ctrl.update_point(s.id, a.id, effort_hours=7)  # an unrelated outside change must not eat what I am typing
    assert page.editor.title_edit.text() == "my half-typed title"


def test_a_failed_save_is_reported_and_the_editor_shows_the_truth(qapp, page, world, ctrl, monkeypatch):
    s, a, *_ = world
    shown = errors(monkeypatch)
    select(page, 0)
    page.editor.title_edit.setText("Will not stick")
    monkeypatch.setattr(ctrl, "update_point", lambda *a, **k: (_ for _ in ()).throw(StorageError("disk full")))
    page.flush()
    assert shown == ["disk full"] and page.editor.title_edit.text() == "Deadlocks" and not page.editor.is_dirty


def test_a_vanished_subject_is_not_worth_a_dialog(qapp, page, world, ctrl, monkeypatch):
    shown = errors(monkeypatch)
    select(page, 0)
    page.editor.title_edit.setText("pending")
    ctrl.delete_subject(world[0].id)  # gone while an edit is pending
    page.flush()
    assert shown == [] and page.title.text() == ""


# ================================================================== the page: subject notes, rename, delete
def test_subject_notes_are_saved(qapp, page, world, ctrl):
    s = world[0]
    page.notes.setPlainText("new subject notes")
    assert ctrl.get_subject(s.id).notes == "subject notes" and page._save_timer.isActive()
    page.flush()
    assert ctrl.get_subject(s.id).notes == "new subject notes"
    page.notes.setPlainText("saved on leaving the box")
    page.notes.editingFinished.emit()
    assert ctrl.get_subject(s.id).notes == "saved on leaving the box"


def test_loading_notes_is_not_an_edit(qapp, ctrl, world):
    p = SubjectPage(ctrl)
    p.show_subject(world[0].id)
    assert not p._notes_dirty and not p._save_timer.isActive()


def test_rename_subject(qapp, page, world, ctrl, monkeypatch):
    s = world[0]
    answers = [None, "OS", "Operating Systems"]
    seen = []
    monkeypatch.setattr(NameDialog, "ask", staticmethod(lambda parent, title, label, validator, initial="", ok_text="OK": (seen.append(initial), answers.pop(0))[1]))
    count = spy(ctrl)
    page.rename_button.click()  # cancelled
    page.rename_button.click()  # same name
    assert count["n"] == 0 and ctrl.get_subject(s.id).name == "OS"
    page.rename_button.click()
    assert ctrl.get_subject(s.id).name == "Operating Systems" and page.title.text() == "Operating Systems" and seen[0] == "OS"


def test_rename_saves_pending_edits_first(qapp, page, world, ctrl, monkeypatch):
    s, a, *_ = world
    monkeypatch.setattr(NameDialog, "ask", staticmethod(lambda *args, **kw: None))
    select(page, 0)
    page.editor.title_edit.setText("pending title")
    page.rename_button.click()
    assert ctrl.get_point(s.id, a.id).title == "pending title"


def test_delete_subject(qapp, page, world, ctrl, monkeypatch):
    s = world[0]
    seen = []
    monkeypatch.setattr(util, "confirm", lambda parent, title, text, **k: (seen.append((text, k.get("detail"))), None)[1])
    page.delete_button.click()  # cancelled
    assert ctrl.subjects() and "OS" in seen[0][0] and "4 study point(s)" in seen[0][1]
    monkeypatch.setattr(util, "confirm", lambda *a, **k: False)
    page.delete_button.click()
    assert ctrl.subjects() == [] and page.title.text() == "" and page.model.rowCount() == 0 and not page.editor.isEnabled()


# ================================================================== inside the main window
def test_main_window_shows_the_page_for_the_selected_subject(qapp, ctrl, world):
    w = MainWindow(ctrl)
    w.subject_list.setCurrentRow(0)
    assert w.pages.currentIndex() == PAGE_SUBJECT and w.subject_page.title.text() == "OS"
    assert w.subject_page.model.rowCount() == 4


def test_leaving_the_subject_saves_pending_edits(qapp, ctrl, world):
    s, a, *_ = world
    w = MainWindow(ctrl)
    w.subject_list.setCurrentRow(0)
    w.subject_page.table.selectRow(0)
    w.subject_page.editor.title_edit.setText("saved on navigation")
    w.nav.setCurrentRow(0)  # back to the dashboard
    assert ctrl.get_point(s.id, a.id).title == "saved on navigation" and w.pages.currentIndex() == PAGE_DASHBOARD
    assert w.subject_page.title.text() == ""


def test_switching_to_another_subject_saves_pending_edits(qapp, ctrl, world):
    s, a, *_ = world
    other = ctrl.add_subject("AAA")  # sorts first
    w = MainWindow(ctrl)
    w.subject_list.setCurrentRow(1)  # OS
    w.subject_page.table.selectRow(0)
    w.subject_page.notes.setPlainText("typed just before clicking away")
    w.subject_list.setCurrentRow(0)  # AAA
    assert ctrl.get_subject(s.id).notes == "typed just before clicking away" and w.subject_page.title.text() == "AAA"


def test_pending_edits_go_to_the_right_user_when_switching(qapp, ctrl, world, tmp_path, monkeypatch):
    s, a, *_ = world
    me = ctrl.current_user
    other = ctrl.create_user("Amit", open_it=False)
    w = MainWindow(ctrl)
    w.subject_list.setCurrentRow(0)
    w.subject_page.table.selectRow(0)
    w.subject_page.editor.title_edit.setText("typed right before switching user")

    class FakePicker:
        def __init__(self, controller, parent=None):
            self.controller = controller

        def exec(self):
            self.controller.open_user(other.id)

    monkeypatch.setattr(mw_module, "UserPickerDialog", FakePicker)
    w.switch_user()
    assert ctrl.current_user.id == other.id and w.subject_page.title.text() == ""
    ctrl.open_user(me.id)
    assert ctrl.get_point(s.id, a.id).title == "typed right before switching user"  # saved for the right user
    assert ctrl.subjects()[0].name == "OS"


def test_closing_the_window_saves_pending_edits(qapp, ctrl, world):
    s, a, *_ = world
    w = MainWindow(ctrl)
    w.show()
    w.subject_list.setCurrentRow(0)
    w.subject_page.table.selectRow(0)
    w.subject_page.editor.title_edit.setText("saved on close")
    w.close()
    assert ctrl.get_point(s.id, a.id).title == "saved on close"


def test_deleting_the_subject_from_its_page_returns_to_the_dashboard(qapp, ctrl, world, monkeypatch):
    w = MainWindow(ctrl)
    w.subject_list.setCurrentRow(0)
    monkeypatch.setattr(util, "confirm", lambda *a, **k: False)
    w.subject_page.delete_button.click()
    assert w.pages.currentIndex() == PAGE_DASHBOARD and w.subject_list.count() == 0


def test_the_page_survives_a_user_switch_and_restart(qapp, ctrl, world, tmp_path, clock):
    s, a, *_ = world
    w = MainWindow(ctrl)
    w.subject_list.setCurrentRow(0)
    w.subject_page.table.selectRow(0)
    w.subject_page.editor.effort.setValue(6.0)
    w.subject_page.editor.effort.valueChanged.emit(6.0)
    w.subject_page.flush()
    again = AppController(UserManager(ctrl.manager.root).root, now=lambda: clock["now"])
    again.start()
    assert again.get_point(s.id, a.id).effort_hours == 6.0


# ================================================================== theme mode groundwork
def test_theme_modes(qapp):
    style.apply_theme(qapp, "dark")
    assert style.current() is style.DARK and qapp.palette().color(qapp.palette().ColorRole.Window).name() == style.DARK.window
    style.apply_theme(qapp, "light")
    assert style.current() is style.LIGHT
    style.apply_theme(qapp, "system")
    assert style.current() in (style.LIGHT, style.DARK)
    with pytest.raises(ValueError):
        style.apply_theme(qapp, "purple")
    assert style.THEME_MODES == ("system", "light", "dark")


# ================================================================== real key presses and mouse clicks
def test_typing_into_the_quick_add_box(qapp, page, world, ctrl):
    page.show()
    page.quick_add.setFocus()
    QTest.keyClicks(page.quick_add, "Segmentation")
    QTest.keyClick(page.quick_add, Qt.Key.Key_Return)
    assert ctrl.get_subject(world[0].id).points[-1].title == "Segmentation" and page.quick_add.text() == ""
    QTest.keyClicks(page.quick_add, "Thrashing")  # focus stays in the box for rapid entry
    QTest.keyClick(page.quick_add, Qt.Key.Key_Enter)
    assert [p.title for p in ctrl.get_subject(world[0].id).points][-2:] == ["Segmentation", "Thrashing"]


def test_clicking_the_checkbox_marks_a_point_done(qapp, page, world, ctrl):
    s, a, *_ = world
    page.resize(900, 700)
    page.show()
    qapp.processEvents()
    rect = page.table.visualRect(page.model.index(0, COL_DONE))
    QTest.mouseClick(page.table.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(rect.left() + 16, rect.center().y()))
    assert ctrl.get_point(s.id, a.id).done is True and cell(page.model, 0, COL_DONE, CHECK) == CHECKED
    assert page.summary.text() == "4 study point(s), 2 done"


def test_typing_in_the_editor_with_real_key_events(qapp, page, world, ctrl):
    s, a, *_ = world
    page.show()
    select(page, 0)
    page.editor.title_edit.setFocus()
    page.editor.title_edit.selectAll()
    QTest.keyClicks(page.editor.title_edit, "Deadlock avoidance")
    assert page.editor.is_dirty
    select(page, 1)  # clicking away saves
    assert ctrl.get_point(s.id, a.id).title == "Deadlock avoidance"


# ================================================================== regression: saving must never re-enter itself
def count_calls(monkeypatch, ctrl, name):
    calls = []
    real = getattr(ctrl, name)
    monkeypatch.setattr(ctrl, name, lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    return calls


@pytest.mark.parametrize("leave", ["dashboard", "other_subject", "close", "other_point"])
def test_leaving_with_a_pending_point_edit_saves_exactly_once(qapp, ctrl, world, monkeypatch, leave):
    """Saving emits dataChanged; the window rebuilds its subject list; that used to re-fire the selection handler,
    which flushed again (RecursionError). conftest turns any exception inside a Qt slot into a test failure."""
    s, a, *_ = world
    ctrl.add_subject("AAA")
    w = MainWindow(ctrl)
    w.show()
    w.subject_list.setCurrentRow(1)  # OS
    w.subject_page.table.selectRow(0)
    w.subject_page.editor.title_edit.setText("saved once")
    calls = count_calls(monkeypatch, ctrl, "update_point")
    if leave == "dashboard":
        w.nav.setCurrentRow(0)
    elif leave == "other_subject":
        w.subject_list.setCurrentRow(0)
    elif leave == "close":
        w.close()
    else:
        w.subject_page.table.selectRow(1)
    assert len(calls) == 1 and ctrl.get_point(s.id, a.id).title == "saved once"


def test_a_pending_edit_is_saved_once_when_the_timer_fires_inside_the_window(qapp, ctrl, world, monkeypatch):
    s, a, *_ = world
    w = MainWindow(ctrl)
    w.subject_list.setCurrentRow(0)
    w.subject_page.table.selectRow(0)
    w.subject_page.editor.title_edit.setText("by timer")
    calls = count_calls(monkeypatch, ctrl, "update_point")
    w.subject_page._save_timer.timeout.emit()
    assert len(calls) == 1 and ctrl.get_point(s.id, a.id).title == "by timer"
    assert w.subject_list.currentRow() == 0 and w.subject_page.title.text() == "OS"  # the selection did not move


def test_the_window_does_not_reannounce_the_selection_when_the_list_is_rebuilt(qapp, ctrl, world):
    w = MainWindow(ctrl)
    w.subject_list.setCurrentRow(0)
    seen = []
    w.subject_list.currentRowChanged.connect(seen.append)
    ctrl.add_subject("Another")  # rebuilds the sidebar list
    ctrl.rename_subject(world[0].id, "OS renamed")
    assert seen == []


# ================================================================== layout: room for everything at 1120x720
def test_subject_notes_have_their_own_tab_with_a_dot_when_not_empty(qapp, ctrl, world):
    page = SubjectPage(ctrl)
    page.show_subject(world[0].id)
    assert [page.tabs.tabText(i) for i in range(2)] == ["Study points", "Notes \u2022"]
    page.notes.setPlainText("")
    assert page.tabs.tabText(1) == "Notes"
    page.notes.setPlainText("typed")
    assert page.tabs.tabText(1) == "Notes \u2022"
    empty = ctrl.add_subject("Empty")
    page.show_subject(empty.id)
    assert page.tabs.tabText(1) == "Notes"


def test_the_tab_choice_is_kept_when_another_subject_is_shown(qapp, ctrl, world):
    page = SubjectPage(ctrl)
    page.show_subject(world[0].id)
    page.tabs.setCurrentIndex(1)
    other = ctrl.add_subject("Other", notes="its notes")
    page.show_subject(other.id)
    assert page.tabs.currentIndex() == 1 and page.notes.toPlainText() == "its notes"


def test_select_point_shows_the_points_tab_and_the_editor(qapp, page, world):
    s, a, b, *_ = world
    page.tabs.setCurrentIndex(1)
    page.select_point(b.id)
    assert page.tabs.currentIndex() == 0 and page.editor.title_edit.text() == "Scheduling"
    assert [i.row() for i in page.table.selectionModel().selectedRows()] == [1]
    page.select_point("no-such-point")  # ignored
    assert page.editor.title_edit.text() == "Scheduling"


@pytest.mark.parametrize(
    "screen, expected",
    [((1366, 728), (1120, 720)), ((1920, 1040), (1497, 915)), ((2560, 1400), (1996, 1232)), ((800, 600), (800, 600)), ((1024, 700), (1024, 700))],
)
def test_default_window_size_follows_the_screen(screen, expected):
    assert mw_module.default_window_size(*screen) == expected


def test_everything_has_room_at_1120_by_720(qapp, ctrl, world):
    """The reported problem: the point's notes box showed only ~2 lines. Now it has room, and the table
    shows the five rows of the sample subject."""
    w = MainWindow(ctrl)
    w.resize(1120, 720)
    w.show()
    w.subject_list.setCurrentRow(0)
    w.subject_page.table.selectRow(0)
    qapp.processEvents()
    page = w.subject_page
    assert page.editor.notes.height() >= 80  # at least four lines of text
    assert page.table.viewport().height() >= 4 * 32  # the sample's four points are all visible without scrolling
    assert page.editor.title_edit.isVisible() and page.editor.delete_button.isVisible()
