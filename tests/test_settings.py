import json
import zipfile

import pytest

from studyflow import PlanSettings, Storage, UserManager
from studyflow.settings import settings_errors, settings_from_dict, settings_to_dict


@pytest.fixture
def store(tmp_path):
    return Storage(tmp_path / "data")


def test_defaults_when_nothing_is_saved(store):
    assert store.load_settings() == PlanSettings()
    assert store.warnings == [] and not store.settings_file.exists()


def test_round_trip_and_file_content(store):
    wanted = PlanSettings(hours_per_day=3.5, default_effort_hours=0.5, soon_days=4)
    store.save_settings(wanted)
    assert store.load_settings() == wanted
    saved = json.loads(store.settings_file.read_text("utf-8"))
    assert saved == {"schemaVersion": 1, "hoursPerDay": 3.5, "defaultEffortHours": 0.5, "soonDays": 4}
    assert settings_errors(saved) == []
    assert not list(store.data_dir.glob("*.tmp"))


def test_whole_numbers_are_fine(store):
    store.settings_file.write_text('{"schemaVersion":1,"hoursPerDay":2,"defaultEffortHours":1,"soonDays":0}')
    assert store.load_settings() == PlanSettings(2, 1, 0) and store.warnings == []


@pytest.mark.parametrize(
    "content",
    [
        "{ not json",
        "[]",
        '{"schemaVersion":1,"hoursPerDay":0,"defaultEffortHours":1,"soonDays":2}',      # out of range
        '{"schemaVersion":1,"hoursPerDay":25,"defaultEffortHours":1,"soonDays":2}',
        '{"schemaVersion":1,"hoursPerDay":2,"defaultEffortHours":-1,"soonDays":2}',
        '{"schemaVersion":1,"hoursPerDay":2,"defaultEffortHours":1,"soonDays":-1}',
        '{"schemaVersion":1,"hoursPerDay":"2","defaultEffortHours":1,"soonDays":2}',    # wrong type
        '{"schemaVersion":1,"hoursPerDay":true,"defaultEffortHours":1,"soonDays":2}',
        '{"schemaVersion":1,"hoursPerDay":2,"defaultEffortHours":1}',                   # missing key
        '{"schemaVersion":1,"hoursPerDay":2,"defaultEffortHours":1,"soonDays":2,"x":1}',  # unknown key
        '{"schemaVersion":2,"hoursPerDay":2,"defaultEffortHours":1,"soonDays":2}',      # newer file
    ],
)
def test_damaged_settings_fall_back_to_defaults_and_are_kept(store, content):
    store.settings_file.write_text(content, "utf-8")
    assert store.load_settings() == PlanSettings()
    assert any("damaged" in w for w in store.warnings)
    [kept] = store.data_dir.glob("settings.corrupt-*.json")
    assert kept.read_text("utf-8") == content and not store.settings_file.exists()


def test_unreadable_settings_file_warns_without_destroying_anything(store):
    store.settings_file.mkdir()  # a directory where the file should be -> OSError when reading
    assert store.load_settings() == PlanSettings()
    assert any("Could not read" in w for w in store.warnings) and store.settings_file.is_dir()


def test_load_settings_keeps_warnings_from_load(store):
    store.data_file.write_text("garbage", "utf-8")
    store.settings_file.write_text("{ nope", "utf-8")
    store.load()
    store.load_settings()
    assert len(store.warnings) >= 2  # the data warning and the settings warning


def test_each_user_has_their_own_settings(tmp_path):
    mgr = UserManager(tmp_path / "root")
    a, b = mgr.create_user("A"), mgr.create_user("B")
    mgr.open_user(a.id).save_settings(PlanSettings(hours_per_day=4))
    assert mgr.open_user(a.id).load_settings().hours_per_day == 4
    assert mgr.open_user(b.id).load_settings() == PlanSettings()


# ---------------------------------------------------------------- backups carry the settings
def test_backup_includes_and_restores_settings(store, tmp_path):
    db = store.load()
    db.add_subject("S")
    store.save(db)
    store.save_settings(PlanSettings(hours_per_day=5))
    archive = store.export_backup(tmp_path / "b")
    assert "settings.json" in zipfile.ZipFile(archive).namelist()
    store.save_settings(PlanSettings(hours_per_day=1))
    store.restore_backup(archive)
    assert store.load_settings().hours_per_day == 5
    assert list(store.data_dir.glob("pre-restore-*.zip"))  # the snapshot of the old state has the old settings too


def test_restoring_an_old_backup_without_settings_keeps_current_settings(store, tmp_path):
    db = store.load()
    store.save(db)
    archive = store.export_backup(tmp_path / "old")  # no settings saved yet -> none in the zip
    assert "settings.json" not in zipfile.ZipFile(archive).namelist()
    store.save_settings(PlanSettings(hours_per_day=6))
    store.restore_backup(archive)
    assert store.load_settings().hours_per_day == 6


def test_a_bad_settings_file_inside_a_backup_does_not_block_the_restore(store, tmp_path):
    db = store.load()
    db.add_subject("Keep me")
    store.save(db)
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.write(store.data_file, "data.json")
        z.writestr("settings.json", '{"hoursPerDay": 999}')
    store.save_settings(PlanSettings(hours_per_day=2.5))
    restored = store.restore_backup(archive)
    assert [s.name for s in restored.subjects] == ["Keep me"]
    assert store.load_settings().hours_per_day == 2.5


# ---------------------------------------------------------------- schema and PlanSettings must agree
@pytest.mark.parametrize("field, value", [
    ("hoursPerDay", 0), ("hoursPerDay", 0.01), ("hoursPerDay", 24), ("hoursPerDay", 24.01), ("hoursPerDay", -1),
    ("defaultEffortHours", 0), ("defaultEffortHours", 0.01), ("defaultEffortHours", -2),
    ("soonDays", 0), ("soonDays", -0.01), ("soonDays", 30),
])
def test_schema_and_planner_accept_exactly_the_same_values(field, value):
    raw = settings_to_dict(PlanSettings())
    raw[field] = value
    schema_ok = settings_errors(raw) == []
    try:
        settings_from_dict(raw)
        engine_ok = True
    except ValueError:
        engine_ok = False
    assert schema_ok == engine_ok
    try:  # and the planner itself agrees
        PlanSettings(hours_per_day=raw["hoursPerDay"], default_effort_hours=raw["defaultEffortHours"], soon_days=raw["soonDays"])
        planner_ok = True
    except ValueError:
        planner_ok = False
    assert planner_ok == schema_ok
