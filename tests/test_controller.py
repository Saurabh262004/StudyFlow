import json
import time
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("PySide6")

from studyflow import NotFoundError, PlanSettings, Storage, StorageError, UserManager  # noqa: E402
from studyflow.ui.controller import (  # noqa: E402
    START_CHOOSE_USER,
    START_CREATE_FIRST_USER,
    START_READY,
    AppController,
    NoUserOpenError,
)

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def root(tmp_path):
    return tmp_path / "root"


@pytest.fixture
def ctrl(qapp, root):
    c = AppController(root, now=lambda: NOW)
    c.create_user("Saurabh")
    return c


@pytest.fixture
def photo(tmp_path):
    p = tmp_path / "board.png"
    p.write_bytes(b"\x89PNGfake")
    return p


class Rec:
    """Counts how often each signal fired."""

    def __init__(self, c):
        self.n = {}
        for name in ("usersChanged", "userChanged", "dataChanged", "settingsChanged", "warningsChanged"):
            self.n[name] = 0
            getattr(c, name).connect(lambda name=name: self.n.__setitem__(name, self.n[name] + 1))

    def __getitem__(self, name):
        return self.n[name]


# ================================================================== start-up and users
def test_first_start_asks_for_a_user(qapp, root):
    assert AppController(root).start().state == START_CREATE_FIRST_USER


def test_start_reopens_the_last_user(qapp, root):
    c = AppController(root)
    c.create_user("A")
    c.create_user("B")  # B is now the last user
    c2 = AppController(root)
    result = c2.start()
    assert result.state == START_READY and c2.current_user.name == "B" and c2.is_open


def test_start_asks_to_choose_when_the_last_user_is_gone(qapp, root):
    c = AppController(root)
    a = c.create_user("A")
    c.create_user("B")
    UserManager(root).delete_user(c.current_user.id)  # B vanishes behind the app's back
    result = AppController(root).start()
    assert result.state == START_CHOOSE_USER and result.error is None
    assert [u.id for u in UserManager(root).list_users()] == [a.id]


def test_start_reports_why_the_last_user_could_not_be_opened(qapp, root):
    c = AppController(root)
    u = c.create_user("A")
    (UserManager(root).users_dir / u.id / "data.json").write_text(json.dumps({"schemaVersion": 99}), "utf-8")
    result = AppController(root).start()
    assert result.state == START_CHOOSE_USER and "newer" in result.error


def test_create_user_opens_it_and_signals(qapp, root):
    c = AppController(root)
    rec = Rec(c)
    u = c.create_user("Saurabh")
    assert c.current_user.id == u.id and c.subjects() == []
    assert rec["usersChanged"] == 1 and rec["userChanged"] == 1
    with pytest.raises(ValueError):
        c.create_user("saurabh")  # duplicate name
    assert rec["usersChanged"] == 1


def test_create_user_without_opening(qapp, ctrl):
    rec = Rec(ctrl)
    me = ctrl.current_user
    ctrl.create_user("Guest", open_it=False)
    assert ctrl.current_user == me and rec["userChanged"] == 0 and rec["usersChanged"] == 1


def test_switching_users_keeps_data_and_settings_apart(qapp, ctrl):
    ctrl.add_subject("Maths")
    ctrl.set_settings(PlanSettings(hours_per_day=4))
    me = ctrl.current_user
    guest = ctrl.create_user("Guest")
    assert ctrl.subjects() == [] and ctrl.settings == PlanSettings()
    ctrl.add_subject("History")
    rec = Rec(ctrl)
    ctrl.open_user(me.id)
    assert [s.name for s in ctrl.subjects()] == ["Maths"] and ctrl.settings.hours_per_day == 4
    assert rec["userChanged"] == 1
    assert ctrl.manager.last_user().id == me.id
    ctrl.open_user(guest.id)
    assert [s.name for s in ctrl.subjects()] == ["History"]


def test_a_failed_switch_leaves_the_current_user_open_and_remembered(qapp, ctrl, root):
    me = ctrl.current_user
    ctrl.add_subject("Maths")
    other = ctrl.create_user("Other", open_it=False)
    (ctrl.manager.users_dir / other.id / "data.json").write_text(json.dumps({"schemaVersion": 99}), "utf-8")
    ctrl.open_user(me.id)
    rec = Rec(ctrl)
    with pytest.raises(StorageError):
        ctrl.open_user(other.id)
    assert ctrl.current_user.id == me.id and [s.name for s in ctrl.subjects()] == ["Maths"]
    assert ctrl.manager.last_user().id == me.id and rec["userChanged"] == 0


def test_open_unknown_user(qapp, ctrl):
    with pytest.raises(NotFoundError):
        ctrl.open_user("0" * 32)
    with pytest.raises(NotFoundError):
        ctrl.open_user("../x")


