from __future__ import annotations

import uuid

import pandas as pd
import pytest

from tools.products.Product import Product
from tools.data.types.time_freq import DataFreq
from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.config import StrategyConfig
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
from tools.testers.backtest.modules.order_construct import OrderConstructModule
from tools.testers.backtest.modules.engine import EngineModule
from tools.testers.backtest.modules.strategy_book import (
    StrategyBookPolicies,
    StrategyIntentPolicy,
    strategy_book_store_for,
)
from tools.testers.backtest.modules.target import _precompute_strategy_intents


def _product() -> Product:
    return Product(name=f"P-{uuid.uuid4().hex}", point_value=1, currency="CNY")


def test_group_quantile_membership_selects_highest_bucket_first():
    """group_index=0 ("第1组") is the highest-factor-value bucket -- the
    highest factor value belongs in the first group."""
    s = Strategy(alias="S")
    products = [_product() for _ in range(4)]
    signal_value = {p: float(i) for i, p in enumerate(products)}  # ranked: p0 < p1 < p2 < p3
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.split_count: 2, GroupMembershipModule.group_index: 0,
    })
    account = BacktestRunState(strategy_configs={s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set_for(FactorSignalModule.signal_value, s, signal_value)

    _group_quantile_membership(account, ctx)
    weights = ctx.get_for(GroupMembershipModule.target_weights, s)
    assert set(weights) == {products[2], products[3]}
    assert weights[products[2]] == pytest.approx(0.5)
    assert sum(weights.values()) == pytest.approx(1.0)


def test_group_quantile_membership_reuses_ranking_across_strategies_sharing_signal_value(monkeypatch):
    """Strategies sharing a factor's precomputed schedule are dispatched in
    the same SIGNAL batch (same ctx.active_strategies) and see byte-identical
    filtered signal_value -- only their group_index/split_count differ. The
    O(n log n) rank-and-sort should happen once per distinct signal_value
    content, not once per strategy, even when split_count differs too."""
    import tools.testers.backtest.modules.group_membership as group_membership_module

    rank_calls = 0
    real_rank = group_membership_module.rank_cross_section

    def _counting_rank(*args, **kwargs):
        nonlocal rank_calls
        rank_calls += 1
        return real_rank(*args, **kwargs)

    monkeypatch.setattr(group_membership_module, "rank_cross_section", _counting_rank)

    products = [_product() for _ in range(4)]
    signal_value = {p: float(i) for i, p in enumerate(products)}
    strategies = [Strategy(alias=f"S{i}") for i in range(5)]
    configs = {
        strategies[0]: StrategyConfig(strategy=strategies[0], field_values={
            GroupMembershipModule.split_count: 5, GroupMembershipModule.group_index: 0,
        }),
        strategies[1]: StrategyConfig(strategy=strategies[1], field_values={
            GroupMembershipModule.split_count: 5, GroupMembershipModule.group_index: 1,
        }),
        strategies[2]: StrategyConfig(strategy=strategies[2], field_values={
            GroupMembershipModule.split_count: 5, GroupMembershipModule.group_index: 2,
        }),
        strategies[3]: StrategyConfig(strategy=strategies[3], field_values={
            GroupMembershipModule.split_count: 5, GroupMembershipModule.group_index: 3,
        }),
        # different split_count, same signal_value content -- must still
        # share the cached ranking, since the ranked order itself doesn't
        # depend on split_count.
        strategies[4]: StrategyConfig(strategy=strategies[4], field_values={
            GroupMembershipModule.split_count: 2, GroupMembershipModule.group_index: 0,
        }),
    }
    account = BacktestRunState(strategy_configs=configs)
    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset(strategies))
    for strategy in strategies:
        ctx.set_for(FactorSignalModule.signal_value, strategy, dict(signal_value))

    _group_quantile_membership(account, ctx)

    assert rank_calls == 1
    # sanity: each strategy still gets its own correct bucket
    weights0 = ctx.get_for(GroupMembershipModule.target_weights, strategies[0])
    weights4 = ctx.get_for(GroupMembershipModule.target_weights, strategies[4])
    assert set(weights0) == {products[3]}  # split_count=5, group_index=0 -> top 1/5
    assert set(weights4) == {products[2], products[3]}  # split_count=2, group_index=0 -> top half


def test_group_quantile_membership_reuses_raw_bucket_for_derived_group_sharing_split_and_index(monkeypatch):
    """A derived group shares its parent's split_count/group_index exactly
    (product_mask_names' own field docstring: "parent bucket intersected
    with mask") -- the raw bucket slice (before masking) should be computed
    once per (signal content, split_count, group_index), not once per
    strategy, even though the two strategies differ in product_mask_names."""
    import tools.testers.backtest.modules.group_membership as group_membership_module

    split_calls = 0
    real_split = group_membership_module.select_rank_group

    def _counting_split(*args, **kwargs):
        nonlocal split_calls
        split_calls += 1
        return real_split(*args, **kwargs)

    monkeypatch.setattr(group_membership_module, "select_rank_group", _counting_split)

    products = [_product() for _ in range(4)]
    signal_value = {p: float(i) for i, p in enumerate(products)}
    parent = Strategy(alias="parent")
    derived = Strategy(alias="derived")
    configs = {
        parent: StrategyConfig(strategy=parent, field_values={
            GroupMembershipModule.split_count: 2, GroupMembershipModule.group_index: 0,
        }),
        derived: StrategyConfig(strategy=derived, field_values={
            GroupMembershipModule.split_count: 2, GroupMembershipModule.group_index: 0,
            # same bucket as parent (top half = {products[2], products[3]}),
            # masked down to just products[2]
            GroupMembershipModule.product_mask_names: (products[2].name,),
        }),
    }
    account = BacktestRunState(strategy_configs=configs)
    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({parent, derived}))
    ctx.set_for(FactorSignalModule.signal_value, parent, dict(signal_value))
    ctx.set_for(FactorSignalModule.signal_value, derived, dict(signal_value))

    _group_quantile_membership(account, ctx)

    # One toolkit split for the shared raw bucket; applying the derived mask
    # must not split or rerank the cross-section again.
    assert split_calls == 1
    parent_weights = ctx.get_for(GroupMembershipModule.target_weights, parent)
    derived_weights = ctx.get_for(GroupMembershipModule.target_weights, derived)
    assert set(parent_weights) == {products[2], products[3]}
    assert set(derived_weights) == {products[2]}


