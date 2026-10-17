from datetime import datetime, timedelta, timezone

import pytest

from studyflow import Database, NotFoundError, PlanSettings, Status, format_remaining, next_up, rank_points

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)
D = timedelta


def build(*points, subject="Subject"):
    """points: (title, deadline offset from NOW or None, effort hours or None)."""
    db = Database()
    s = db.add_subject(subject)
    made = {}
    for title, offset, effort in points:
        deadline = None if offset is None else NOW + offset
        made[title] = db.add_point(s.id, title, deadline=deadline, effort_hours=effort)
    return db, s, made


def ranked(db, **kw):
    return rank_points(db, now=NOW, **kw)


def by_title(rows):
    return {r.point.title: r for r in rows}


# ------------------------------------------------------------------ start_by and status
def test_start_by_is_deadline_minus_effort_over_daily_hours():
    db, *_ = build(("A", D(days=3), 3))
    row = ranked(db)[0]
    assert row.start_by == NOW + D(days=3) - D(days=1.5)  # 3 h at 2 h/day = 1.5 days
    assert row.time_remaining == D(days=3)
    assert row.effort_hours == 3 and row.effort_estimated


def test_daily_hours_setting_changes_start_by():
    db, *_ = build(("A", D(days=3), 3))
    row = ranked(db, settings=PlanSettings(hours_per_day=3))[0]
    assert row.start_by == NOW + D(days=2)  # 3 h at 3 h/day = 1 day


def test_status_thresholds():
    # effort 2 h at 2 h/day needs exactly 1 day; soon_days is 2
    db, *_ = build(
        ("late", D(hours=12), 2),       # start_by = 12 h ago        -> START_NOW
        ("edge_now", D(days=1), 2),     # start_by == now            -> START_NOW
        ("soon", D(days=2), 2),         # start_by = +1 day          -> SOON
        ("edge_soon", D(days=3), 2),    # start_by = +2 days (== soon_days) -> SOON
        ("fine", D(days=5), 2),         # start_by = +4 days         -> ON_TRACK
        ("past", -D(hours=1), 2),       #                            -> OVERDUE
        ("none", None, 2),              #                            -> NO_DEADLINE
    )
    s = {t: r.status for t, r in by_title(ranked(db)).items()}
    assert s == {
        "late": Status.START_NOW, "edge_now": Status.START_NOW, "soon": Status.SOON,
        "edge_soon": Status.SOON, "fine": Status.ON_TRACK, "past": Status.OVERDUE, "none": Status.NO_DEADLINE,
    }


def test_deadline_exactly_now_is_overdue():
    db, *_ = build(("A", D(0), 1))
    assert ranked(db)[0].status is Status.OVERDUE


def test_missing_effort_uses_default_and_says_so():
    db, *_ = build(("A", D(days=2), None))
    row = ranked(db)[0]
    assert row.effort_hours == 1.0 and not row.effort_estimated
    assert row.start_by == NOW + D(days=2) - D(days=0.5)
    row = ranked(db, settings=PlanSettings(default_effort_hours=4))[0]
    assert row.effort_hours == 4


# ------------------------------------------------------------------ ordering
def test_big_task_due_later_comes_before_small_task_due_sooner():
    db, *_ = build(("small", D(days=2), 1), ("big", D(days=3), 8))
    assert [r.point.title for r in ranked(db)] == ["big", "small"]


def test_full_order_overdue_then_start_by_then_no_deadline_then_done():
    db, s, p = build(
        ("none", None, 1),
        ("later", D(days=9), 2),
        ("sooner", D(days=4), 2),
        ("overdue_a", -D(days=1), 2),
        ("overdue_b", -D(days=3), 2),
        ("finished", D(days=1), 2),
    )
    p["finished"].done = True
    assert [r.point.title for r in ranked(db)] == ["overdue_b", "overdue_a", "sooner", "later", "none"]
    assert [r.point.title for r in ranked(db, include_done=True)][-1] == "finished"
    assert by_title(ranked(db, include_done=True))["finished"].status is Status.DONE


