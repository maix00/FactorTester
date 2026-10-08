import base64
import hashlib

from tools.cli.release.research_reporting.public_research.library import PublicResearchLibrary
from tools.cli.release.research_reporting.public_research.projection import (
    asset_id_for,
    build_upload_projection,
    read_local_asset,
    read_local_resource,
)


def test_public_research_asset_is_stored_and_read_with_visibility(tmp_path):
    raw = b"test image bytes"
    asset_id = "asset-12345678"
    digest = hashlib.sha256(raw).hexdigest()
    projection = {
        "schema_version": 2,
        "report_id": "report-1",
        "title": "Report",
        "language": "zh-Hans",
        "generation": 1,
        "components": [],
        "assets": [{
            "asset_id": asset_id,
            "media_type": "image/png",
            "filename": "figure.png",
            "content_hash": digest,
            "caption": "Figure",
            "alt_text": "",
            "content_base64": base64.b64encode(raw).decode("ascii"),
        }],
        "local_resources": [],
        "projection_hash": "hash",
    }
    library = PublicResearchLibrary(tmp_path)
    result = library.sync({
        "report_id": "report-1", "owner_ref": "owner", "projection": projection,
    })
    library.configure(
        owner_ref="owner", report_id="report-1", projection=None,
        visibility="public", auto_sync=True, relay_local_files=False,
        authorized_users=[],
    )

    assert library.asset(result["publication_id"], asset_id, None)[:2] == (raw, "image/png")


def test_upload_projection_preserves_safe_binding_metadata():
    snapshot = {
        "head": {"report_id": "r", "title": "Report", "generation": 3},
        "components": [{
            "component_id": "section-1", "parent_id": None, "kind": "section",
            "title": "A", "body": "[Factor](factortester://factor/f1)",
            "content": None, "display_kind": "",
        }],
        "bindings": [{
            "binding_id": "b1", "component_id": "section-1", "kind": "factor",
            "target_ref": "factor:f1", "label": "Factor", "data": {"path": "/Users/private"},
        }],
    }
    payload = build_upload_projection(snapshot)
    assert payload["components"][0]["binding_ids"] == ["b1"]
    assert payload["bindings"][0]["label"] == "Factor"
    assert "/Users/private" not in str(payload["bindings"])


def test_upload_projection_can_emit_metadata_without_component_bodies():
    snapshot = {
        "head": {"report_id": "r", "title": "Report", "generation": 3},
        "components": [{
            "component_id": "section-1", "parent_id": None, "kind": "section",
            "title": "A", "body": "正文", "content": {"rows": [[1]]},
            "display_kind": "",
        }],
        "bindings": [],
    }
    payload = build_upload_projection(snapshot, include_component_content=False)

    assert payload["content_lazy"] is True
    assert payload["components"][0]["content_available"] is True
    assert payload["components"][0]["body"] == ""
    assert payload["components"][0]["content"] is None


def test_local_chapter_projection_keeps_resource_bytes_on_demand(tmp_path):
    raw = b"local terminal evidence"
    authoring = tmp_path / "branches" / "branch-1" / "authoring"
    authoring.mkdir(parents=True)
    source_file = authoring / "evidence.txt"
    source_file.write_bytes(raw)
    target = source_file.as_uri()
    snapshot = {
        "paths": {"root": authoring},
        "head": {"report_id": "r", "title": "Report", "generation": 1},
        "components": [{
            "component_id": "chapter-1", "parent_id": None, "kind": "chapter",
            "title": "Chapter", "body": f"[证据]({target})", "content": None,
            "display_kind": "",
        }],
        "bindings": [],
    }

    eager = build_upload_projection(snapshot)
    lazy = build_upload_projection(snapshot, include_local_resource_bytes=False)

    assert eager["local_resources"][0]["content_base64"] == base64.b64encode(raw).decode()
    assert lazy["local_resources"][0]["available"] is True
    assert lazy["local_resources"][0]["content_hash"] == hashlib.sha256(raw).hexdigest()
    assert "content_base64" not in lazy["local_resources"][0]


def test_upload_projection_preserves_chapter_timeline_metadata():
    snapshot = {
        "head": {"report_id": "r", "title": "Report", "generation": 4},
        "components": [{
            "component_id": "chapter-1", "parent_id": None, "kind": "chapter",
            "title": "数据契约", "body": "", "content": None,
            "display_kind": "", "created_at": 123.5,
        }],
        "bindings": [],
    }

    payload = build_upload_projection(snapshot)

    assert payload["components"][0]["created_at"] == 123.5
    assert "graph_version" not in payload["components"][0]


