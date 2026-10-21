import json
import zipfile

import pytest

from studyflow import Database, NotFoundError, Storage, StorageError
from studyflow.storage import schema_errors


@pytest.fixture
def store(tmp_path):
    return Storage(tmp_path / "data")


@pytest.fixture
def photo(tmp_path):
    p = tmp_path / "board.png"
    p.write_bytes(b"\x89PNGfake")
    return p


@pytest.fixture
def world(store, photo):
    """Two subjects; OS has two points. One picture imported on point `dead`."""
    db = Database()
    os_ = db.add_subject("OS")
    dbms = db.add_subject("DBMS")
    dead = db.add_point(os_.id, "Deadlocks")
    paging = db.add_point(os_.id, "Paging")
    img = store.attach_image(db, photo, os_.id, dead.id, tags=["board"])
    return db, os_, dbms, dead, paging, img


# ---------------------------------------------------------------- one image, many places
def test_one_image_can_be_shown_on_many_points_and_subjects(store, world):
    db, os_, dbms, dead, paging, img = world
    store.link_image(db, img.id, os_.id, paging.id)
    store.link_image(db, img.id, dbms.id)  # a different subject
    store.link_image(db, img.id, os_.id)  # the subject itself
    assert len(db.images) == 1  # still one picture, one file
    assert db.images_of(os_.id, dead.id) == db.images_of(os_.id, paging.id) == [img]
    assert sorted(db.usage(img.id), key=str) == sorted(
        [(os_.id, dead.id), (os_.id, paging.id), (dbms.id, None), (os_.id, None)], key=str
    )
    assert len(list(store.images_dir.iterdir())) == 1
    again = store.load()
    assert again.images_of(os_.id, paging.id)[0].id == img.id


def test_linking_twice_does_not_duplicate(store, world):
    db, os_, _, dead, _, img = world
    store.link_image(db, img.id, os_.id, dead.id)
    assert db.get_point(os_.id, dead.id).image_ids == [img.id]


def test_link_errors(store, world):
    db, os_, _, dead, _, img = world
    with pytest.raises(NotFoundError):
        store.link_image(db, "0" * 32, os_.id)
    with pytest.raises(NotFoundError):
        store.link_image(db, img.id, "nope")
    with pytest.raises(NotFoundError):
        store.link_image(db, img.id, os_.id, "nope")


def test_images_keep_the_order_they_were_added(store, world, photo):
    db, os_, _, dead, _, first = world
    second = store.attach_image(db, photo, os_.id, dead.id)
    assert [i.id for i in db.images_of(os_.id, dead.id)] == [first.id, second.id]


# ---------------------------------------------------------------- removing uses
def test_unlink_keeps_the_picture_while_something_else_uses_it(store, world):
    db, os_, _, dead, paging, img = world
    store.link_image(db, img.id, os_.id, paging.id)
    assert store.unlink_image(db, img.id, os_.id, dead.id) is False
    assert store.image_path(img).exists() and db.images_of(os_.id, paging.id) == [img]


def test_unlinking_the_last_use_deletes_the_picture(store, world):
    db, os_, _, dead, _, img = world
    assert store.unlink_image(db, img.id, os_.id, dead.id) is True
    assert db.images == [] and not store.image_path(img).exists()
    assert store.load().images == []
    with pytest.raises(NotFoundError):
        store.unlink_image(db, img.id, os_.id, dead.id)


def test_unlink_where_it_is_not_linked_is_an_error(store, world):
    db, os_, dbms, _, _, img = world
    with pytest.raises(NotFoundError):
        store.unlink_image(db, img.id, dbms.id)


def test_deleting_a_point_keeps_pictures_used_elsewhere(store, world):
    db, os_, dbms, dead, paging, img = world
    store.link_image(db, img.id, dbms.id)
    store.delete_point(db, os_.id, dead.id)
    assert db.images == [img] and store.image_path(img).exists()
    store.delete_subject(db, dbms.id)  # last user goes away
    assert db.images == [] and not store.image_path(img).exists()


