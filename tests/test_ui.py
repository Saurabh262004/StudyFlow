import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QKeySequence  # noqa: E402
from PySide6.QtWidgets import QDialog  # noqa: E402

from studyflow import StorageError  # noqa: E402
from studyflow.ui import app as app_module  # noqa: E402
from studyflow.ui import main_window as mw_module  # noqa: E402
from studyflow.ui import startup, style, util  # noqa: E402
from studyflow.ui.controller import AppController  # noqa: E402
from studyflow.ui.dialogs.name_dialog import NameDialog  # noqa: E402
from studyflow.ui.dialogs.user_picker import UserPickerDialog  # noqa: E402
from studyflow.ui.main_window import PAGE_DASHBOARD, PAGE_IMAGES, PAGE_SUBJECT, MainWindow  # noqa: E402


@pytest.fixture
def root(tmp_path):
    return tmp_path / "root"


@pytest.fixture
def ctrl(qapp, root):
    c = AppController(root)
    c.create_user("Saurabh")
    return c


def stub_ask(monkeypatch, *answers):
    """Make NameDialog.ask return the given answers one after the other, and record how it was called."""
    calls, queue = [], list(answers)

    def fake(parent, title, label, validator, initial="", ok_text="OK"):
        calls.append({"title": title, "validator": validator, "initial": initial})
        return queue.pop(0)

    monkeypatch.setattr(NameDialog, "ask", staticmethod(fake))
    return calls


def stub_errors(monkeypatch):
    shown = []
    monkeypatch.setattr(util, "show_error", lambda parent, message: shown.append(message))
    return shown


def subject_names(w):
    return [w.subject_list.item(i).text() for i in range(w.subject_list.count())]


# ================================================================== NameDialog
def test_name_dialog_enables_ok_only_for_valid_text(qapp):
    d = NameDialog("T", "Label", lambda t: "Nope" if t == "bad" else None)
    assert not d.ok_button.isEnabled() and d.error.text() == ""  # empty: disabled, but no scolding yet
    d.edit.setText("good")
    assert d.ok_button.isEnabled() and d.error.text() == ""
    d.edit.setText("bad")
    assert not d.ok_button.isEnabled() and d.error.text() == "Nope"
    d.edit.setText("  padded  ")
    assert d.ok_button.isEnabled() and d.value() == "padded"
    d.edit.setText("   ")
    assert not d.ok_button.isEnabled()


def test_name_dialog_with_a_valid_initial_value(qapp):
    d = NameDialog("T", "Label", lambda t: None, initial="Keep", ok_text="Go")
    assert d.ok_button.isEnabled() and d.ok_button.text() == "Go" and d.value() == "Keep"


# ================================================================== user picker
def test_picker_lists_users_and_selects_the_current_one(qapp, ctrl):
    ctrl.create_user("Amit", open_it=False)
    d = UserPickerDialog(ctrl)
    texts = [d.users.item(i).text() for i in range(d.users.count())]
    assert texts == ["Amit", "Saurabh   (current)"]
    assert d.selected_id() == ctrl.current_user.id and d.open_button.isEnabled()


def test_picker_opens_another_user(qapp, ctrl):
    other = ctrl.create_user("Amit", open_it=False)
    d = UserPickerDialog(ctrl)
    d.users.setCurrentRow(0)
    assert d.selected_id() == other.id
    d.open_selected()
    assert ctrl.current_user.id == other.id and d.result() == QDialog.DialogCode.Accepted


def test_picker_open_of_the_current_user_just_closes(qapp, ctrl):
    got = []
    ctrl.userChanged.connect(lambda: got.append(1))
    d = UserPickerDialog(ctrl)
    d.open_selected()
    assert d.result() == QDialog.DialogCode.Accepted and got == []


def test_picker_shows_why_a_user_cannot_be_opened_and_stays_open(qapp, ctrl):
    import json

    bad = ctrl.create_user("Bad", open_it=False)
    (ctrl.manager.users_dir / bad.id / "data.json").write_text(json.dumps({"schemaVersion": 99}), "utf-8")
    d = UserPickerDialog(ctrl)
    d.users.setCurrentRow(0)  # Bad
    d.open_selected()
    assert "newer" in d.error.text() and d.result() != QDialog.DialogCode.Accepted
    assert ctrl.current_user.name == "Saurabh"


def test_picker_shows_a_start_up_error(qapp, ctrl):
    assert UserPickerDialog(ctrl, error="Could not open X").error.text() == "Could not open X"


