from __future__ import annotations

import pytest

import settings as Settings
from server.services import research_runs
from server.services.research_run_report_binding import normalize_report_binding
from server.services.research_run_identity import RUN_SPEC_VERSION


def _binding(report_id: str = "report:v1:m0zMIM6zzugveWCEt5CG0Rvl") -> dict:
    return {
        "profile_ref": "profile:maxa",
        "report_workspace_id": "workspace-package-1",
        "branch_id": "branch-1",
        "report_id": report_id,
        "report_generation": 7,
        "report_head_hash": "b" * 64,
        "report_parent_id": "direct-trials",
    }


def test_plain_run_needs_no_report_binding() -> None:
    assert normalize_report_binding(None) is None


def test_direct_report_binding_freezes_an_explicit_parent() -> None:
    assert normalize_report_binding(_binding()) == _binding()


def test_report_binding_is_independent_from_sample_policy() -> None:
    assert normalize_report_binding(_binding()) == _binding()


def test_run_retains_frozen_report_identity(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "runs.sqlite")
    binding = _binding()
    run = research_runs.create_run(
        owner="alice",
        workspace_id="workspace-1",
        configuration_id="configuration-1",
        configuration_revision=1,
        run_spec={"run_spec_version": RUN_SPEC_VERSION, "analyses": ["ic"]},
        report_binding=binding,
    )
    assert run["report_binding"] == binding
    assert research_runs.load_run(
        run_id=run["run_id"], owner="alice"
    )["report_binding"] == binding


@pytest.mark.parametrize(
    "report_id",
    ["report:v1:", "report:v2:id", "report:v1:../escape",
     "report:v1:%2Fescape", "report:v1:id/child"],
)
def test_report_catalog_identity_rejects_other_namespaces_or_paths(report_id):
    with pytest.raises(ValueError, match="report_binding.report_id"):
        normalize_report_binding(_binding(report_id))
