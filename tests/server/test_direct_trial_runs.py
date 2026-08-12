from __future__ import annotations

import settings as Settings
import pytest

from server.services import direct_trial_plan_registry, research_runs
from server.services.direct_trial_plans import create_binding
from tests.server.trial_plan_fixtures import run_spec, semantic_hash, trial_plan


def test_direct_trial_run_does_not_require_a_graph_branch(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "direct-run.sqlite")
    run_spec_value = run_spec()
    run_hash = semantic_hash(run_spec_value)
    binding = create_binding(
        trial_plan=trial_plan(run_hash),
        run_spec_hash=run_hash,
        trial_role="selection",
        comparison_id="main-comparison",
    )
    direct_trial_plan_registry.save(owner="alice", binding=binding)

    run = research_runs.create_run(
        owner="alice",
        workspace_id="workspace-1",
        configuration_id="configuration-1",
        configuration_revision=1,
        run_spec=run_spec_value,
        trial_binding=binding,
    )

    assert run["trial_plan_hash"] == binding["trial_plan_hash"]
    assert run["graph_instance_id"] == ""
    assert run["graph_branch_id"] == ""
    assert run["graph_execution_node"] == ""


def test_direct_trial_run_persists_its_report_parent(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "direct-report.sqlite")
    run_spec_value = run_spec()
    run_hash = semantic_hash(run_spec_value)
    binding = create_binding(
        trial_plan=trial_plan(run_hash),
        run_spec_hash=run_hash,
        trial_role="selection",
        comparison_id="main-comparison",
    )
    direct_trial_plan_registry.save(owner="alice", binding=binding)
    report_binding = {
        "binding_origin": "agent_direct",
        "profile_ref": "profile:maxa",
        "work_package_ref": "work-package:package-1",
        "branch_id": "branch-1",
        "report_id": "report-package-1-branch-1",
        "report_generation": 7,
        "report_head_hash": "b" * 64,
        "report_parent_id": "direct-trials",
    }

    created = research_runs.create_run(
        owner="alice",
        workspace_id="workspace-1",
        configuration_id="configuration-1",
        configuration_revision=1,
        run_spec=run_spec_value,
        trial_binding=binding,
        report_binding=report_binding,
    )
    loaded = research_runs.load_run(run_id=created["run_id"], owner="alice")

    assert created["report_binding"]["report_parent_id"] == "direct-trials"
    assert loaded["report_binding"] == created["report_binding"]


def test_direct_trial_run_rejects_an_unregistered_binding(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(
        Settings, "CACHE_DB_PATH", tmp_path / "unregistered-direct.sqlite",
    )
    run_spec_value = run_spec()
    run_hash = semantic_hash(run_spec_value)
    binding = create_binding(
        trial_plan=trial_plan(run_hash),
        run_spec_hash=run_hash,
        trial_role="selection",
        comparison_id="main-comparison",
    )

    with pytest.raises(ValueError, match="not registered"):
        research_runs.create_run(
            owner="alice",
            workspace_id="workspace-1",
            configuration_id="configuration-1",
            configuration_revision=1,
            run_spec=run_spec_value,
            trial_binding=binding,
        )