def test_upload_projection_reads_assets_next_to_authoring_root(tmp_path):
    raw = b"published figure"
    digest = hashlib.sha256(raw).hexdigest()
    package_root = tmp_path / "work-package"
    (package_root / "authoring").mkdir(parents=True)
    (package_root / "assets").mkdir()
    (package_root / "assets" / f"{digest}.png").write_bytes(raw)
    snapshot = {
        "paths": {"root": package_root / "authoring"},
        "head": {
            "report_id": "r", "title": "Report", "generation": 1,
            "assets": [{
                "asset_ref": f"report-asset:sha256:{digest}",
                "media_type": "image/png", "filename": f"{digest}.png",
                "content_hash": digest, "caption": "Figure", "alt_text": "",
            }],
        },
        "components": [], "bindings": [],
    }

    payload = build_upload_projection(snapshot)

    assert payload["assets"][0]["content_base64"] == base64.b64encode(raw).decode()


def test_local_asset_projection_is_metadata_only_and_reads_on_demand(tmp_path):
    raw = b"local figure"
    digest = hashlib.sha256(raw).hexdigest()
    package_root = tmp_path / "work-package"
    authoring_root = package_root / "authoring"
    authoring_root.mkdir(parents=True)
    assets_root = package_root / "assets"
    assets_root.mkdir()
    asset_ref = f"report-asset:sha256:{digest}"
    (assets_root / "figure.png").write_bytes(raw)
    snapshot = {
        "paths": {"root": authoring_root},
        "head": {
            "report_id": "r", "title": "Report", "generation": 1,
            "assets": [{
                "asset_ref": asset_ref, "media_type": "image/png",
                "filename": "figure.png", "content_hash": digest,
                "caption": "Figure", "alt_text": "",
            }],
        },
        "components": [], "bindings": [],
    }

    payload = build_upload_projection(snapshot, include_asset_bytes=False)

    asset_id = asset_id_for(asset_ref)
    assert payload["assets"][0]["asset_id"] == asset_id
    assert "content_base64" not in payload["assets"][0]
    assert read_local_asset(snapshot, asset_id) == (raw, "image/png", "figure.png")


def test_upload_projection_can_scope_assets_to_selected_chapter():
    first_ref = "report-asset:sha256:" + "a" * 64
    second_ref = "report-asset:sha256:" + "b" * 64
    snapshot = {
        "head": {
            "report_id": "r", "title": "Report", "generation": 1,
            "assets": [
                {
                    "asset_ref": first_ref, "media_type": "image/png",
                    "filename": "a.png", "content_hash": "a" * 64,
                    "caption": "A", "alt_text": "",
                },
                {
                    "asset_ref": second_ref, "media_type": "image/png",
                    "filename": "b.png", "content_hash": "b" * 64,
                    "caption": "B", "alt_text": "",
                },
            ],
        },
        "components": [{
            "component_id": "chapter-a", "parent_id": None, "kind": "chapter",
            "title": "A", "body": "", "display_kind": "",
            "content": {"asset_ref": first_ref},
        }],
        "bindings": [],
    }

    payload = build_upload_projection(snapshot, asset_refs={first_ref})

    assert [item["filename"] for item in payload["assets"]] == ["a.png"]


def test_upload_projection_reads_job_artifact_asset(tmp_path, monkeypatch):
    raw = b"job generated figure"
    digest = hashlib.sha256(raw).hexdigest()
    job_root = tmp_path / "Documents" / "FactorTester" / "jobs" / "job-1"
    job_root.mkdir(parents=True)
    (job_root / "figure.svg").write_bytes(raw)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    snapshot = {
        "head": {
            "report_id": "r", "title": "Report", "generation": 1,
            "assets": [{
                "asset_ref": "factortester-artifact://jobs/job-1/figure.svg",
                "external_ref": "factortester-artifact://jobs/job-1/figure.svg",
                "media_type": "image/svg+xml", "filename": "figure.svg",
                "content_hash": digest, "caption": "Figure", "alt_text": "",
            }],
        },
        "components": [], "bindings": [],
    }

    payload = build_upload_projection(snapshot)

    assert payload["assets"][0]["content_base64"] == base64.b64encode(raw).decode()


