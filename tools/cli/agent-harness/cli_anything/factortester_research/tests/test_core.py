from __future__ import annotations

from pathlib import Path

from cli_anything.factortester_research.core.plan import build_factor_research_plan, validation_checklist
from cli_anything.factortester_research.core.external_factor import (
    validate_dataset_manifest,
    validate_factor_manifest,
    vibe_pipeline_plan,
)
from cli_anything.factortester_research.core.service import ManagedWorktree, select_worktree
from cli_anything.factortester_research.core.session import ResearchSession, record_gap, resolve_gap
from cli_anything.factortester_research.core.slices import default_factor_validation_plan


HARNESS_ROOT = Path(__file__).resolve().parents[3]


def test_plan_uses_one_workspace_run_job_contract() -> None:
    plan = build_factor_research_plan(
        factor_families=["SgCCS", "MmRet"],
        factors=["SgCCS=SgCCS|P:CA|N:10d", "MmRet=MmRet|P:CA|N:5d"],
        configuration_file="run spec.json",
        analyses=["ic", "factor_type_analysis", "backtest"],
    )
    commands = "\n".join(item["command"] for item in plan)
    phases = [item["phase"] for item in plan]
    assert phases.index("understand_factor_source") < phases.index("submit_run")
    assert "workspace create --factor-family SgCCS --factor-family MmRet" in commands
    assert "--factor 'SgCCS=SgCCS|P:CA|N:10d'" in commands
    assert "workspace update --file 'run spec.json'" in commands
    assert "run submit --analysis ic --analysis factor_type_analysis --analysis backtest" in commands
    assert "job watch <job_id>" in commands
    assert "single_factor_test" not in commands
    assert "ic_test grid" not in commands
    assert "backtest compare" not in commands


def test_plan_treats_factor_families_as_values() -> None:
    plan = build_factor_research_plan(
        factor_families=["MyCustomFamily", "AnotherFamily"],
        configuration_file="configuration.json",
    )
    commands = "\n".join(item["command"] for item in plan)
    assert "--factor-family MyCustomFamily" in commands
    assert "--factor-family AnotherFamily" in commands
    assert "SgCCS" not in commands


def test_validation_checklist_encodes_durable_and_quant_contracts() -> None:
    text = "\n".join(validation_checklist())
    for required in (
        "RunSpec", "ranking universe", "product mask", "多重检验", "未来函数",
        "费用", "ResearchSlice/ValidationPlan", "traceback", "TTL", "retry_of",
        "page_uuid",
    ):
        assert required in text


def test_gap_state_machine_blocks_and_resumes_research() -> None:
    session = ResearchSession(status="research_ready")
    gap = record_gap(session, "missing IC decay", "backend did not return decay")
    assert gap["id"] == "gap-1"
    assert session.status == "code_improvement_required"
    resolve_gap(session, "gap-1", note="implemented")
    assert session.status == "research_ready"


def test_service_target_selection_requires_unambiguous_worktree() -> None:
    worktrees = [
        ManagedWorktree("feat", "feat", "/repo", 7999, False, False),
        ManagedWorktree("fix/issue-123", "fix/issue-123", "/repo/.workspace/fix/issue-123", 8123, True, True),
    ]
    assert select_worktree(worktrees, target_port=8123).branch == "fix/issue-123"


def test_default_validation_plan_separates_selection_from_oos_annotation() -> None:
    payload = default_factor_validation_plan().to_dict()
    assert payload["in_sample_end"] == "2025-12-31"
    assert payload["oos_start"] == "2026-01-01"
    all_slices = [item for group in payload["slice_sets"] for item in group["slices"]]
    assert any(item["kind"] == "rolling" for item in all_slices)
    assert not any(
        item["purpose"] in {"selection", "validation"} and item["start"].startswith("2026")
        for item in all_slices
    )


def test_packaging_and_docs_record_durable_remote_contract() -> None:
    setup_text = (HARNESS_ROOT / "setup.py").read_text(encoding="utf-8")
    readme = (HARNESS_ROOT / "cli_anything/factortester_research/README.md").read_text(encoding="utf-8")
    skill = (HARNESS_ROOT / "cli_anything/factortester_research/skills/SKILL.md").read_text(encoding="utf-8")
    assert 'python_requires=">=3.10"' in setup_text
    for text in (readme, skill):
        assert "workspace" in text
        assert "RunSpec" in text
        assert "job_id" in text
        assert "page_uuid" in text


def test_vibe_pipeline_includes_daily_minute_and_explicit_gtht_gap(tmp_path: Path) -> None:
    steps = vibe_pipeline_plan(
        integration_root=str(tmp_path / "integration"),
        data_root=str(tmp_path / "LocalCNFutures"),
        alpha_id="academic_carhart_mom",
    )
    phases = [item["phase"] for item in steps]
    assert phases[:3] == [
        "build_daily_panel", "build_minute_panel", "compute_vibe_daily_factor",
    ]
    assert steps[-1]["status"] == "platform_gap"
    assert "FactorRunResult" in steps[-1]["reason"]


def test_external_manifests_require_next_bar_and_experimental_status(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.json"
    dataset.write_text(
        '{"schema_version":1,"rows":10,"symbols":2,'
        '"frequency":"1min","timing":{"earliest_execution":"next_bar"}}',
        encoding="utf-8",
    )
    factor = tmp_path / "factor.json"
    factor.write_text(
        '{"schema_version":1,"alpha_id":"x",'
        '"research_status":"experimental_unvalidated","input":{},'
        '"output":{"finite_observations":8},'
        '"timing":{"earliest_execution":"next_bar"}}',
        encoding="utf-8",
    )
    assert validate_dataset_manifest(str(dataset))["frequency"] == "1min"
    assert validate_factor_manifest(str(factor))["alpha_id"] == "x"
