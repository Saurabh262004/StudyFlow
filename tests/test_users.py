import json

import pytest

from studyflow import NotFoundError, StorageError, UserManager


@pytest.fixture
def mgr(tmp_path):
    return UserManager(tmp_path / "root")


@pytest.fixture
def photo(tmp_path):
    p = tmp_path / "board.png"
    p.write_bytes(b"\x89PNGfake")
    return p


def test_starts_empty(mgr):
    assert mgr.list_users() == []
    assert mgr.last_user() is None


def test_create_and_list_sorted(mgr):
    mgr.create_user("zara")
    mgr.create_user("Amit")
    mgr.create_user("बीना")
    names = [u.name for u in mgr.list_users()]
    assert names == sorted(names, key=str.casefold)
    assert set(names) == {"zara", "Amit", "बीना"}


def test_folder_is_an_id_not_the_name(mgr):
    u = mgr.create_user("Saurabh / test")
    assert (mgr.users_dir / u.id).is_dir()
    assert [p.name for p in mgr.users_dir.iterdir()] == [u.id]


def test_name_validation(mgr):
    mgr.create_user("Saurabh")
    for bad in ["", "   ", "x" * 51, "two\nlines"]:
        with pytest.raises(ValueError):
            mgr.create_user(bad)
    with pytest.raises(ValueError):
        mgr.create_user("  saurabh ")  # same name, different case/spaces


def test_users_data_is_separate(mgr, photo):
    a, b = mgr.create_user("A"), mgr.create_user("B")

    sa = mgr.open_user(a.id)
    dba = sa.load()
    subj = dba.add_subject("Maths")
    sa.attach_image(dba, photo, subj.id)

    sb = mgr.open_user(b.id)
    dbb = sb.load()
    assert dbb.subjects == [] and dbb.images == []
    dbb.add_subject("History")
    sb.save(dbb)

    # switch back: A still has only A's data
    sa2 = mgr.open_user(a.id)
    dba2 = sa2.load()
    assert [s.name for s in dba2.subjects] == ["Maths"]
    assert len(dba2.images) == 1 and sa2.image_path(dba2.images[0]).exists()
    assert not (mgr.users_dir / b.id / "images").exists()  # A's photo never leaked into B's folder


def test_last_user_is_remembered_across_restarts(mgr, tmp_path):
    a, b = mgr.create_user("A"), mgr.create_user("B")
    mgr.open_user(a.id)
    mgr.open_user(b.id)
    again = UserManager(tmp_path / "root")  # app restarted
    assert again.last_user().id == b.id


def test_corrupt_app_json_is_harmless(mgr):
    mgr.create_user("A")
    (mgr.root / "app.json").write_text("{{{", "utf-8")
    assert mgr.last_user() is None


def test_rename_keeps_data(mgr):
    u = mgr.create_user("Old")
    st = mgr.open_user(u.id)
    db = st.load()
    db.add_subject("Keep me")
    st.save(db)
    mgr.rename_user(u.id, "New")
    assert mgr.get_user(u.id).name == "New"
    assert [s.name for s in mgr.open_user(u.id).load().subjects] == ["Keep me"]
    mgr.create_user("Other")
    with pytest.raises(ValueError):
        mgr.rename_user(u.id, "other")
    mgr.rename_user(u.id, "NEW")  # renaming to a different case of your own name is fine


def test_delete_removes_everything_and_forgets_last_user(mgr, photo):
    a, b = mgr.create_user("A"), mgr.create_user("B")
    st = mgr.open_user(a.id)
    db = st.load()
    s = db.add_subject("x")
    st.attach_image(db, photo, s.id)
    mgr.delete_user(a.id)
    assert not (mgr.users_dir / a.id).exists()
    assert mgr.last_user() is None
    assert [u.id for u in mgr.list_users()] == [b.id]
    with pytest.raises(NotFoundError):
        mgr.open_user(a.id)


@pytest.mark.parametrize("bad", ["../x", "..", "", "A" * 32, "0" * 31, "0" * 32, "/etc", None])
def test_bad_ids_are_rejected(mgr, bad):
    with pytest.raises(NotFoundError):
        mgr.open_user(bad)
    with pytest.raises(NotFoundError):
        mgr.delete_user(bad)


def test_damaged_user_json_does_not_hide_the_user(mgr):
    u = mgr.create_user("Real name")
    (mgr.users_dir / u.id / "user.json").write_text("garbage", "utf-8")
    listed = mgr.list_users()
    assert len(listed) == 1 and listed[0].id == u.id
    assert listed[0].name.startswith("Unnamed user")


def test_stray_folders_and_files_are_ignored(mgr):
    mgr.create_user("A")
    (mgr.users_dir / "not-an-id").mkdir()
    (mgr.users_dir / "notes.txt").write_text("hi")
    assert [u.name for u in mgr.list_users()] == ["A"]


def test_user_json_content(mgr):
    u = mgr.create_user("Saurabh")
    raw = json.loads((mgr.users_dir / u.id / "user.json").read_text("utf-8"))
    assert raw["name"] == "Saurabh" and raw["createdAt"].endswith("+00:00")


def test_storage_for_has_no_side_effects_but_open_user_remembers(mgr):
    a, b = mgr.create_user("A"), mgr.create_user("B")
    mgr.open_user(a.id)
    mgr.storage_for(b.id)
    assert mgr.last_user().id == a.id  # peeking at B did not change the last user
    mgr.remember_user(b.id)
    assert mgr.last_user().id == b.id
    with pytest.raises(NotFoundError):
        mgr.remember_user("0" * 32)
    with pytest.raises(NotFoundError):
        mgr.storage_for("../x")
