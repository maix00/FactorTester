import base64
import hashlib

from tools.cli.release.research_reporting.public_research.library import PublicResearchLibrary
from tools.cli.release.research_reporting.public_research.projection import build_upload_projection


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


def test_upload_projection_preserves_chapter_timeline_metadata():
    snapshot = {
        "head": {"report_id": "r", "title": "Report", "generation": 4},
        "components": [{
            "component_id": "chapter-1", "parent_id": None, "kind": "chapter",
            "title": "数据契约", "body": "", "content": None,
            "display_kind": "", "created_at": 123.5, "graph_version": "v10",
        }],
        "bindings": [],
    }

    payload = build_upload_projection(snapshot)

    assert payload["components"][0]["created_at"] == 123.5
    assert payload["components"][0]["graph_version"] == "v10"


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
