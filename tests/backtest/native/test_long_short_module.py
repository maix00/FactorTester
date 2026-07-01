from __future__ import annotations

import uuid

import pandas as pd
import pytest

from tools.products.Product import Product
from tools.testers.backtest.engines.native.ledger import RunState, StrategyConfig
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.group_membership import GroupMembershipModule
from tools.testers.backtest.modules.long_short import (
    LongShortCompositionModule,
    _compose_long_short_target,
)


def _product() -> Product:
    return Product(name=f"P-{uuid.uuid4().hex}", point_value=1, currency="CNY")


def test_long_short_composes_peer_strategy_targets_without_group_fields():
    long_strategy = Strategy(alias="trend_long")
    short_strategy = Strategy(alias="carry_short")
    ls_strategy = Strategy(alias="ls")
    p_long_a, p_long_b, p_short = _product(), _product(), _product()
    account = RunState(strategy_configs={
        long_strategy: StrategyConfig(strategy=long_strategy),
        short_strategy: StrategyConfig(strategy=short_strategy),
        ls_strategy: StrategyConfig(strategy=ls_strategy, field_values={
            LongShortCompositionModule.strategy_kind: "long_short",
            LongShortCompositionModule.long_leg_strategy_ids: [{"strategy_id": "trend_long"}],
            LongShortCompositionModule.short_leg_strategy_ids: [{"strategy_id": "carry_short"}],
        }),
    })
    ctx = FlowContext(
        timestamp=pd.Timestamp("2026-01-02 09:01"),
        event_queue=EventQueue(),
        active_strategies=frozenset({ls_strategy}),
    )
    ctx.set_for(GroupMembershipModule.target_weights, long_strategy, {p_long_a: 0.25, p_long_b: 0.75})
    ctx.set_for(GroupMembershipModule.target_weights, short_strategy, {p_short: 1.0})

    _compose_long_short_target(account, ctx)

    weights = ctx.get_for(GroupMembershipModule.target_weights, ls_strategy)
    assert weights[p_long_a] == pytest.approx(0.125)
    assert weights[p_long_b] == pytest.approx(0.375)
    assert weights[p_short] == pytest.approx(-0.5)
    assert sum(abs(value) for value in weights.values()) == pytest.approx(1.0)
    assert set(weights) == {p_long_a, p_long_b, p_short}


def test_long_short_removes_overlapping_legs_and_reports_diagnostics():
    long_strategy = Strategy(alias="A")
    short_strategy = Strategy(alias="B")
    ls_strategy = Strategy(alias="LS")
    overlap, long_only, short_only = _product(), _product(), _product()
    account = RunState(strategy_configs={
        long_strategy: StrategyConfig(strategy=long_strategy),
        short_strategy: StrategyConfig(strategy=short_strategy),
        ls_strategy: StrategyConfig(strategy=ls_strategy, field_values={
            LongShortCompositionModule.strategy_kind: "long_short",
            LongShortCompositionModule.long_leg_strategy_ids: [{"strategy_id": "A"}],
            LongShortCompositionModule.short_leg_strategy_ids: [{"strategy_id": "B"}],
        }),
    })
    ctx = FlowContext(
        timestamp=pd.Timestamp("2026-01-02 09:01"),
        event_queue=EventQueue(),
        active_strategies=frozenset({ls_strategy}),
    )
    ctx.set_for(GroupMembershipModule.target_weights, long_strategy, {overlap: 0.5, long_only: 0.5})
    ctx.set_for(GroupMembershipModule.target_weights, short_strategy, {overlap: 0.5, short_only: 0.5})

    _compose_long_short_target(account, ctx)

    weights = ctx.get_for(GroupMembershipModule.target_weights, ls_strategy)
    diagnostics = ctx.get_for(LongShortCompositionModule.long_short_diagnostics, ls_strategy)
    assert weights == {long_only: pytest.approx(0.5), short_only: pytest.approx(-0.5)}
    assert diagnostics["overlap_count"] == 1
    assert diagnostics["overlaps"] == [str(overlap)]
