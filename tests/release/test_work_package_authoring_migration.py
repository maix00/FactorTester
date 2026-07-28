from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pytest
from click.testing import CliRunner

from tools.cli.app import cli
from tools.cli.commands import client_research_migration
from tools.cli.release.local_profile import LocalProfileStore, new_local_profile
from tools.cli.release.research_reporting.authoring import (
    migrate_profile_work_packages,
)
from tools.cli.release.research_reporting.authoring.legacy_import import (
    equivalent_to_document,
)
from tools.cli.release.research_reporting.authoring.tree_model import load_snapshot
from tools.cli.release.research_reporting.authoring.legacy_document import (
    legacy_bindings_path,
    legacy_document_hash,
)


def _legacy_profile(tmp_path: Path) -> tuple[Path, Path, LocalProfileStore]:
    client_root = tmp_path / "client"
    workspace_root = tmp_path / "workspace"
    store = LocalProfileStore(client_root)
    profile = new_local_profile(
        profile_id="maxa", display_name="MaxA",
        server_url="http://127.0.0.1:8141", workspace_root=workspace_root,
    )
    profile["research_records"] = [{
        "record_id": "package-1", "title": "旧报告",
        "status": "pending", "scope": {"factor_families": ["SgCCS"]},
        "factor_family_versions": ["MaxA:SgCCS@1"],
        "agent_id": "research-maxa", "created_at": 1.0, "updated_at": 1.0,
        "workspace_ref": "workspace:workspace-1", "run_ref": "",
        "graph_instance_ref": "work-package:package-1",
        "graph_branch_ref": "graph-branch:instance-1:branch-1",
        "checkpoint_ref": "", "evidence_refs": [], "timeline_refs": [],
        "artifacts": [{
            "artifact_ref": "artifact:research/package-1/REPORT.json",
            "format": "document", "status": "ready", "content_hash": "0" * 64,
            "local_ref": "file:///old/REPORT.json", "index_ref": "",
            "section_refs": [],
        }], "provenance": {"kind": "owned_research"},
    }]
    store.save(profile)
    package = workspace_root / "research" / "package-1"
    (package / "grill" / "assets").mkdir(parents=True)
    (package / ".report.lock").write_text("transient\n", encoding="utf-8")
    preserved = package / "grill" / "assets" / "private-note.txt"
    preserved.write_text("do not rewrite\n", encoding="utf-8")
    document, bindings = _legacy_document_and_bindings()
    root_document = package / "REPORT.json"
    root_document.write_text(json.dumps(document), encoding="utf-8")
    legacy_bindings_path(root_document).write_text(
        json.dumps(bindings), encoding="utf-8",
    )
    return client_root, package, store