def test_picker_new_user(qapp, ctrl, monkeypatch):
    calls = stub_ask(monkeypatch, None, "Amit")
    d = UserPickerDialog(ctrl)
    d.new_user()  # cancelled
    assert [u.name for u in ctrl.users()] == ["Saurabh"] and d.result() != QDialog.DialogCode.Accepted
    d.new_user()
    assert ctrl.current_user.name == "Amit" and d.result() == QDialog.DialogCode.Accepted
    assert calls[0]["validator"]("saurabh") == "A user named 'Saurabh' already exists"  # the dialog is wired to the real rules


def test_picker_rename(qapp, ctrl, monkeypatch):
    calls = stub_ask(monkeypatch, "Renamed")
    d = UserPickerDialog(ctrl)
    d.rename_user()
    assert ctrl.current_user.name == "Renamed" and d.users.item(0).text().startswith("Renamed")
    assert calls[0]["initial"] == "Saurabh"
    assert calls[0]["validator"]("Saurabh") is None  # may keep its own name


def test_picker_delete_paths(qapp, ctrl, monkeypatch, tmp_path):
    guest = ctrl.create_user("Guest", open_it=False)
    ctrl.add_subject("mine")
    shown = stub_errors(monkeypatch)
    d = UserPickerDialog(ctrl)
    d.users.setCurrentRow(0)  # Guest
    assert d._selected_user().id == guest.id

    monkeypatch.setattr(util, "confirm", lambda *a, **k: None)  # cancelled
    d.delete_user()
    assert len(ctrl.users()) == 2

    monkeypatch.setattr(util, "confirm", lambda *a, **k: True)  # "Save a backup first" ticked ...
    monkeypatch.setattr(util, "ask_save_path", lambda *a, **k: None)  # ... but no place chosen
    d.delete_user()
    assert len(ctrl.users()) == 2

    monkeypatch.setattr(util, "ask_save_path", lambda *a, **k: tmp_path / "guest-backup.zip")
    d.delete_user()  # Guest has no data file yet, so the backup fails and NOTHING is deleted
    assert len(ctrl.users()) == 2 and shown and "nothing was deleted" in shown[0]

    monkeypatch.setattr(util, "confirm", lambda *a, **k: False)  # plain delete
    d.delete_user()
    assert [u.name for u in ctrl.users()] == ["Saurabh"]


def test_picker_delete_with_a_real_backup(qapp, ctrl, monkeypatch, tmp_path):
    other = ctrl.create_user("Other")
    ctrl.add_subject("Precious")
    ctrl.open_user(next(u for u in ctrl.users() if u.name == "Saurabh").id)
    d = UserPickerDialog(ctrl)
    d.users.setCurrentRow(0)  # Other
    assert d.selected_id() == other.id
    target = tmp_path / "other.zip"
    monkeypatch.setattr(util, "confirm", lambda *a, **k: True)
    monkeypatch.setattr(util, "ask_save_path", lambda *a, **k: target)
    d.delete_user()
    assert target.exists() and [u.name for u in ctrl.users()] == ["Saurabh"]


def test_picker_buttons_follow_the_selection(qapp, ctrl):
    ctrl.delete_user(ctrl.current_user.id)
    d = UserPickerDialog(ctrl)
    assert d.users.count() == 0
    assert not any(b.isEnabled() for b in (d.open_button, d.rename_button, d.delete_button)) and d.new_button.isEnabled()


# ================================================================== start-up flow
def test_startup_opens_the_last_user_without_asking(qapp, root, monkeypatch):
    c = AppController(root)
    c.create_user("A")
    c2 = AppController(root)
    monkeypatch.setattr(startup, "UserPickerDialog", lambda *a, **k: pytest.fail("must not be shown"))
    monkeypatch.setattr(NameDialog, "ask", staticmethod(lambda *a, **k: pytest.fail("must not be shown")))
    assert startup.run_startup(c2) is True and c2.current_user.name == "A"


def test_startup_first_run(qapp, root, monkeypatch):
    c = AppController(root)
    calls = stub_ask(monkeypatch, "Saurabh")
    assert startup.run_startup(c) is True and c.current_user.name == "Saurabh"
    assert calls[0]["title"] == "Welcome to StudyFlow"
    c2 = AppController(root / "other")
    stub_ask(monkeypatch, None)
    assert startup.run_startup(c2) is False and not c2.is_open  # the user gave up


class FakePicker:
    """Stands in for the real (blocking) dialog."""

    script = []
    seen_errors = []

    def __init__(self, controller, error=None, parent=None):
        self.controller = controller
        FakePicker.seen_errors.append(error)

    def exec(self):
        step = FakePicker.script.pop(0)
        step(self.controller)


