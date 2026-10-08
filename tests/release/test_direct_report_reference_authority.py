from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.cli.http import HttpClientError
from tools.cli.release.research_reporting.authoring.declared_links import (
    DeclaredReportReference,
)
from tools.cli.release.research_reporting.references.authority import (
    validate_declared_reference,
)


def test_direct_trial_plan_uses_owner_registry_without_timeline(
    tmp_path: Path,
) -> None:
    target = "trial-plan:sha256:" + "b" * 64
    class Client:
        def get_direct_trial_plan(self, requested):
            assert requested == target
            return {
                "binding_origin": "agent_direct",
                "trial_plan_ref": target,
                "trial_plan_hash": "b" * 64,
                "trial_plan_id": "direct-plan",
                "trial_plan_version": 1,
                "title_zh": "直接试验计划",
            }

        def list_profile_research_branch_timeline(self, *args, **kwargs):
            raise AssertionError("direct TrialPlan must not require timeline")

    result = _validate(tmp_path, "trial_plan", target, Client())

    assert result["data"]["binding_origin"] == "agent_direct"
    assert result["data"]["authority_scope"] == "direct_registry"


def test_trial_plan_server_failure_does_not_fall_back_to_timeline(
    tmp_path: Path,
) -> None:
    target = "trial-plan:sha256:" + "f" * 64

    class Client:
        def get_direct_trial_plan(self, requested):
            raise HttpClientError(500, "/api/trial-plans/direct", "unavailable")

        def list_profile_research_branch_timeline(self, *args, **kwargs):
            raise AssertionError("server failure must not use timeline")

    with pytest.raises(HttpClientError) as error:
        _validate(tmp_path, "trial_plan", target, Client())

    assert error.value.status == 500


def test_run_uses_owner_registry_without_timeline(tmp_path: Path) -> None:
    class Client:
        def get_run(self, run_id):
            return {"run_id": run_id, "run_spec_hash": "d" * 64}

        def list_profile_research_branch_timeline(self, *args, **kwargs):
            raise AssertionError("owned Run must not require timeline")

    result = _validate(tmp_path, "run", "run:direct-run-1", Client())

    assert result["data"]["run_id"] == "direct-run-1"
    assert result["data"]["authority_scope"] == "owner_run_registry"


def test_run_spec_uses_owner_registry_without_timeline(tmp_path: Path) -> None:
    class Client:
        def get_run_spec(self, run_spec_hash):
            return {"run_spec_hash": run_spec_hash, "run_spec_version": 3}

        def list_profile_research_branch_timeline(self, *args, **kwargs):
            raise AssertionError("owned RunSpec must not require timeline")

    target = "runspec:sha256:" + "e" * 64
    result = _validate(tmp_path, "run_spec", target, Client())

    assert result["data"]["run_spec_hash"] == "e" * 64
    assert result["data"]["authority_scope"] == "owner_run_registry"


def _validate(
    tmp_path: Path,
    kind: str,
    target: str,
    client,
):
    scope = {
        "client_root": tmp_path / "client",
        "profile_id": "maxa",
        "profile": {},
        "package_root": tmp_path / "research" / "wp-1",
    }
    return validate_declared_reference(
        reference=DeclaredReportReference(
            kind=kind, target_ref=target, label="对象",
        ),
        scope=SimpleNamespace(**scope),
        client=client,
    )
