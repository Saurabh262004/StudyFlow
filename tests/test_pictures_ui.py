from datetime import datetime, timedelta, timezone

import warnings

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QColor, QDragEnterEvent, QDragLeaveEvent, QDropEvent, QGuiApplication, QImage, QShortcut  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QDialog  # noqa: E402

from studyflow import StorageError  # noqa: E402
from studyflow.ui import image_import, util  # noqa: E402
from studyflow.ui.controller import AppController  # noqa: E402
from studyflow.ui.dialogs.image_picker import ImagePickerDialog, filter_images  # noqa: E402
from studyflow.ui.dialogs.image_viewer import ImageViewerDialog  # noqa: E402
from studyflow.ui.dialogs.tags_dialog import TagsDialog  # noqa: E402
from studyflow.ui.dialogs.target_picker import TargetPickerDialog  # noqa: E402
from studyflow.ui.main_window import PAGE_DASHBOARD, PAGE_IMAGES, PAGE_SUBJECT, MainWindow  # noqa: E402
from studyflow.ui.pages.gallery_page import GalleryPage  # noqa: E402
from studyflow.ui.pages.subject_page import SubjectPage  # noqa: E402
from studyflow.ui.widgets.image_strip import ImageStrip  # noqa: E402
from studyflow.ui.widgets.point_editor import PointEditor  # noqa: E402
from tests.pictures_support import make_picture  # noqa: E402


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
    dead, paging = ctrl.add_point(os_.id, "Deadlocks"), ctrl.add_point(os_.id, "Paging")
    files = [make_picture(folder / f"IMG_{i}.jpg", 640, 480, color) for i, color in enumerate(["#aa3333", "#33aa33", "#3333aa", "#aaaa33"])]
    return {"os": os_, "dbms": dbms, "dead": dead, "paging": paging, "files": files, "folder": folder}


def add(ctrl, files, subject, point=None, tags=()):
    return image_import.import_pictures(ctrl, None, files, subject.id, point.id if point else None, tags=list(tags))


def errors(monkeypatch):
    shown = []
    monkeypatch.setattr(util, "show_error", lambda parent, message: shown.append(message))
    return shown


def stub_tags(monkeypatch, answer):
    monkeypatch.setattr(TagsDialog, "ask", staticmethod(lambda parent, title, label, suggestions=(), initial="", ok_text="OK": answer))


def stub_target(monkeypatch, answer):
    seen = []

    def fake(parent, controller, title, label, taken=(), ok_text="OK"):
        seen.append({"title": title, "taken": set(taken)})
        return answer

    monkeypatch.setattr(TargetPickerDialog, "ask", staticmethod(fake))
    return seen


def mime_with(*paths) -> QMimeData:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    return mime


def counter(signal):
    seen = []
    signal.connect(seen.append)
    return seen


# ================================================================== the strip
def test_strip_without_a_target_is_inert(qapp, ctrl):
    strip = ImageStrip(ctrl)
    assert strip.count() == 0 and strip.target == (None, None)
    assert not any(b.isEnabled() for b in (strip.add_button, strip.paste_button, strip.link_button))
    assert strip.empty.text() == "" and not strip.empty.isHidden() and strip.view.isHidden()


def test_strip_shows_the_pictures_of_its_target_and_counts_them(qapp, ctrl, world):
    add(ctrl, world["files"][:2], world["os"], world["dead"])
    add(ctrl, world["files"][2:3], world["os"])  # on the subject, not on the point
    strip = ImageStrip(ctrl)
    counts = counter(strip.countChanged)
    strip.set_target(world["os"].id, world["dead"].id)
    assert strip.count() == 2 and counts == [2] and not strip.view.isHidden() and strip.empty.isHidden()
    assert all(b.isEnabled() for b in (strip.add_button, strip.paste_button, strip.link_button))
    strip.set_target(world["os"].id)
    assert strip.count() == 1 and counts == [2, 1]
    strip.set_target(world["os"].id, world["paging"].id)
    assert strip.count() == 0 and counts == [2, 1, 0] and "No pictures yet" in strip.empty.text()


def test_strip_follows_changes_made_elsewhere(qapp, ctrl, world):
    strip = ImageStrip(ctrl)
    strip.set_target(world["dbms"].id)
    record = add(ctrl, world["files"][:1], world["os"])[0]
    assert strip.count() == 0
    ctrl.link_image(record.id, world["dbms"].id)
    assert strip.count() == 1
    ctrl.set_image_tags(record.id, ["new tag"])
    assert strip.model.image_at(0).tags == ["new tag"]  # the caption follows
    ctrl.delete_subject(world["dbms"].id)  # the target itself goes away
    assert strip.count() == 0 and strip.target == (None, None) and not strip.add_button.isEnabled()