def test_rename_user(qapp, ctrl):
    rec = Rec(ctrl)
    ctrl.rename_user(ctrl.current_user.id, "Renamed")
    assert ctrl.current_user.name == "Renamed" and rec["usersChanged"] == 1
    assert ctrl.users()[0].name == "Renamed"


def test_deleting_the_open_user_closes_everything(qapp, ctrl):
    other = ctrl.create_user("B", open_it=False)
    rec = Rec(ctrl)
    ctrl.delete_user(ctrl.current_user.id)
    assert not ctrl.is_open and ctrl.current_user is None
    assert rec["userChanged"] == 1 and rec["usersChanged"] == 1
    with pytest.raises(NoUserOpenError):
        ctrl.add_subject("x")
    with pytest.raises(NoUserOpenError):
        ctrl.subjects()
    ctrl.open_user(other.id)  # and the app can carry on with someone else
    assert ctrl.is_open


def test_deleting_another_user_keeps_the_open_one(qapp, ctrl):
    other = ctrl.create_user("B", open_it=False)
    me = ctrl.current_user
    rec = Rec(ctrl)
    ctrl.delete_user(other.id)
    assert ctrl.current_user == me and rec["userChanged"] == 0 and rec["usersChanged"] == 1


def test_nothing_works_before_a_user_is_open(qapp, root):
    c = AppController(root)
    for call in (lambda: c.add_subject("x"), c.subjects, c.ranking, lambda: c.search("x"),
                 lambda: c.set_settings(PlanSettings()), lambda: c.export_backup("x")):
        with pytest.raises(NoUserOpenError):
            call()


# ================================================================== subjects and points
def test_subject_changes_are_saved_and_announced_once_each(qapp, ctrl, root):
    rec = Rec(ctrl)
    s = ctrl.add_subject("Maths", notes="n")
    ctrl.rename_subject(s.id, "Mathematics")
    ctrl.set_subject_notes(s.id, "new notes")
    assert rec["dataChanged"] == 3
    on_disk = AppController(root)
    on_disk.start()
    [again] = on_disk.subjects()
    assert (again.name, again.notes) == ("Mathematics", "new notes")
    ctrl.delete_subject(s.id)
    assert rec["dataChanged"] == 4 and ctrl.subjects() == []
    on_disk.open_user(on_disk.current_user.id)
    assert on_disk.subjects() == []


def test_bad_input_changes_nothing_and_sends_no_signal(qapp, ctrl):
    s = ctrl.add_subject("Maths")
    p = ctrl.add_point(s.id, "Algebra", effort_hours=2)
    rec = Rec(ctrl)
    with pytest.raises(ValueError):
        ctrl.add_subject("  ")
    with pytest.raises(ValueError):
        ctrl.rename_subject(s.id, "")
    with pytest.raises(ValueError):
        ctrl.add_point(s.id, "")
    with pytest.raises(ValueError):  # title is fine but effort is not: NOTHING may change
        ctrl.update_point(s.id, p.id, title="Changed", effort_hours=0)
    with pytest.raises(NotFoundError):
        ctrl.rename_subject("nope", "x")
    with pytest.raises(NotFoundError):
        ctrl.update_point(s.id, "nope", title="x")
    assert rec["dataChanged"] == 0
    assert ctrl.get_point(s.id, p.id).title == "Algebra" and ctrl.get_point(s.id, p.id).effort_hours == 2


def test_update_point_changes_only_what_is_passed(qapp, ctrl):
    s = ctrl.add_subject("Maths")
    deadline = NOW + timedelta(days=3)
    p = ctrl.add_point(s.id, "Algebra", notes="keep", deadline=deadline, effort_hours=2)
    ctrl.update_point(s.id, p.id, title="Algebra 2")
    q = ctrl.get_point(s.id, p.id)
    assert (q.title, q.notes, q.deadline, q.effort_hours, q.done) == ("Algebra 2", "keep", deadline, 2, False)
    ctrl.update_point(s.id, p.id, deadline=None, effort_hours=None, done=True)  # None CLEARS
    q = ctrl.get_point(s.id, p.id)
    assert (q.deadline, q.effort_hours, q.done, q.title) == (None, None, True, "Algebra 2")
    ctrl.update_point(s.id, p.id, deadline=datetime(2026, 12, 1, 9, 0), effort_hours=1.5)  # naive = local time
    assert ctrl.get_point(s.id, p.id).deadline.tzinfo is not None
    ctrl.set_point_done(s.id, p.id, False)
    assert ctrl.get_point(s.id, p.id).done is False


def test_points_persist_and_delete(qapp, ctrl, root):
    s = ctrl.add_subject("Maths")
    p = ctrl.add_point(s.id, "Algebra", deadline=NOW + timedelta(days=1), effort_hours=1)
    other = AppController(root)
    other.start()
    assert other.subjects()[0].points[0].title == "Algebra"
    rec = Rec(ctrl)
    ctrl.delete_point(s.id, p.id)
    assert rec["dataChanged"] == 1 and ctrl.get_subject(s.id).points == []


