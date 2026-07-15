from __future__ import annotations

from cli_anything.factortester_research.core.plan import build_factor_research_plan, validation_checklist
from cli_anything.factortester_research.core.service import ManagedWorktree, select_worktree
from cli_anything.factortester_research.core.session import ResearchSession, record_gap, resolve_gap
from cli_anything.factortester_research.core.slices import default_factor_validation_plan


def test_plan_orders_diagnostics_before_backtest() -> None:
    plan = build_factor_research_plan(
        factor_family="SgCCS",
        template="2026-06-02 07:20:47",
        product_groups=["中国期货日盘"],
        n_values=["2m"],
        f_values=["1m"],
    )
    phases = [item["phase"] for item in plan]
    assert phases.index("inspect_factor_expr_dsl") < phases.index("operator_coverage_gate")
    assert phases.index("operator_coverage_gate") < phases.index("prepare_factor_workspace")
    assert phases.index("inspect_factor_expr_dsl") < phases.index("prepare_factor_workspace")
    assert phases.index("prepare_factor_workspace") < phases.index("understand_factor_source")
    assert phases.index("understand_factor_source") < phases.index("diagnose_ic")
    assert phases.index("build_validation_slices") < phases.index("diagnose_ic")
    assert phases.index("query_research_library") < phases.index("diagnose_ic")
    assert phases.index("diagnose_ic") < phases.index("backtest")
    assert phases.index("diagnose_type") < phases.index("backtest")
    assert phases.index("cost_capacity_screen") < phases.index("backtest")
    assert any("ic_test grid" in item["command"] for item in plan)
    assert any("custom_factors operators" in item["command"] for item in plan)
    assert any(item["phase"] == "operator_coverage_gate" for item in plan)
    assert any("workspace prepare --build --sync" in item["command"] for item in plan)
    assert any("slice-plan --json" in item["command"] for item in plan)
    assert any("--volume-capacity-mode volume_participation" in item["command"] for item in plan)
    assert any("factor-library history" in item["command"] for item in plan)
    assert any("factor-library import-result" in item["command"] for item in plan)
    assert any("factor-library rank" in item["command"] for item in plan)
    assert any(item["phase"] == "platform_gap_loop" for item in plan)


def test_plan_treats_factor_family_as_value_not_sgccs_default() -> None:
    plan = build_factor_research_plan(factor_family="MyCustomFamily", n_values=["3m"])
    commands = "\n".join(str(item["command"]) for item in plan)
    assert "--factor-family MyCustomFamily" in commands
    assert "SgCCS" not in commands


def test_validation_checklist_encodes_quant_research_guardrails() -> None:
    text = "\n".join(validation_checklist())
    assert "费用" in text
    assert "多重检验" in text
    assert "FactorExpr 算子表" in text
    assert "算子不全" in text
    assert "workspace prepare --build --sync" in text
    assert "未来函数" in text
    assert "ResearchSlice/ValidationPlan" in text
    assert "2026" in text
    assert "gap" in text
    assert "7998" in text
    assert "client_only" in text
    assert "branch/worktree" in text
    assert "factor-library import-result" in text
    assert "factor-library history/rank" in text


def test_platform_gap_plan_requires_owner_worktree_before_cli_merge() -> None:
    plan = build_factor_research_plan(factor_family="SgCCS")
    platform = next(item for item in plan if item["phase"] == "platform_gap_loop")
    text = platform["purpose"] + " " + platform["command"]
    assert "issue/task" in text
    assert "branch/worktree" in text
    assert "merge 到 CLI worktree" in text


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
        ManagedWorktree("fix/issue-123-factortester-cli-http", "fix/issue-123-factortester-cli-http", "/repo/.workspace/fix/issue-123", 8123, True, True),
    ]
    target = select_worktree(worktrees, target_port=8123)
    assert target.branch == "fix/issue-123-factortester-cli-http"


def test_default_validation_plan_separates_selection_from_oos_annotation() -> None:
    plan = default_factor_validation_plan()
    payload = plan.to_dict()
    assert payload["in_sample_start"] == "2024-01-01"
    assert payload["in_sample_end"] == "2025-12-31"
    assert payload["oos_start"] == "2026-01-01"
    names = {item["name"] for item in payload["slice_sets"]}
    assert {"calendar_quarterly", "rolling_63d_step21d", "oos_annotation"} <= names
    all_slices = [
        item
        for slice_set in payload["slice_sets"]
        for item in slice_set["slices"]
    ]
    assert any(item["name"] == "2024Q1" for item in all_slices)
    assert any(item["kind"] == "rolling" for item in all_slices)
    oos = [item for item in all_slices if item["purpose"] == "oos_annotation"]
    assert oos and all(item["start"].startswith("2026") for item in oos)
    assert not any(item["purpose"] in {"selection", "validation"} and item["start"].startswith("2026") for item in all_slices)
