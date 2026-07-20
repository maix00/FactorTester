"""Canonical research artifacts projected from authoritative backtest state."""

from __future__ import annotations

import pytest

from server.modules.single_factor_test.backtest_research_artifacts import (
    project_net_returns,
)


def test_net_returns_come_from_fee_adjusted_ledger_equity() -> None:
    artifact = project_net_returns(
        engine_result={
            "engine": "native",
            "portfolios": {
                "strategy-2": {
                    "display_equity_curve": {
                        "2024-01-01T00:00:00": 100.0,
                        "2024-01-02T00:00:00": 90.0,
                    },
                },
                "strategy-1": {
                    "display_equity_curve": {
                        "2024-01-01T00:00:00": 100.0,
                        "2024-01-02T00:00:00": 110.0,
                        "2024-01-03T00:00:00": 121.0,
                    },
                },
            },
        },
        group_owner=[
            {
                "group_id": "strategy-2",
                "group_name": "short",
                "factor_alias": "Alpha|N:5d",
            },
            {
                "group_id": "strategy-1",
                "group_name": "long",
                "factor_alias": "Alpha|N:5d",
            },
        ],
    )

    assert artifact["artifact_kind"] == "net_return_series"
    assert artifact["accounting_basis"] == (
        "ledger_equity_after_fees_slippage_margin_and_settlement"
    )
    assert [row["strategy_id"] for row in artifact["series"]] == [
        "strategy-1",
        "strategy-2",
    ]
    assert artifact["series"][0]["returns"] == [0.0, 0.1, 0.1]
    assert artifact["series"][1]["returns"] == [0.0, -0.1]


@pytest.mark.parametrize(
    "portfolio",
    [
        {},
        {"display_equity_curve": {}},
        {
            "display_equity_curve": {
                "2024-01-01T00:00:00": 0.0,
                "2024-01-02T00:00:00": 1.0,
            },
        },
    ],
)
def test_net_returns_fail_closed_without_valid_equity(
    portfolio: dict,
) -> None:
    with pytest.raises(ValueError, match="equity"):
        project_net_returns(
            engine_result={
                "engine": "native",
                "portfolios": {"strategy-1": portfolio},
            },
            group_owner=[{"group_id": "strategy-1"}],
        )


def test_unvalidated_external_engine_omits_net_return_artifact() -> None:
    assert project_net_returns(
        engine_result={"engine": "zipline", "portfolios": {}},
        group_owner=[],
    ) is None
