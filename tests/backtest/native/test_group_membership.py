from __future__ import annotations

import uuid

import pandas as pd
import pytest

from tools.products.Product import Product
from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.ledger import RunState, StrategyConfig
from tools.testers.backtest.engines.native.order import Order, OrderStatus
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.factor_signal import FactorSignalModule
from tools.testers.backtest.modules.group_membership import (
    GroupMembershipModule, _group_quantile_membership, _resolve_execution_schedule,
    _resolve_execution_timestamp, _schedule_order_execution, target_trace_for,
)
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.order_execution import OrderExecutionModule
from tools.testers.backtest.modules.order_book import OrderBookModule


def _product() -> Product:
    return Product(name=f"P-{uuid.uuid4().hex}", point_value=1, currency="CNY")


def test_group_quantile_membership_selects_lowest_bucket():
    s = Strategy(alias="S")
    products = [_product() for _ in range(4)]
    signal_value = {p: float(i) for i, p in enumerate(products)}  # ranked: p0 < p1 < p2 < p3
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.split_count: 2, GroupMembershipModule.group_index: 0,
    })
    account = RunState(strategy_configs={s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set_for(FactorSignalModule.signal_value, s, signal_value)

    _group_quantile_membership(account, ctx)
    weights = ctx.get_for(GroupMembershipModule.target_weights, s)
    assert set(weights) == {products[0], products[1]}
    assert weights[products[0]] == pytest.approx(0.5)
    assert sum(weights.values()) == pytest.approx(1.0)


def test_group_quantile_membership_ignores_products_without_current_price():
    s = Strategy(alias="S")
    tradable, removed = _product(), _product()
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.split_count: 1, GroupMembershipModule.group_index: 0,
    })
    account = RunState(strategy_configs={s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set(MarketDataModule.current_prices, {tradable: 10.0})
    ctx.set_for(FactorSignalModule.signal_value, s, {removed: 1.0, tradable: 2.0})

    _group_quantile_membership(account, ctx)

    weights = ctx.get_for(GroupMembershipModule.target_weights, s)
    assert weights == {tradable: pytest.approx(1.0)}


def test_group_quantile_membership_selects_highest_bucket():
    s = Strategy(alias="S")
    products = [_product() for _ in range(4)]
    signal_value = {p: float(i) for i, p in enumerate(products)}
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.split_count: 2, GroupMembershipModule.group_index: 1,
    })
    account = RunState(strategy_configs={s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set_for(FactorSignalModule.signal_value, s, signal_value)

    _group_quantile_membership(account, ctx)
    weights = ctx.get_for(GroupMembershipModule.target_weights, s)
    assert set(weights) == {products[2], products[3]}


def test_resolve_execution_timestamp_rejects_same_bar_execution():
    s = Strategy(alias="S")
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.execution_timing: "same_bar",
    })
    account = RunState(strategy_configs={s: config})
    t = pd.Timestamp("2024-01-01")
    ctx = FlowContext(timestamp=t, event_queue=EventQueue())
    with pytest.raises(ValueError, match="next-bar open"):
        _resolve_execution_timestamp(account, ctx, s)


def test_resolve_execution_timestamp_next_bar_advances_by_delay():
    s = Strategy(alias="S")
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.execution_timing: "next_bar",
        GroupMembershipModule.execution_delay_bars: 2,
    })
    account = RunState(strategy_configs={s: config})
    account.market_data_store.current_prices_table = pd.DataFrame(
        {"P1": [1, 2, 3, 4]}, index=pd.date_range("2024-01-01", periods=4))
    t = pd.Timestamp("2024-01-01")
    ctx = FlowContext(timestamp=t, event_queue=EventQueue())
    result = _resolve_execution_timestamp(account, ctx, s)
    assert result == pd.Timestamp("2024-01-02") + pd.Timedelta(nanoseconds=1)


def test_resolve_execution_schedule_next_bar_open_uses_next_row_price_and_open_boundary_event():
    s_open = Strategy(alias="open")
    idx = pd.date_range("2024-01-01 09:01", periods=3, freq="1min")
    account = RunState(strategy_configs={
        s_open: StrategyConfig(strategy=s_open, field_values={
            GroupMembershipModule.execution_timing: "next_bar",
            GroupMembershipModule.execution_delay_bars: 1,
            OrderExecutionModule.execution_price_basis: "open",
        }),
    })
    account.market_data_store.current_prices_table = pd.DataFrame({"P1": [1, 2, 3]}, index=idx)
    ctx = FlowContext(timestamp=idx[0], event_queue=EventQueue())

    open_event_ts, open_price_ts = _resolve_execution_schedule(account, ctx, s_open)

    assert open_event_ts == idx[0] + pd.Timedelta(nanoseconds=1)
    assert open_price_ts == idx[1]