def test_upload_projection_does_not_publish_arbitrary_asset_path():
    snapshot = {
        "head": {
            "report_id": "r", "title": "Report", "generation": 1,
            "assets": [{
                "asset_ref": "report-asset:sha256:abc",
                "external_ref": "file:///Users/private/secret.png",
                "media_type": "image/png", "filename": "secret.png",
                "content_hash": "a" * 64, "caption": "", "alt_text": "",
            }],
        },
        "components": [], "bindings": [],
    }

    payload = build_upload_projection(snapshot)

    assert "external_ref" not in payload["assets"][0]


def test_upload_projection_captures_report_relative_local_links(tmp_path):
    package_root = tmp_path / "package"
    authoring_root = package_root / "authoring"
    authoring_root.mkdir(parents=True)
    local_file = package_root / "notes" / "audit.txt"
    local_file.parent.mkdir()
    local_file.write_text("frozen audit result\n", encoding="utf-8")
    snapshot = {
        "paths": {"root": authoring_root},
        "head": {"report_id": "r", "title": "Report", "generation": 1},
        "components": [{
            "component_id": "section-1", "parent_id": None, "kind": "section",
            "title": "证据", "body": "[审计记录](notes/audit.txt)",
            "content": None, "display_kind": "",
        }],
        "bindings": [],
    }

    payload = build_upload_projection(snapshot)

    body = payload["components"][0]["body"]
    assert "factortester-local://" in body
    assert "/notes/audit.txt" not in body
    assert payload["local_resources"][0]["available"] is True
    assert base64.b64decode(payload["local_resources"][0]["content_base64"]) == b"frozen audit result\n"


def test_read_local_resource_resolves_only_requested_report_link(tmp_path):
    package_root = tmp_path / "package"
    authoring_root = package_root / "authoring"
    authoring_root.mkdir(parents=True)
    first = package_root / "notes" / "requested.txt"
    second = package_root / "notes" / "other.txt"
    first.parent.mkdir()
    first.write_text("requested resource\n", encoding="utf-8")
    second.write_text("other resource\n", encoding="utf-8")
    target = "notes/requested.txt"
    resource_id = hashlib.sha256(target.encode("utf-8")).hexdigest()[:24]
    snapshot = {
        "paths": {"root": authoring_root},
        "head": {"report_id": "r-resource", "title": "Report", "generation": 1},
        "components": [{
            "component_id": "section-1", "parent_id": None, "kind": "section",
            "title": "证据", "body": f"[请求文件]({target})",
            "content": None, "display_kind": "",
        }],
        "bindings": [],
    }

    value = read_local_resource(snapshot, resource_id)

    assert value == (b"requested resource\n", "text/plain", "requested.txt")


def test_read_local_resource_rejects_unknown_or_invalid_resource_id(tmp_path):
    snapshot = {
        "paths": {"root": tmp_path / "authoring"},
        "head": {"report_id": "r-resource", "title": "Report", "generation": 1},
        "components": [], "bindings": [],
    }

    assert read_local_resource(snapshot, "not-a-resource") is None
    assert read_local_resource(snapshot, "a" * 24) is None


def test_upload_projection_captures_native_factortester_file_link(tmp_path):
    authoring_root = tmp_path / "package" / "authoring"
    authoring_root.mkdir(parents=True)
    local_file = authoring_root / "assets" / "notes.txt"
    local_file.parent.mkdir()
    local_file.write_text("native local link\n", encoding="utf-8")
    snapshot = {
        "paths": {"root": authoring_root},
        "head": {"report_id": "r-native", "title": "Report", "generation": 1},
        "components": [{
            "component_id": "section-1", "parent_id": None, "kind": "section",
            "title": "证据", "body": "[审计记录](factortester://file/assets/notes.txt)",
            "content": None, "display_kind": "",
        }],
        "bindings": [],
    }

    payload = build_upload_projection(snapshot)

    assert payload["local_resources"][0]["available"] is True


