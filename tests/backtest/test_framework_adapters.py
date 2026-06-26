from __future__ import annotations

import pandas as pd
import pytest

from tools.backtest_engines.adapters.frameworks import (
    FactorBridgeRequest,
    Framework,
    FrameworkFeature,
    IncrementalFactorSource,
    PrecomputedFactorSource,
    UnsupportedFrameworkPlan,
    built_in_adapters,
)
from tools.data.types import DataColumn
from tools.factors.expr import ColumnRef


def request(*features: FrameworkFeature) -> FactorBridgeRequest:
    return FactorBridgeRequest(
        factor_alias="momentum-5",
        factor_source=PrecomputedFactorSource(pd.DataFrame(
            [[0.2, -0.1]],
            index=[pd.Timestamp("2026-01-01")],
            columns=["A", "B"],
        )),
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
    assert all(
        plan.factor_source is bridge_request.factor_source
        for plan in plans.values()
    )


def test_incremental_factor_plan_is_not_forced_through_a_signal_dataframe() -> None:
    expression = ColumnRef(DataColumn.CLOSE).rolling_mean(5)
    bridge_request = FactorBridgeRequest(
        factor_alias="momentum-5",
        factor_source=IncrementalFactorSource(expression),
        strategy_ids=("group-1",),
        required_features=frozenset({FrameworkFeature.TARGET_WEIGHTS}),
    )

    plans = {
        framework: adapter.prepare(bridge_request)
        for framework, adapter in built_in_adapters().items()
    }

    assert all(plan.factor_source.factor_plan is expression for plan in plans.values())
    assert FrameworkFeature.INCREMENTAL_FACTORS in plans[Framework.NATIVE].capability_report.native
    for framework in (Framework.BACKTRADER, Framework.QLIB, Framework.ZIPLINE):
        assert FrameworkFeature.INCREMENTAL_FACTORS in (
            plans[framework].capability_report.extension_required
        )


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