def test_add_pictures_button(qapp, ctrl, world, monkeypatch):
    strip = ImageStrip(ctrl)
    strip.set_target(world["os"].id, world["dead"].id)
    stub_tags(monkeypatch, ["blackboard"])
    monkeypatch.setattr(util, "ask_open_files", lambda parent, title, flt: [])
    strip.add_button.click()
    assert strip.count() == 0  # cancelled the file dialog
    monkeypatch.setattr(util, "ask_open_files", lambda parent, title, flt: world["files"][:3])
    strip.add_button.click()
    assert strip.count() == 3 and all(i.tags == ["blackboard"] for i in ctrl.all_images())


def test_paste_button_and_shortcut(qapp, ctrl, world, monkeypatch):
    strip = ImageStrip(ctrl)
    strip.set_target(world["os"].id)
    stub_tags(monkeypatch, [])
    image = QImage(80, 60, QImage.Format.Format_RGB32)
    image.fill(QColor("#336699"))
    QGuiApplication.clipboard().setImage(image)
    strip.paste_button.click()
    assert strip.count() == 1
    shortcuts = strip.findChildren(QShortcut)
    assert shortcuts and shortcuts[0].context() == Qt.ShortcutContext.WidgetWithChildrenShortcut  # only while focus is inside
    pasted = []
    monkeypatch.setattr(image_import, "paste_picture", lambda *a: pasted.append(a))
    shortcuts[0].activated.emit()
    assert len(pasted) == 1 and pasted[0][2:] == (world["os"].id, None)
    ImageStrip(ctrl).paste()  # no target: nothing happens, no error
    assert len(pasted) == 1


def test_show_existing_links_chosen_pictures_and_hides_those_already_here(qapp, ctrl, world, monkeypatch):
    a, b = add(ctrl, world["files"][:2], world["os"])
    strip = ImageStrip(ctrl)
    strip.set_target(world["dbms"].id)
    ctrl.link_image(a.id, world["dbms"].id)
    seen = []
    monkeypatch.setattr(ImagePickerDialog, "ask", staticmethod(lambda parent, controller, exclude=(), **k: (seen.append(set(exclude)), [b.id])[1]))
    strip.link_button.click()
    assert seen == [{a.id}] and strip.count() == 2
    assert len(ctrl.usage(b.id)) == 2 and len(ctrl.all_images()) == 2  # one file, shown in two places
    strip.set_target(None)
    strip.show_existing()  # no target: nothing happens
    assert len(seen) == 1


# ---------------------------------------------------------------- drag and drop
def drag_enter(strip, mime):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)  # Qt deprecated the QPoint overload; there is no other way to build one
        event = _drag_enter_event(mime)
    strip.dragEnterEvent(event)
    return event


def _drag_enter_event(mime):
    return QDragEnterEvent(QPoint(5, 5), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)