def test_precomputed_target_intents_match_event_membership_and_skip_event_sort(monkeypatch):
    import tools.testers.backtest.modules.group_membership as group_membership_module

    products = [_product() for _ in range(4)]
    idx = pd.date_range("2024-01-01 09:00", periods=2, freq="min")
    signal_table = pd.DataFrame(
        [
            [0.0, 1.0, 2.0, 3.0],
            [3.0, 2.0, 1.0, 0.0],
        ],
        index=idx,
        columns=products,
    )
    s_top = Strategy(alias="TOP")
    s_bottom = Strategy(alias="BOTTOM")
    configs = {
        s_top: StrategyConfig(
            strategy=s_top,
            active_flow_names=frozenset({"signal_precomputed", "precompute_strategy_intents", "group_quantile_membership"}),
            field_values={GroupMembershipModule.split_count: 2, GroupMembershipModule.group_index: 0},
        ),
        s_bottom: StrategyConfig(
            strategy=s_bottom,
            active_flow_names=frozenset({"signal_precomputed", "precompute_strategy_intents", "group_quantile_membership"}),
            field_values={GroupMembershipModule.split_count: 2, GroupMembershipModule.group_index: 1},
        ),
    }
    account = BacktestRunState(strategy_configs=configs)
    account.market_data_store.current_prices_table = pd.DataFrame(
        {product: [10.0, 10.0] for product in products},
        index=idx,
    )
    account.factor_signal_store.put_precomputed_table("schedule", signal_table)
    account.factor_signal_store.bind_precomputed_table(s_top, "schedule")
    account.factor_signal_store.bind_precomputed_table(s_bottom, "schedule")

    pre_ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s_top, s_bottom}))
    _precompute_strategy_intents(account, pre_ctx)

    sort_calls = 0
    real_sorted = sorted

    def _counting_sorted(*args, **kwargs):
        nonlocal sort_calls
        sort_calls += 1
        return real_sorted(*args, **kwargs)

    monkeypatch.setattr(group_membership_module, "sorted", _counting_sorted, raising=False)

    event_ctx = FlowContext(timestamp=idx[0], event_queue=EventQueue(), active_strategies=frozenset({s_top, s_bottom}))
    _group_quantile_membership(account, event_ctx)

    assert sort_calls == 0
    assert set(event_ctx.get_for(GroupMembershipModule.target_weights, s_top)) == {products[2], products[3]}
    assert set(event_ctx.get_for(GroupMembershipModule.target_weights, s_bottom)) == {products[0], products[1]}


def test_precomputed_buy_and_hold_waits_for_first_non_empty_masked_target():
    products = [_product() for _ in range(4)]
    idx = pd.date_range("2024-01-01 09:00", periods=3, freq="min")
    signal_table = pd.DataFrame(
        [
            [0.0, 3.0, 2.0, 1.0],  # masked product not in top bucket
            [3.0, 2.0, 1.0, 0.0],  # masked product enters top bucket
            [0.0, 3.0, 2.0, 1.0],  # buy-and-hold must keep the established target
        ],
        index=idx,
        columns=products,
    )
    strategy = Strategy(alias="BUY_AND_HOLD_MASKED")
    config = StrategyConfig(
        strategy=strategy,
        active_flow_names=frozenset({"signal_precomputed", "precompute_strategy_intents", "group_quantile_membership"}),
        field_values={
            GroupMembershipModule.split_count: 2,
            GroupMembershipModule.group_index: 0,
            GroupMembershipModule.position_policy: "buy_and_hold",
            GroupMembershipModule.product_mask_names: (products[0].name,),
        },
    )
    account = BacktestRunState(strategy_configs={strategy: config})
    account.market_data_store.current_prices_table = pd.DataFrame(
        {product: [10.0, 10.0, 10.0] for product in products},
        index=idx,
    )
    account.factor_signal_store.put_precomputed_table("schedule", signal_table)
    account.factor_signal_store.bind_precomputed_table(strategy, "schedule")

    pre_ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({strategy}))
    _precompute_strategy_intents(account, pre_ctx)

    table = account.target_store.precomputed_target_intents[strategy]
    assert table[idx[0]].weights == {}
    assert table[idx[1]].weights == {products[0]: pytest.approx(1.0)}
    assert table[idx[2]].weights == {products[0]: pytest.approx(1.0)}


def test_execution_schedule_cache_reuses_next_bar_lookup(monkeypatch):
    import tools.testers.backtest.modules.group_membership as group_membership_module

    strategy = Strategy(alias="S")
    config = StrategyConfig(strategy=strategy, field_values={
        GroupMembershipModule.execution_delay_bars: 1,
        OrderExecutionModule.execution_price_basis: "open",
    })
    account = BacktestRunState(strategy_configs={strategy: config})
    idx = pd.date_range("2024-01-01 09:01", periods=3, freq="min", tz="Asia/Shanghai")
    account.market_data_store.current_prices_table = pd.DataFrame({"P": [1.0, 2.0, 3.0]}, index=idx)
    ctx = FlowContext(timestamp=idx[0], event_queue=EventQueue(), active_strategies=frozenset({strategy}))
    calls = 0
    real_signal_timestamps = group_membership_module.signal_timestamps

    def _counting_signal_timestamps(table):
        nonlocal calls
        calls += 1
        return real_signal_timestamps(table)

    monkeypatch.setattr(group_membership_module, "signal_timestamps", _counting_signal_timestamps)

    first = _resolve_execution_schedule(account, ctx, strategy)
    second = _resolve_execution_schedule(account, ctx, strategy)

    assert first == second
    assert first == (
        idx[0] + pd.Timedelta(microseconds=1),
        idx[1],
    )
    assert calls == 1


def test_precomputed_target_intents_share_ranking_across_groups(monkeypatch):
    import tools.testers.backtest.modules.group_membership as group_membership_module

    products = [_product() for _ in range(4)]
    idx = pd.date_range("2024-01-01 09:00", periods=1, freq="min")
    signal_table = pd.DataFrame([[0.0, 1.0, 2.0, 3.0]], index=idx, columns=products)
    strategies = [Strategy(alias=f"S{i}") for i in range(2)]
    configs = {
        strategies[0]: StrategyConfig(
            strategy=strategies[0],
            active_flow_names=frozenset({"signal_precomputed", "precompute_strategy_intents"}),
            field_values={GroupMembershipModule.split_count: 2, GroupMembershipModule.group_index: 0},
        ),
        strategies[1]: StrategyConfig(
            strategy=strategies[1],
            active_flow_names=frozenset({"signal_precomputed", "precompute_strategy_intents"}),
            field_values={GroupMembershipModule.split_count: 2, GroupMembershipModule.group_index: 1},
        ),
    }
    account = BacktestRunState(strategy_configs=configs)
    account.market_data_store.current_prices_table = pd.DataFrame(
        {product: [10.0] for product in products},
        index=idx,
    )
    for strategy in strategies:
        account.factor_signal_store.put_precomputed_table("schedule", signal_table)
        account.factor_signal_store.bind_precomputed_table(strategy, "schedule")

    sort_calls = 0
    real_sorted = sorted

    def _counting_sorted(*args, **kwargs):
        nonlocal sort_calls
        sort_calls += 1
        return real_sorted(*args, **kwargs)

    monkeypatch.setattr(group_membership_module, "sorted", _counting_sorted, raising=False)
    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset(strategies))
    _precompute_strategy_intents(account, ctx)

    # One call orders the precompute event groups; one call ranks the shared
    # cross-section.  A second strategy sharing the signal row must not add a
    # second cross-section sort.
    assert sort_calls == 2


