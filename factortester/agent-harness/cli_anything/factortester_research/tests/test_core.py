from __future__ import annotations

from cli_anything.factortester_research.core.plan import build_factor_research_plan, validation_checklist
from cli_anything.factortester_research.core.service import ManagedWorktree, select_worktree
from cli_anything.factortester_research.core.session import ResearchSession, record_gap, resolve_gap


def test_plan_orders_diagnostics_before_backtest() -> None:
    plan = build_factor_research_plan(
        factor_family="SgCCS",
        template="2026-06-02 07:20:47",
        product_groups=["中国期货日盘"],
        n_values=["2m"],
        f_values=["1m"],
    )
    phases = [item["phase"] for item in plan]
    assert phases.index("diagnose_ic") < phases.index("backtest")
    assert phases.index("diagnose_type") < phases.index("backtest")
    assert phases.index("cost_capacity_screen") < phases.index("backtest")
    assert any("ic_test grid" in item["command"] for item in plan)
    assert any("--volume-capacity-mode volume_participation" in item["command"] for item in plan)
    assert any(item["phase"] == "platform_gap_loop" for item in plan)


def test_validation_checklist_encodes_quant_research_guardrails() -> None:
    text = "\n".join(validation_checklist())
    assert "费用" in text
    assert "多重检验" in text
    assert "未来函数" in text
    assert "gap" in text
    assert "7998" in text
    assert "client_only" in text
    assert "branch/worktree" in text


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