def test_resolve_execution_schedule_rejects_non_open_price_basis():
    s = Strategy(alias="S")
    idx = pd.date_range("2024-01-01 09:01", periods=2, freq="1min")
    account = RunState(strategy_configs={
        s: StrategyConfig(strategy=s, field_values={
            GroupMembershipModule.execution_timing: "next_bar",
            OrderExecutionModule.execution_price_basis: "close",
        }),
    })
    account.market_data_store.current_prices_table = pd.DataFrame({"P1": [1, 2]}, index=idx)
    ctx = FlowContext(timestamp=idx[0], event_queue=EventQueue())

    with pytest.raises(ValueError, match="next-bar open"):
        _resolve_execution_schedule(account, ctx, s)


def test_resolve_execution_timestamp_clips_to_last_available_bar():
    s = Strategy(alias="S")
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.execution_timing: "next_bar",
        GroupMembershipModule.execution_delay_bars: 10,
    })
    account = RunState(strategy_configs={s: config})
    account.market_data_store.current_prices_table = pd.DataFrame(
        {"P1": [1, 2]}, index=pd.date_range("2024-01-01", periods=2))
    t = pd.Timestamp("2024-01-01")
    ctx = FlowContext(timestamp=t, event_queue=EventQueue())
    event_ts, price_ts = _resolve_execution_schedule(account, ctx, s)
    assert event_ts == pd.Timestamp("2024-01-01") + pd.Timedelta(nanoseconds=1)
    assert price_ts == pd.Timestamp("2024-01-02")


def test_schedule_order_execution_sets_scheduled_and_pushes_event():
    s = Strategy(alias="S")
    p = _product()
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.execution_timing: "next_bar",
        OrderExecutionModule.execution_price_basis: "open",
    })
    account = RunState(strategy_configs={s: config})
    account.market_data_store.current_prices_table = pd.DataFrame(
        {p: [1, 2]}, index=pd.date_range("2024-01-01", periods=2))
    queue = EventQueue()
    t = pd.Timestamp("2024-01-01")
    order = Order(instrument=p, timestamp=t, quantity=10.0, intent_quantity=10.0, strategy=s)
    ctx = FlowContext(timestamp=t, event_queue=queue, active_strategies=frozenset({s}))
    ctx.set_for(OrderBookModule.orders, s, [order])

    _schedule_order_execution(account, ctx)

    assert order.status == OrderStatus.SCHEDULED
    seen = []
    queue.set_dispatcher(EventKind.ORDER, lambda batch: seen.extend(batch))
    queue.run_until_drained()
    assert len(seen) == 1
    assert seen[0].payload is order


def test_schedule_order_execution_cancels_pending_order_still_genuinely_in_the_future():
    """A signal at t1 schedules an order for a later t3 (next_bar, delay
    spans two periods). Before t3 arrives, a fresh signal at t2 (t1 < t2 <
    t3) recomputes and supersedes it -- the old order is still strictly in
    the future relative to t2, so it gets cancelled."""
    s = Strategy(alias="S")
    p = _product()
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.execution_timing: "next_bar",
        GroupMembershipModule.execution_delay_bars: 2,
    })
    account = RunState(strategy_configs={s: config})
    account.market_data_store.current_prices_table = pd.DataFrame(
        {p: [1, 2, 3, 4]}, index=pd.date_range("2024-01-01", periods=4))
    queue = EventQueue()
    t1, t2 = pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-02")

    old_order = Order(instrument=p, timestamp=t1, quantity=10.0, intent_quantity=10.0, strategy=s)
    ctx1 = FlowContext(timestamp=t1, event_queue=queue, active_strategies=frozenset({s}))
    ctx1.set_for(OrderBookModule.orders, s, [old_order])
    _schedule_order_execution(account, ctx1)
    assert old_order.status == OrderStatus.SCHEDULED
    assert old_order.timestamp == pd.Timestamp("2024-01-02") + pd.Timedelta(nanoseconds=1)
    assert old_order.get("price_timestamp") == pd.Timestamp("2024-01-03")

    new_order = Order(instrument=p, timestamp=t2, quantity=20.0, intent_quantity=20.0, strategy=s)
    ctx2 = FlowContext(timestamp=t2, event_queue=queue, active_strategies=frozenset({s}))
    ctx2.set_for(OrderBookModule.orders, s, [new_order])
    _schedule_order_execution(account, ctx2)

    assert old_order.status == OrderStatus.CANCELLED
    assert new_order.status == OrderStatus.SCHEDULED


