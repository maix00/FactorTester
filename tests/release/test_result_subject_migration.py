from __future__ import annotations

import json

from click.testing import CliRunner

from server.services.research_step.result_reporting.projection import (
    build_result_report_projection,
)
from tools.cli.app import cli
from tests.release.test_local_research_report import (
    _carrier,
    _profile,
    publish_research_checkpoint,
)
from tools.cli.release.research_reporting.publisher import (
    publish_current_node_report_checkpoint,
)
from tools.cli.release.research_reporting.report_items import (
    report_fragment_hash,
    report_item_hash,
)
from tools.cli.release.research_reporting.result_subject_apply import (
    migrate_result_subject_package,
)


def test_result_subject_package_migration_is_complete_and_idempotent(
    tmp_path,
):
    root = tmp_path / "client-support"
    _profile(root)
    carrier = _carrier()
    carrier["current_node"] = "trial_execution"
    carrier["latest_transition"]["from_node"] = "trial_execution"
    carrier["latest_transition"]["to_node"] = "trial_execution"
    publish_research_checkpoint(
        client_root=root, profile_id="maxa",
        agent_id="research-maxa", carrier=carrier,
    )
    projection = build_result_report_projection(
        action={
            "action_id": "action:in-sample-ic",
            "output_evidence_refs": ["evidence:" + "a" * 64],
        },
        plan_hash="b" * 64,
        rows=[{
            "index": 1, "run_id": "run-1", "job_id": "job-1",
            "kind": "ic", "status": "succeeded",
            "trial_role": "candidate", "run_spec_hash": "c" * 64,
            "run_spec_alias_zh": "截面 IC · 日盘",
            "result_summary": {"mean": 0.031},
        }],
        receipt=None,
    )
    _corrupt_subjects(projection)
    publish_current_node_report_checkpoint(
        client_root=root, profile_id="maxa",
        agent_id="research-maxa", carrier=carrier,
        projection=projection,
    )
    package = root / "profile-root" / "research" / "sgccs-review"
    protocol = package / "protocol"
    protocol.mkdir()
    (protocol / "bootstrap-evidence.json").write_text(json.dumps({
        "identity_refs": {"methodology_hash": "1" * 64},
    }))
    (protocol / "decision-contract.json").write_text(json.dumps({
        "scope": {"product_group": "CNFutures"},
    }))
    section_root = package / "branches" / "branch-sgccs" / "sections"
    old_paths = {
        path for path in section_root.glob("*.json")
        if "action:action:" in path.read_text()
    }
    assert len(old_paths) == 1

    receipt = migrate_result_subject_package(
        package_root=package, branch_id="branch-sgccs",
        apply=True, client_root=root, profile_id="maxa",
        agent_id="research-maxa",
    )

    assert receipt["mode"] == "applied"
    assert receipt["changed_fragment_count"] == 1
    assert all(not path.exists() for path in old_paths)
    assert all(
        "action:action:" not in path.read_text()
        and "audit:action:" not in path.read_text()
        for path in [
            *section_root.glob("*.json"),
            package / "branches" / "branch-sgccs" / "JOURNAL.json",
            package / "branches" / "branch-sgccs" / "LOGICAL_JOURNAL.json",
            package / "branches" / "branch-sgccs" / "REPORT.md",
            package / "INDEX.json",
            package / "REPORT.md",
        ]
    )
    assert set(receipt["projection_hashes"]) == {
        "index", "work_package_report", "physical_journal",
        "logical_journal", "branch_report",
    }
    assert receipt["projection_hashes"]["physical_journal"][
        "before"
    ] != receipt["projection_hashes"]["physical_journal"]["after"]
    assert receipt["projection_hashes"]["logical_journal"][
        "before"
    ] != receipt["projection_hashes"]["logical_journal"]["after"]
    persisted = json.loads((
        package / "migrations"
        / "result-action-subject-v1.receipt.json"
    ).read_text())
    assert persisted == receipt
    assert not (
        package / "migrations" / "result-action-subject-v1.backup.zip"
    ).exists()

    replay = migrate_result_subject_package(
        package_root=package, branch_id="branch-sgccs",
        apply=True, client_root=root, profile_id="maxa",
        agent_id="research-maxa",
    )
    assert replay["mode"] == "already_applied"
    assert replay["changed"] is False

    help_result = CliRunner().invoke(
        cli, ["client", "research", "migrate-result-subjects", "--help"],
    )
    assert help_result.exit_code == 0
    assert "--product-group" not in help_result.output
    assert "--current-node" not in help_result.output


def _corrupt_subjects(projection):
    submitted = []
    for item in projection["local_report_items"]:
        subject = item["subject_ref"]
        subject = (
            "action:" + subject
            if subject.startswith("action:")
            else "audit:action:" + subject.removeprefix("audit:")
        )
        item["subject_ref"] = subject
        item["report_binding"]["subject_ref"] = subject
        item["item_hash"] = report_item_hash(
            report_requirement_id=item["report_requirement_id"],
            subject_ref=subject, content_kind=item["content_kind"],
            content=item["content"],
        )
        submitted.append({
            key: item[key] for key in (
                "report_requirement_id", "subject_ref",
                "content_kind", "item_hash",
            )
        })
    projection["report_submission"] = {
        "schema_version": 1,
        "fragment_hash": report_fragment_hash(submitted),
        "items": submitted,
    }