def test_migration_moves_only_root_document_and_preserves_custom_material(
    tmp_path: Path,
) -> None:
    client_root, package, store = _legacy_profile(tmp_path)
    root_document = package / "REPORT.json"
    root_bindings = legacy_bindings_path(root_document)
    preserved = package / "grill" / "assets" / "private-note.txt"
    preserved_hash = hashlib.sha256(preserved.read_bytes()).hexdigest()

    dry_run = migrate_profile_work_packages(
        client_root=client_root, profile_id="maxa", apply=False,
    )
    assert dry_run["items"][0]["status"] == "would_migrate"
    assert root_document.exists()

    receipt = migrate_profile_work_packages(
        client_root=client_root, profile_id="maxa", apply=True,
    )
    item = receipt["items"][0]
    target = package / "branches" / "branch-1" / "authoring"
    assert item["status"] == "migrated"
    assert not root_document.exists()
    assert not root_bindings.exists()
    assert (target / "HEAD.json").is_file()
    snapshot = load_snapshot(package_root=package, branch_id="branch-1")
    document, bindings = _legacy_document_and_bindings()
    assert equivalent_to_document(snapshot, document, bindings)
    assert hashlib.sha256(preserved.read_bytes()).hexdigest() == preserved_hash
    assert not (package / "INDEX.json").exists()
    assert (package / "branches" / "branch-1" / "REPORT.md").is_file()
    assert (package / ".git").is_dir()
    tracked = subprocess.run(
        ["git", "-C", str(package), "ls-files"],
        check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    assert "grill/assets/private-note.txt" in tracked
    assert ".gitignore" in tracked
    assert ".report.lock" not in tracked
    assert subprocess.run(
        ["git", "-C", str(package), "status", "--porcelain"],
        check=True, capture_output=True, text=True,
    ).stdout == ""
    record = store.load("maxa")["research_records"][0]
    assert record["artifacts"][-1]["local_ref"].endswith(
        "/branches/branch-1/authoring/HEAD.json"
    )
    assert not any(
        item["artifact_ref"].endswith("/REPORT.json")
        for item in record["artifacts"]
    )
    migration_receipt = json.loads(Path(item["receipt"]).read_text(encoding="utf-8"))
    assert migration_receipt["sources"] == [{
        "branch_id": "branch-1", "document": str(root_document),
        "bindings": str(root_bindings),
        "document_hash": migration_receipt["sources"][0]["document_hash"],
        "bindings_hash": migration_receipt["sources"][0]["bindings_hash"],
    }]

    second = migrate_profile_work_packages(
        client_root=client_root, profile_id="maxa", apply=True,
    )
    assert second["items"][0]["status"] == "ready"
    assert second["items"][0]["git"]["committed"] is False
    assert json.loads(Path(item["receipt"]).read_text(encoding="utf-8")) == migration_receipt


def test_migration_command_defaults_to_dry_run(tmp_path, monkeypatch) -> None:
    client_root, package, _ = _legacy_profile(tmp_path)
    monkeypatch.setattr(
        client_research_migration, "load_profile_root", lambda _: client_root,
    )
    result = CliRunner().invoke(cli, [
        "client", "research", "migrate-work-packages", "maxa",
    ])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["apply"] is False
    assert (package / "REPORT.json").exists()


def test_migration_converts_each_branch_journal_then_removes_it(tmp_path: Path) -> None:
    client_root, package, _ = _legacy_profile(tmp_path)
    journal = package / "branches" / "history" / "JOURNAL.json"
    journal.parent.mkdir(parents=True)
    journal.write_text(json.dumps({
        "checkpoints": [{
            "checkpoint_ref": "trace:legacy", "sections": [{
                "section_id": "outcome", "title": "历史结果", "body": "说明",
                "asset_refs": [], "evidence_refs": ["evidence:legacy"],
                "links": [{"link_id": "job", "kind": "job", "target_ref": "job:1", "label": "回测"}],
                "blocks": [{"kind": "table", "columns": ["指标"], "rows": [{"cells": ["Sharpe"]}]}],
            }],
        }],
    }, ensure_ascii=False), encoding="utf-8")

    result = migrate_profile_work_packages(
        client_root=client_root, profile_id="maxa", apply=True,
    )

    assert result["items"][0]["status"] == "migrated"
    assert not journal.exists()
    assert not (package / "INDEX.json").exists()
    snapshot = load_snapshot(package_root=package, branch_id="history")
    assert [item["kind"] for item in snapshot["components"]] == [
        "chapter", "section", "table",
    ]
    assert any(item["target_ref"] == "job:1" for item in snapshot["bindings"])
    assert "| 指标 |" in (package / "branches" / "history" / "REPORT.md").read_text()


def test_migration_imports_branch_document_and_preserves_user_section_file(
    tmp_path: Path,
) -> None:
    client_root, package, _ = _legacy_profile(tmp_path)
    document, bindings = _legacy_document_and_bindings()
    branch = package / "branches" / "history"
    document_path = branch / "authoring" / "DOCUMENT.json"
    document_path.parent.mkdir(parents=True)
    document_path.write_text(json.dumps(document), encoding="utf-8")
    branch.joinpath("authoring", "BINDINGS.json").write_text(
        json.dumps(bindings), encoding="utf-8",
    )
    journal = branch / "JOURNAL.json"
    journal.write_text(json.dumps({"checkpoints": []}), encoding="utf-8")
    custom = branch / "sections" / "notes.json"
    custom.parent.mkdir()
    custom.write_text(json.dumps({"note": "keep"}), encoding="utf-8")

    result = migrate_profile_work_packages(
        client_root=client_root, profile_id="maxa", apply=True,
    )

    assert result["items"][0]["status"] == "migrated"
    assert not document_path.exists()
    assert not branch.joinpath("authoring", "BINDINGS.json").exists()
    assert not journal.exists()
    assert custom.read_text(encoding="utf-8") == '{"note": "keep"}'
    assert equivalent_to_document(
        load_snapshot(package_root=package, branch_id="history"), document, bindings,
    )


def test_migration_rejects_unmatched_legacy_projection_before_writing(
    tmp_path: Path,
) -> None:
    client_root, package, _ = _legacy_profile(tmp_path)
    branch = package / "branches" / "history"
    journal = branch / "JOURNAL.json"
    journal.parent.mkdir(parents=True)
    journal.write_text(json.dumps({"checkpoints": []}), encoding="utf-8")
    carrier = branch / "sections" / "stale.json"
    carrier.parent.mkdir()
    carrier.write_text(json.dumps({
        "schema_version": 3, "checkpoint_ref": "trace:stale",
        "sections": [], "section_hash": "stale",
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="does not match JOURNAL"):
        migrate_profile_work_packages(
            client_root=client_root, profile_id="maxa", apply=True,
        )

    assert journal.exists()
    assert carrier.exists()
    assert (package / "REPORT.json").exists()
    assert not (package / "branches" / "branch-1" / "authoring" / "HEAD.json").exists()


def _legacy_document_and_bindings() -> tuple[dict, dict]:
    document = {
        "schema_version": 2, "document_id": "legacy-document",
        "title": "旧报告", "language": "zh-Hans", "revision": 1,
        "components": [{
            "component_id": "table", "kind": "table", "parent_id": None,
            "title": "结果", "body": "", "display_kind": "",
            "content": {"columns": ["指标"], "rows": [["Sharpe"]]},
            "created_at": 1.0,
        }], "assets": [],
    }
    return document, {
        "schema_version": 1, "document_id": "legacy-document",
        "document_hash": legacy_document_hash(document), "migration": None,
        "bindings": [{
            "binding_id": "job-1", "component_id": "table", "kind": "job",
            "target_ref": "job:1", "label": "", "data": {},
        }],
    }