def test_precomputed_target_intents_skip_historical_fields_when_allocation_does_not_need_them(monkeypatch):
    import tools.testers.backtest.modules.group_membership as group_membership_module

    products = [_product() for _ in range(2)]
    idx = pd.date_range("2024-01-01 09:00", periods=1, freq="min")
    signal_table = pd.DataFrame([[1.0, 2.0]], index=idx, columns=products)
    strategy = Strategy(alias="S")
    config = StrategyConfig(
        strategy=strategy,
        active_flow_names=frozenset({"signal_precomputed", "precompute_strategy_intents"}),
        field_values={
            GroupMembershipModule.split_count: 1,
            GroupMembershipModule.group_index: 0,
            GroupMembershipModule.allocation_policy: "equal_notional",
        },
    )
    account = BacktestRunState(strategy_configs={strategy: config})
    account.market_data_store.current_prices_table = pd.DataFrame({product: [10.0] for product in products}, index=idx)
    account.factor_signal_store.put_precomputed_table("schedule", signal_table)
    account.factor_signal_store.bind_precomputed_table(strategy, "schedule")

    def _forbidden(*args, **kwargs):
        raise AssertionError("FieldHistory should not be read for equal_notional precompute")

    monkeypatch.setattr(group_membership_module, "current_historical_fields_at", _forbidden)

    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({strategy}))
    _precompute_strategy_intents(account, ctx)

    assert account.target_store.precomputed_target_intents[strategy]


def test_precomputed_target_intents_read_historical_fields_for_equal_margin(monkeypatch):
    import tools.testers.backtest.modules.group_membership as group_membership_module

    products = [_product() for _ in range(2)]
    idx = pd.date_range("2024-01-01 09:00", periods=1, freq="min")
    signal_table = pd.DataFrame([[1.0, 2.0]], index=idx, columns=products)
    strategy = Strategy(alias="S")
    config = StrategyConfig(
        strategy=strategy,
        active_flow_names=frozenset({"signal_precomputed", "precompute_strategy_intents"}),
        field_values={
            GroupMembershipModule.split_count: 1,
            GroupMembershipModule.group_index: 0,
            GroupMembershipModule.allocation_policy: "equal_margin",
        },
    )
    account = BacktestRunState(strategy_configs={strategy: config})
    account.market_data_store.current_prices_table = pd.DataFrame({product: [10.0] for product in products}, index=idx)
    account.factor_signal_store.put_precomputed_table("schedule", signal_table)
    account.factor_signal_store.bind_precomputed_table(strategy, "schedule")
    calls = []

    def _historical_fields_at(_state, timestamp):
        calls.append(timestamp)
        return {
            product: {"LongMarginRatioByMoney": 0.1}
            for product in products
        }

    monkeypatch.setattr(group_membership_module, "current_historical_fields_at", _historical_fields_at)

    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({strategy}))
    _precompute_strategy_intents(account, ctx)

    assert calls == [idx[0]]
    assert account.target_store.precomputed_target_intents[strategy]


@pytest.mark.parametrize("allocation_policy", ["equal_notional", "inverse_volatility"])
def test_vectorized_precompute_matches_legacy_event_precompute(monkeypatch, allocation_policy):
    import tools.testers.backtest.modules.group_membership as group_membership_module

    products = [_product() for _ in range(5)]
    idx = pd.date_range("2024-01-01 09:00", periods=30, freq="min")
    signal_table = pd.DataFrame(
        [
            [float((row * 3 + col * 7) % 11) for col in range(len(products))]
            for row in range(len(idx))
        ],
        index=idx,
        columns=products,
    )
    price_table = pd.DataFrame(
        {
            product: [10.0 + product_index + row * 0.01 for row in range(len(idx))]
            for product_index, product in enumerate(products)
        },
        index=idx,
    )
    strategies = [Strategy(alias=f"S{i}") for i in range(2)]
    configs = {
        strategies[0]: StrategyConfig(
            strategy=strategies[0],
            active_flow_names=frozenset({"signal_precomputed", "precompute_strategy_intents"}),
            field_values={
                GroupMembershipModule.split_count: 3,
                GroupMembershipModule.group_index: 0,
                GroupMembershipModule.allocation_policy: allocation_policy,
                GroupMembershipModule.volatility_lookback: 4,
                GroupMembershipModule.volatility_warmup: "equal_notional",
            },
        ),
        strategies[1]: StrategyConfig(
            strategy=strategies[1],
            active_flow_names=frozenset({"signal_precomputed", "precompute_strategy_intents"}),
            field_values={
                GroupMembershipModule.split_count: 3,
                GroupMembershipModule.group_index: 2,
                GroupMembershipModule.allocation_policy: allocation_policy,
                GroupMembershipModule.volatility_lookback: 4,
                GroupMembershipModule.volatility_warmup: "equal_notional",
            },
        ),
    }

    def _state() -> BacktestRunState:
        account = BacktestRunState(strategy_configs=configs)
        account.market_data_store.current_prices_table = price_table
        account.factor_signal_store.put_precomputed_table("schedule", signal_table)
        for strategy in strategies:
            account.factor_signal_store.bind_precomputed_table(strategy, "schedule")
        return account

    vectorized = _state()
    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset(strategies))
    _precompute_strategy_intents(vectorized, ctx)

    legacy = _state()
    monkeypatch.setattr(group_membership_module, "_can_vectorize_group_precompute", lambda _state, _strategy: False)
    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset(strategies))
    _precompute_strategy_intents(legacy, ctx)

    for strategy in strategies:
        vectorized_table = vectorized.target_store.precomputed_target_intents[strategy]
        legacy_table = legacy.target_store.precomputed_target_intents[strategy]
        for timestamp in idx:
            assert vectorized_table[timestamp].weights == pytest.approx(legacy_table[timestamp].weights)


def test_precomputed_group_target_intents_uses_strategy_book_policy_hook():
    products = [_product() for _ in range(2)]
    idx = pd.date_range("2024-01-01 09:00", periods=1, freq="min")
    signal_table = pd.DataFrame([[1.0, 2.0]], index=idx, columns=products)
    strategy = Strategy(alias="S")
    config = StrategyConfig(
        strategy=strategy,
        active_flow_names=frozenset({"signal_precomputed", "precompute_strategy_intents"}),
        field_values={GroupMembershipModule.split_count: 1, GroupMembershipModule.group_index: 0},
    )
    account = BacktestRunState(strategy_configs={strategy: config})
    account.market_data_store.current_prices_table = pd.DataFrame({product: [10.0] for product in products}, index=idx)
    account.factor_signal_store.put_precomputed_table("schedule", signal_table)
    account.factor_signal_store.bind_precomputed_table(strategy, "schedule")
    calls = []

    def _policy(state, ctx, strategies, default_policy):
        calls.append((tuple(strategies), default_policy.__class__.__name__))
        default_policy.precompute_strategy_intents(state, ctx, strategies)

    strategy_book_store_for(account).policies = StrategyBookPolicies(strategy_intent_precompute=_policy)
    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({strategy}))

    _precompute_strategy_intents(account, ctx)

    assert calls == [((strategy,), "GroupMembershipIntentPolicy")]
    assert account.target_store.precomputed_target_intents[strategy]


