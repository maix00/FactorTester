from __future__ import annotations

import pandas as pd
import pytest

from tools.backtest.adapters.frameworks import (
    Framework,
    FrameworkFeature,
    SignalBridgeRequest,
    UnsupportedFrameworkPlan,
    built_in_adapters,
)


def request(*features: FrameworkFeature) -> SignalBridgeRequest:
    return SignalBridgeRequest(
        factor_alias="momentum-5",
        signals=pd.DataFrame(
            [[0.2, -0.1]],
            index=[pd.Timestamp("2026-01-01")],
            columns=["A", "B"],
        ),
        strategy_ids=("group-1", "group-5"),
        required_features=frozenset(features),
    )


def test_same_factor_signals_prepare_for_all_frameworks() -> None:
    adapters = built_in_adapters()
    bridge_request = request(
        FrameworkFeature.PRECOMPUTED_SIGNALS,
        FrameworkFeature.TARGET_WEIGHTS,
    )

    plans = {framework: adapter.prepare(bridge_request) for framework, adapter in adapters.items()}

    assert set(plans) == set(Framework)
    assert all(plan.signals is bridge_request.signals for plan in plans.values())


def test_qlib_rejects_close_today_fee_semantics_before_execution() -> None:
    adapter = built_in_adapters()[Framework.QLIB]

    with pytest.raises(UnsupportedFrameworkPlan, match="close_today_fees"):
        adapter.prepare(request(FrameworkFeature.CLOSE_TODAY_FEES))


def test_backtrader_reports_futures_extensions_instead_of_silent_approximation() -> None:
    adapter = built_in_adapters()[Framework.BACKTRADER]
    plan = adapter.prepare(request(
        FrameworkFeature.PRECOMPUTED_SIGNALS,
        FrameworkFeature.PARTIAL_FILLS,
        FrameworkFeature.FUTURES_MARGIN,
        FrameworkFeature.DAILY_SETTLEMENT,
    ))

    assert plan.capability_report.native == frozenset({
        FrameworkFeature.PRECOMPUTED_SIGNALS,
        FrameworkFeature.PARTIAL_FILLS,
    })
    assert plan.capability_report.extension_required == frozenset({
        FrameworkFeature.FUTURES_MARGIN,
        FrameworkFeature.DAILY_SETTLEMENT,
    })
    assert not plan.capability_report.missing
