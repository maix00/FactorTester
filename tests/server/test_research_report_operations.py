import json
from server.jobs.storage.research_report_operations import move_chapter


def test_move_chapter_reorders_and_rejects_unknown():
    index = {"chapters": [{"component_id": "a"}, {"component_id": "b"}, {"component_id": "c"}]}
    moved = move_chapter(index, "c", "a")
    assert [c["component_id"] for c in moved["chapters"]] == ["a", "c", "b"]
    try:
        move_chapter(index, "missing", "a")
    except ValueError:
        pass
    else:
        raise AssertionError("missing chapter should fail")


def test_move_component_reparents_and_rejects_cycle():
    from server.jobs.storage.research_report_operations import move_component
    chapter = {"components": [
        {"component_id": "root", "kind": "chapter", "parent_id": None},
        {"component_id": "a", "kind": "section", "parent_id": "root"},
        {"component_id": "b", "kind": "section", "parent_id": "root"},
        {"component_id": "c", "kind": "paragraph", "parent_id": "a"},
    ]}
    moved = move_component(chapter, "c", "root", "b")
    assert moved["components"][-1]["component_id"] == "c"
    assert moved["components"][-1]["parent_id"] == "root"
    try:
        move_component(chapter, "a", "c", "b")
    except ValueError:
        pass
    else:
        raise AssertionError("cycle should fail")
