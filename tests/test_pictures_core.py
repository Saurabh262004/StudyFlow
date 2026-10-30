import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QMimeData, QPoint, QSize, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from tests.pictures_support import make_picture  # noqa: E402
from studyflow import StorageError  # noqa: E402
from studyflow.ui import image_import, thumbnails, util  # noqa: E402
from studyflow.ui.controller import AppController  # noqa: E402
from studyflow.ui.dialogs.tags_dialog import TagsDialog, parse_tags  # noqa: E402
from studyflow.ui.widgets.image_list import ID_ROLE, ImageListModel, ImageListView, caption_for  # noqa: E402


@pytest.fixture
def ctrl(qapp, tmp_path):
    c = AppController(tmp_path / "root")
    c.create_user("Saurabh")
    return c


@pytest.fixture
def world(ctrl, tmp_path):
    folder = tmp_path / "photos"
    folder.mkdir()
    os_, dbms = ctrl.add_subject("OS"), ctrl.add_subject("DBMS")
    dead = ctrl.add_point(os_.id, "Deadlocks")
    files = [make_picture(folder / f"IMG_{i}.jpg", color=c) for i, c in enumerate(["#aa3333", "#33aa33", "#3333aa"])]
    return {"os": os_, "dbms": dbms, "dead": dead, "files": files, "folder": folder}


def errors(monkeypatch):
    shown = []
    monkeypatch.setattr(util, "show_error", lambda parent, message: shown.append(message))
    return shown


def stub_tags(monkeypatch, answer):
    asked = []

    def fake(parent, title, label, suggestions=(), initial="", ok_text="OK"):
        asked.append({"label": label, "suggestions": list(suggestions)})
        return answer

    monkeypatch.setattr(TagsDialog, "ask", staticmethod(fake))
    return asked


# ================================================================== reading and thumbnails
def test_read_image_limits_the_size_and_keeps_proportions(qapp, tmp_path):
    big = make_picture(tmp_path / "big.png", 2000, 1000)
    image = thumbnails.read_image(big, 200)
    assert (image.width(), image.height()) == (200, 100)
    assert thumbnails.read_image(big).width() == 2000
    small = make_picture(tmp_path / "small.png", 50, 40)
    assert thumbnails.read_image(small, 200).width() == 50  # never scaled up


def test_unreadable_files_give_none(qapp, tmp_path):
    junk = tmp_path / "junk.png"
    junk.write_bytes(b"this is not a picture")
    assert thumbnails.read_image(junk, 96) is None
    assert thumbnails.read_image(tmp_path / "missing.png", 96) is None


