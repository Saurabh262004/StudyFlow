"""End-to-end demo of everything built so far (no UI, no priority engine yet).

    python demo.py                 # runs in a throw-away temp folder, touches none of your real data
    python demo.py --root DIR      # keeps the data under DIR so you can look at the files afterwards

It walks through: users -> subjects/points/notes -> tagged images -> JSON Schema checks ->
switching users -> refused invalid save -> backup & restore -> corruption recovery -> priority ranking -> deleting a user.
"""
import argparse
import json
import struct
import tempfile
import time
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from studyflow import PlanSettings, StorageError, UserManager, next_up, rank_points
from studyflow.storage import schema_errors


def section(title):
    print(f"\n=== {title} ===")


def tiny_png(path):
    """Write a valid 1x1 red PNG (stands in for a blackboard photo)."""

    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)
    return path


def due_in(deadline):
    # Naive countdown only; the real "time remaining + what to start first" engine is the next stage.
    delta = deadline - datetime.now(timezone.utc)
    secs = int(abs(delta.total_seconds()))
    text = f"{secs // 86400}d {secs % 86400 // 3600}h"
    return f"overdue by {text}" if delta.total_seconds() < 0 else f"due in {text}"


def show(db):
    for s in db.subjects:
        print(f"  {s.name}" + (f"  - {s.notes}" if s.notes else ""))
        for p in s.points:
            bits = []
            if p.deadline:
                bits.append(due_in(p.deadline))
            if p.effort_hours:
                bits.append(f"{p.effort_hours:g}h effort")
            n = len(db.find_images(point_id=p.id))
            if n:
                bits.append(f"{n} image")
            print(f"    [{'x' if p.done else ' '}] {p.title}" + (f"  ({', '.join(bits)})" if bits else ""))
        for img in db.images_of(s.id):
            print(f"    image: {img.original_name}  tags={img.tags}")


def tree(path, labels, depth=0):
    for p in sorted(path.iterdir(), key=lambda q: (q.is_file(), q.name)):
        name = labels.get(p.name, p.name)
        print("  " * depth + "  " + name + ("/" if p.is_dir() else ""))
        if p.is_dir():
            tree(p, labels, depth + 1)