def test_precomputed_intent_resolves_per_strategy_policy_before_kind_default():
    custom_strategy = Strategy(alias="custom")
    default_strategy = Strategy(alias="default")
    strategies = (custom_strategy, default_strategy)
    idx = pd.date_range("2024-01-01 09:00", periods=1, freq="min")
    product = _product()
    configs = {
        strategy: StrategyConfig(
            strategy=strategy,
            active_flow_names=frozenset({"signal_precomputed", "precompute_strategy_intents"}),
            field_values={GroupMembershipModule.split_count: 1, GroupMembershipModule.group_index: 0},
        )
        for strategy in strategies
    }
    account = BacktestRunState(strategy_configs=configs)
    account.market_data_store.current_prices_table = pd.DataFrame({product: [10.0]}, index=idx)
    account.factor_signal_store.put_precomputed_table("schedule", pd.DataFrame({product: [1.0]}, index=idx))
    for strategy in strategies:
        account.factor_signal_store.bind_precomputed_table(strategy, "schedule")

    calls = []

    class RecordingPolicy(StrategyIntentPolicy):
        def precompute_strategy_intents(self, state, ctx, selected_strategies):
            calls.append(tuple(selected_strategies))

    strategy_book_store_for(account).policies = StrategyBookPolicies(
        strategy_intent_by_alias={"custom": RecordingPolicy()},
    )
    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset(strategies))

    _precompute_strategy_intents(account, ctx)

    assert calls == [(custom_strategy,)]
    assert default_strategy in account.target_store.precomputed_target_intents
    assert custom_strategy not in account.target_store.precomputed_target_intents


def test_group_quantile_membership_ignores_products_without_current_price():
    s = Strategy(alias="S")
    tradable, removed = _product(), _product()
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.split_count: 1, GroupMembershipModule.group_index: 0,
    })
    account = BacktestRunState(strategy_configs={s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set(MarketDataModule.current_prices, {tradable: 10.0})
    ctx.set_for(FactorSignalModule.signal_value, s, {removed: 1.0, tradable: 2.0})

    _group_quantile_membership(account, ctx)

    weights = ctx.get_for(GroupMembershipModule.target_weights, s)
    assert weights == {tradable: pytest.approx(1.0)}


def test_group_quantile_membership_uses_explicit_tradable_status():
    s = Strategy(alias="S")
    tradable, halted = _product(), _product()
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.split_count: 1, GroupMembershipModule.group_index: 0,
    })
    account = BacktestRunState(strategy_configs={s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set(MarketDataModule.current_prices, {tradable: 10.0, halted: 10.0})
    ctx.set(MarketDataModule.current_tradable_status, {tradable: True, halted: False})
    ctx.set_for(FactorSignalModule.signal_value, s, {halted: 100.0, tradable: 1.0})

    _group_quantile_membership(account, ctx)

    weights = ctx.get_for(GroupMembershipModule.target_weights, s)
    assert weights == {tradable: pytest.approx(1.0)}


def test_group_quantile_membership_applies_product_mask_after_full_bucket_selection():
    s = Strategy(alias="S")
    products = [_product() for _ in range(4)]
    signal_value = {p: float(i) for i, p in enumerate(products)}
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.split_count: 2,
        GroupMembershipModule.group_index: 0,
        # highest bucket is {products[2], products[3]}; mask excludes products[3]
        GroupMembershipModule.product_mask_names: tuple(p.name for p in products[:3]),
    })
    account = BacktestRunState(strategy_configs={s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set(MarketDataModule.current_prices, {p: 10.0 for p in products})
    ctx.set_for(FactorSignalModule.signal_value, s, signal_value)

    _group_quantile_membership(account, ctx)

    weights = ctx.get_for(GroupMembershipModule.target_weights, s)
    assert weights == {products[2]: pytest.approx(1.0)}


def test_equal_margin_allocation_reads_the_per_strategy_historical_field_override():
    """_set_current_historical_fields (market_data.py) computes a per-strategy
    override via ctx.set_for(..., strategy, ...) for engine_mode="custom"
    strategies with custom margin fields -- _allocate_equal_margin must
    actually read that per-strategy value (ctx.get_for), not just the
    global one (ctx.get), or a strategy's custom margin ratios silently
    never take effect."""
    s = Strategy(alias="S")
    products = [_product() for _ in range(2)]
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.split_count: 1, GroupMembershipModule.group_index: 0,
        GroupMembershipModule.allocation_policy: "equal_margin",
    })
    account = BacktestRunState(strategy_configs={s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set_for(FactorSignalModule.signal_value, s, {p: 1.0 for p in products})
    # global fields say both products have equal margin ratio (would give
    # equal weight); the per-strategy override says product[0] has a much
    # higher ratio (lower weight) -- only the per-strategy read should win.
    ctx.set(MarketDataModule.current_historical_fields, {
        products[0]: {"LongMarginRatioByMoney": 0.1},
        products[1]: {"LongMarginRatioByMoney": 0.1},
    })
    ctx.set_for(MarketDataModule.current_historical_fields, s, {
        products[0]: {"LongMarginRatioByMoney": 0.4},
        products[1]: {"LongMarginRatioByMoney": 0.1},
    })

    _group_quantile_membership(account, ctx)

    weights = ctx.get_for(GroupMembershipModule.target_weights, s)
    # equal_margin weights ∝ 1/ratio: product[0] gets 1/0.4=2.5, product[1] gets 1/0.1=10
    total = 2.5 + 10.0
    assert weights[products[0]] == pytest.approx(2.5 / total)
    assert weights[products[1]] == pytest.approx(10.0 / total)


def test_group_quantile_membership_selects_lowest_bucket_last():
    s = Strategy(alias="S")
    products = [_product() for _ in range(4)]
    signal_value = {p: float(i) for i, p in enumerate(products)}
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.split_count: 2, GroupMembershipModule.group_index: 1,
    })
    account = BacktestRunState(strategy_configs={s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set_for(FactorSignalModule.signal_value, s, signal_value)

    _group_quantile_membership(account, ctx)
    weights = ctx.get_for(GroupMembershipModule.target_weights, s)
    assert set(weights) == {products[0], products[1]}


def test_resolve_execution_timestamp_rejects_same_bar_execution():
    s = Strategy(alias="S")
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.execution_timing: "same_bar",
    })
    account = BacktestRunState(strategy_configs={s: config})
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
    account = BacktestRunState(strategy_configs={s: config})
    account.market_data_store.current_prices_table = pd.DataFrame(
        {"P1": [1, 2, 3, 4]}, index=pd.date_range("2024-01-01", periods=4))
    t = pd.Timestamp("2024-01-01")
    ctx = FlowContext(timestamp=t, event_queue=EventQueue())
    result = _resolve_execution_timestamp(account, ctx, s)
    assert result == pd.Timestamp("2024-01-02") + pd.Timedelta(microseconds=1)


