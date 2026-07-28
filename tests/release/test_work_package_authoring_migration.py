from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

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
from tools.cli.release.research_reporting.document import (
    add_binding,
    add_component,
    bindings_path_for,
    new_bindings,
    new_document,
    save_bindings,
    save_document,
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
    document = add_component(
        new_document("legacy-document", "旧报告"),
        component_id="table", kind="table", title="结果",
        content={"columns": ["指标"], "rows": [["Sharpe"]]},
    )
    bindings = add_binding(
        new_bindings(document), document, component_id="table",
        binding_id="job-1", kind="job", target_ref="job:1",
    )
    root_document = package / "REPORT.json"
    save_document(root_document, document)
    save_bindings(bindings_path_for(root_document), bindings, document)
    return client_root, package, store


def test_migration_moves_only_root_document_and_preserves_custom_material(
    tmp_path: Path,
) -> None:
    client_root, package, store = _legacy_profile(tmp_path)
    root_document = package / "REPORT.json"
    root_bindings = bindings_path_for(root_document)
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
    document = add_component(
        new_document("legacy-document", "旧报告"),
        component_id="table", kind="table", title="结果",
        content={"columns": ["指标"], "rows": [["Sharpe"]]},
    )
    bindings = add_binding(
        new_bindings(document), document, component_id="table",
        binding_id="job-1", kind="job", target_ref="job:1",
    )
    assert equivalent_to_document(snapshot, document, bindings)
    assert hashlib.sha256(preserved.read_bytes()).hexdigest() == preserved_hash
    assert (package / "INDEX.json").is_file()
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
    assert migration_receipt["source_root_report"] == str(root_document)

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
