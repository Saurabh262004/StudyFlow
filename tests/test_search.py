import pytest

from studyflow import Database, Storage


@pytest.fixture
def world(tmp_path):
    store = Storage(tmp_path / "data")
    photo = tmp_path / "Lecture_Board.png"
    photo.write_bytes(b"\x89PNGx")
    db = Database()
    os_ = db.add_subject("Operating Systems", notes="Unit 3 and 4 are important")
    dbms = db.add_subject("DBMS")
    dead = db.add_point(os_.id, "Deadlocks", notes="Coffman conditions:\nmutual exclusion,   hold and wait")
    paging = db.add_point(os_.id, "Paging")
    norm = db.add_point(dbms.id, "Normalisation", notes="Remember BCNF and 3NF")
    norm.done = True
    img = store.attach_image(db, photo, os_.id, dead.id, tags=["Blackboard", "unit3"])
    return db, os_, dbms, dead, paging, norm, img


def kinds(hits):
    return [(h.kind, h.field) for h in hits]


def test_empty_queries_find_nothing(world):
    db = world[0]
    assert db.search("") == [] and db.search("   ") == []


def test_finds_each_kind_and_reports_where(world):
    db, os_, dbms, dead, paging, norm, img = world
    [h] = db.search("operating")
    assert (h.kind, h.field, h.subject_id, h.point_id, h.image_id) == ("subject", "name", os_.id, None, None)
    [h] = db.search("deadlocks")
    assert (h.kind, h.field, h.subject_id, h.point_id) == ("point", "title", os_.id, dead.id)
    [h] = db.search("blackboard")
    assert (h.kind, h.field, h.image_id, h.subject_id) == ("image", "tag", img.id, None)
    [h] = db.search("lecture_board")
    assert (h.kind, h.field, h.image_id) == ("image", "file name", img.id)


def test_case_insensitive_and_unicode(world):
    db = world[0]
    assert len(db.search("DEADLOCKS")) == 1 and len(db.search("dEaDlOcKs")) == 1
    s = db.add_subject("Gäng Ünïcode गणित")
    assert [h.subject_id for h in db.search("गणित")] == [s.id]
    assert [h.subject_id for h in db.search("ÜNÏCODE")] == [s.id]


def test_every_word_must_match(world):
    db = world[0]
    assert len(db.search("coffman wait")) == 1
    assert db.search("coffman banana") == []


def test_a_subject_name_can_help_find_a_point_but_never_matches_alone(world):
    db, os_, dbms, dead, paging, *_ = world
    assert [(h.kind, h.point_id) for h in db.search("operating deadlocks")] == [("point", dead.id)]
    # "operating" alone finds the subject, NOT every point inside it
    assert kinds(db.search("operating")) == [("subject", "name")]


def test_searches_notes_and_collapses_whitespace_in_snippets(world):
    db, os_, dbms, dead, *_ = world
    [h] = db.search("exclusion")
    assert (h.kind, h.field, h.point_id) == ("point", "notes", dead.id)
    assert "\n" not in h.snippet and "  " not in h.snippet and "exclusion" in h.snippet
    found = {(h.kind, h.field) for h in db.search("unit 3")}
    assert ("subject", "notes") in found  # the subject's notes ...
    assert ("image", "tag") in found  # ... and the picture tagged "unit3" (every word is matched as a substring)


def test_long_notes_get_a_short_snippet_with_ellipses(world):
    db, os_, *_ = world
    p = db.add_point(os_.id, "Long", notes="x " * 100 + "NEEDLE" + " y" * 100)
    [h] = db.search("needle")
    assert "NEEDLE" in h.snippet and h.snippet.startswith("\u2026") and h.snippet.endswith("\u2026")
    assert len(h.snippet) < 120


def test_title_matches_come_before_notes_matches(world):
    db, os_, *_ = world
    db.get_subject(os_.id).notes = "all about deadlocks"
    hits = db.search("deadlocks")
    assert [h.field for h in hits] == ["title", "notes"]  # point title first, then the subject's notes


def test_done_points_are_still_searchable(world):
    db, *_, norm, img = world
    assert [h.point_id for h in db.search("bcnf")] == [norm.id]


def test_subject_filter_limits_everything(world):
    db, os_, dbms, dead, paging, norm, img = world
    assert [h.point_id for h in db.search("normalisation", subject_id=os_.id)] == []
    assert len(db.search("normalisation", subject_id=dbms.id)) == 1
    assert [h.kind for h in db.search("blackboard", subject_id=os_.id)] == ["image"]
    assert db.search("blackboard", subject_id=dbms.id) == []  # the picture is not used in DBMS


def test_limit(world):
    db, os_, *_ = world
    for i in range(5):
        db.add_point(os_.id, f"Topic {i}")
    assert len(db.search("topic")) == 5 and len(db.search("topic", limit=2)) == 2


@pytest.mark.parametrize("query", ["c++", "(x)", "[a-z]", "a.b", "\\", "$^", "*", "?"])
def test_special_characters_are_plain_text(world, query):
    db, os_, *_ = world
    assert db.search(query) == []  # nothing matches, and nothing blows up
    p = db.add_point(os_.id, f"Learn {query} now")
    assert [h.point_id for h in db.search(query)] == [p.id]


def test_search_never_changes_the_database(world):
    db = world[0]
    before = db.to_dict()
    db.search("deadlocks")
    db.search("a", limit=1)
    assert db.to_dict() == before