def test_resolve_execution_schedule_next_bar_open_uses_next_row_price_and_open_visibility_event():
    s_open = Strategy(alias="open")
    idx = pd.date_range("2024-01-01 09:01", periods=3, freq="1min")
    account = BacktestRunState(strategy_configs={
        s_open: StrategyConfig(strategy=s_open, field_values={
            GroupMembershipModule.execution_timing: "next_bar",
            GroupMembershipModule.execution_delay_bars: 1,
            OrderExecutionModule.execution_price_basis: "open",
        }),
    })
    account.market_data_store.current_prices_table = pd.DataFrame({"P1": [1, 2, 3]}, index=idx)
    ctx = FlowContext(timestamp=idx[0], event_queue=EventQueue())

    schedule = _resolve_execution_schedule(account, ctx, s_open)
    assert schedule is not None
    open_event_ts, open_price_ts = schedule

    assert open_event_ts == idx[0] + pd.Timedelta(microseconds=1)
    assert open_price_ts == idx[1]


def test_resolve_execution_schedule_allows_configured_open_visibility_delay():
    s_open = Strategy(alias="open")
    idx = pd.date_range("2024-01-01 09:01", periods=3, freq="1min")
    account = BacktestRunState(strategy_configs={
        s_open: StrategyConfig(strategy=s_open, field_values={
            GroupMembershipModule.execution_timing: "next_bar",
            GroupMembershipModule.execution_delay_bars: 1,
            OrderExecutionModule.execution_price_basis: "open",
            EngineModule.bar_open_visibility_delay: "5ms",
        }),
    })
    account.market_data_store.current_prices_table = pd.DataFrame({"P1": [1, 2, 3]}, index=idx)
    ctx = FlowContext(timestamp=idx[0], event_queue=EventQueue())

    schedule = _resolve_execution_schedule(account, ctx, s_open)
    assert schedule is not None
    event_ts, price_ts = schedule

    assert event_ts == idx[0] + pd.Timedelta(milliseconds=5)
    assert price_ts == idx[1]


def test_resolve_execution_schedule_next_bar_open_does_not_leak_across_session_gap():
    s_open = Strategy(alias="open")
    idx = pd.DatetimeIndex([
        pd.Timestamp("2026-01-06 14:59", tz="Asia/Shanghai"),
        pd.Timestamp("2026-01-06 15:00", tz="Asia/Shanghai"),
        pd.Timestamp("2026-01-07 09:01", tz="Asia/Shanghai"),
    ])
    account = BacktestRunState(strategy_configs={
        s_open: StrategyConfig(strategy=s_open, field_values={
            GroupMembershipModule.execution_timing: "next_bar",
            GroupMembershipModule.execution_delay_bars: 1,
            OrderExecutionModule.execution_price_basis: "open",
            EngineModule.bar_open_visibility_delay: "1us",
        }),
    })
    account.market_data_store.current_prices_table = pd.DataFrame({"P1": [1, 2, 3]}, index=idx)
    ctx = FlowContext(timestamp=idx[1], event_queue=EventQueue())

    schedule = _resolve_execution_schedule(account, ctx, s_open)
    assert schedule is not None
    event_ts, price_ts = schedule

    assert event_ts == pd.Timestamp("2026-01-07 09:00:00.000001", tz="Asia/Shanghai")
    assert price_ts == idx[2]


def test_resolve_execution_schedule_uses_resolved_market_data_frequency():
    s_open = Strategy(alias="open")
    idx = pd.DatetimeIndex([
        pd.Timestamp("2026-01-06 15:00", tz="Asia/Shanghai"),
        pd.Timestamp("2026-01-07 09:31", tz="Asia/Shanghai"),
    ])
    account = BacktestRunState(strategy_configs={
        s_open: StrategyConfig(strategy=s_open, field_values={
            GroupMembershipModule.execution_timing: "next_bar",
            GroupMembershipModule.execution_delay_bars: 1,
            OrderExecutionModule.execution_price_basis: "open",
            EngineModule.bar_open_visibility_delay: "1us",
        }),
    })
    account.market_data_store.required_frequency_by_strategy[s_open] = DataFreq("MIN30")
    account.market_data_store.current_prices_table = pd.DataFrame({"P1": [1, 2]}, index=idx)
    ctx = FlowContext(timestamp=idx[0], event_queue=EventQueue())

    schedule = _resolve_execution_schedule(account, ctx, s_open)
    assert schedule is not None
    event_ts, price_ts = schedule

    assert event_ts == pd.Timestamp("2026-01-07 09:01:00.000001", tz="Asia/Shanghai")
    assert price_ts == idx[1]


def test_resolve_execution_schedule_rejects_non_positive_open_visibility_delay():
    s_open = Strategy(alias="open")
    idx = pd.date_range("2024-01-01 09:01", periods=3, freq="1min")
    account = BacktestRunState(strategy_configs={
        s_open: StrategyConfig(strategy=s_open, field_values={
            GroupMembershipModule.execution_timing: "next_bar",
            GroupMembershipModule.execution_delay_bars: 1,
            OrderExecutionModule.execution_price_basis: "open",
            EngineModule.bar_open_visibility_delay: "0ns",
        }),
    })
    account.market_data_store.current_prices_table = pd.DataFrame({"P1": [1, 2, 3]}, index=idx)
    ctx = FlowContext(timestamp=idx[0], event_queue=EventQueue())

    with pytest.raises(ValueError, match="bar_open_visibility_delay must be positive"):
        _resolve_execution_schedule(account, ctx, s_open)


def test_resolve_execution_schedule_rejects_non_open_price_basis():
    s = Strategy(alias="S")
    idx = pd.date_range("2024-01-01 09:01", periods=2, freq="1min")
    account = BacktestRunState(strategy_configs={
        s: StrategyConfig(strategy=s, field_values={
            GroupMembershipModule.execution_timing: "next_bar",
            OrderExecutionModule.execution_price_basis: "close",
        }),
    })
    account.market_data_store.current_prices_table = pd.DataFrame({"P1": [1, 2]}, index=idx)
    ctx = FlowContext(timestamp=idx[0], event_queue=EventQueue())

    with pytest.raises(ValueError, match="next-bar open"):
        _resolve_execution_schedule(account, ctx, s)


def test_resolve_execution_schedule_returns_none_without_future_bar():
    s = Strategy(alias="S")
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.execution_timing: "next_bar",
        GroupMembershipModule.execution_delay_bars: 10,
    })
    account = BacktestRunState(strategy_configs={s: config})
    account.market_data_store.current_prices_table = pd.DataFrame(
        {"P1": [1, 2]}, index=pd.date_range("2024-01-01", periods=2))
    t = pd.Timestamp("2024-01-01")
    ctx = FlowContext(timestamp=t, event_queue=EventQueue())
    assert _resolve_execution_schedule(account, ctx, s) is None


