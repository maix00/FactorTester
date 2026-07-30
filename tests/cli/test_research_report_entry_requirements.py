from __future__ import annotations

import pytest
import click

from tools.cli.commands.research_graph_local_report import (
    resolve_local_graph_report,
)
from tools.cli.commands.research_graph_report_policy import report_container
from tools.cli.commands.research_graph_report_sync import (
    synchronize_report_container,
)
from tools.cli.commands.research_report_entry_requirement import (
    obligation_requirement_body,
)
from tools.cli.release.local_profile import (
    LocalProfileStore,
    new_local_profile,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    load_snapshot,
)
from tools.cli.release.research_reporting.workspace import (
    initialize_work_package,
)


def test_node_checks_create_one_system_overview_only_when_present(
    tmp_path,
) -> None:
    scope = _scope(tmp_path)
    no_checks = synchronize_report_container(
        scope,
        container=report_container(_packet([])),
        commit=False,
    )
    assert no_checks["entry_requirements_summary"] == {
        "changed": False,
        "component_id": "",
    }
    with_checks = synchronize_report_container(
        scope,
        container=report_container(_packet([{
            "requirement_id": "factor_semantics.expression_identity",
            "title_zh": "表达式身份",
            "gate_policy": "required",
            "detail_ref": (
                "graph-requirement:"
                "factor_semantics.expression_identity"
            ),
        }])),
        commit=False,
    )
    repeated = synchronize_report_container(
        scope,
        container=report_container(_packet([{
            "requirement_id": "factor_semantics.expression_identity",
            "title_zh": "表达式身份",
        }])),
        commit=False,
    )

    assert with_checks["entry_requirements_summary"]["changed"] is True
    assert repeated["entry_requirements_summary"]["changed"] is False
    snapshot = load_snapshot(
        package_root=scope.package_root,
        branch_id=scope.branch_id,
    )
    summaries = [
        item for item in snapshot["components"]
        if item["display_kind"] == "entry_requirements"
    ]
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary["parent_id"] == with_checks["component_id"]
    assert "factortester://entry_requirement/" in summary["body"]
    assert any(
        binding["kind"] == "entry_requirement"
        and binding["target_ref"] == (
            "requirement:factor_semantics.expression_identity"
        )
        for binding in snapshot["bindings"]
        if binding["component_id"] == summary["component_id"]
    )


def test_authored_obligation_category_requires_exact_special_contract() -> None:
    body = obligation_requirement_body(
        body="核对因子表达式",
        kind="special",
        display_kind="obligation_requirement",
        requirement_id="factor_semantics.expression_identity",
    )
    assert "核对因子表达式" in body
    assert "factortester://entry_requirement/" in body
    assert "requirement%3Afactor_semantics.expression_identity" in body

    with pytest.raises(click.ClickException):
        obligation_requirement_body(
            body="",
            kind="section",
            display_kind="obligation_requirement",
            requirement_id="factor_semantics.expression_identity",
        )


def _packet(requirements):
    return {
        "graph": "factor-research@v10",
        "current_node": "hypothesis_preregistration",
        "node": {"node_id": "hypothesis_preregistration"},
        "entry_requirements": requirements,
        "report_container": {
            "kind": "chapter",
            "anchor_node": "hypothesis_preregistration",
        },
    }


def _scope(tmp_path):
    client_root = tmp_path / "client"
    workspace = tmp_path / "workspace"
    profile = new_local_profile(
        profile_id="maxa",
        display_name="MaxA",
        server_url="http://127.0.0.1:8141",
        workspace_root=workspace,
    )
    profile["research_records"] = [{
        "record_id": "wp",
        "title": "研究",
        "status": "pending",
        "scope": {},
        "factor_family_versions": [],
        "agent_id": "research-maxa",
        "created_at": 1,
        "updated_at": 1,
        "workspace_ref": "workspace:1",
        "run_ref": "",
        "graph_instance_ref": "work-package:instance",
        "graph_branch_ref": "graph-branch:instance:branch",
        "checkpoint_ref": "",
        "evidence_refs": [],
        "timeline_refs": [],
        "artifacts": [],
        "provenance": {"kind": "owned_research"},
    }]
    LocalProfileStore(client_root).save(profile)
    initialize_work_package(
        workspace_root=workspace,
        work_package_id="wp",
        branch_id="branch",
        workspace_id="1",
        title="研究",
        branch_ref="graph-branch:instance:branch",
    )
    return resolve_local_graph_report(
        client_root=client_root,
        profile_id="maxa",
        agent_id="research-maxa",
        instance_id="instance",
        branch_id="branch",
    )