def test_schedule_order_execution_replaces_pending_next_bar_open_order_at_same_signal_time():
    """With fixed next-bar-open execution, a pending order created at this
    signal timestamp still targets a future price row, so a recomputed order
    for the same strategy/product supersedes it."""
    s = Strategy(alias="S")
    p = _product()
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.execution_timing: "next_bar",
        GroupMembershipModule.execution_delay_bars: 1,
        OrderExecutionModule.execution_price_basis: "open",
    })
    account = RunState(strategy_configs={s: config})
    account.market_data_store.current_prices_table = pd.DataFrame(
        {p: [1, 2]}, index=pd.date_range("2024-01-01", periods=2))
    queue = EventQueue()
    t = pd.Timestamp("2024-01-01")

    old_order = Order(instrument=p, timestamp=t, quantity=10.0, intent_quantity=10.0, strategy=s)
    ctx1 = FlowContext(timestamp=t, event_queue=queue, active_strategies=frozenset({s}))
    ctx1.set_for(OrderBookModule.orders, s, [old_order])
    _schedule_order_execution(account, ctx1)
    assert old_order.status == OrderStatus.SCHEDULED

    new_order = Order(instrument=p, timestamp=t, quantity=20.0, intent_quantity=20.0, strategy=s)
    ctx2 = FlowContext(timestamp=t, event_queue=queue, active_strategies=frozenset({s}))
    ctx2.set_for(OrderBookModule.orders, s, [new_order])
    _schedule_order_execution(account, ctx2)

    assert old_order.status == OrderStatus.CANCELLED
    assert new_order.status == OrderStatus.SCHEDULED


def test_schedule_order_execution_does_not_cancel_across_different_products():
    s = Strategy(alias="S")
    p1, p2 = _product(), _product()
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.execution_timing: "next_bar",
        OrderExecutionModule.execution_price_basis: "open",
    })
    account = RunState(strategy_configs={s: config})
    account.market_data_store.current_prices_table = pd.DataFrame(
        {p1: [1, 2], p2: [1, 2]}, index=pd.date_range("2024-01-01", periods=2))
    queue = EventQueue()
    t = pd.Timestamp("2024-01-01")

    order1 = Order(instrument=p1, timestamp=t, quantity=10.0, intent_quantity=10.0, strategy=s)
    ctx1 = FlowContext(timestamp=t, event_queue=queue, active_strategies=frozenset({s}))
    ctx1.set_for(OrderBookModule.orders, s, [order1])
    _schedule_order_execution(account, ctx1)

    order2 = Order(instrument=p2, timestamp=t, quantity=20.0, intent_quantity=20.0, strategy=s)
    ctx2 = FlowContext(timestamp=t, event_queue=queue, active_strategies=frozenset({s}))
    ctx2.set_for(OrderBookModule.orders, s, [order2])
    _schedule_order_execution(account, ctx2)

    assert order1.status == OrderStatus.SCHEDULED  # untouched, different product
    assert order2.status == OrderStatus.SCHEDULED


def test_buy_and_hold_freezes_target_weights_after_first_computation():
    s = Strategy(alias="S")
    products = [_product() for _ in range(4)]
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.split_count: 2, GroupMembershipModule.group_index: 0,
        GroupMembershipModule.position_policy: "buy_and_hold",
    })
    account = RunState(strategy_configs={s: config})

    ctx1 = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx1.set_for(FactorSignalModule.signal_value, s, {p: float(i) for i, p in enumerate(products)})
    _group_quantile_membership(account, ctx1)
    first_weights = ctx1.get_for(GroupMembershipModule.target_weights, s)
    assert set(first_weights) == {products[0], products[1]}

    # signal completely reverses ranking -- under rebalance_to_target this
    # would select the opposite bucket; buy_and_hold must ignore it
    ctx2 = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx2.set_for(FactorSignalModule.signal_value, s, {p: float(len(products) - i) for i, p in enumerate(products)})
    _group_quantile_membership(account, ctx2)
    second_weights = ctx2.get_for(GroupMembershipModule.target_weights, s)
    assert second_weights == first_weights


