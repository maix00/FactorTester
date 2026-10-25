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


def test_insert_and_remove_components():
    from server.jobs.storage.research_report_operations import insert_component, remove_component
    chapter = {"components": [
        {"component_id": "root", "kind": "chapter", "parent_id": None},
        {"component_id": "a", "kind": "section", "parent_id": "root"},
    ]}
    inserted = insert_component(chapter, {"component_id": "b", "kind": "paragraph"},
                                "root", "a")
    assert [c["component_id"] for c in inserted["components"]] == ["root", "a", "b"]
    removed = remove_component(inserted, "b")
    assert [c["component_id"] for c in removed["components"]] == ["root", "a"]


def test_component_batch_validates_single_chapter():
    from server.jobs.storage.research_report_operations import apply_component_batch
    import json
    class Store:
        def get_attachment(self, ref, name):
            return json.dumps({"components": [
                {"component_id": "root", "kind": "chapter", "parent_id": None},
                {"component_id": "a", "kind": "section", "parent_id": "root"},
            ]}).encode()
        def _request(self, *args, **kwargs):
            raise AssertionError("save should not be reached")
    document = {"_id": "research-report:p1", "_rev": "1-a", "attachments": {
        "chapters/" + __import__("hashlib").sha256(b"chapter-x").hexdigest()[:32] + ".json": {"name": "x.json"}}}
    try:
        apply_component_batch(Store(), document, base_rev="1-a", operations=[
            {"op": "remove_component", "chapter_id": "chapter-x", "component_id": "a"},
            {"op": "remove_component", "chapter_id": "other", "component_id": "a"},
        ])
    except ValueError as exc:
        assert "one chapter" in str(exc)
    else:
        raise AssertionError("mixed chapters should fail")