def test_deleting_a_subject_removes_pictures_only_it_used(store, world, photo):
    db, os_, dbms, dead, paging, img = world
    own = store.attach_image(db, photo, os_.id)  # subject-level, unshared
    store.link_image(db, img.id, dbms.id)  # shared with the other subject
    store.delete_subject(db, os_.id)
    assert [i.id for i in db.images] == [img.id]
    assert store.image_path(img).exists() and not store.image_path(own).exists()


def test_delete_image_removes_every_use(store, world):
    db, os_, dbms, dead, paging, img = world
    store.link_image(db, img.id, os_.id, paging.id)
    store.link_image(db, img.id, dbms.id)
    store.delete_image(db, img.id)
    assert db.images == [] and not store.image_path(img).exists()
    assert db.get_point(os_.id, dead.id).image_ids == [] and db.get_subject(dbms.id).image_ids == []
    assert db.integrity_problems() == []


def test_failed_save_rolls_back_an_import(store, world, photo, monkeypatch):
    db, os_, _, dead, _, img = world

    def boom(_db):
        raise StorageError("disk full")

    monkeypatch.setattr(store, "save", boom)
    with pytest.raises(StorageError):
        store.attach_image(db, photo, os_.id, dead.id)
    assert db.images == [img] and db.get_point(os_.id, dead.id).image_ids == [img.id]
    assert len(list(store.images_dir.iterdir())) == 1


# ---------------------------------------------------------------- search
def test_find_images(store, world, photo):
    db, os_, dbms, dead, paging, img = world
    other = store.attach_image(db, photo, os_.id, tags=["Slides"])  # subject-level
    store.link_image(db, other.id, dbms.id)
    assert db.find_images(point_id=dead.id) == [img]
    assert db.find_images(subject_id=os_.id) == [img, other]  # subject itself + its points
    assert db.find_images(subject_id=dbms.id) == [other]
    assert db.find_images(tag="BOARD") == [img] and db.find_images(tag="slides") == [other]
    assert db.find_images(subject_id=os_.id, tag="slides") == [other]
    assert db.find_images(point_id=paging.id) == []


# ---------------------------------------------------------------- consistency
def test_save_refuses_a_dangling_image_reference(store, world):
    db, os_, *_ = world
    db.get_subject(os_.id).image_ids.append("f" * 32)
    before = store.data_file.read_bytes()
    with pytest.raises(StorageError) as exc:
        store.save(db)
    assert "missing image" in str(exc.value) and store.data_file.read_bytes() == before


def test_dangling_reference_on_disk_counts_as_corrupt(store, world):
    db, os_, *_ = world
    store.save(db)
    data = json.loads(store.data_file.read_text("utf-8"))
    data["subjects"][0]["imageIds"].append("f" * 32)
    store.data_file.write_text(json.dumps(data), "utf-8")
    store.load()
    assert any("damaged" in w for w in store.warnings)
    assert list(store.data_dir.glob("data.corrupt-*.json"))


def test_duplicate_image_ids_are_reported(world):
    db, *_ , img = world
    db.images.append(img)
    assert any("twice" in p for p in db.integrity_problems())


def test_saved_files_match_schema_v2(store, world):
    db, os_, dbms, _, paging, img = world
    store.link_image(db, img.id, dbms.id)
    data = json.loads(store.data_file.read_text("utf-8"))
    assert data["schemaVersion"] == 2 and schema_errors(data) == []
    assert "subjectId" not in data["images"][0] and "pointId" not in data["images"][0]


# ---------------------------------------------------------------- migration from schema 1
SUBJ, OTHER, P1, P2 = "a" * 32, "b" * 32, "c" * 32, "d" * 32
I1, I2, I3, I4 = "1" * 32, "2" * 32, "3" * 32, "4" * 32
STAMP = "2026-10-01T10:00:00+00:00"