def test_startup_shows_the_picker_with_the_reason_and_loops_until_a_user_is_open(qapp, root, monkeypatch):
    import json

    c = AppController(root)
    a = c.create_user("A")
    (c.manager.users_dir / a.id / "data.json").write_text(json.dumps({"schemaVersion": 99}), "utf-8")
    b = c.create_user("B", open_it=False)
    FakePicker.seen_errors = []
    FakePicker.script = [lambda ctl: None, lambda ctl: ctl.open_user(b.id)]  # first closed without choosing, then B
    monkeypatch.setattr(startup, "UserPickerDialog", FakePicker)
    c2 = AppController(root)
    # first attempt: the user closes the picker -> gives up
    assert startup.run_startup(c2) is False
    assert "newer" in FakePicker.seen_errors[0]
    assert startup.choose_user(c2) is True and c2.current_user.name == "B"
    assert FakePicker.seen_errors[1] is None  # the old error is not repeated


def test_choose_user_when_everyone_was_deleted_asks_for_a_new_user(qapp, root, monkeypatch):
    c = AppController(root)
    c.create_user("A")
    c2 = AppController(root)
    FakePicker.seen_errors, FakePicker.script = [], [lambda ctl: [ctl.manager.delete_user(u.id) for u in ctl.users()]]
    monkeypatch.setattr(startup, "UserPickerDialog", FakePicker)
    stub_ask(monkeypatch, "Fresh")
    assert startup.choose_user(c2) is True and c2.current_user.name == "Fresh"


# ================================================================== main window
def test_main_window_shows_the_open_user_and_their_subjects(qapp, ctrl):
    for name in ("operating systems", "DBMS", "Maths"):
        ctrl.add_subject(name)
    w = MainWindow(ctrl)
    assert w.windowTitle() == "Saurabh \u2014 StudyFlow" and "Saurabh" in w.user_button.text()
    assert subject_names(w) == ["DBMS", "Maths", "operating systems"]  # sorted ignoring case
    assert w.pages.currentIndex() == PAGE_DASHBOARD and w.nav.currentRow() == 0
    assert "3 subject(s)" in w.dashboard_page.body.text()
    assert w.switch_action.shortcut() == QKeySequence("Ctrl+U")


def test_sidebar_follows_the_controller(qapp, ctrl):
    w = MainWindow(ctrl)
    assert subject_names(w) == []
    s = ctrl.add_subject("Maths")
    assert subject_names(w) == ["Maths"] and w.pages.currentIndex() == PAGE_DASHBOARD
    ctrl.rename_subject(s.id, "Mathematics")
    assert subject_names(w) == ["Mathematics"]
    ctrl.add_point(s.id, "Algebra")
    assert "1 unfinished" in w.dashboard_page.body.text()


def test_selecting_subjects_and_navigation(qapp, ctrl):
    ctrl.add_subject("A")
    s = ctrl.add_subject("B")
    w = MainWindow(ctrl)
    w.subject_list.setCurrentRow(1)
    assert w.pages.currentIndex() == PAGE_SUBJECT and w.subject_page.title.text() == "B" and w.nav.currentRow() == -1
    w.nav.setCurrentRow(1)
    assert w.pages.currentIndex() == PAGE_IMAGES and w.subject_list.currentRow() == -1
    w.nav.setCurrentRow(0)
    assert w.pages.currentIndex() == PAGE_DASHBOARD
    w.subject_list.setCurrentRow(1)
    ctrl.add_subject("C")  # the selection survives a refresh
    assert w.subject_page.title.text() == "B" and w.pages.currentIndex() == PAGE_SUBJECT
    ctrl.delete_subject(s.id)  # ... unless the selected subject itself is deleted
    assert w.pages.currentIndex() == PAGE_DASHBOARD


def test_add_subject_button(qapp, ctrl, monkeypatch):
    w = MainWindow(ctrl)
    stub_ask(monkeypatch, None, "Maths")
    w.add_subject_button.click()
    assert subject_names(w) == []
    w.add_subject_button.click()
    assert subject_names(w) == ["Maths"] and w.pages.currentIndex() == PAGE_SUBJECT and w.subject_page.title.text() == "Maths"