def test_resolve_execution_schedule_returns_none_when_signal_is_after_price_index():
    s = Strategy(alias="S")
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.execution_timing: "next_bar",
        GroupMembershipModule.execution_delay_bars: 1,
        OrderExecutionModule.execution_price_basis: "open",
    })
    account = BacktestRunState(strategy_configs={s: config})
    index = pd.date_range("2024-01-01 09:01", periods=2, freq="1min")
    account.market_data_store.current_prices_table = pd.DataFrame({"P1": [1, 2]}, index=index)
    ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01 09:05"), event_queue=EventQueue())

    assert _resolve_execution_schedule(account, ctx, s) is None


def test_schedule_order_execution_skips_orders_without_future_bar():
    s = Strategy(alias="S")
    p = _product()
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.execution_timing: "next_bar",
        OrderExecutionModule.execution_price_basis: "open",
    })
    account = BacktestRunState(strategy_configs={s: config})
    last = pd.Timestamp("2024-01-02")
    account.market_data_store.current_prices_table = pd.DataFrame(
        {p: [1, 2]}, index=pd.date_range("2024-01-01", periods=2))
    queue = EventQueue()
    order = Order(instrument=p, timestamp=last, quantity=10.0, intent_quantity=10.0, strategy=s)
    ctx = FlowContext(timestamp=last, event_queue=queue, active_strategies=frozenset({s}))
    ctx.set_for(OrderConstructModule.orders, s, [order])

    _schedule_order_execution(account, ctx)

    assert order.status == OrderStatus.DRAFT
    seen = []
    queue.set_dispatcher(EventKind.ORDER, lambda batch: seen.extend(batch))
    queue.run_until_drained()
    assert seen == []


def test_schedule_order_execution_sets_scheduled_and_pushes_event():
    s = Strategy(alias="S")
    p = _product()
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.execution_timing: "next_bar",
        OrderExecutionModule.execution_price_basis: "open",
    })
    account = BacktestRunState(strategy_configs={s: config})
    account.market_data_store.current_prices_table = pd.DataFrame(
        {p: [1, 2]}, index=pd.date_range("2024-01-01", periods=2))
    queue = EventQueue()
    t = pd.Timestamp("2024-01-01")
    order = Order(instrument=p, timestamp=t, quantity=10.0, intent_quantity=10.0, strategy=s)
    ctx = FlowContext(timestamp=t, event_queue=queue, active_strategies=frozenset({s}))
    ctx.set_for(OrderConstructModule.orders, s, [order])

    _schedule_order_execution(account, ctx)

    assert order.status == OrderStatus.SCHEDULED
    seen = []
    queue.set_dispatcher(EventKind.ORDER, lambda batch: seen.extend(batch))
    queue.run_until_drained()
    assert len(seen) == 1
    assert seen[0].payload is order


def test_schedule_order_execution_uses_each_products_next_available_open_bar():
    s = Strategy(alias="S")
    day_product, night_product = _product(), _product()
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.execution_timing: "next_bar",
        OrderExecutionModule.execution_price_basis: "open",
    })
    account = BacktestRunState(strategy_configs={s: config})
    index = pd.DatetimeIndex([
        pd.Timestamp("2026-01-05 15:00"),
        pd.Timestamp("2026-01-05 21:00"),
        pd.Timestamp("2026-01-06 09:01"),
    ])
    account.market_data_store.current_prices_table = pd.DataFrame(
        {
            day_product: [10.0, 10.0, 11.0],
            night_product: [20.0, 21.0, 22.0],
        },
        index=index,
    )
    account.market_data_store.market_price_tables = {
        "open": pd.DataFrame(
            {
                day_product: [10.0, float("nan"), 11.0],
                night_product: [20.0, 21.0, 22.0],
            },
            index=index,
        )
    }
    queue = EventQueue()
    t = pd.Timestamp("2026-01-05 15:00")
    day_order = Order(instrument=day_product, timestamp=t, quantity=1.0, intent_quantity=1.0, strategy=s)
    night_order = Order(instrument=night_product, timestamp=t, quantity=1.0, intent_quantity=1.0, strategy=s)
    ctx = FlowContext(timestamp=t, event_queue=queue, active_strategies=frozenset({s}))
    ctx.set_for(OrderConstructModule.orders, s, [day_order, night_order])

    _schedule_order_execution(account, ctx)

    assert night_order.get("price_timestamp") == pd.Timestamp("2026-01-05 21:00")
    assert day_order.get("price_timestamp") == pd.Timestamp("2026-01-06 09:01")


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
    account = BacktestRunState(strategy_configs={s: config})
    account.market_data_store.current_prices_table = pd.DataFrame(
        {p: [1, 2, 3, 4]}, index=pd.date_range("2024-01-01", periods=4))
    queue = EventQueue()
    t1, t2 = pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-02")

    old_order = Order(instrument=p, timestamp=t1, quantity=10.0, intent_quantity=10.0, strategy=s)
    ctx1 = FlowContext(timestamp=t1, event_queue=queue, active_strategies=frozenset({s}))
    ctx1.set_for(OrderConstructModule.orders, s, [old_order])
    _schedule_order_execution(account, ctx1)
    assert old_order.status == OrderStatus.SCHEDULED
    assert old_order.timestamp == pd.Timestamp("2024-01-02") + pd.Timedelta(microseconds=1)
    assert old_order.get("price_timestamp") == pd.Timestamp("2024-01-03")

    new_order = Order(instrument=p, timestamp=t2, quantity=20.0, intent_quantity=20.0, strategy=s)
    ctx2 = FlowContext(timestamp=t2, event_queue=queue, active_strategies=frozenset({s}))
    ctx2.set_for(OrderConstructModule.orders, s, [new_order])
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
    account = BacktestRunState(strategy_configs={s: config})
    account.market_data_store.current_prices_table = pd.DataFrame(
        {p: [1, 2]}, index=pd.date_range("2024-01-01", periods=2))
    queue = EventQueue()
    t = pd.Timestamp("2024-01-01")

    old_order = Order(instrument=p, timestamp=t, quantity=10.0, intent_quantity=10.0, strategy=s)
    ctx1 = FlowContext(timestamp=t, event_queue=queue, active_strategies=frozenset({s}))
    ctx1.set_for(OrderConstructModule.orders, s, [old_order])
    _schedule_order_execution(account, ctx1)
    assert old_order.status == OrderStatus.SCHEDULED

    new_order = Order(instrument=p, timestamp=t, quantity=20.0, intent_quantity=20.0, strategy=s)
    ctx2 = FlowContext(timestamp=t, event_queue=queue, active_strategies=frozenset({s}))
    ctx2.set_for(OrderConstructModule.orders, s, [new_order])
    _schedule_order_execution(account, ctx2)

    assert old_order.status == OrderStatus.CANCELLED
    assert new_order.status == OrderStatus.SCHEDULED