def test_phone_photos_stored_sideways_are_shown_upright(qapp, tmp_path):
    PIL = pytest.importorskip("PIL.Image")
    image = PIL.new("RGB", (400, 200), (30, 30, 30))
    for x in range(200):
        for y in range(200):
            image.putpixel((x, y), (230, 40, 40))  # the left half is red
    exif = PIL.Exif()
    exif[274] = 6  # "rotate 90 degrees clockwise to display", how a phone saves a portrait photo
    path = tmp_path / "phone.jpg"
    image.save(path, exif=exif, quality=92)
    for limit in (0, 100):  # full size and as a thumbnail
        upright = thumbnails.read_image(path, limit)
        assert upright.height() > upright.width(), "a portrait photo must come out portrait"
        assert QColor(upright.pixel(upright.width() // 2, 4)).red() > 200, "the red half is now at the top"
        assert QColor(upright.pixel(upright.width() // 2, upright.height() - 4)).red() < 100


def test_thumbnails_are_square_so_captions_never_overlap_the_picture(qapp, tmp_path):
    cache = thumbnails.ThumbnailCache()
    for name, (w, h) in {"wide.png": (400, 100), "tall.png": (100, 400), "square.png": (200, 200)}.items():
        pixmap = cache.get(make_picture(tmp_path / name, w, h), 96)
        assert (pixmap.width(), pixmap.height()) == (96, 96), name
    wide = cache.get(tmp_path / "wide.png", 96).toImage()
    assert wide.pixelColor(48, 0).alpha() == 0 and wide.pixelColor(48, 48).alpha() == 255  # centred, transparent above


def test_thumbnail_cache_remembers_and_forgets(qapp, tmp_path):
    cache = thumbnails.ThumbnailCache(capacity=2)
    paths = [make_picture(tmp_path / f"{i}.png") for i in range(3)]
    first = cache.get(paths[0])
    assert cache.get(paths[0]) is first and len(cache) == 1
    cache.get(paths[1])
    cache.get(paths[2])
    assert len(cache) == 2  # the oldest was dropped
    cache.forget(paths[2])
    assert len(cache) == 1


def test_missing_and_broken_pictures_get_a_placeholder(qapp, tmp_path):
    cache = thumbnails.ThumbnailCache()
    assert cache.get(tmp_path / "gone.png", 96).size() == QSize(96, 96)
    junk = tmp_path / "junk.png"
    junk.write_bytes(b"nope")
    assert cache.get(junk, 96).size() == QSize(96, 96)


def test_big_photos_are_decoded_at_reduced_size_and_quickly(qapp, tmp_path):
    big = make_picture(tmp_path / "photo.jpg", 4000, 3000)
    started = time.time()
    image = thumbnails.read_image(big, 96)
    assert max(image.width(), image.height()) <= 96 and time.time() - started < 1.0


def test_fit_helper(qapp):
    assert thumbnails.fit(QSize(50, 40), QSize(100, 100)) == QSize(50, 40)
    assert thumbnails.fit(QSize(400, 200), QSize(100, 100)) == QSize(100, 50)


# ================================================================== the model and view
def test_model_roles(qapp, ctrl, world):
    record = image_import.import_pictures(ctrl, None, world["files"][:1], world["os"].id, tags=["Blackboard", "unit 3"])[0]
    ctrl.link_image(record.id, world["dbms"].id)
    model = ImageListModel(ctrl)
    model.set_images(ctrl.all_images())
    index = model.index(0)
    assert model.rowCount() == 1 and model.data(index, ID_ROLE) == record.id
    assert model.data(index, Qt.ItemDataRole.DisplayRole) == "blackboard, unit 3" == caption_for(record)
    tooltip = model.data(index, Qt.ItemDataRole.ToolTipRole)
    assert "IMG_0.jpg" in tooltip and "blackboard, unit 3" in tooltip and "2 place(s)" in tooltip
    icon = model.data(index, Qt.ItemDataRole.DecorationRole)
    assert not icon.isNull() and icon.pixmap(96, 96).width() > 0
    assert model.row_of(record.id) == 0 and model.row_of("x") == -1 and model.image_ids() == [record.id]
    assert model.data(model.index(5), ID_ROLE) is None


def test_untagged_pictures_have_no_caption(qapp, ctrl, world):
    record = image_import.import_pictures(ctrl, None, world["files"][:1], world["os"].id, tags=[])[0]
    assert caption_for(record) == ""


def test_view_selection_activation_and_delete_key(qapp, ctrl, world):
    records = image_import.import_pictures(ctrl, None, world["files"], world["os"].id, tags=[])
    model = ImageListModel(ctrl)
    model.set_images(records)
    view = ImageListView(model)
    view.resize(500, 300)
    view.show()
    qapp.processEvents()
    activated, deletes = [], []
    view.imageActivated.connect(activated.append)
    view.deleteRequested.connect(lambda: deletes.append(1))
    view.selectAll()
    assert view.selected_ids() == [r.id for r in records]
    view.clearSelection()
    view.setCurrentIndex(model.index(1))
    QTest.keyClick(view, Qt.Key.Key_Return)
    assert activated == [records[1].id]
    view.clearSelection()
    QTest.keyClick(view, Qt.Key.Key_Delete)  # nothing selected: ignored
    assert deletes == []
    view.selectionModel().select(model.index(1), view.selectionModel().SelectionFlag.Select)
    QTest.keyClick(view, Qt.Key.Key_Delete)
    assert deletes == [1]
    pos = view.visualRect(model.index(2)).center()
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    assert activated[-1] == records[2].id and activated.count(records[2].id) == 1


def test_row_view_is_one_scrolling_row(qapp, ctrl):
    view = ImageListView(ImageListModel(ctrl), row=True)
    assert not view.isWrapping() and view.flow().name == "LeftToRight" and view.height() > 96


# ================================================================== tags
def test_parse_tags():
    assert parse_tags(" Blackboard, unit 3 ,,blackboard,  ") == ["blackboard", "unit 3"]
    assert parse_tags("") == [] and parse_tags(" , ") == []


def test_tags_dialog_suggests_and_completes_the_tag_being_typed(qapp):
    dialog = TagsDialog("T", "Tags:", ["blackboard", "slides", "unit 3"], ok_text="Add")
    assert dialog.ok_button.text() == "Add" and "blackboard, slides, unit 3" in dialog.hint.text()
    assert dialog.completer.splitPath("blackboard, sl") == ["sl"] and dialog.completer.splitPath("sl") == ["sl"]
    dialog.show()
    qapp.processEvents()
    for typed, expected in (("blackboard, sl", "blackboard, slides"), ("un", "unit 3"), ("SLI", "slides")):
        dialog.edit.clear()
        dialog.edit.setFocus()
        QTest.keyClicks(dialog.edit, typed)  # type, then pick the suggestion in the pop-up with the keyboard
        qapp.processEvents()
        assert dialog.completer.popup().isVisible(), typed
        QTest.keyClick(dialog.completer.popup(), Qt.Key.Key_Down)
        QTest.keyClick(dialog.completer.popup(), Qt.Key.Key_Return)
        qapp.processEvents()
        assert dialog.edit.text() == expected, typed
    dialog.edit.setText("blackboard, slides")
    assert dialog.tags() == ["blackboard", "slides"]


def test_tags_dialog_without_suggestions(qapp):
    assert TagsDialog("T", "L").hint.text() == "Separate tags with commas."


def test_tags_dialog_ask(qapp, monkeypatch):
    from PySide6.QtWidgets import QDialog

    for result, expected in ((QDialog.DialogCode.Accepted, ["a", "b"]), (QDialog.DialogCode.Rejected, None)):
        monkeypatch.setattr(TagsDialog, "exec", lambda self, result=result: (self.edit.setText("A, b"), result)[1])
        assert TagsDialog.ask(None, "T", "L") == expected


# ================================================================== importing
def mime_with(*paths) -> QMimeData:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    return mime


def test_dropped_paths_keep_only_supported_picture_files(qapp, world, tmp_path):
    text = tmp_path / "notes.txt"
    text.write_text("hi")
    mime = mime_with(world["files"][0], text, tmp_path / "nothing.png", world["folder"])
    paths, ignored = image_import.picture_paths_from_mime(mime)
    assert paths == [world["files"][0]] and ignored == 3
    assert image_import.can_accept(mime) and not image_import.can_accept(mime_with(text)) and not image_import.can_accept(QMimeData())
    web = QMimeData()
    web.setUrls([QUrl("https://example.com/pic.png")])
    assert not image_import.can_accept(web)


def test_import_asks_for_tags_once_for_the_whole_batch(qapp, ctrl, world, monkeypatch):
    ctrl.add_point(world["os"].id, "x")
    asked = stub_tags(monkeypatch, ["blackboard"])
    added = image_import.import_pictures(ctrl, None, world["files"], world["os"].id, world["dead"].id)
    assert len(asked) == 1 and "these 3 pictures" in asked[0]["label"]
    assert [r.tags for r in added] == [["blackboard"]] * 3 and len(ctrl.images_of(world["os"].id, world["dead"].id)) == 3
    asked.clear()
    image_import.import_pictures(ctrl, None, world["files"][:1], world["dbms"].id)
    assert "this picture" in asked[0]["label"] and asked[0]["suggestions"] == ["blackboard"]  # earlier tags are suggested


def test_cancelling_the_tags_dialog_adds_nothing(qapp, ctrl, world, monkeypatch):
    stub_tags(monkeypatch, None)
    assert image_import.import_pictures(ctrl, None, world["files"], world["os"].id) == [] and ctrl.all_images() == []
    assert image_import.import_pictures(ctrl, None, [], world["os"].id) == []  # nothing chosen: nothing asked


def test_explicit_tags_skip_the_dialog(qapp, ctrl, world, monkeypatch):
    stub_tags(monkeypatch, None)  # would cancel if it were asked
    added = image_import.import_pictures(ctrl, None, world["files"][:2], world["os"].id, tags=["x"])
    assert len(added) == 2


def test_some_failures_do_not_stop_the_others_and_are_reported_together(qapp, ctrl, world, monkeypatch, tmp_path):
    shown = errors(monkeypatch)
    text = tmp_path / "notes.txt"
    text.write_text("hi")
    added = image_import.import_pictures(ctrl, None, [world["files"][0], text, tmp_path / "gone.png", world["files"][1]], world["os"].id, tags=[])
    assert len(added) == 2
    assert len(shown) == 1 and "notes.txt" in shown[0] and "gone.png" in shown[0] and "IMG_0" not in shown[0]


# ================================================================== the clipboard
def test_pasting_a_copied_picture(qapp, ctrl, world, monkeypatch):
    stub_tags(monkeypatch, ["screenshot"])
    image = QImage(200, 120, QImage.Format.Format_RGB32)
    image.fill(QColor("#336699"))
    QGuiApplication.clipboard().setImage(image)
    added = image_import.paste_picture(ctrl, None, world["os"].id)
    assert len(added) == 1 and added[0].original_name.startswith("Pasted picture ") and added[0].original_name.endswith(".png")
    assert ctrl.image_path(added[0]).exists() and thumbnails.read_image(ctrl.image_path(added[0])).width() == 200
    assert added[0].tags == ["screenshot"]


def test_pasting_copied_files(qapp, ctrl, world, monkeypatch):
    stub_tags(monkeypatch, [])
    QGuiApplication.clipboard().setMimeData(mime_with(*world["files"][:2]))
    assert len(image_import.paste_picture(ctrl, None, world["os"].id, world["dead"].id)) == 2


def test_pasting_with_nothing_useful_on_the_clipboard(qapp, ctrl, world, monkeypatch):
    shown = errors(monkeypatch)
    stub_tags(monkeypatch, [])
    QGuiApplication.clipboard().setText("just some text")
    assert image_import.paste_picture(ctrl, None, world["os"].id) == []
    assert shown == ["There is no picture on the clipboard."] and ctrl.all_images() == []


# ================================================================== removing
def test_removing_from_a_place_asks_only_for_the_last_use(qapp, ctrl, world, monkeypatch):
    shown = errors(monkeypatch)
    record = image_import.import_pictures(ctrl, None, world["files"][:1], world["os"].id, tags=[])[0]
    ctrl.link_image(record.id, world["dbms"].id)
    asked = []
    monkeypatch.setattr(util, "confirm", lambda *a, **k: (asked.append(k), False)[1])
    assert image_import.remove_from_place(ctrl, None, [record.id], world["dbms"].id) == 1
    assert asked == [] and len(ctrl.usage(record.id)) == 1  # shared: no question
    monkeypatch.setattr(util, "confirm", lambda *a, **k: (asked.append(k), None)[1])
    assert image_import.remove_from_place(ctrl, None, [record.id], world["os"].id) == 0
    assert "deletes the picture" in asked[0]["detail"] and ctrl.all_images()  # declined: still there
    monkeypatch.setattr(util, "confirm", lambda *a, **k: False)
    assert image_import.remove_from_place(ctrl, None, [record.id], world["os"].id) == 1
    assert ctrl.all_images() == [] and shown == []


def test_delete_everywhere(qapp, ctrl, world, monkeypatch):
    records = image_import.import_pictures(ctrl, None, world["files"][:2], world["os"].id, tags=[])
    ctrl.link_image(records[0].id, world["dbms"].id)
    details = []
    monkeypatch.setattr(util, "confirm", lambda parent, title, text, **k: (details.append((text, k["detail"])), None)[1])
    assert image_import.delete_everywhere(ctrl, None, [r.id for r in records]) == 0 and len(ctrl.all_images()) == 2
    assert "these 2 pictures" in details[0][0] and "3 place(s)" in details[0][1]
    assert image_import.delete_everywhere(ctrl, None, []) == 0
    monkeypatch.setattr(util, "confirm", lambda *a, **k: False)
    paths = [ctrl.image_path(r) for r in records]
    assert image_import.delete_everywhere(ctrl, None, [r.id for r in records]) == 2
    assert ctrl.all_images() == [] and not any(p.exists() for p in paths)


def test_storage_errors_while_removing_are_shown(qapp, ctrl, world, monkeypatch):
    shown = errors(monkeypatch)
    record = image_import.import_pictures(ctrl, None, world["files"][:1], world["os"].id, tags=[])[0]
    ctrl.link_image(record.id, world["dbms"].id)
    monkeypatch.setattr(ctrl, "unlink_image", lambda *a: (_ for _ in ()).throw(StorageError("disk full")))
    assert image_import.remove_from_place(ctrl, None, [record.id], world["dbms"].id) == 0 and shown == ["disk full"]
    monkeypatch.setattr(util, "confirm", lambda *a, **k: False)
    monkeypatch.setattr(ctrl, "delete_image", lambda *a: (_ for _ in ()).throw(StorageError("nope")))
    assert image_import.delete_everywhere(ctrl, None, [record.id]) == 0 and shown[-1] == "nope"


# ================================================================== controller helpers
def test_controller_picture_helpers(qapp, ctrl, world):
    a = image_import.import_pictures(ctrl, None, world["files"][:2], world["os"].id, world["dead"].id, tags=["blackboard", "unit 3"])
    image_import.import_pictures(ctrl, None, world["files"][2:], world["dbms"].id, tags=["slides", "blackboard"])
    ctrl.link_image(a[0].id, world["os"].id)
    assert ctrl.tag_counts() == {"blackboard": 3, "slides": 1, "unit 3": 2}
    assert list(ctrl.tag_counts()) == sorted(ctrl.tag_counts())
    assert ctrl.describe_usage(a[0].id) == ["OS", "OS \u203a Deadlocks"]
    assert ctrl.get_image(a[1].id).original_name == "IMG_1.jpg"
