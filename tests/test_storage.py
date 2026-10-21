import json
import zipfile
from datetime import datetime, timedelta, timezone

import pytest

from studyflow import Database, NotFoundError, Storage, StorageError


@pytest.fixture
def store(tmp_path):
    return Storage(tmp_path / "data")


@pytest.fixture
def photo(tmp_path):
    p = tmp_path / "board.jpg"
    p.write_bytes(b"\xff\xd8fake-jpeg")
    return p


def sample_db():
    db = Database()
    s = db.add_subject("Operating Systems", notes="Unit 3 is important")
    db.add_point(s.id, "Deadlocks", deadline=datetime.now(timezone.utc) + timedelta(days=3), effort_hours=2.5)
    return db, s


# ---------------------------------------------------------------- round trip
def test_first_run_is_empty(store):
    assert store.load().subjects == []
    assert store.warnings == []


def test_round_trip(store):
    db, s = sample_db()
    store.save(db)
    loaded = store.load()
    assert loaded.to_dict() == db.to_dict()
    p = loaded.subjects[0].points[0]
    assert p.effort_hours == 2.5 and p.deadline.tzinfo is not None


def test_unicode_notes_survive(store):
    db = Database()
    db.add_subject("गणित", notes="Ünïcode ✓")
    store.save(db)
    assert store.load().subjects[0].notes == "Ünïcode ✓"


def test_second_save_creates_backup(store):
    db, _ = sample_db()
    store.save(db)
    assert not store.backup_file.exists()
    db.add_subject("DBMS")
    store.save(db)
    assert store.backup_file.exists()
    assert len(json.loads(store.backup_file.read_text("utf-8"))["subjects"]) == 1


def test_no_temp_files_left_behind(store):
    db, _ = sample_db()
    store.save(db)
    store.save(db)
    assert not list(store.data_dir.glob("*.tmp"))


# ---------------------------------------------------------------- validation
def test_validation(store):
    db, s = sample_db()
    with pytest.raises(ValueError):
        db.add_subject("   ")
    with pytest.raises(ValueError):
        db.add_point(s.id, "x", effort_hours=0)
    with pytest.raises(NotFoundError):
        db.add_point("nope", "x")


# ---------------------------------------------------------------- corruption
def test_corrupt_file_is_restored_from_backup_and_kept(store):
    db, _ = sample_db()
    store.save(db)
    db.add_subject("DBMS")
    store.save(db)  # now .bak holds the 1-subject version
    store.data_file.write_text("{ this is not json", "utf-8")
    loaded = store.load()
    assert len(loaded.subjects) == 1
    assert len(store.warnings) == 2
    kept = list(store.data_dir.glob("data.corrupt-*.json"))
    assert len(kept) == 1 and kept[0].read_text("utf-8") == "{ this is not json"
    assert len(Storage(store.data_dir).load().subjects) == 1  # data.json is valid again


def test_corrupt_without_backup_is_not_overwritten(store):
    store.data_file.write_text("garbage", "utf-8")
    assert store.load().subjects == []
    assert any("empty" in w for w in store.warnings)
    assert list(store.data_dir.glob("data.corrupt-*.json"))[0].read_text() == "garbage"


def test_wrong_shape_counts_as_corrupt(store):
    store.data_file.write_text(json.dumps({"subjects": [{"name": "no id"}]}), "utf-8")
    store.load()
    assert list(store.data_dir.glob("data.corrupt-*.json"))


def test_newer_schema_is_refused_and_left_alone(store):
    store.data_file.write_text(json.dumps({"schemaVersion": 99, "subjects": []}), "utf-8")
    with pytest.raises(StorageError):
        store.load()
    assert store.data_file.exists() and not list(store.data_dir.glob("data.corrupt-*"))


def test_missing_data_file_restores_backup(store):
    db, _ = sample_db()
    store.save(db)
    store.save(db)
    store.data_file.unlink()
    assert len(store.load().subjects) == 1
    assert store.warnings


# ---------------------------------------------------------------- images
def test_attach_and_find_images(store, photo):
    db, s = sample_db()
    point = s.points[0]
    rec = store.attach_image(db, photo, s.id, point.id, tags=[" Blackboard ", "unit3", "blackboard"])
    assert rec.tags == ["blackboard", "unit3"]
    assert store.image_path(rec).read_bytes() == photo.read_bytes()
    assert db.find_images(tag="BLACKBOARD") == [rec]
    assert db.find_images(point_id=point.id) == [rec]
    assert store.load().images[0].id == rec.id


def test_attach_rejects_bad_input(store, photo, tmp_path):
    db, s = sample_db()
    txt = tmp_path / "notes.txt"
    txt.write_text("hi")
    with pytest.raises(StorageError):
        store.attach_image(db, txt, s.id)
    with pytest.raises(StorageError):
        store.attach_image(db, tmp_path / "missing.png", s.id)
    with pytest.raises(NotFoundError):
        store.attach_image(db, photo, "bad-id")
    assert db.images == []


def test_failed_save_rolls_back_attach(store, photo, monkeypatch):
    db, s = sample_db()

    def boom(_db):
        raise StorageError("disk full")

    monkeypatch.setattr(store, "save", boom)
    with pytest.raises(StorageError):
        store.attach_image(db, photo, s.id)
    assert db.images == []
    assert not list(store.images_dir.glob("*"))