def test_upload_projection_captures_package_research_files_without_sibling_branch_access(
    tmp_path,
):
    package_root = tmp_path / "package"
    authoring_root = package_root / "branches" / "branch-a" / "authoring"
    authoring_root.mkdir(parents=True)
    source = package_root / "research" / "trial-plans" / "day.json"
    source.parent.mkdir(parents=True)
    source.write_text('{"session":"day"}\n', encoding="utf-8")
    sibling = package_root / "branches" / "branch-b" / "secret.json"
    sibling.parent.mkdir(parents=True)
    sibling.write_text("must not publish", encoding="utf-8")
    snapshot = {
        "paths": {"root": authoring_root},
        "head": {"report_id": "r-package", "title": "Report", "generation": 1},
        "components": [{
            "component_id": "section-1", "parent_id": None, "kind": "section",
            "title": "可复核文件",
            "body": (
                "[日盘配置](research/trial-plans/day.json) "
                "file:///" + str(sibling).lstrip("/")
            ),
            "content": None, "display_kind": "",
        }],
        "bindings": [],
    }

    payload = build_upload_projection(snapshot)

    body = payload["components"][0]["body"]
    assert "factortester-local://" in body
    assert "must not publish" not in str(payload)
    available = [item for item in payload["local_resources"] if item["available"]]
    assert [item["filename"] for item in available] == ["day.json"]


def test_upload_projection_keeps_bare_local_uri_as_typed_link(tmp_path):
    authoring_root = tmp_path / "package" / "authoring"
    authoring_root.mkdir(parents=True)
    local_file = authoring_root / "notes.txt"
    local_file.write_text("plain local reference\n", encoding="utf-8")
    snapshot = {
        "paths": {"root": authoring_root},
        "head": {"report_id": "r-bare", "title": "Report", "generation": 1},
        "components": [{
            "component_id": "section-1", "parent_id": None, "kind": "section",
            "title": "证据", "body": "file://" + str(local_file),
            "content": None, "display_kind": "",
        }],
        "bindings": [],
    }

    payload = build_upload_projection(snapshot)

    body = payload["components"][0]["body"]
    assert body.startswith("[notes.txt](factortester-local://")
    assert payload["local_resources"][0]["available"] is True


def test_upload_projection_does_not_read_outside_report_branch(tmp_path):
    authoring_root = tmp_path / "package" / "branches" / "branch-a" / "authoring"
    authoring_root.mkdir(parents=True)
    (tmp_path / "package" / "branches" / "branch-b").mkdir()
    secret = tmp_path / "package" / "branches" / "branch-b" / "secret.txt"
    secret.write_text("do not publish", encoding="utf-8")
    snapshot = {
        "paths": {"root": authoring_root},
        "head": {"report_id": "r-safe", "title": "Report", "generation": 1},
        "components": [{
            "component_id": "section-1", "parent_id": None, "kind": "section",
            "title": "证据", "body": "[越界](../branch-b/secret.txt)",
            "content": None, "display_kind": "",
        }],
        "bindings": [],
    }

    payload = build_upload_projection(snapshot)

    assert payload["local_resources"][0]["available"] is False
    assert "do not publish" not in str(payload)


def test_public_research_local_resource_is_stored_and_read(tmp_path):
    raw = b"terminal-like local evidence"
    digest = hashlib.sha256(raw).hexdigest()
    resource_id = "a" * 24
    projection = {
        "schema_version": 2,
        "report_id": "report-local-resource",
        "title": "Report",
        "language": "zh-Hans",
        "generation": 1,
        "components": [],
        "bindings": [],
        "assets": [],
        "local_resources": [{
            "resource_id": resource_id, "title": "证据文件", "filename": "evidence.txt",
            "media_type": "text/plain", "available": True, "content_hash": digest,
            "content_base64": base64.b64encode(raw).decode("ascii"),
        }],
        "related_objects": [], "attachments": [], "projection_hash": "hash",
    }
    library = PublicResearchLibrary(tmp_path)
    result = library.sync({
        "report_id": "report-local-resource", "owner_ref": "owner", "projection": projection,
    })
    library.configure(
        owner_ref="owner", report_id="report-local-resource", projection=None,
        visibility="public", auto_sync=True, relay_local_files=False, authorized_users=[],
    )

    assert library.local_resource(result["publication_id"], resource_id, None)[:2] == (raw, "text/plain")
    assert "content_base64" not in library.projection(result["publication_id"], None)["local_resources"][0]


