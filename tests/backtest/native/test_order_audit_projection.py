from __future__ import annotations

import json

import pandas as pd

from tools.testers.backtest.engines.native.order import (
    Fill,
    FillSettlement,
    Order,
    OrderGroup,
    OrderOffset,
)
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.config import StrategyConfig
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.order_lifecycle import create_order_attempt
from tools.testers.backtest.modules.order_lifecycle.projection import (
    project_strategy_order_audit,
)
from tools.testers.backtest.modules.order_lifecycle.artifact import (
    emit_order_audit_artifact,
)


def test_order_audit_projection_is_json_safe_and_preserves_fill_links():
    strategy = Strategy(alias="audit")
    timestamp = pd.Timestamp("2024-01-01 09:01")
    state = BacktestRunState()
    order = Order(
        instrument="RB.SHF", timestamp=timestamp,
        quantity=-3.0, intent_quantity=-3.0, strategy=strategy,
        order_id="O1", order_group_id="G1", parent_intent_id="I1",
        offset=OrderOffset.CLOSE,
    )
    state.order_store.register_group(OrderGroup(
        order_group_id="G1", parent_intent_id="I1",
        created_at=timestamp, child_order_ids=("O1",),
    ))
    state.order_store.register_order(order)
    attempt = create_order_attempt(
        state, order, timestamp=timestamp, market_timestamp=timestamp,
    )
    state.order_store.record_fill(Fill(
        fill_id="F1", order_id="O1", attempt_id=attempt.attempt_id,
        timestamp=timestamp, quantity=1.0, price=3500.0,
        side=order.side, offset=order.offset,
    ))
    state.order_store.record_settlement(FillSettlement(
        fill_id="F1", realized_pnl=10.0, fee=1.0,
        cash_before=100.0, cash_after=109.0,
        margin_before=20.0, margin_after=8.0,
        account_id="ledger-usd", cash_pool_id="pool-global",
        account_currency="USD", cash_pool_base_currency="CNY",
    ))

    audit = project_strategy_order_audit(state, strategy)

    assert json.loads(json.dumps(audit))["fills"][0]["fill_id"] == "F1"
    assert audit["groups"][0]["status"] == "partially_filled"
    assert audit["orders"][0]["active_leaves"] == 2.0
    assert audit["attempts"][0]["attempt_id"] == attempt.attempt_id
    assert audit["settlements"][0]["margin_after"] == 8.0
    assert audit["settlements"][0]["account_currency"] == "USD"
    assert audit["settlements"][0]["cash_pool_base_currency"] == "CNY"
    assert audit["actions"][0]["action"] == "submit"


def test_summary_retention_does_not_pay_order_projection_cost():
    class SummarySink:
        retention_mode = "summary"

        def emit_artifact(self, name, value):
            raise AssertionError("summary retention must not build full audit")

    class UnprojectableState:
        @property
        def strategy_configs(self):
            raise AssertionError("order projection was evaluated")

    emit_order_audit_artifact(SummarySink(), UnprojectableState(), "run-1")


def test_full_order_audit_projects_one_strategy_at_a_time():
    strategies = [Strategy(alias="A1"), Strategy(alias="A2")]
    state = BacktestRunState(
        strategy_configs={
            strategy: StrategyConfig(strategy=strategy)
            for strategy in strategies
        }
    )
    captured = {}

    class IncrementalSink:
        def should_retain_artifact(self, name):
            return name == "order_audit"

        def emit_mapping_artifact(self, name, *, fields, mapping_name, items):
            captured["name"] = name
            captured["fields"] = fields
            captured["mapping_name"] = mapping_name
            captured["items"] = list(items)

        def emit_artifact(self, name, value):
            raise AssertionError("order audit must use incremental mapping output")

    emit_order_audit_artifact(IncrementalSink(), state, "run-1")

    assert captured["name"] == "order_audit"
    assert captured["fields"] == {"run_id": "run-1"}
    assert captured["mapping_name"] == "strategies"
    assert [name for name, _value in captured["items"]] == ["A1", "A2"]


def test_paired_intent_projection_exposes_unbalanced_leg_fills():
    strategy = Strategy(alias="carry")
    timestamp = pd.Timestamp("2025-01-01")
    state = BacktestRunState()
    orders = [
        Order(
            instrument=product,
            timestamp=timestamp,
            quantity=quantity,
            intent_quantity=quantity,
            strategy=strategy,
            order_id=f"O{index}",
            order_group_id=f"G{index}",
            parent_intent_id="CARRY-1",
        )
        for index, (product, quantity) in enumerate(
            (("NEAR", 2.0), ("FAR", -4.0)),
            start=1,
        )
    ]
    for order in orders:
        order.set("paired_execution_policy", "synchronized_submit")
        state.order_store.register_order(order)
    orders[0].register_fill(2.0)

    paired = project_strategy_order_audit(
        state, strategy,
    )["paired_intents"][0]

    assert paired["fill_ratios"] == [1.0, 0.0]
    assert paired["leg_exposure"] is True
    assert paired["status"] == "exposed"
    assert paired["execution_policy"] == "synchronized_submit"


def test_order_audit_projection_uses_strategy_reverse_indexes():
    strategy = Strategy(alias="indexed")
    timestamp = pd.Timestamp("2024-01-01")
    state = BacktestRunState()
    order = Order(
        instrument="RB.SHF", timestamp=timestamp,
        quantity=1.0, intent_quantity=1.0, strategy=strategy,
        order_id="indexed-order",
    )
    state.order_store.register_order(order)
    attempt = create_order_attempt(
        state, order, timestamp=timestamp, market_timestamp=timestamp,
    )

    class NoGlobalValuesScan(dict):
        def values(self):
            raise AssertionError("projection scanned a global order index")

    state.order_store.orders_by_id = NoGlobalValuesScan(state.order_store.orders_by_id)
    state.order_store.attempts_by_id = NoGlobalValuesScan(state.order_store.attempts_by_id)

    audit = project_strategy_order_audit(state, strategy)

    assert [item["order_id"] for item in audit["orders"]] == [order.order_id]
    assert [item["attempt_id"] for item in audit["attempts"]] == [attempt.attempt_id]
