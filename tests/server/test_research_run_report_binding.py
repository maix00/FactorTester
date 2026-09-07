from __future__ import annotations

import pytest

import settings as Settings
from server.jobs.repository import JobRepository
from server.services import research_runs
from server.services.research_run_report_binding import (
    normalize_report_binding,
)
from server.services.research_graph.trial_plan import trial_plan_hash
from tests.server.trial_plan_fixtures import (
    initialize_branch,
    job_record,
    run_spec,
    semantic_hash,
    trial_binding,
    trial_plan,
)


def _binding() -> dict:
    return {
        "profile_ref": "profile:maxa",
        "work_package_ref": "work-package:package-1",
        "instance_id": "instance-1",
        "branch_id": "branch-1",
        "report_id": "report-package-1-branch-1",
        "report_generation": 7,
        "report_head_hash": "b" * 64,
    }


def test_plain_job_needs_no_report_binding() -> None:
    assert normalize_report_binding(
        None,
        trial_binding=None,
        branch_snapshot={},
    ) is None


def test_report_binding_freezes_server_owned_execution_node() -> None:
    value = normalize_report_binding(
        _binding(),
        trial_binding={
            "instance_id": "instance-1",
            "branch_id": "branch-1",
        },
        branch_snapshot={
            "work_package_ref": "work-package:package-1",
            "execution_node": "trial_execution",
        },
    )

    assert value == {
        **_binding(),
        "execution_node": "trial_execution",
    }


def test_report_binding_rejects_a_different_owned_scope() -> None:
    with pytest.raises(ValueError, match="work_package_ref"):
        normalize_report_binding(
            _binding(),
            trial_binding={
                "instance_id": "instance-1",
                "branch_id": "branch-1",
            },
            branch_snapshot={
                "work_package_ref": "work-package:another-package",
                "execution_node": "trial_execution",
            },
        )


def test_report_binding_cannot_exist_without_trial_binding() -> None:
    with pytest.raises(ValueError, match="requires trial_binding"):
        normalize_report_binding(
            _binding(),
            trial_binding=None,
            branch_snapshot={},
        )


@pytest.mark.parametrize("report_id", ["report-package-1-branch-1", "report:v1:m0zMIM6zzugveWCEt5CG0Rvl"])
def test_direct_report_binding_freezes_an_explicit_parent_without_graph_node(report_id) -> None:
    value = normalize_report_binding(
        {
            "binding_origin": "agent_direct",
            "profile_ref": "profile:maxa",
            "work_package_ref": "work-package:package-1",
            "branch_id": "branch-1",
            "report_id": report_id,
            "report_generation": 7,
            "report_head_hash": "b" * 64,
            "report_parent_id": "direct-trials",
        },
        trial_binding={"binding_origin": "agent_direct"},
        branch_snapshot={},
    )

    assert value["report_id"] == report_id
    assert value["binding_origin"] == "agent_direct"
    assert value["report_parent_id"] == "direct-trials"
    assert value["execution_node"] == ""


@pytest.mark.parametrize("report_id", ["report-package-1-branch-1", "report:v1:m0zMIM6zzugveWCEt5CG0Rvl"])
def test_research_run_and_job_detail_retain_frozen_report_identity(
    tmp_path, monkeypatch, report_id,
) -> None:
    path = tmp_path / "report-binding.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    run_spec_value = run_spec()
    plan = trial_plan(semantic_hash(run_spec_value))
    initialize_branch(path, trial_plan_hash(plan))
    report_binding = {
        **_binding(),
        "report_id": report_id,
        "work_package_ref": "work-package:instance-1",
    }

    run = research_runs.create_run(
        owner="alice",
        workspace_id="workspace-1",
        configuration_id="configuration-1",
        configuration_revision=1,
        run_spec=run_spec_value,
        trial_binding=trial_binding(plan),
        report_binding=report_binding,
    )
    job = JobRepository(path).create(
        job_record(run["run_id"], run_spec_value)
    )
    detail = JobRepository(path).load_detail(job.job_id, owner="alice")

    expected = {
        **report_binding,
        "execution_node": "validation_design",
    }
    assert run["report_binding"] == expected
    assert research_runs.load_run(
        run_id=run["run_id"], owner="alice",
    )["report_binding"] == expected
    assert detail is not None
    assert detail["report_binding"] == expected


def test_graph_run_workspace_is_execution_provenance_not_branch_authority(
    tmp_path, monkeypatch,
) -> None:
    path = tmp_path / "workspace-provenance.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    run_spec_value = run_spec()
    plan = trial_plan(semantic_hash(run_spec_value))
    initialize_branch(path, trial_plan_hash(plan))

    run = research_runs.create_run(
        owner="alice",
        workspace_id="workspace-used-for-this-run",
        configuration_id="configuration-1",
        configuration_revision=1,
        run_spec=run_spec_value,
        trial_binding=trial_binding(plan),
    )

    assert run["workspace_id"] == "workspace-used-for-this-run"
    assert run["graph_branch_id"] == "branch-1"


@pytest.mark.parametrize("report_id", ["report:v1:", "report:v2:id", "report:v1:../escape", "report:v1:%2Fescape", "report:v1:id/child"])
def test_report_catalog_identity_does_not_accept_other_namespaces_or_paths(report_id):
    binding = {**_binding(), "report_id": report_id}
    with pytest.raises(ValueError, match="report_binding.report_id"):
        normalize_report_binding(binding, trial_binding={"instance_id": "instance-1", "branch_id": "branch-1"}, branch_snapshot={"work_package_ref": "work-package:package-1"})