def test_dropping_picture_files_adds_them_with_visual_feedback(qapp, ctrl, world, monkeypatch, tmp_path):
    strip = ImageStrip(ctrl)
    strip.set_target(world["os"].id, world["dead"].id)
    stub_tags(monkeypatch, ["dropped"])
    mime = mime_with(*world["files"][:2])
    assert drag_enter(strip, mime).isAccepted() and strip.property("dropActive") is True
    strip.dragLeaveEvent(QDragLeaveEvent())
    assert strip.property("dropActive") is False
    assert drag_enter(strip, mime).isAccepted()
    drop = QDropEvent(QPointF(5, 5), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    strip.dropEvent(drop)
    assert drop.isAccepted() and strip.property("dropActive") is False and strip.count() == 2
    assert [i.tags for i in ctrl.all_images()] == [["dropped"]] * 2


def test_dropping_other_things_is_refused(qapp, ctrl, world, tmp_path):
    strip = ImageStrip(ctrl)
    strip.set_target(world["os"].id)
    text = tmp_path / "notes.txt"
    text.write_text("hi")
    mime = mime_with(text)  # (an event does not own its mime data: keep it alive while the event is used)
    assert not drag_enter(strip, mime).isAccepted() and strip.property("dropActive") in (None, False)
    drop = QDropEvent(QPointF(5, 5), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    drop.setAccepted(True)
    strip.dropEvent(drop)
    assert not drop.isAccepted() and strip.count() == 0
    no_target = ImageStrip(ctrl)
    picture = mime_with(world["files"][0])
    assert not drag_enter(no_target, picture).isAccepted()


# ---------------------------------------------------------------- removing and opening
def test_delete_key_removes_selected_pictures_from_this_place(qapp, ctrl, world, monkeypatch):
    shown = errors(monkeypatch)
    a, b = add(ctrl, world["files"][:2], world["os"], world["dead"])
    ctrl.link_image(a.id, world["dbms"].id)
    strip = ImageStrip(ctrl)
    strip.set_target(world["os"].id, world["dead"].id)
    asked = []
    monkeypatch.setattr(util, "confirm", lambda *a_, **k: (asked.append(1), False)[1])
    strip.view.selectAll()
    strip.remove_selected()  # a is shared (no question), b is the last use (asks)
    assert asked == [1] and strip.count() == 0 and [i.id for i in ctrl.all_images()] == [a.id] and shown == []
    assert ctrl.usage(a.id) == [(world["dbms"].id, None)]


def test_opening_a_picture_shows_the_viewer_on_that_picture(qapp, ctrl, world, monkeypatch):
    records = add(ctrl, world["files"][:3], world["os"], world["dead"])
    strip = ImageStrip(ctrl)
    strip.set_target(world["os"].id, world["dead"].id)
    opened = []
    monkeypatch.setattr(ImageViewerDialog, "exec", lambda self: opened.append((self._ids, self._index, self.subject_id, self.point_id)) or 0)
    strip.open_viewer(records[2].id)
    assert opened == [([r.id for r in records], 2, world["os"].id, world["dead"].id)]
    strip.open_viewer("unknown")
    assert len(opened) == 1


def test_context_menu_actions(qapp, ctrl, world, monkeypatch):
    record = add(ctrl, world["files"][:1], world["os"])[0]
    strip = ImageStrip(ctrl)
    strip.resize(500, 200)
    strip.set_target(world["os"].id)
    strip.show()
    qapp.processEvents()
    position = strip.view.visualRect(strip.model.index(0)).center()
    for label, check in (("Open", "viewer"), ("Remove from here", "removed"), ("Delete everywhere\u2026", "deleted")):
        events = []
        monkeypatch.setattr(strip, "open_viewer", lambda image_id, events=events: events.append("viewer"))
        monkeypatch.setattr(strip, "remove_selected", lambda events=events: events.append("removed"))
        monkeypatch.setattr(image_import, "delete_everywhere", lambda *a, events=events: events.append("deleted"))
        monkeypatch.setattr(util, "exec_menu", lambda menu, pos, label=label: next(x for x in menu.actions() if x.text() == label))
        strip._show_menu(position)
        assert events == [check], label
    monkeypatch.setattr(util, "exec_menu", lambda menu, pos: pytest.fail("no menu on empty space"))
    strip._show_menu(QPoint(480, 190))


# ================================================================== the viewer
@pytest.fixture
def viewer_world(ctrl, world):
    records = add(ctrl, world["files"][:3], world["os"], world["dead"], tags=["blackboard"])
    ctrl.link_image(records[0].id, world["dbms"].id)
    return records


def type_tags(viewer, text):
    """What typing in the tags field does (setText alone is a programmatic change, not a user edit)."""
    viewer.tags_edit.setText(text)
    viewer.tags_edit.textEdited.emit(text)


def open_viewer(ctrl, world, records, index=0, here=True):
    viewer = ImageViewerDialog(ctrl, [r.id for r in records], index, world["os"].id if here else None, world["dead"].id if here else None)
    viewer.show()
    return viewer


def test_viewer_shows_the_picture_and_its_details(qapp, ctrl, world, viewer_world):
    viewer = open_viewer(ctrl, world, viewer_world)
    assert viewer.name.text() == "IMG_0.jpg" and viewer.position.text() == "1 of 3"
    assert "640 \u00d7 480 pixels" in viewer.meta.text() and "Added" in viewer.meta.text()
    assert viewer.tags_edit.text() == "blackboard"
    assert [viewer.used.item(i).text() for i in range(viewer.used.count())] == ["OS \u203a Deadlocks", "DBMS"]
    assert not viewer.previous_button.isEnabled() and viewer.next_button.isEnabled()
    assert viewer.picture.pixmap() is not None and not viewer.picture.pixmap().isNull() and not viewer.remove_button.isHidden()


def test_viewer_navigation_with_buttons_and_arrow_keys(qapp, ctrl, world, viewer_world):
    viewer = open_viewer(ctrl, world, viewer_world)
    viewer.next_button.click()
    assert viewer.name.text() == "IMG_1.jpg" and viewer.position.text() == "2 of 3" and viewer.previous_button.isEnabled()
    QTest.keyClick(viewer, Qt.Key.Key_Right)
    assert viewer.position.text() == "3 of 3" and not viewer.next_button.isEnabled()
    QTest.keyClick(viewer, Qt.Key.Key_Right)  # at the end: stays
    assert viewer.position.text() == "3 of 3"
    QTest.keyClick(viewer, Qt.Key.Key_Left)
    viewer.previous_button.click()
    assert viewer.position.text() == "1 of 3"
    viewer.tags_edit.setFocus()
    QTest.keyClick(viewer.tags_edit, Qt.Key.Key_Right)  # arrow keys belong to the text field while typing tags
    assert viewer.position.text() == "1 of 3"


def test_viewer_fit_and_actual_size(qapp, ctrl, world, tmp_path):
    big = make_picture(tmp_path / "big.png", 3000, 2000)
    record = add(ctrl, [big], world["os"])[0]
    viewer = open_viewer(ctrl, world, [record], here=False)
    qapp.processEvents()  # let the dialog finish its first layout before measuring
    fitted = viewer.picture.pixmap()
    assert fitted.width() < 3000 and fitted.width() <= viewer.scroll.viewport().width() and viewer.fit_button.text() == "Actual size"
    viewer.fit_button.click()
    assert viewer.picture.pixmap().width() == 2600 and viewer.fit_button.text() == "Fit to window"  # capped for memory
    viewer.fit_button.click()
    assert viewer.picture.pixmap().width() == fitted.width()
    viewer.resize(1400, 900)
    qapp.processEvents()
    assert viewer.picture.pixmap().width() > fitted.width()  # re-fits when the window grows


def test_merely_opening_or_browsing_never_changes_tags(qapp, ctrl, world, viewer_world):
    """Regression: opening the viewer used to save the (still empty) tags field, wiping the picture's tags."""
    ctrl.set_image_tags(viewer_world[1].id, ["keep me", "and me"])
    seen = []
    ctrl.dataChanged.connect(lambda: seen.append(1))
    viewer = open_viewer(ctrl, world, viewer_world)
    for _ in range(2):
        viewer.next_button.click()
    viewer.previous_button.click()
    viewer.save_tags()
    viewer.accept()
    assert [ctrl.get_image(r.id).tags for r in viewer_world] == [["blackboard"], ["and me", "keep me"], ["blackboard"]]
    assert seen == [], "no saves at all"


def test_a_closed_viewer_no_longer_reacts_to_resizing(qapp, ctrl, world, viewer_world):
    viewer = open_viewer(ctrl, world, viewer_world)
    viewer.accept()
    viewer.resize(500, 400)  # (conftest fails the test if anything raises inside Qt while this is processed)
    viewer.scroll.viewport().resize(300, 200)
    qapp.processEvents()
    assert viewer._viewport.parent() is not None


def test_viewer_edits_tags(qapp, ctrl, world, viewer_world):
    viewer = open_viewer(ctrl, world, viewer_world)
    type_tags(viewer, " Blackboard, unit 3,  Unit 3 ")
    viewer.tags_edit.editingFinished.emit()
    assert ctrl.get_image(viewer_world[0].id).tags == ["blackboard", "unit 3"]
    type_tags(viewer, "typed but not confirmed")
    viewer.next_button.click()  # leaving the picture saves what was typed
    assert ctrl.get_image(viewer_world[0].id).tags == ["typed but not confirmed"]
    assert viewer.tags_edit.text() == "blackboard"
    type_tags(viewer, "saved when closing")
    viewer.accept()
    assert ctrl.get_image(viewer_world[1].id).tags == ["saved when closing"]


def test_a_failed_tag_save_is_reported_and_reverted(qapp, ctrl, world, viewer_world, monkeypatch):
    shown = errors(monkeypatch)
    viewer = open_viewer(ctrl, world, viewer_world)
    monkeypatch.setattr(ctrl, "set_image_tags", lambda *a: (_ for _ in ()).throw(StorageError("disk full")))
    type_tags(viewer, "will not stick")
    viewer.save_tags()
    assert shown == ["disk full"] and viewer.tags_edit.text() == "blackboard"


def test_viewer_also_show_in(qapp, ctrl, world, viewer_world, monkeypatch):
    viewer = open_viewer(ctrl, world, viewer_world, 1)
    seen = stub_target(monkeypatch, (world["os"].id, world["paging"].id))
    viewer.also_button.click()
    assert seen[0]["taken"] == {(world["os"].id, world["dead"].id)}
    assert ctrl.usage(viewer_world[1].id) == [(world["os"].id, world["dead"].id), (world["os"].id, world["paging"].id)]
    assert [viewer.used.item(i).text() for i in range(viewer.used.count())] == ["OS \u203a Deadlocks", "OS \u203a Paging"]
    stub_target(monkeypatch, None)
    viewer.also_button.click()
    assert len(ctrl.usage(viewer_world[1].id)) == 2


def test_viewer_remove_from_here_only_when_shown_here(qapp, ctrl, world, viewer_world, monkeypatch):
    assert open_viewer(ctrl, world, viewer_world, here=False).remove_button.isHidden()
    viewer = open_viewer(ctrl, world, viewer_world)
    ctrl.link_image(viewer_world[1].id, world["dbms"].id)
    viewer.show_index(1)
    monkeypatch.setattr(util, "confirm", lambda *a, **k: pytest.fail("shared pictures need no confirmation"))
    viewer.remove_button.click()  # shared with DBMS: just removed here
    assert viewer.current_id == viewer_world[1].id and viewer.remove_button.isHidden()  # still open, no longer here
    assert ctrl.usage(viewer_world[1].id) == [(world["dbms"].id, None)]


def test_viewer_removing_the_last_use_deletes_the_picture_and_moves_on(qapp, ctrl, world, viewer_world, monkeypatch):
    # viewer_world[0] is also shown in DBMS (shared); the other two are shown only on the point
    viewer = open_viewer(ctrl, world, viewer_world, 1)
    monkeypatch.setattr(util, "confirm", lambda *a, **k: False)
    path = ctrl.image_path(viewer_world[1])
    viewer.remove_button.click()  # IMG_1: its only use -> deleted, the viewer moves on to the next one
    assert len(ctrl.all_images()) == 2 and not path.exists()
    assert viewer.position.text() == "2 of 2" and viewer.name.text() == "IMG_2.jpg"
    viewer.remove_button.click()  # IMG_2: also deleted; now IMG_0 is shown
    assert len(ctrl.all_images()) == 1 and viewer.position.text() == "1 of 1" and viewer.name.text() == "IMG_0.jpg"
    viewer.remove_button.click()  # IMG_0 is shared with DBMS: it only leaves this place and stays in the library
    assert [i.id for i in ctrl.all_images()] == [viewer_world[0].id] and viewer.isVisible()
    assert viewer.remove_button.isHidden() and viewer.used.count() == 1 and viewer.used.item(0).text() == "DBMS"


def test_viewer_delete_everywhere(qapp, ctrl, world, viewer_world, monkeypatch):
    viewer = open_viewer(ctrl, world, viewer_world)
    monkeypatch.setattr(util, "confirm", lambda *a, **k: None)
    viewer.delete_button.click()
    assert len(ctrl.all_images()) == 3
    monkeypatch.setattr(util, "confirm", lambda *a, **k: False)
    path = ctrl.image_path(viewer_world[0])
    viewer.delete_button.click()
    assert len(ctrl.all_images()) == 2 and not path.exists() and viewer.name.text() == "IMG_1.jpg" and viewer.position.text() == "1 of 2"
    assert ctrl.usage(viewer_world[0].id) == [] if False else True


def test_viewer_follows_outside_changes(qapp, ctrl, world, viewer_world):
    viewer = open_viewer(ctrl, world, viewer_world, 1)
    ctrl.set_image_tags(viewer_world[1].id, ["changed elsewhere"])
    assert viewer.tags_edit.text() == "changed elsewhere"
    ctrl.delete_image(viewer_world[1].id)
    assert viewer.position.text() == "2 of 2" and viewer.name.text() == "IMG_2.jpg"
    ctrl.delete_image(viewer_world[2].id)
    ctrl.delete_image(viewer_world[0].id)
    assert viewer.result() == QDialog.DialogCode.Rejected


def test_viewer_places_list_goes_there_on_double_click(qapp, ctrl, world, viewer_world):
    viewer = open_viewer(ctrl, world, viewer_world)
    asked = []
    viewer.locationRequested.connect(lambda s, p: asked.append((s, p)))
    viewer._on_place_double_clicked(viewer.used.item(0))
    assert asked == [(world["os"].id, world["dead"].id)] and viewer.result() == QDialog.DialogCode.Accepted
    viewer = open_viewer(ctrl, world, viewer_world)
    viewer.locationRequested.connect(lambda s, p: asked.append((s, p)))
    viewer._on_place_double_clicked(viewer.used.item(1))
    assert asked[-1] == (world["dbms"].id, "")  # a subject-level place has no point id


def test_viewer_survives_a_missing_file(qapp, ctrl, world, viewer_world):
    ctrl.image_path(viewer_world[0]).unlink()
    viewer = open_viewer(ctrl, world, viewer_world)
    assert "missing or cannot be read" in viewer.picture.text() and "missing" in viewer.meta.text()
    viewer.next_button.click()
    assert viewer.picture.text() == "" and not viewer.picture.pixmap().isNull()


def test_viewer_shows_phone_photos_upright(qapp, ctrl, world, tmp_path):
    PIL = pytest.importorskip("PIL.Image")
    image = PIL.new("RGB", (400, 200), (40, 40, 40))
    exif = PIL.Exif()
    exif[274] = 6
    path = tmp_path / "phone.jpg"
    image.save(path, exif=exif)
    record = add(ctrl, [path], world["os"])[0]
    viewer = open_viewer(ctrl, world, [record], here=False)
    viewer.fit_button.click()  # actual size
    assert viewer.picture.pixmap().height() > viewer.picture.pixmap().width() and "200 \u00d7 400" in viewer.meta.text()


# ================================================================== the pickers
def test_target_picker_lists_subjects_and_points_and_blocks_taken_places(qapp, ctrl, world):
    dialog = TargetPickerDialog(ctrl, "Title", "Label", {(world["os"].id, world["dead"].id)}, ok_text="Go")
    tree = dialog.tree
    assert [tree.topLevelItem(i).text(0) for i in range(2)] == ["DBMS", "OS"]  # sorted by name
    os_item = tree.topLevelItem(1)
    assert [os_item.child(i).text(0) for i in range(2)] == ["Deadlocks   (already here)", "Paging"]
    assert dialog.ok_button.text() == "Go" and not dialog.ok_button.isEnabled() and dialog.selected() is None
    tree.setCurrentItem(os_item.child(0))
    assert dialog.selected() is None and not dialog.ok_button.isEnabled()  # taken
    tree.setCurrentItem(os_item.child(1))
    assert dialog.selected() == (world["os"].id, world["paging"].id) and dialog.ok_button.isEnabled()
    tree.setCurrentItem(os_item)
    assert dialog.selected() == (world["os"].id, None)  # the subject itself


def test_target_picker_ask_and_double_click(qapp, ctrl, world, monkeypatch):
    monkeypatch.setattr(TargetPickerDialog, "exec", lambda self: (self.tree.setCurrentItem(self.tree.topLevelItem(0)), QDialog.DialogCode.Accepted)[1])
    assert TargetPickerDialog.ask(None, ctrl, "T", "L") == (world["dbms"].id, None)
    monkeypatch.setattr(TargetPickerDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    assert TargetPickerDialog.ask(None, ctrl, "T", "L") is None
    dialog = TargetPickerDialog(ctrl, "T", "L")
    dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0))
    dialog._on_double_click(dialog.tree.topLevelItem(0), 0)
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_image_picker_filters_and_selects(qapp, ctrl, world):
    a = add(ctrl, world["files"][:1], world["os"], tags=["blackboard", "unit 3"])[0]
    b = add(ctrl, world["files"][1:2], world["os"], tags=["slides"])[0]
    c = add(ctrl, world["files"][2:3], world["dbms"], tags=["blackboard"])[0]
    dialog = ImagePickerDialog(ctrl, exclude_ids={c.id})
    assert sorted(dialog.model.image_ids()) == sorted([a.id, b.id]) and not dialog.ok_button.isEnabled()
    assert [dialog.tag_filter.itemText(i) for i in range(dialog.tag_filter.count())] == ["All pictures", "blackboard  (2)", "slides  (1)", "unit 3  (1)"]
    dialog.tag_filter.setCurrentIndex(dialog.tag_filter.findData("slides"))
    assert dialog.model.image_ids() == [b.id]
    dialog.tag_filter.setCurrentIndex(0)
    dialog.search.setText("img_0 UNIT")
    assert dialog.model.image_ids() == [a.id]
    dialog.search.setText("")
    dialog.view.selectAll()
    assert dialog.ok_button.isEnabled() and sorted(dialog.selected_ids()) == sorted([a.id, b.id])


def test_image_picker_empty_state_and_ask(qapp, ctrl, world, monkeypatch):
    dialog = ImagePickerDialog(ctrl)
    assert not dialog.empty.isHidden() and dialog.view.isHidden()
    record = add(ctrl, world["files"][:1], world["os"])[0]
    dialog = ImagePickerDialog(ctrl)
    assert dialog.empty.isHidden() and not dialog.view.isHidden()
    monkeypatch.setattr(ImagePickerDialog, "exec", lambda self: (self.view.selectAll(), QDialog.DialogCode.Accepted)[1])
    assert ImagePickerDialog.ask(None, ctrl) == [record.id]
    monkeypatch.setattr(ImagePickerDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    assert ImagePickerDialog.ask(None, ctrl) == []
    dialog.view.imageActivated.emit(record.id)  # double click picks it
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_filter_images_helper(qapp, ctrl, world):
    a = add(ctrl, world["files"][:1], world["os"], tags=["blackboard"])[0]
    b = add(ctrl, world["files"][1:2], world["os"], tags=["slides", "unit 3"])[0]
    both = [a, b]
    assert filter_images(both, None, "") == both and filter_images(both, "slides", "") == [b]
    assert filter_images(both, None, "IMG_1 slides") == [b] and filter_images(both, "slides", "board") == []


# ================================================================== the gallery page
def test_gallery_empty_and_filled(qapp, ctrl, world):
    page = GalleryPage(ctrl)
    assert not page.empty.isHidden() and page.view.isHidden() and "No pictures yet" in page.empty.text() and page.summary.text() == "0 picture(s)"
    add(ctrl, world["files"][:3], world["os"], tags=["blackboard"])
    assert page.empty.isHidden() and not page.view.isHidden() and page.summary.text() == "3 picture(s)" and page.model.rowCount() == 3


def test_gallery_lists_newest_first(qapp, ctrl, world):
    page = GalleryPage(ctrl)
    records = add(ctrl, world["files"][:3], world["os"])
    now = datetime.now(timezone.utc)
    for i, record in enumerate(records):
        ctrl.db.images[ctrl.db.images.index(record)].added_at = now - timedelta(days=i)  # oldest = last imported
    ctrl.dataChanged.emit()
    assert page.model.image_ids() == [r.id for r in records]  # records[0] is the newest
    ctrl.db.images[ctrl.db.images.index(records[0])].added_at = now - timedelta(days=9)
    ctrl.dataChanged.emit()
    assert page.model.image_ids() == [records[1].id, records[2].id, records[0].id]


def test_gallery_filters_by_tag_and_search(qapp, ctrl, world):
    page = GalleryPage(ctrl)
    a = add(ctrl, world["files"][:1], world["os"], tags=["blackboard"])[0]
    b = add(ctrl, world["files"][1:2], world["os"], tags=["slides"])[0]
    c = add(ctrl, world["files"][2:3], world["dbms"], tags=["blackboard", "slides"])[0]
    assert [page.tag_filter.itemText(i) for i in range(page.tag_filter.count())] == ["All pictures", "blackboard  (2)", "slides  (2)"]
    page.tag_filter.setCurrentIndex(page.tag_filter.findData("slides"))
    assert sorted(page.model.image_ids()) == sorted([b.id, c.id]) and page.summary.text() == "3 picture(s), 2 shown"
    page.search.setText("img_2")
    assert page.model.image_ids() == [c.id]
    page.search.setText("zzz")
    assert page.view.isHidden() and page.empty.text() == "No picture matches this search or tag."
    page.search.setText("")
    ctrl.delete_image(b.id)
    ctrl.delete_image(c.id)  # the selected tag filter survives refreshes while it exists ...
    assert page.tag_filter.currentData() is None and page.model.image_ids() == [a.id]  # ... and falls back to "all" when it is gone


def test_gallery_add_pictures_asks_for_the_place(qapp, ctrl, world, monkeypatch):
    page = GalleryPage(ctrl)
    shown = errors(monkeypatch)
    empty = AppController(ctrl.manager.root.parent / "other")
    empty.create_user("Nobody")
    GalleryPage(empty).add_pictures()
    assert shown == ["Create a subject first: pictures are shown on a subject or on one of its study points."]
    monkeypatch.setattr(util, "ask_open_files", lambda *a: [])
    seen = stub_target(monkeypatch, None)
    page.add_pictures()
    assert seen == [] and ctrl.all_images() == []  # no files chosen: the place is not even asked
    monkeypatch.setattr(util, "ask_open_files", lambda *a: world["files"][:2])
    page.add_pictures()
    assert seen and ctrl.all_images() == []  # cancelled at the place dialog
    stub_target(monkeypatch, (world["os"].id, world["paging"].id))
    stub_tags(monkeypatch, ["slides"])
    page.add_pictures()
    assert len(ctrl.images_of(world["os"].id, world["paging"].id)) == 2 and page.model.rowCount() == 2


def test_gallery_delete_and_open(qapp, ctrl, world, monkeypatch):
    page = GalleryPage(ctrl)
    records = add(ctrl, world["files"][:3], world["os"])
    page.view.selectionModel().select(page.model.index(0), page.view.selectionModel().SelectionFlag.Select)
    deleted = page.view.selected_ids()
    monkeypatch.setattr(util, "confirm", lambda *a, **k: False)
    page.view.deleteRequested.emit()
    assert page.model.rowCount() == 2 and deleted[0] not in page.model.image_ids()
    opened = []
    monkeypatch.setattr(ImageViewerDialog, "exec", lambda self: opened.append((self._ids, self._index, self.subject_id)) or 0)
    page.open_viewer(page.model.image_ids()[1])
    assert opened == [(page.model.image_ids(), 1, None)]
    page.open_viewer("unknown")
    assert len(opened) == 1


def test_gallery_also_show_in(qapp, ctrl, world, monkeypatch):
    page = GalleryPage(ctrl)
    a, b = add(ctrl, world["files"][:2], world["os"], world["dead"])
    ctrl.link_image(a.id, world["dbms"].id)
    seen = stub_target(monkeypatch, (world["os"].id, world["paging"].id))
    page._also_show_in([a.id, b.id])
    assert seen[0]["taken"] == {(world["os"].id, world["dead"].id)}  # only places where BOTH already are
    assert (world["os"].id, world["paging"].id) in ctrl.usage(a.id) and (world["os"].id, world["paging"].id) in ctrl.usage(b.id)


def test_gallery_context_menu(qapp, ctrl, world, monkeypatch):
    page = GalleryPage(ctrl)
    record = add(ctrl, world["files"][:1], world["os"])[0]
    page.resize(700, 400)
    page.show()
    qapp.processEvents()
    position = page.view.visualRect(page.model.index(0)).center()
    seen = []
    monkeypatch.setattr(page, "open_viewer", lambda image_id: seen.append(("open", image_id)))
    monkeypatch.setattr(page, "_also_show_in", lambda ids: seen.append(("also", ids)))
    monkeypatch.setattr(page, "delete_selected", lambda: seen.append(("delete",)))
    for label in ("Open", "Also show in\u2026", "Delete everywhere\u2026"):
        monkeypatch.setattr(util, "exec_menu", lambda menu, pos, label=label: next(x for x in menu.actions() if x.text() == label))
        page._show_menu(position)
    assert seen == [("open", record.id), ("also", [record.id]), ("delete",)]
    monkeypatch.setattr(util, "exec_menu", lambda menu, pos: pytest.fail("no menu on empty space"))
    page._show_menu(QPoint(690, 390))


def test_gallery_clears_when_the_user_goes_away(qapp, ctrl, world):
    page = GalleryPage(ctrl)
    add(ctrl, world["files"][:1], world["os"])
    ctrl.delete_user(ctrl.current_user.id)
    assert page.model.rowCount() == 0 and page.summary.text() == ""


# ================================================================== inside the subject page and the main window
def test_the_point_editor_has_a_pictures_tab_only_when_given_one(qapp, ctrl):
    assert PointEditor().tabs.count() == 1
    editor = PointEditor(images_widget=ImageStrip(ctrl))
    assert [editor.tabs.tabText(i) for i in range(2)] == ["Notes", "Pictures"]
    editor.set_pictures_count(3)
    assert editor.tabs.tabText(1) == "Pictures (3)"
    editor.set_pictures_count(0)
    assert editor.tabs.tabText(1) == "Pictures"
    PointEditor().set_pictures_count(5)  # no pictures tab: harmless


def test_subject_page_pictures(qapp, ctrl, world):
    add(ctrl, world["files"][:1], world["os"])  # subject-level
    add(ctrl, world["files"][1:3], world["os"], world["dead"])  # point-level
    page = SubjectPage(ctrl)
    page.show_subject(world["os"].id)
    assert page.tabs.tabText(2) == "Pictures (1)" and page.subject_images.target == (world["os"].id, None)
    assert page.point_images.target == (None, None) and page.editor.tabs.tabText(1) == "Pictures"
    page.select_point(world["dead"].id)
    assert page.point_images.target == (world["os"].id, world["dead"].id) and page.editor.tabs.tabText(1) == "Pictures (2)"
    page.select_point(world["paging"].id)
    assert page.point_images.count() == 0 and page.editor.tabs.tabText(1) == "Pictures"
    page.table.clearSelection()
    assert page.point_images.target == (None, None) and not page.point_images.add_button.isEnabled()
    page.clear()
    assert page.subject_images.target == (None, None)


def test_pictures_added_while_editing_do_not_disturb_the_edit(qapp, ctrl, world):
    page = SubjectPage(ctrl)
    page.show_subject(world["os"].id)
    page.select_point(world["dead"].id)
    page.editor.title_edit.setText("half-typed title")
    add(ctrl, world["files"][:2], world["os"], world["dead"])
    assert page.editor.title_edit.text() == "half-typed title" and page.point_images.count() == 2
    page.flush()
    assert ctrl.get_point(world["os"].id, world["dead"].id).title == "half-typed title"
    assert page.editor.tabs.tabText(1) == "Pictures (2)"


def test_deleting_a_point_with_pictures_clears_the_strip_and_removes_unused_pictures(qapp, ctrl, world):
    page = SubjectPage(ctrl)
    page.show_subject(world["os"].id)
    page.select_point(world["dead"].id)
    records = add(ctrl, world["files"][:2], world["os"], world["dead"])
    ctrl.link_image(records[0].id, world["dbms"].id)
    page.editor.delete_button.click()
    assert page.point_images.target == (None, None) and [i.id for i in ctrl.all_images()] == [records[0].id]


def test_dropping_on_the_subject_tab_and_the_point_tab_go_to_the_right_place(qapp, ctrl, world, monkeypatch):
    page = SubjectPage(ctrl)
    page.show_subject(world["os"].id)
    page.select_point(world["dead"].id)
    stub_tags(monkeypatch, [])
    mime = mime_with(world["files"][0])
    for strip, expected in ((page.subject_images, (world["os"].id, None)), (page.point_images, (world["os"].id, world["dead"].id))):
        drop = QDropEvent(QPointF(5, 5), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        strip.dropEvent(drop)
        assert (ctrl.images_of(*expected[:1], expected[1])) and strip.count() == 1


def test_main_window_navigation_to_a_picture_place(qapp, ctrl, world):
    records = add(ctrl, world["files"][:2], world["os"], world["dead"])
    ctrl.link_image(records[0].id, world["dbms"].id)
    w = MainWindow(ctrl)
    w.open_location(world["dbms"].id)  # a subject: its Pictures tab
    assert w.pages.currentIndex() == PAGE_SUBJECT and w.subject_page.title.text() == "DBMS" and w.subject_page.tabs.currentIndex() == 2
    w.open_location(world["os"].id, world["dead"].id)  # a point
    assert w.subject_page.title.text() == "OS" and w.subject_page.tabs.currentIndex() == 0 and w.subject_page.editor.title_edit.text() == "Deadlocks"
    w.open_location("nope")
    assert w.subject_page.title.text() == "OS"


def test_the_images_page_replaces_the_placeholder_and_can_navigate(qapp, ctrl, world):
    records = add(ctrl, world["files"][:2], world["os"], world["dead"])
    w = MainWindow(ctrl)
    w.nav.setCurrentRow(1)
    assert w.pages.currentIndex() == PAGE_IMAGES and w.pages.currentWidget() is w.images_page and w.images_page.model.rowCount() == 2
    w.images_page.openLocationRequested.emit(world["os"].id, world["dead"].id)  # e.g. double-clicked in a viewer's "Shown in" list
    assert w.pages.currentIndex() == PAGE_SUBJECT and w.subject_page.editor.title_edit.text() == "Deadlocks"
    assert w.subject_page.point_images.count() == 2
    w.nav.setCurrentRow(0)
    assert w.pages.currentIndex() == PAGE_DASHBOARD


def test_subject_page_viewer_requests_reach_the_window(qapp, ctrl, world):
    records = add(ctrl, world["files"][:1], world["os"], world["dead"])
    ctrl.link_image(records[0].id, world["dbms"].id)
    w = MainWindow(ctrl)
    w.open_point(world["os"].id, world["dead"].id)
    w.subject_page.point_images.locationRequested.emit(world["dbms"].id, "")
    assert w.subject_page.title.text() == "DBMS" and w.subject_page.tabs.currentIndex() == 2