# ================================================================== images
def test_image_lifecycle(qapp, ctrl, photo):
    s1, s2 = ctrl.add_subject("A"), ctrl.add_subject("B")
    p = ctrl.add_point(s1.id, "Point")
    rec = Rec(ctrl)
    img = ctrl.import_image(photo, s1.id, p.id, tags=["Board"])
    ctrl.link_image(img.id, s2.id)
    assert rec["dataChanged"] == 2
    assert ctrl.images_of(s1.id, p.id) == ctrl.images_of(s2.id) == [img]
    assert len(ctrl.usage(img.id)) == 2 and ctrl.find_images(tag="BOARD") == [img]
    assert ctrl.image_path(img).exists()

    ctrl.set_image_tags(img.id, [" Unit3 ", "unit3", "Slides"])
    assert ctrl.find_images(tag="slides") == [img] and img.tags == ["slides", "unit3"]

    assert ctrl.unlink_image(img.id, s2.id) is False and ctrl.image_path(img).exists()
    assert ctrl.unlink_image(img.id, s1.id, p.id) is True and not ctrl.image_path(img).exists()
    assert ctrl.all_images() == []
    img2 = ctrl.import_image(photo, s1.id)
    ctrl.delete_image(img2.id)
    assert ctrl.all_images() == []


def test_bad_image_input(qapp, ctrl, photo, tmp_path):
    s = ctrl.add_subject("A")
    rec = Rec(ctrl)
    with pytest.raises(StorageError):
        ctrl.import_image(tmp_path / "missing.png", s.id)
    with pytest.raises(NotFoundError):
        ctrl.import_image(photo, "nope")
    assert rec["dataChanged"] == 0  # harmless errors must not make every screen refresh


# ================================================================== disk failure
def test_harmless_storage_errors_keep_the_same_database_object(qapp, ctrl, tmp_path):
    ctrl.add_subject("A")
    before = ctrl.db
    with pytest.raises(StorageError):
        ctrl.import_image(tmp_path / "missing.png", ctrl.subjects()[0].id)
    assert ctrl.db is before  # views holding references stay valid



def test_failed_save_puts_memory_back_in_line_with_disk(qapp, ctrl):
    s = ctrl.add_subject("Keep")
    rec = Rec(ctrl)
    real_save = ctrl.store.save
    ctrl.store.save = lambda db: (_ for _ in ()).throw(StorageError("disk full"))
    with pytest.raises(StorageError):
        ctrl.add_subject("Lost")
    assert [x.name for x in ctrl.subjects()] == ["Keep"]  # the unsaved "Lost" is not shown
    assert rec["dataChanged"] == 1  # the resync told the views
    ctrl.store.save = real_save
    ctrl.add_subject("Fine again")
    assert [x.name for x in ctrl.subjects()] == ["Keep", "Fine again"]


def test_failed_settings_save_keeps_old_settings(qapp, ctrl):
    ctrl.set_settings(PlanSettings(hours_per_day=3))
    rec = Rec(ctrl)

    def boom(_s):
        raise StorageError("nope")

    ctrl.store.save_settings = boom
    with pytest.raises(StorageError):
        ctrl.set_settings(PlanSettings(hours_per_day=9))
    assert ctrl.settings.hours_per_day == 3 and rec["settingsChanged"] == 0


# ================================================================== priority, settings, search
def test_ranking_uses_the_fixed_clock_and_the_users_settings(qapp, ctrl):
    s = ctrl.add_subject("S")
    ctrl.add_point(s.id, "big", deadline=NOW + timedelta(days=3), effort_hours=6)
    ctrl.add_point(s.id, "small", deadline=NOW + timedelta(days=2), effort_hours=1)
    assert [r.point.title for r in ctrl.ranking()] == ["big", "small"]  # at 2 h/day big must start now
    assert ctrl.next_up().point.title == "big" and ctrl.next_up(subject_id=s.id).point.title == "big"
    rec = Rec(ctrl)
    ctrl.set_settings(PlanSettings(hours_per_day=24))
    assert rec["settingsChanged"] == 1
    assert [r.point.title for r in ctrl.ranking()] == ["small", "big"]  # with 24 h/day, small has to start first
    assert ctrl.ranking(include_done=True) and ctrl.ranking(subject_id=s.id)
    ctrl.set_point_done(s.id, ctrl.subjects()[0].points[0].id, True)
    assert [r.point.title for r in ctrl.ranking()] == ["small"]


def test_settings_survive_a_restart(qapp, ctrl, root):
    ctrl.set_settings(PlanSettings(hours_per_day=5, default_effort_hours=2, soon_days=1))
    again = AppController(root)
    again.start()
    assert again.settings == PlanSettings(5, 2, 1)