def test_order_is_deterministic_for_ties():
    db, *_ = build(("b", D(days=2), 1), ("a", D(days=2), 1), ("c", D(days=2), 1))
    first = [r.point.title for r in ranked(db)]
    assert first == ["a", "b", "c"] and first == [r.point.title for r in ranked(db)]


def test_done_points_are_hidden_by_default_and_do_not_count_as_workload():
    db, s, p = build(("done_big", D(days=1), 20), ("small", D(days=1), 1))
    p["done_big"].done = True
    rows = ranked(db)
    assert [r.point.title for r in rows] == ["small"] and not rows[0].at_risk


# ------------------------------------------------------------------ at_risk (workload piling up)
def test_at_risk_when_deadlines_pile_up():
    # 2 h/day. By day 1 you have 2 h, by day 2 you have 4 h.
    db, *_ = build(("a", D(days=1), 2), ("b", D(days=2), 2))
    assert not any(r.at_risk for r in ranked(db))  # 2 <= 2 and 4 <= 4
    db, *_ = build(("a", D(days=1), 2), ("b", D(days=2), 3))
    r = by_title(ranked(db))
    assert not r["a"].at_risk and r["b"].at_risk  # 5 h of work by day 2, only 4 h available


def test_single_point_too_big_for_its_time_is_at_risk():
    db, *_ = build(("a", D(days=1), 5))
    assert ranked(db)[0].at_risk


def test_workload_is_counted_across_subjects_even_when_filtering():
    db = Database()
    x, y = db.add_subject("X"), db.add_subject("Y")
    db.add_point(x.id, "x1", deadline=NOW + D(days=1), effort_hours=2)
    db.add_point(y.id, "y1", deadline=NOW + D(days=2), effort_hours=3)
    only_y = rank_points(db, now=NOW, subject_id=y.id)
    assert [r.point.title for r in only_y] == ["y1"]
    assert only_y[0].at_risk  # 2 h (X) + 3 h (Y) = 5 h by day 2, only 4 h available
    with pytest.raises(NotFoundError):
        rank_points(db, now=NOW, subject_id="nope")


def test_overdue_points_still_use_up_study_time_for_later_deadlines():
    db, *_ = build(("overdue", -D(days=1), 4), ("next", D(days=1), 1))
    r = by_title(ranked(db))
    assert r["overdue"].at_risk and r["next"].at_risk  # 5 h of work, 2 h available by tomorrow


# ------------------------------------------------------------------ misc
def test_next_up():
    db, *_ = build(("a", D(days=5), 1), ("b", D(days=2), 2))
    assert next_up(db, now=NOW).point.title == "b"
    assert next_up(Database(), now=NOW) is None
    db2, _, p = build(("a", D(days=1), 1))
    p["a"].done = True
    assert next_up(db2, now=NOW) is None


def test_engine_never_changes_the_database():
    db, *_ = build(("a", D(days=5), 1), ("b", None, None))
    before = db.to_dict()
    ranked(db, include_done=True)
    next_up(db, now=NOW)
    assert db.to_dict() == before


def test_settings_validation():
    for bad in [dict(hours_per_day=0), dict(hours_per_day=25), dict(hours_per_day=float("nan")),
                dict(default_effort_hours=0), dict(soon_days=-1)]:
        with pytest.raises(ValueError):
            PlanSettings(**bad)


@pytest.mark.parametrize(
    "delta, text",
    [
        (None, "no deadline"),
        (D(days=3, hours=4, minutes=59), "3d 4h left"),
        (D(hours=5, minutes=30), "5h 30m left"),
        (D(minutes=20), "20m left"),
        (D(0), "0m left"),
        (-D(days=2, hours=1), "overdue by 2d 1h"),
        (-D(minutes=5), "overdue by 5m"),
    ],
)
def test_format_remaining(delta, text):
    assert format_remaining(delta) == text


def test_remaining_text_property():
    db, _, p = build(("a", D(days=1), 1), ("b", D(days=1), 1))
    p["b"].done = True
    rows = by_title(ranked(db, include_done=True))
    assert rows["a"].remaining_text == "1d 0h left" and rows["b"].remaining_text == "done"
