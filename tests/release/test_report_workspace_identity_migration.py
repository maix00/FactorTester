import json
from pathlib import Path

from tools.cli.release.research_reporting.authoring.tree_model import initialize_tree
from tools.cli.release.research_reporting.authoring.tree_paths import report_tree_paths
from tools.cli.release.research_reporting.authoring.tree_store import load_head
from tools.cli.release.research_reporting.report_identity_migration import (
    migrate_report_workspace_identity,
)


def test_legacy_branch_report_ids_collapse_without_splitting_package(tmp_path: Path):
    package = tmp_path / "momentum"
    initialize_tree(
        package_root=package, branch_id="main", report_id="legacy-main",
        title="动量研究",
    )
    initialize_tree(
        package_root=package, branch_id="trial", report_id="legacy-trial",
        title="动量研究",
    )

    plan = migrate_report_workspace_identity(package, apply=False)
    assert plan["report_id"] == "report-momentum"
    assert plan["changed_branch_count"] == 2
    assert not (package / "report-workspace.json").exists()

    result = migrate_report_workspace_identity(package, apply=True)
    assert result["status"] == "migrated"
    assert {
        load_head(report_tree_paths(package, branch))["report_id"]
        for branch in ("main", "trial")
    } == {"report-momentum"}
    assert (package / "report-workspace.json").is_file()
    assert (package / "report-workspace-report-identity-migration.json").is_file()


def test_explicit_identity_migration_upgrades_legacy_v2_head(tmp_path: Path):
    package = tmp_path / "legacy"
    initialize_tree(
        package_root=package, branch_id="main", report_id="legacy-report",
        title="旧报告",
    )
    paths = report_tree_paths(package, "main")
    legacy = {**load_head(paths), "schema_version": 2}
    paths["head"].write_text(json.dumps(legacy), encoding="utf-8")

    plan = migrate_report_workspace_identity(package, apply=False)
    assert plan["upgraded_head_count"] == 1
    assert json.loads(paths["head"].read_text())["schema_version"] == 2

    migrate_report_workspace_identity(package, apply=True)
    assert load_head(paths)["schema_version"] == 3
