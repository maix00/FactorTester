from __future__ import annotations

import pandas as pd
import pytest

from tools.testers.backtest.policies.margin_budget import (
    MarginBudgetRequest,
    default_margin_budget_policy,
)


def _request(*, projected_margin: float) -> MarginBudgetRequest:
    return MarginBudgetRequest(
        cash_pool_id="P", effective_timestamp=pd.Timestamp("2025-01-02"),
        equity=100_000_000.0, target_utilization=0.80,
        max_utilization=0.85, tolerance=0.01,
        raw_gross_notional=100_000_000.0,
        raw_projected_margin=projected_margin,
    )


def test_default_margin_budget_reports_six_point_four_gross_leverage() -> None:
    decision = default_margin_budget_policy(_request(projected_margin=12_500_000.0))

    assert decision.scale == pytest.approx(6.4)
    assert decision.gross_leverage == pytest.approx(6.4)
    assert decision.projected_utilization == pytest.approx(0.80)


def test_margin_budget_never_falls_back_to_one_x_without_margin_projection() -> None:
    with pytest.raises(ValueError, match="positive projected margin"):
        default_margin_budget_policy(_request(projected_margin=0.0))