def test_schedule_order_execution_respects_strategy_book_pending_order_policy():
    s = Strategy(alias="S")
    p = _product()
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.execution_timing: "next_bar",
        GroupMembershipModule.execution_delay_bars: 1,
        OrderExecutionModule.execution_price_basis: "open",
    })
    account = BacktestRunState(strategy_configs={s: config})
    account.market_data_store.current_prices_table = pd.DataFrame(
        {p: [1, 2]}, index=pd.date_range("2024-01-01", periods=2))
    strategy_book_store_for(account).policies = StrategyBookPolicies(
        pending_order_conflict=lambda _state, _strategy, _order, _timestamp: None
    )
    queue = EventQueue()
    t = pd.Timestamp("2024-01-01")

    old_order = Order(instrument=p, timestamp=t, quantity=10.0, intent_quantity=10.0, strategy=s)
    ctx1 = FlowContext(timestamp=t, event_queue=queue, active_strategies=frozenset({s}))
    ctx1.set_for(OrderConstructModule.orders, s, [old_order])
    _schedule_order_execution(account, ctx1)

    new_order = Order(instrument=p, timestamp=t, quantity=20.0, intent_quantity=20.0, strategy=s)
    ctx2 = FlowContext(timestamp=t, event_queue=queue, active_strategies=frozenset({s}))
    ctx2.set_for(OrderConstructModule.orders, s, [new_order])
    _schedule_order_execution(account, ctx2)

    assert old_order.status == OrderStatus.SCHEDULED
    assert new_order.status == OrderStatus.SCHEDULED


def test_schedule_order_execution_does_not_cancel_across_different_products():
    s = Strategy(alias="S")
    p1, p2 = _product(), _product()
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.execution_timing: "next_bar",
        OrderExecutionModule.execution_price_basis: "open",
    })
    account = BacktestRunState(strategy_configs={s: config})
    account.market_data_store.current_prices_table = pd.DataFrame(
        {p1: [1, 2], p2: [1, 2]}, index=pd.date_range("2024-01-01", periods=2))
    queue = EventQueue()
    t = pd.Timestamp("2024-01-01")

    order1 = Order(instrument=p1, timestamp=t, quantity=10.0, intent_quantity=10.0, strategy=s)
    ctx1 = FlowContext(timestamp=t, event_queue=queue, active_strategies=frozenset({s}))
    ctx1.set_for(OrderConstructModule.orders, s, [order1])
    _schedule_order_execution(account, ctx1)

    order2 = Order(instrument=p2, timestamp=t, quantity=20.0, intent_quantity=20.0, strategy=s)
    ctx2 = FlowContext(timestamp=t, event_queue=queue, active_strategies=frozenset({s}))
    ctx2.set_for(OrderConstructModule.orders, s, [order2])
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
    account = BacktestRunState(strategy_configs={s: config})

    ctx1 = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx1.set_for(FactorSignalModule.signal_value, s, {p: float(i) for i, p in enumerate(products)})
    _group_quantile_membership(account, ctx1)
    first_weights = ctx1.get_for(GroupMembershipModule.target_weights, s)
    assert set(first_weights) == {products[2], products[3]}

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
    account = BacktestRunState(strategy_configs={s: config})

    ctx1 = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx1.set_for(FactorSignalModule.signal_value, s, {p: float(i) for i, p in enumerate(products)})
    _group_quantile_membership(account, ctx1)
    first_weights = ctx1.get_for(GroupMembershipModule.target_weights, s)

    ctx2 = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx2.set_for(FactorSignalModule.signal_value, s, {p: float(len(products) - i) for i, p in enumerate(products)})
    _group_quantile_membership(account, ctx2)
    second_weights = ctx2.get_for(GroupMembershipModule.target_weights, s)
    assert second_weights != first_weights
    assert set(second_weights) == {products[0], products[1]}


def test_membership_change_trigger_skips_recompute_when_bucket_unchanged():
    s = Strategy(alias="S")
    products = [_product() for _ in range(4)]
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.split_count: 2, GroupMembershipModule.group_index: 0,
        GroupMembershipModule.rebalance_trigger: "membership_change",
    })
    account = BacktestRunState(strategy_configs={s: config})

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
    account = BacktestRunState(strategy_configs={s: config})

    ctx1 = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx1.set_for(FactorSignalModule.signal_value, s, {p: float(i) for i, p in enumerate(products)})
    _group_quantile_membership(account, ctx1)
    first_weights = ctx1.get_for(GroupMembershipModule.target_weights, s)
    assert set(first_weights) == {products[2], products[3]}

    ctx2 = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx2.set_for(FactorSignalModule.signal_value, s, {p: float(len(products) - i) for i, p in enumerate(products)})
    _group_quantile_membership(account, ctx2)
    second_weights = ctx2.get_for(GroupMembershipModule.target_weights, s)
    assert set(second_weights) == {products[0], products[1]}
    assert second_weights != first_weights


def test_scheduled_trigger_raises_not_implemented():
    s = Strategy(alias="S")
    products = [_product() for _ in range(2)]
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.split_count: 2, GroupMembershipModule.group_index: 0,
        GroupMembershipModule.rebalance_trigger: "scheduled",
    })
    account = BacktestRunState(strategy_configs={s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set_for(FactorSignalModule.signal_value, s, {p: float(i) for i, p in enumerate(products)})
    with pytest.raises(NotImplementedError):
        _group_quantile_membership(account, ctx)


def test_membership_change_trigger_rejects_inverse_volatility_allocation():
    """membership_change's reuse-shortcut assumes weight is a pure function
    of membership size ("same set -> same weights"), true only for
    equal_notional. inverse_volatility derives weight from trailing
    volatility at ctx.timestamp -- a rolling window that drifts every bar
    even for a fixed membership set -- so reusing stale weights here would
    silently serve a no-longer-risk-balanced allocation. Must reject, not
    silently misbehave."""
    s = Strategy(alias="S")
    products = [_product() for _ in range(2)]
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.split_count: 1, GroupMembershipModule.group_index: 0,
        GroupMembershipModule.rebalance_trigger: "membership_change",
        GroupMembershipModule.allocation_policy: "inverse_volatility",
    })
    account = BacktestRunState(strategy_configs={s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set_for(FactorSignalModule.signal_value, s, {p: float(i) for i, p in enumerate(products)})
    with pytest.raises(ValueError, match="membership_change"):
        _group_quantile_membership(account, ctx)


def test_membership_change_trigger_rejects_equal_margin_allocation():
    s = Strategy(alias="S")
    products = [_product() for _ in range(2)]
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.split_count: 1, GroupMembershipModule.group_index: 0,
        GroupMembershipModule.rebalance_trigger: "membership_change",
        GroupMembershipModule.allocation_policy: "equal_margin",
    })
    account = BacktestRunState(strategy_configs={s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set_for(FactorSignalModule.signal_value, s, {p: float(i) for i, p in enumerate(products)})
    with pytest.raises(ValueError, match="membership_change"):
        _group_quantile_membership(account, ctx)


def test_membership_change_trigger_still_allowed_with_equal_notional_allocation():
    s = Strategy(alias="S")
    products = [_product() for _ in range(2)]
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.split_count: 1, GroupMembershipModule.group_index: 0,
        GroupMembershipModule.rebalance_trigger: "membership_change",
        GroupMembershipModule.allocation_policy: "equal_notional",
    })
    account = BacktestRunState(strategy_configs={s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set_for(FactorSignalModule.signal_value, s, {p: float(i) for i, p in enumerate(products)})

    _group_quantile_membership(account, ctx)

    weights = ctx.get_for(GroupMembershipModule.target_weights, s)
    assert set(weights) == set(products)


def test_inverse_volatility_allocates_more_to_calmer_product():
    s = Strategy(alias="S")
    p_calm, p_volatile = _product(), _product()
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.split_count: 1, GroupMembershipModule.group_index: 0,
        GroupMembershipModule.allocation_policy: "inverse_volatility",
        GroupMembershipModule.volatility_lookback: 3,
    })
    account = BacktestRunState(strategy_configs={s: config})
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