def test_delete_point_and_subject_remove_image_files(store, photo):
    db, s = sample_db()
    p = s.points[0]
    r1 = store.attach_image(db, photo, s.id, p.id)
    r2 = store.attach_image(db, photo, s.id)
    store.delete_point(db, s.id, p.id)
    assert not store.image_path(r1).exists() and store.image_path(r2).exists()
    store.delete_subject(db, s.id)
    assert not store.image_path(r2).exists()
    assert db.subjects == [] and db.images == []
    assert store.load().subjects == []


def test_delete_single_image(store, photo):
    db, s = sample_db()
    rec = store.attach_image(db, photo, s.id)
    store.delete_image(db, rec.id)
    assert not store.image_path(rec).exists() and db.images == []


def test_image_path_cannot_escape_data_dir(store):
    from studyflow import ImageRecord

    evil = ImageRecord(file="../../etc/passwd")
    with pytest.raises(StorageError):
        store.image_path(evil)


# ---------------------------------------------------------------- backup / restore
def test_backup_and_restore_round_trip(store, photo, tmp_path):
    db, s = sample_db()
    rec = store.attach_image(db, photo, s.id, tags=["x"])
    zip_path = store.export_backup(tmp_path / "mybackup")
    assert zip_path.suffix == ".zip"

    store.delete_subject(db, s.id)  # lose everything
    restored = store.restore_backup(zip_path)
    assert restored.subjects[0].name == "Operating Systems"
    assert store.image_path(rec).read_bytes() == photo.read_bytes()
    assert list(store.data_dir.glob("pre-restore-*.zip"))  # safety snapshot of the pre-restore state
    assert store.load().to_dict() == restored.to_dict()


def test_restore_rejects_bad_archives(store, tmp_path):
    db, _ = sample_db()
    store.save(db)

    not_zip = tmp_path / "x.zip"
    not_zip.write_text("nope")
    with pytest.raises(StorageError):
        store.restore_backup(not_zip)

    no_data = tmp_path / "nodata.zip"
    with zipfile.ZipFile(no_data, "w") as z:
        z.writestr("hello.txt", "hi")
    with pytest.raises(StorageError):
        store.restore_backup(no_data)

    slip = tmp_path / "slip.zip"
    with zipfile.ZipFile(slip, "w") as z:
        z.writestr("data.json", json.dumps({"subjects": []}))
        z.writestr("images/../../evil.txt", "x")
    with pytest.raises(StorageError):
        store.restore_backup(slip)

    bad_json = tmp_path / "badjson.zip"
    with zipfile.ZipFile(bad_json, "w") as z:
        z.writestr("data.json", "{oops")
    with pytest.raises(StorageError):
        store.restore_backup(bad_json)

    assert len(store.load().subjects) == 1  # current data untouched by all the failed restores


# ---------------------------------------------------------------- JSON Schema checks
def test_app_written_files_match_the_schema(store, photo):
    from studyflow.storage import schema_errors

    db, s = sample_db()
    store.attach_image(db, photo, s.id, s.points[0].id, tags=["a"])
    store.save(db)
    assert schema_errors(json.loads(store.data_file.read_text("utf-8"))) == []


def test_extra_field_on_disk_counts_as_corrupt(store):
    db, _ = sample_db()
    store.save(db)
    store.save(db)
    data = json.loads(store.data_file.read_text("utf-8"))
    data["subjects"][0]["surprise"] = 1
    store.data_file.write_text(json.dumps(data), "utf-8")
    assert len(store.load().subjects) == 1  # restored from the .bak
    assert list(store.data_dir.glob("data.corrupt-*.json"))


def test_bad_value_on_disk_is_caught(store):
    db, _ = sample_db()
    store.save(db)
    data = json.loads(store.data_file.read_text("utf-8"))
    data["subjects"][0]["points"][0]["effortHours"] = 0
    store.data_file.write_text(json.dumps(data), "utf-8")
    store.load()
    assert any("damaged" in w for w in store.warnings)


def test_save_refuses_invalid_data_and_keeps_old_file(store):
    db, s = sample_db()
    store.save(db)
    before = store.data_file.read_bytes()
    s.points[0].effort_hours = -3  # bypasses the model's own check on purpose
    with pytest.raises(StorageError) as exc:
        store.save(db)
    assert "effortHours" in str(exc.value) and "minimum" in str(exc.value)  # readable, not "not valid under any schema"
    assert store.data_file.read_bytes() == before
    assert not list(store.data_dir.glob("*.tmp"))


def test_schema_error_messages_name_the_location():
    from studyflow.storage import schema_errors

    msgs = schema_errors({"schemaVersion": 1, "subjects": [{"id": "x"}], "images": []})
    assert any(m.startswith("subjects[0]") for m in msgs)


def test_nullable_fields_accept_null_but_still_check_values():
    from studyflow.storage import schema_errors

    point = {"id": "a" * 32, "title": "t", "notes": "", "done": False, "deadline": None,
             "effortHours": None, "imageIds": [], "createdAt": "2026-10-17T00:00:00+00:00"}

    def errs(**changes):
        data = {"schemaVersion": 2, "images": [],
                "subjects": [{"id": "b" * 32, "name": "s", "notes": "", "createdAt": point["createdAt"],
                              "imageIds": [], "points": [dict(point, **changes)]}]}
        return schema_errors(data)

    assert errs() == []
    assert any("minimum" in m for m in errs(effortHours=0))
    assert any("does not match" in m for m in errs(deadline="tomorrow"))
    assert errs(deadline="2026-11-02T18:30:00+00:00", effortHours=1.5) == []