def test_search_passthrough(qapp, ctrl):
    s = ctrl.add_subject("Operating Systems")
    ctrl.add_point(s.id, "Deadlocks")
    assert [h.kind for h in ctrl.search("deadlocks")] == ["point"]
    assert ctrl.search("deadlocks", subject_id=s.id, limit=1)


# ================================================================== backup, warnings, clock
def test_backup_and_restore(qapp, ctrl, tmp_path, photo):
    s = ctrl.add_subject("Keep me")
    ctrl.import_image(photo, s.id)
    ctrl.set_settings(PlanSettings(hours_per_day=4))
    archive = ctrl.export_backup(tmp_path / "bk")
    assert archive.suffix == ".zip"
    ctrl.delete_subject(s.id)
    ctrl.set_settings(PlanSettings(hours_per_day=1))
    rec = Rec(ctrl)
    ctrl.restore_backup(archive)
    assert [x.name for x in ctrl.subjects()] == ["Keep me"] and len(ctrl.all_images()) == 1
    assert ctrl.settings.hours_per_day == 4
    assert rec["dataChanged"] == 1 and rec["settingsChanged"] == 1


def test_bad_restore_changes_nothing(qapp, ctrl, tmp_path):
    ctrl.add_subject("Stay")
    junk = tmp_path / "junk.zip"
    junk.write_text("not a zip")
    with pytest.raises(StorageError):
        ctrl.restore_backup(junk)
    assert [x.name for x in ctrl.subjects()] == ["Stay"]


def test_load_warnings_reach_the_ui_and_can_be_dismissed(qapp, root):
    c = AppController(root)
    u = c.create_user("A")
    c.add_subject("one")
    c.add_subject("two")  # now a backup of the 1-subject state exists
    (c.manager.users_dir / u.id / "data.json").write_text("{ broken", "utf-8")
    c2 = AppController(root)
    rec = Rec(c2)
    assert c2.start().state == START_READY
    assert any("damaged" in w for w in c2.warnings) and rec["warningsChanged"] == 1
    assert [s.name for s in c2.subjects()] == ["one"]
    c2.dismiss_warnings()
    assert c2.warnings == [] and rec["warningsChanged"] == 2


def test_switching_user_replaces_warnings(qapp, root):
    c = AppController(root)
    a = c.create_user("A")
    c.add_subject("x")
    c.add_subject("y")
    (c.manager.users_dir / a.id / "data.json").write_text("{ broken", "utf-8")
    b = c.create_user("B")  # opens B, which is clean
    assert c.warnings == []
    c.open_user(a.id)
    assert c.warnings
    c.open_user(b.id)
    assert c.warnings == []


def test_clock_ticks(qapp, ctrl):
    ticks = []
    ctrl.tick.connect(lambda: ticks.append(1))
    ctrl.start_clock(interval_ms=10)
    end = time.time() + 3
    while not ticks and time.time() < end:
        qapp.processEvents()
        time.sleep(0.005)
    ctrl.stop_clock()
    assert ticks
    count = len(ticks)
    for _ in range(20):
        qapp.processEvents()
        time.sleep(0.005)
    assert len(ticks) == count  # stopped


def test_controller_never_changes_data_by_reading(qapp, ctrl):
    s = ctrl.add_subject("S")
    ctrl.add_point(s.id, "P", deadline=NOW + timedelta(days=1), effort_hours=1)
    before = ctrl.db.to_dict()
    rec = Rec(ctrl)
    ctrl.ranking(), ctrl.next_up(), ctrl.search("p"), ctrl.subjects(), ctrl.all_images()
    assert ctrl.db.to_dict() == before and rec["dataChanged"] == 0


def test_user_name_validation_messages_are_ready_for_the_screen(qapp, ctrl):
    assert ctrl.validate_user_name("Fresh") is None
    assert ctrl.validate_user_name("") == "User name cannot be empty"
    assert ctrl.validate_user_name("saurabh") == "A user named 'Saurabh' already exists"
    assert ctrl.validate_user_name("x" * 51).startswith("User name cannot be longer")
    assert ctrl.validate_user_name("Saurabh", ignore_id=ctrl.current_user.id) is None  # keeping your own name is fine


def test_backup_of_a_user_who_is_not_open(qapp, ctrl, tmp_path):
    ctrl.add_subject("Mine")
    other = ctrl.create_user("Other")  # opens Other, who has no data file yet
    with pytest.raises(StorageError):
        ctrl.export_user_backup(other.id, tmp_path / "none")
    first = next(u for u in ctrl.users() if u.name == "Saurabh")
    archive = ctrl.export_user_backup(first.id, tmp_path / "mine")
    assert archive.exists() and ctrl.current_user.id == other.id  # the open user did not change