def v1_document():
    """Exactly the shape the previous version of the app wrote."""
    def image(image_id, subject_id, point_id):
        return {"id": image_id, "file": f"images/{image_id}.png", "originalName": "x.png",
                "subjectId": subject_id, "pointId": point_id, "tags": ["board"], "addedAt": STAMP}
    return {
        "schemaVersion": 1,
        "subjects": [
            {"id": SUBJ, "name": "OS", "notes": "n", "createdAt": STAMP, "points": [
                {"id": P1, "title": "Deadlocks", "notes": "", "done": False, "deadline": None,
                 "effortHours": 2.0, "createdAt": STAMP},
                {"id": P2, "title": "Paging", "notes": "", "done": True, "deadline": None,
                 "effortHours": None, "createdAt": STAMP}]},
            {"id": OTHER, "name": "DBMS", "notes": "", "createdAt": STAMP, "points": []},
        ],
        "images": [image(I1, SUBJ, P1), image(I2, SUBJ, None), image(I3, OTHER, None),
                   image(I4, SUBJ, "9" * 32)],  # I4's point no longer exists -> falls back to its subject
    }


def test_v1_file_is_migrated_on_load(store):
    store.data_file.write_text(json.dumps(v1_document()), "utf-8")
    db = store.load()
    assert db.schema_version == 2
    assert db.get_point(SUBJ, P1).image_ids == [I1]
    assert db.get_subject(SUBJ).image_ids == [I2, I4]
    assert db.get_subject(OTHER).image_ids == [I3]
    assert db.get_point(SUBJ, P2).image_ids == []
    assert len(db.images) == 4 and db.integrity_problems() == []
    assert not hasattr(db.images[0], "subject_id")
    assert db.get_point(SUBJ, P2).done and db.get_point(SUBJ, P1).effort_hours == 2.0  # nothing else changed


def test_migration_keeps_a_copy_of_the_old_file_and_saves_as_v2(store):
    original = json.dumps(v1_document())
    store.data_file.write_text(original, "utf-8")
    db = store.load()
    kept = store.data_dir / "data.pre-v1.json"
    assert kept.read_text("utf-8") == original and any("upgraded" in w for w in store.warnings)
    assert json.loads(store.data_file.read_text("utf-8"))["schemaVersion"] == 1  # untouched until a save
    store.save(db)
    saved = json.loads(store.data_file.read_text("utf-8"))
    assert saved["schemaVersion"] == 2 and schema_errors(saved) == []
    again = Storage(store.data_dir)
    again.load()
    assert again.warnings == [] and kept.read_text("utf-8") == original  # no second copy, no new warning


def test_v1_data_is_not_mistaken_for_corruption(store):
    store.data_file.write_text(json.dumps(v1_document()), "utf-8")
    store.load()
    assert not list(store.data_dir.glob("data.corrupt-*"))
    assert schema_errors(v1_document())  # the v2 schema itself rejects the old shape; migration handles it


def test_v1_image_whose_subject_is_gone_is_kept_but_unused(store):
    doc = v1_document()
    doc["images"].append({"id": "5" * 32, "file": f"images/{'5' * 32}.png", "originalName": "x.png",
                          "subjectId": "e" * 32, "pointId": None, "tags": [], "addedAt": STAMP})
    store.data_file.write_text(json.dumps(doc), "utf-8")
    db = store.load()
    assert db.get_image("5" * 32) and db.usage("5" * 32) == []
    assert not list(store.data_dir.glob("data.corrupt-*"))


def test_broken_v1_file_is_corrupt_not_a_crash(store):
    doc = v1_document()
    del doc["subjects"][0]["id"]
    store.data_file.write_text(json.dumps(doc), "utf-8")
    assert store.load().subjects == []
    assert list(store.data_dir.glob("data.corrupt-*"))


def test_restoring_a_v1_backup_zip_migrates_it(store, tmp_path):
    archive = tmp_path / "old.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("data.json", json.dumps(v1_document()))
        z.writestr(f"images/{I1}.png", b"\x89PNGold")
    db = store.restore_backup(archive)
    assert db.get_point(SUBJ, P1).image_ids == [I1]
    assert (store.images_dir / f"{I1}.png").read_bytes() == b"\x89PNGold"
    assert json.loads(store.data_file.read_text("utf-8"))["schemaVersion"] == 2
