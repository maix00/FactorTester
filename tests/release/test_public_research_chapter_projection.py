from tools.cli.release.research_reporting.public_research.projection import (
    component_projection,
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


def test_metadata_chapter_holds_structure_but_not_component_content():
    value = chapter_projection(_projection(), "chapter-a", include_content=False)

    assert value["content_lazy"] is True
    section = next(item for item in value["components"] if item["component_id"] == "section-a")
    assert section["content_available"] is True
    assert section["body"] == ""
    assert section["content"] is None
    assert value["bindings"][0]["binding_id"] == "b-a"


def test_metadata_chapter_compacts_binding_details_but_keeps_job_port():
    projection = _projection()
    projection["bindings"][0]["data"] = {
        "port": 8141,
        "revision": "sha256:source-snapshot",
        "relative_path": "custom_factors/example.py",
    }
    value = chapter_projection(projection, "chapter-a", include_content=False)

    assert value["bindings"][0]["data"] == {"port": 8141}

    full = chapter_projection(projection, "chapter-a")
    assert full["bindings"][0]["data"]["revision"] == "sha256:source-snapshot"


def test_component_projection_returns_only_requested_full_component():
    value = component_projection(_projection(), "chapter-a", "section-a")

    assert [item["component_id"] for item in value["components"]] == ["section-a"]
    assert value["components"][0]["body"] == "正文"
    assert [item["binding_id"] for item in value["bindings"]] == ["b-a"]


def test_public_library_exposes_index_and_chapter_reads(tmp_path):
    library = PublicResearchLibrary(tmp_path / "public-research")
    projection = _projection()
    result = library.sync({
        "report_id": "r", "owner_ref": "owner", "projection": projection,
    })
    local = library.list_visible("owner")
    assert local[0]["build_source"] == "client"
    assert local[0]["sharing_state"] == "not_shared"
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

    metadata = library.chapter(
        result["publication_id"], "chapter-a", None, include_content=False,
    )
    section = next(item for item in metadata["components"] if item["component_id"] == "section-a")
    assert metadata["content_lazy"] is True
    assert section["body"] == ""
    component = library.component(
        result["publication_id"], "chapter-a", "section-a", None,
    )
    assert component["components"][0]["body"] == "正文"
    shared = library.list_visible(None)
    assert shared[0]["sharing_state"] == "shared"
    assert shared[0]["is_shared"] is True


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


def test_public_library_visible_list_uses_registry_metadata(tmp_path, monkeypatch):
    library = PublicResearchLibrary(tmp_path / "public-research")
    projection = _projection()
    result = library.sync({
        "report_id": "r", "owner_ref": "owner", "projection": projection,
    })

    def fail_full_projection(_publication_id):
        raise AssertionError("visible list must not decode the full report")

    monkeypatch.setattr(library, "_projection", fail_full_projection)
    value = library.list_visible("owner")
    assert value[0]["title"] == projection["title"]
    assert value[0]["generation"] == projection["generation"]
    assert value[0]["publication_id"] == result["publication_id"]