def test_rebalance_to_target_recomputes_every_time():
    s = Strategy(alias="S")
    products = [_product() for _ in range(4)]
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.split_count: 2, GroupMembershipModule.group_index: 0,
        GroupMembershipModule.position_policy: "rebalance_to_target",
    })
    account = RunState(strategy_configs={s: config})

    ctx1 = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx1.set_for(FactorSignalModule.signal_value, s, {p: float(i) for i, p in enumerate(products)})
    _group_quantile_membership(account, ctx1)
    first_weights = ctx1.get_for(GroupMembershipModule.target_weights, s)

    ctx2 = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx2.set_for(FactorSignalModule.signal_value, s, {p: float(len(products) - i) for i, p in enumerate(products)})
    _group_quantile_membership(account, ctx2)
    second_weights = ctx2.get_for(GroupMembershipModule.target_weights, s)
    assert second_weights != first_weights
    assert set(second_weights) == {products[2], products[3]}


def test_membership_change_trigger_skips_recompute_when_bucket_unchanged():
    s = Strategy(alias="S")
    products = [_product() for _ in range(4)]
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.split_count: 2, GroupMembershipModule.group_index: 0,
        GroupMembershipModule.rebalance_trigger: "membership_change",
    })
    account = RunState(strategy_configs={s: config})

    ctx1 = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx1.set_for(FactorSignalModule.signal_value, s, {p: float(i) for i, p in enumerate(products)})
    _group_quantile_membership(account, ctx1)
    first_weights = ctx1.get_for(GroupMembershipModule.target_weights, s)

    # signal values shift slightly but the bottom-2 bucket membership is identical
    ctx2 = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx2.set_for(FactorSignalModule.signal_value, s, {p: float(i) + 0.1 for i, p in enumerate(products)})
    _group_quantile_membership(account, ctx2)
    second_weights = ctx2.get_for(GroupMembershipModule.target_weights, s)
    assert second_weights == first_weights


def test_membership_change_trigger_recomputes_when_bucket_actually_changes():
    s = Strategy(alias="S")
    products = [_product() for _ in range(4)]
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.split_count: 2, GroupMembershipModule.group_index: 0,
        GroupMembershipModule.rebalance_trigger: "membership_change",
    })
    account = RunState(strategy_configs={s: config})

    ctx1 = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx1.set_for(FactorSignalModule.signal_value, s, {p: float(i) for i, p in enumerate(products)})
    _group_quantile_membership(account, ctx1)
    first_weights = ctx1.get_for(GroupMembershipModule.target_weights, s)
    assert set(first_weights) == {products[0], products[1]}

    ctx2 = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx2.set_for(FactorSignalModule.signal_value, s, {p: float(len(products) - i) for i, p in enumerate(products)})
    _group_quantile_membership(account, ctx2)
    second_weights = ctx2.get_for(GroupMembershipModule.target_weights, s)
    assert set(second_weights) == {products[2], products[3]}
    assert second_weights != first_weights


