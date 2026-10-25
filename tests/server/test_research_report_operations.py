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
