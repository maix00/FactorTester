from pathlib import Path

from scripts.research.migrate_work_package_report_identity import migrate
from tools.cli.release.research_reporting.authoring.tree_model import initialize_tree
from tools.cli.release.research_reporting.authoring.tree_paths import report_tree_paths
from tools.cli.release.research_reporting.authoring.tree_store import load_head


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

    plan = migrate(package, apply=False)
    assert plan["report_id"] == "report-momentum"
    assert plan["changed_branch_count"] == 2
    assert not (package / "work-package.json").exists()

    result = migrate(package, apply=True)
    assert result["status"] == "migrated"
    assert {
        load_head(report_tree_paths(package, branch))["report_id"]
        for branch in ("main", "trial")
    } == {"report-momentum"}
    assert (package / "work-package.json").is_file()
    assert (package / "work-package-report-identity-migration.json").is_file()
