from __future__ import annotations

from cli_anything.factortester_research.core.plan import build_factor_research_plan, validation_checklist
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


def test_validation_checklist_encodes_quant_research_guardrails() -> None:
    text = "\n".join(validation_checklist())
    assert "费用" in text
    assert "多重检验" in text
    assert "未来函数" in text
    assert "gap" in text


def test_gap_state_machine_blocks_and_resumes_research() -> None:
    session = ResearchSession(status="research_ready")
    gap = record_gap(session, "missing IC decay", "backend did not return decay")
    assert gap["id"] == "gap-1"
    assert session.status == "code_improvement_required"
    resolve_gap(session, "gap-1", note="implemented")
    assert session.status == "research_ready"