def test_public_research_attachment_is_stored_and_read(tmp_path):
    raw = b"frozen factor source"
    digest = hashlib.sha256(raw).hexdigest()
    attachment_ref = f"attachment:sha256:{digest}"
    projection = {
        "schema_version": 2,
        "report_id": "report-attachment",
        "title": "Report",
        "language": "zh-Hans",
        "generation": 1,
        "components": [],
        "bindings": [],
        "assets": [],
        "local_resources": [],
        "related_objects": [{
            "object_kind": "factor",
            "object_ref": "factor:example",
            "title": "示例因子",
            "resolution": "git_snapshot",
            "snapshot": {},
            "attachment_refs": [attachment_ref],
        }],
        "attachments": [{
            "attachment_ref": attachment_ref,
            "attachment_kind": "factor_source",
            "filename": "Example.py",
            "relative_path": "public_factors/Example.py",
            "media_type": "text/x-python",
            "content_hash": digest,
            "git_blob": "a" * 40,
            "revision": "b" * 40,
            "content_base64": base64.b64encode(raw).decode("ascii"),
        }],
        "projection_hash": "hash",
    }
    library = PublicResearchLibrary(tmp_path)
    result = library.sync({
        "report_id": "report-attachment", "owner_ref": "owner", "projection": projection,
    })
    library.configure(
        owner_ref="owner", report_id="report-attachment", projection=None,
        visibility="public", auto_sync=True, relay_local_files=False,
        authorized_users=[],
    )

    assert library.attachment(
        result["publication_id"], attachment_ref, None,
    )[:2] == (raw, "text/x-python")
    stored = library.projection(result["publication_id"], None)
    assert "content_base64" not in stored["attachments"][0]


def test_public_research_sync_removes_unreferenced_attachment_files(tmp_path):
    raw = b"old source"
    old_hash = hashlib.sha256(raw).hexdigest()
    old_ref = f"attachment:sha256:{old_hash}"
    projection = {
        "schema_version": 2,
        "report_id": "report-cleanup",
        "title": "Report",
        "language": "zh-Hans",
        "generation": 1,
        "components": [], "bindings": [], "assets": [],
        "local_resources": [], "related_objects": [],
        "attachments": [{
            "attachment_ref": old_ref, "attachment_kind": "factor_source",
            "filename": "Old.py", "media_type": "text/x-python",
            "content_hash": old_hash,
            "content_base64": base64.b64encode(raw).decode("ascii"),
        }],
        "projection_hash": "hash-1",
    }
    library = PublicResearchLibrary(tmp_path)
    result = library.sync({
        "report_id": "report-cleanup", "owner_ref": "owner", "projection": projection,
    })
    attachment_dir = tmp_path / "mirrors" / result["publication_id"] / "attachments"
    assert (attachment_dir / old_hash).is_file()

    updated = {**projection, "generation": 2, "attachments": [], "projection_hash": "hash-2"}
    library.sync({
        "report_id": "report-cleanup", "owner_ref": "owner", "projection": updated,
    })
    assert not (attachment_dir / old_hash).exists()


def test_upload_projection_attaches_matching_factor_blob(tmp_path, monkeypatch):
    package_root = tmp_path / "package"
    (package_root / "authoring").mkdir(parents=True)
    worktree = package_root / "factor-worktree"
    (worktree / ".git").mkdir(parents=True)
    source = worktree / "public_factors" / "Example.py"
    source.parent.mkdir(parents=True)
    source.write_text("def Example():\n    return 1\n", encoding="utf-8")
    monkeypatch.setattr(
        "tools.cli.release.research_reporting.public_research.attachments._git_blob_at",
        lambda _path: "a" * 40,
    )
    snapshot = {
        "paths": {"root": package_root / "authoring"},
        "head": {"report_id": "r", "title": "Report", "generation": 1},
        "components": [],
        "bindings": [{
            "binding_id": "factor-binding", "component_id": "root",
            "kind": "factor", "target_ref": "factor:example",
            "label": "Example", "data": {
                "relative_path": "public_factors/Example.py",
                "blob_hash": "a" * 40, "revision": "b" * 40,
                "identity": "Example|P:CA", "scope": "profile-maxa",
            },
        }],
    }

    payload = build_upload_projection(snapshot)

    assert payload["related_objects"][0]["resolution"] == "git_snapshot"
    assert payload["related_objects"][0]["attachment_refs"]
    assert payload["attachments"][0]["attachment_kind"] == "factor_source"