def test_inverse_volatility_reuses_rolling_volatility_table(monkeypatch):
    build_calls = 0
    real_pct_change = pd.DataFrame.pct_change

    def _counting_pct_change(self, *args, **kwargs):
        nonlocal build_calls
        build_calls += 1
        return real_pct_change(self, *args, **kwargs)

    monkeypatch.setattr(pd.DataFrame, "pct_change", _counting_pct_change)

    s = Strategy(alias="S")
    p_calm, p_volatile = _product(), _product()
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.split_count: 1,
        GroupMembershipModule.group_index: 0,
        GroupMembershipModule.allocation_policy: "inverse_volatility",
        GroupMembershipModule.volatility_lookback: 3,
    })
    account = BacktestRunState(strategy_configs={s: config})
    idx = pd.date_range("2024-01-01", periods=6)
    account.market_data_store.current_prices_table = pd.DataFrame({
        p_calm: [100.0, 101.0, 100.0, 101.0, 100.0, 101.0],
        p_volatile: [100.0, 120.0, 90.0, 130.0, 80.0, 140.0],
    }, index=idx)

    for timestamp in (idx[-2], idx[-1]):
        ctx = FlowContext(timestamp=timestamp, event_queue=EventQueue(), active_strategies=frozenset({s}))
        ctx.set_for(FactorSignalModule.signal_value, s, {p_calm: 1.0, p_volatile: 1.0})
        _group_quantile_membership(account, ctx)

    assert build_calls == 1
    assert len(account.target_store.rolling_volatility_tables) == 1


def test_inverse_volatility_warmup_equal_notional_fallback_for_insufficient_history():
    s = Strategy(alias="S")
    p_established, p_new = _product(), _product()
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.split_count: 1, GroupMembershipModule.group_index: 0,
        GroupMembershipModule.allocation_policy: "inverse_volatility",
        GroupMembershipModule.volatility_lookback: 3,
        GroupMembershipModule.volatility_warmup: "equal_notional",
    })
    account = BacktestRunState(strategy_configs={s: config})
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
    account = BacktestRunState(strategy_configs={s: config})
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
    account = BacktestRunState(strategy_configs={s: config})
    t = pd.Timestamp("2024-01-01")

    ctx = FlowContext(timestamp=t, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set_for(FactorSignalModule.signal_value, s, {p: float(i) for i, p in enumerate(products)})
    _group_quantile_membership(account, ctx)

    trace = target_trace_for(account, s)
    assert t.isoformat() in trace
    assert trace[t.isoformat()] == {str(products[2]): 0.5, str(products[3]): 0.5}


def test_target_trace_not_recorded_when_membership_change_skips_recompute():
    s = Strategy(alias="S")
    products = [_product() for _ in range(4)]
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.split_count: 2, GroupMembershipModule.group_index: 0,
        GroupMembershipModule.rebalance_trigger: "membership_change",
    })
    account = BacktestRunState(strategy_configs={s: config})
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


def test_nan_signal_values_are_excluded_from_every_bucket():
    """A product whose factor value is NaN on this cross-section cannot be
    ranked. Industry cross-section convention (Alphalens/Qlib quantile
    bucketing): NaN samples are dropped from the ranking entirely and the
    bucket boundaries are computed over the valid universe -- a NaN product
    silently landing in some bucket (wherever an undefined NaN comparison
    happens to leave it in the sort) is a correctness bug, not a tie."""
    s_top, s_bottom = Strategy(alias="TOP"), Strategy(alias="BOTTOM")
    products = [_product() for _ in range(4)]
    nan_product = _product()
    signal_value = {p: float(i) for i, p in enumerate(products)}  # p0 < p1 < p2 < p3
    signal_value[nan_product] = float("nan")

    config_top = StrategyConfig(strategy=s_top, field_values={
        GroupMembershipModule.split_count: 2, GroupMembershipModule.group_index: 0,
    })
    config_bottom = StrategyConfig(strategy=s_bottom, field_values={
        GroupMembershipModule.split_count: 2, GroupMembershipModule.group_index: 1,
    })
    account = BacktestRunState(strategy_configs={s_top: config_top, s_bottom: config_bottom})
    ctx = FlowContext(
        timestamp=None, event_queue=EventQueue(),
        active_strategies=frozenset({s_top, s_bottom}),
    )
    ctx.set_for(FactorSignalModule.signal_value, s_top, dict(signal_value))
    ctx.set_for(FactorSignalModule.signal_value, s_bottom, dict(signal_value))

    _group_quantile_membership(account, ctx)

    top = ctx.get_for(GroupMembershipModule.target_weights, s_top)
    bottom = ctx.get_for(GroupMembershipModule.target_weights, s_bottom)
    assert nan_product not in top and nan_product not in bottom
    # bucket boundaries over the 4 valid products: top half / bottom half
    assert set(top) == {products[2], products[3]}
    assert set(bottom) == {products[0], products[1]}
    assert sum(top.values()) == pytest.approx(1.0)
    assert sum(bottom.values()) == pytest.approx(1.0)


def test_all_nan_cross_section_produces_empty_target():
    """When every signal value is NaN at a timestamp (e.g. factor warmup not
    yet satisfied for any product), the rebalance target must be empty --
    not an arbitrary bucket of unrankable products."""
    s = Strategy(alias="S")
    products = [_product() for _ in range(3)]
    config = StrategyConfig(strategy=s, field_values={
        GroupMembershipModule.split_count: 3, GroupMembershipModule.group_index: 0,
    })
    account = BacktestRunState(strategy_configs={s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set_for(FactorSignalModule.signal_value, s, {p: float("nan") for p in products})

    _group_quantile_membership(account, ctx)

    assert ctx.get_for(GroupMembershipModule.target_weights, s) == {}
