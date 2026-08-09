from tools.cli.release.research_reporting.public_research.projection import (
    chapter_projection,
    projection_index,
)
from tools.cli.release.research_reporting.public_research.library import PublicResearchLibrary


def _projection():
    return {
        "schema_version": 2,
        "report_id": "r",
        "title": "报告",
        "language": "zh-Hans",
        "generation": 4,
        "projection_hash": "hash",
        "components": [
            {"component_id": "chapter-a", "parent_id": None, "kind": "chapter",
             "title": "第一章", "body": "", "content": None},
            {"component_id": "section-a", "parent_id": "chapter-a", "kind": "section",
             "title": "章内", "body": "正文", "content": None},
            {"component_id": "chapter-b", "parent_id": None, "kind": "chapter",
             "title": "第二章", "body": "", "content": None},
            {"component_id": "section-b", "parent_id": "chapter-b", "kind": "section",
             "title": "另一章", "body": "factortester-local://aaaaaaaaaaaaaaaaaaaaaaaa", "content": None},
        ],
        "bindings": [
            {"binding_id": "b-a", "component_id": "section-a", "kind": "factor",
             "target_ref": "factor:a", "label": "A"},
            {"binding_id": "b-b", "component_id": "section-b", "kind": "factor",
             "target_ref": "factor:b", "label": "B"},
        ],
        "assets": [],
        "local_resources": [
            {"resource_id": "a" * 24, "filename": "a.txt"},
            {"resource_id": "b" * 24, "filename": "b.txt"},
        ],
        "related_objects": [],
        "attachments": [],
    }


def test_projection_index_contains_only_chapter_metadata():
    value = projection_index(_projection())

    assert [item["component_id"] for item in value["chapters"]] == [
        "chapter-a", "chapter-b",
    ]
    assert "components" not in value
    assert value["chapters"][0]["preview"] == "章内"


def test_chapter_projection_keeps_descendants_and_scoped_bindings_and_resources():
    value = chapter_projection(_projection(), "chapter-b")

    assert [item["component_id"] for item in value["components"]] == [
        "chapter-b", "section-b",
    ]
    assert [item["binding_id"] for item in value["bindings"]] == ["b-b"]
    assert [item["resource_id"] for item in value["local_resources"]] == ["a" * 24]


def test_public_library_exposes_index_and_chapter_reads(tmp_path):
    library = PublicResearchLibrary(tmp_path / "public-research")
    projection = _projection()
    result = library.sync({
        "report_id": "r", "owner_ref": "owner", "projection": projection,
    })
    library.configure(
        owner_ref="owner", report_id="r", projection=None,
        visibility="public", auto_sync=True, relay_local_files=False,
        authorized_users=[],
    )

    index = library.index(result["publication_id"], None)
    chapter = library.chapter(result["publication_id"], "chapter-a", None)
    assert [item["component_id"] for item in index["chapters"]] == [
        "chapter-a", "chapter-b",
    ]
    assert [item["component_id"] for item in chapter["components"]] == [
        "chapter-a", "section-a",
    ]


def test_public_library_index_uses_persisted_sidecar(tmp_path, monkeypatch):
    library = PublicResearchLibrary(tmp_path / "public-research")
    projection = _projection()
    result = library.sync({
        "report_id": "r", "owner_ref": "owner", "projection": projection,
    })
    publication_id = result["publication_id"]
    index_path = library._index_path(publication_id)
    assert index_path.is_file()

    def fail_full_projection(_publication_id):
        raise AssertionError("index must not decode the full report")

    monkeypatch.setattr(library, "_projection", fail_full_projection)
    value = library.index(publication_id, "owner")
    assert [item["component_id"] for item in value["chapters"]] == [
        "chapter-a", "chapter-b",
    ]


def test_public_library_chapter_uses_persisted_sidecar(tmp_path, monkeypatch):
    library = PublicResearchLibrary(tmp_path / "public-research")
    projection = _projection()
    result = library.sync({
        "report_id": "r", "owner_ref": "owner", "projection": projection,
    })
    publication_id = result["publication_id"]
    assert library._chapter_path(publication_id, "chapter-a").is_file()

    def fail_full_projection(_publication_id):
        raise AssertionError("chapter must not decode the full report")

    monkeypatch.setattr(library, "_projection", fail_full_projection)
    value = library.chapter(publication_id, "chapter-a", "owner")
    assert [item["component_id"] for item in value["components"]] == [
        "chapter-a", "section-a",
    ]