def main(root_arg):
    with tempfile.TemporaryDirectory() as scratch:
        scratch = Path(scratch)
        root = Path(root_arg) if root_arg else scratch / "StudyFlowData"
        suffix = f" {time.strftime('%H%M%S')}" if root_arg else ""  # avoid name clashes in a kept folder
        photo = tiny_png(scratch / "blackboard.png")

        section("1. Users")
        mgr = UserManager(root)
        me = mgr.create_user("Saurabh" + suffix)
        guest = mgr.create_user("Guest" + suffix)
        print("users:", [u.name for u in mgr.list_users()])

        section("2. Subjects, study points, notes, deadlines, images (user: %s)" % me.name)
        store = mgr.open_user(me.id)
        db = store.load()
        print("load warnings:", store.warnings or "none")
        now = datetime.now(timezone.utc)
        os_ = db.add_subject("Operating Systems", notes="Unit 3 and 4 are important")
        deadlocks = db.add_point(os_.id, "Deadlocks", notes="Coffman conditions", deadline=now + timedelta(days=3, hours=4), effort_hours=2.5)
        paging = db.add_point(os_.id, "Paging", deadline=now + timedelta(days=9), effort_hours=1.5)
        dbms = db.add_subject("DBMS")
        db.add_point(dbms.id, "Normalisation", deadline=now + timedelta(hours=20), effort_hours=3)
        er = db.add_point(dbms.id, "ER diagrams")
        er.done = True
        store.save(db)
        board = store.attach_image(db, photo, os_.id, deadlocks.id, tags=["Blackboard", "unit3"])  # photo for one study point
        store.attach_image(db, photo, dbms.id, tags=["blackboard"])                                # photo for a whole subject
        store.link_image(db, board.id, os_.id, paging.id)  # the SAME photo, also shown on Paging (no second copy)
        show(db)

        section("3. Searching images")
        print("tag 'blackboard':", len(db.find_images(tag="blackboard")), "image(s)")
        print("tag 'UNIT3' (any case):", len(db.find_images(tag="UNIT3")), "image(s)")
        print("attached to 'Deadlocks':", [i.original_name for i in db.find_images(point_id=deadlocks.id)])
        print(f"the first photo is used in {len(db.usage(board.id))} places (Deadlocks and Paging) but stored only once")
        print("pictures stored in total:", len(db.images), "| files in the images folder:", len(list(store.images_dir.iterdir())))
        for query in ("deadlock", "unit3", "normal"):
            for hit in db.search(query):
                print(f"search {query!r}: {hit.kind} ({hit.field}): {hit.snippet}")

        section("4. JSON Schema check of the saved file")
        problems = schema_errors(json.loads(store.data_file.read_text("utf-8")))
        print("data.json matches schema:", not problems, problems or "")

        section("5. Switching users")
        gstore = mgr.open_user(guest.id)
        gdb = gstore.load()
        print(f"{guest.name} starts with:", len(gdb.subjects), "subjects")
        gdb.add_subject("Maths")
        gstore.save(gdb)
        store = mgr.open_user(me.id)
        db = store.load()
        print(f"back to {me.name}:", [s.name for s in db.subjects], "(Maths is not here)")
        print("last user remembered:", mgr.last_user().name)

        section("6. An invalid save is refused, saved file untouched")
        point = db.subjects[0].points[0]
        before = store.data_file.read_bytes()
        good_value, point.effort_hours = point.effort_hours, -3
        try:
            store.save(db)
        except StorageError as exc:
            print("refused:", exc)
        point.effort_hours = good_value
        print("file unchanged:", store.data_file.read_bytes() == before)

        section("7. Backup, accidental delete, restore")
        zip_path = store.export_backup(scratch / "my-backup")
        print("backup written:", zip_path.name)
        store.delete_subject(db, dbms.id)
        print("after delete:", [s.name for s in db.subjects], "| images:", len(db.images))
        db = store.restore_backup(zip_path)
        print("after restore:", [s.name for s in db.subjects], "| images:", len(db.images))
        print("image file back on disk:", all(store.image_path(i).exists() for i in db.images))

        section("8. Corrupted data.json")
        store.save(db)  # every save refreshes data.json.bak, so the backup is current
        store.data_file.write_text("{ this is not valid json", encoding="utf-8")
        db = store.load()
        for w in store.warnings:
            print("warning:", w)
        print("recovered subjects:", [s.name for s in db.subjects])

        section("9. What should I study first? (priority engine; settings are saved per user)")
        settings = store.load_settings()  # the defaults on first run
        print(f"saved setting: {settings.hours_per_day:g} study hours per day (default)")
        store.save_settings(PlanSettings(hours_per_day=3))
        settings = store.load_settings()
        print(f"after changing it and reloading: {settings.hours_per_day:g} study hours per day")
        print("other user's setting is separate:", mgr.open_user(guest.id).load_settings().hours_per_day, "h/day")
        mgr.open_user(me.id)  # make Saurabh the active user again
        for rank, row in enumerate(rank_points(db, settings=settings), start=1):
            start = row.start_by.astimezone().strftime("%a %d %b %H:%M") if row.start_by else "-"
            default = "" if row.effort_estimated else " (default)"
            warn = "   ! more work than time before this deadline" if row.at_risk else ""
            print(f"  {rank}. {row.subject_name} / {row.point.title}: {row.status.value}, {row.remaining_text}, "
                  f"{row.effort_hours:g}h{default}, start by {start}{warn}")
        top = next_up(db, settings=settings)
        print("study next:", f"{top.subject_name} / {top.point.title}" if top else "nothing left")

        section("10. Deleting a user, and the folders on disk")
        temp = mgr.create_user("Temp" + suffix)  # a throw-away user, so the two real ones stay
        print("users:", [u.name for u in mgr.list_users()])
        mgr.delete_user(temp.id)
        print("after deleting Temp:", [u.name for u in mgr.list_users()])
        print(f"\n{root}")
        tree(root, {me.id: f"<{me.name}>", guest.id: f"<{guest.name}>"})
        if root_arg:
            print(f"\nData kept in {root}")
        else:
            print("\n(temp folder is removed when the demo exits; run with --root DIR to keep it)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", help="keep the demo data in this folder instead of a temp folder")
    main(parser.parse_args().root)