def test_add_subject_failure_is_shown_not_raised(qapp, ctrl, monkeypatch):
    w = MainWindow(ctrl)
    shown = stub_errors(monkeypatch)
    stub_ask(monkeypatch, "Maths")
    ctrl.store.save = lambda db: (_ for _ in ()).throw(StorageError("disk full"))
    w.add_subject()
    assert shown == ["disk full"] and subject_names(w) == []


def test_switching_and_renaming_users_updates_the_window(qapp, ctrl):
    ctrl.add_subject("Mine")
    w = MainWindow(ctrl)
    w.subject_list.setCurrentRow(0)
    other = ctrl.create_user("Amit")
    assert w.windowTitle().startswith("Amit") and subject_names(w) == [] and w.pages.currentIndex() == PAGE_DASHBOARD
    ctrl.rename_user(other.id, "Amit K")
    assert w.windowTitle().startswith("Amit K") and "Amit K" in w.user_status.text()
    ctrl.open_user(next(u for u in ctrl.users() if u.name == "Saurabh").id)
    assert subject_names(w) == ["Mine"] and w.windowTitle().startswith("Saurabh")


def test_warning_banner(qapp, ctrl):
    w = MainWindow(ctrl)
    assert w.banner.isHidden()
    ctrl.warnings = ["First problem", "Second problem"]
    ctrl.warningsChanged.emit()
    assert not w.banner.isHidden() and w.banner.label.text() == "First problem\nSecond problem"
    w.banner.dismiss.click()
    assert w.banner.isHidden() and ctrl.warnings == []


def test_deleting_the_open_user_asks_for_another(qapp, ctrl, monkeypatch):
    other = ctrl.create_user("Amit", open_it=False)
    w = MainWindow(ctrl)
    asked = []

    def fake_choose(controller, error=None, parent=None):
        asked.append(controller)
        controller.open_user(other.id)
        return True

    monkeypatch.setattr(mw_module, "choose_user", fake_choose)
    ctrl.delete_user(ctrl.current_user.id)
    qapp.processEvents()
    assert asked == [ctrl] and w.windowTitle().startswith("Amit")


def test_the_window_closes_when_no_user_is_chosen(qapp, ctrl, monkeypatch):
    w = MainWindow(ctrl)
    w.show()
    monkeypatch.setattr(mw_module, "choose_user", lambda *a, **k: False)
    ctrl.delete_user(ctrl.current_user.id)
    qapp.processEvents()
    assert not w.isVisible()


def test_closing_stops_the_clock(qapp, ctrl):
    w = MainWindow(ctrl)
    ctrl.start_clock(60_000)
    assert ctrl._timer.isActive()
    w.show()
    w.close()
    assert not ctrl._timer.isActive()


# ================================================================== look and entry point
def test_themes(qapp):
    light, dark = style.build_palette(style.LIGHT), style.build_palette(style.DARK)
    assert light.color(light.ColorRole.Window).name() == "#f6f7f9" and dark.color(dark.ColorRole.Window).name() == "#171a21"
    assert style.DARK.accent in style.build_stylesheet(style.DARK) and style.LIGHT.accent in style.build_stylesheet(style.LIGHT)
    style.apply_theme(qapp)
    assert qapp.palette().color(qapp.palette().ColorRole.Window).name() in ("#f6f7f9", "#171a21")  # one of our two themes
    assert qapp.styleSheet().strip()
    assert style.system_is_dark(qapp) in (True, False)


@pytest.mark.parametrize("colors", [style.LIGHT, style.DARK])
def test_the_window_renders_in_both_themes(qapp, ctrl, colors):
    ctrl.add_subject("Maths")
    ctrl.warnings = ["Something to read"]
    qapp.setPalette(style.build_palette(colors))
    qapp.setStyleSheet(style.build_stylesheet(colors))
    w = MainWindow(ctrl)
    w.show()
    qapp.processEvents()
    image = w.grab().toImage()
    assert image.width() >= 880 and image.height() >= 560
    assert len({image.pixelColor(x, y).rgb() for x in range(0, 880, 5) for y in range(0, 560, 5)}) > 3  # not a blank rectangle
    qapp.setStyleSheet("")
    style.apply_theme(qapp)


def test_command_line_options(monkeypatch):
    monkeypatch.delenv("STUDYFLOW_HOME", raising=False)
    args, qt_args = app_module.parse_args(["--data-dir", "/x", "-style", "fusion"])
    assert args.data_dir == "/x" and qt_args == ["-style", "fusion"]
    assert app_module.parse_args([])[0].data_dir is None
    monkeypatch.setenv("STUDYFLOW_HOME", "/from/env")
    assert app_module.parse_args([])[0].data_dir == "/from/env"