def test_scheduled_trigger_raises_not_implemented():
    s = Strategy(alias="S")
    products = [_product() for _ in range(2)]
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.split_count: 2, GroupMembershipModule.group_index: 0,
        GroupMembershipModule.rebalance_trigger: "scheduled",
    })
    account = RunState(strategy_configs={s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set_for(FactorSignalModule.signal_value, s, {p: float(i) for i, p in enumerate(products)})
    with pytest.raises(NotImplementedError):
        _group_quantile_membership(account, ctx)


def test_inverse_volatility_allocates_more_to_calmer_product():
    s = Strategy(alias="S")
    p_calm, p_volatile = _product(), _product()
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.split_count: 1, GroupMembershipModule.group_index: 0,
        GroupMembershipModule.allocation_policy: "inverse_volatility",
        GroupMembershipModule.volatility_lookback: 3,
    })
    account = RunState(strategy_configs={s: config})
    idx = pd.date_range("2024-01-01", periods=5)
    account.market_data_store.current_prices_table = pd.DataFrame({
        p_calm: [100.0, 101.0, 100.0, 101.0, 100.0],       # low volatility
        p_volatile: [100.0, 120.0, 90.0, 130.0, 80.0],      # high volatility
    }, index=idx)

    ctx = FlowContext(timestamp=idx[-1], event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set_for(FactorSignalModule.signal_value, s, {p_calm: 1.0, p_volatile: 1.0})
    _group_quantile_membership(account, ctx)
    weights = ctx.get_for(GroupMembershipModule.target_weights, s)

    assert weights[p_calm] > weights[p_volatile]
    assert sum(weights.values()) == pytest.approx(1.0)


def test_inverse_volatility_warmup_equal_notional_fallback_for_insufficient_history():
    s = Strategy(alias="S")
    p_established, p_new = _product(), _product()
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.split_count: 1, GroupMembershipModule.group_index: 0,
        GroupMembershipModule.allocation_policy: "inverse_volatility",
        GroupMembershipModule.volatility_lookback: 3,
        GroupMembershipModule.volatility_warmup: "equal_notional",
    })
    account = RunState(strategy_configs={s: config})
    idx = pd.date_range("2024-01-01", periods=5)
    account.market_data_store.current_prices_table = pd.DataFrame({
        p_established: [100.0, 101.0, 100.0, 101.0, 100.0],
        p_new: [None, None, None, None, 100.0],  # just appeared, no trailing history
    }, index=idx)

    ctx = FlowContext(timestamp=idx[-1], event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set_for(FactorSignalModule.signal_value, s, {p_established: 1.0, p_new: 1.0})
    _group_quantile_membership(account, ctx)
    weights = ctx.get_for(GroupMembershipModule.target_weights, s)

    assert weights[p_new] == pytest.approx(0.5)  # fell back to its equal-notional share
    assert sum(weights.values()) == pytest.approx(1.0)


def test_inverse_volatility_warmup_error_raises_for_insufficient_history():
    s = Strategy(alias="S")
    p_new = _product()
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.split_count: 1, GroupMembershipModule.group_index: 0,
        GroupMembershipModule.allocation_policy: "inverse_volatility",
        GroupMembershipModule.volatility_lookback: 10,
        GroupMembershipModule.volatility_warmup: "error",
    })
    account = RunState(strategy_configs={s: config})
    idx = pd.date_range("2024-01-01", periods=2)
    account.market_data_store.current_prices_table = pd.DataFrame({p_new: [100.0, 101.0]}, index=idx)

    ctx = FlowContext(timestamp=idx[-1], event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set_for(FactorSignalModule.signal_value, s, {p_new: 1.0})
    with pytest.raises(ValueError):
        _group_quantile_membership(account, ctx)


def test_target_trace_records_fresh_computation():
    s = Strategy(alias="S")
    products = [_product() for _ in range(4)]
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.split_count: 2, GroupMembershipModule.group_index: 0,
    })
    account = RunState(strategy_configs={s: config})
    t = pd.Timestamp("2024-01-01")

    ctx = FlowContext(timestamp=t, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set_for(FactorSignalModule.signal_value, s, {p: float(i) for i, p in enumerate(products)})
    _group_quantile_membership(account, ctx)

    trace = target_trace_for(account, s)
    assert t.isoformat() in trace
    assert trace[t.isoformat()] == {str(products[0]): 0.5, str(products[1]): 0.5}


def test_target_trace_not_recorded_when_membership_change_skips_recompute():
    s = Strategy(alias="S")
    products = [_product() for _ in range(4)]
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.split_count: 2, GroupMembershipModule.group_index: 0,
        GroupMembershipModule.rebalance_trigger: "membership_change",
    })
    account = RunState(strategy_configs={s: config})
    t1, t2 = pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-02")

    ctx1 = FlowContext(timestamp=t1, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx1.set_for(FactorSignalModule.signal_value, s, {p: float(i) for i, p in enumerate(products)})
    _group_quantile_membership(account, ctx1)

    ctx2 = FlowContext(timestamp=t2, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx2.set_for(FactorSignalModule.signal_value, s, {p: float(i) + 0.1 for i, p in enumerate(products)})
    _group_quantile_membership(account, ctx2)

    trace = target_trace_for(account, s)
    assert t1.isoformat() in trace
    assert t2.isoformat() not in trace  # membership unchanged, no fresh trace entry
