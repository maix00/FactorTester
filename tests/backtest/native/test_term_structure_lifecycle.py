from __future__ import annotations

from typing import cast

import pandas as pd

from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.ledger import AccountState, ProductPosition, StrategyConfig
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.product_selection import (
    DeliveryForceCloseModule,
    ProductSelectionModule,
    RolloverModule,
    TermStructureExpandModule,
    _expand_term_structure,
    _handle_delivery_force_close_notice,
    _register_force_close_notices,
    _register_rollover_notices,
    _resolve_tradable_target_weights,
)
from tools.testers.backtest.modules.group_membership import GroupMembershipModule
from tools.testers.backtest.modules.run_window import RunWindowModule, strategy_run_window_datetimes


def _ms(value: str) -> int:
    return int(cast(pd.Timestamp, pd.Timestamp(value)).timestamp() * 1000)


class _Contract:
    def __init__(self, name: str):
        self.name = name

    def __repr__(self) -> str:
        return self.name

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Contract) and other.name == self.name

    def __hash__(self) -> int:
        return hash(self.name)


class _TermProduct:
    name = "P.DCE"
    contract_class = _Contract

    def supports_term_structure(self) -> bool:
        return True

    def get_contract_list(self, start_date=None, end_date=None):
        return [{
            "uid": "P2601.DCE",
            "contract": "P2601",
            "start": "2026-01-01",
            "end": "2026-01-31",
            "end_ts": _ms("2026-01-31 15:00"),
            "last_trade_ts": _ms("2026-01-31 15:00"),
        }]


class _TwoContractTermProduct(_TermProduct):
    def get_contract_list(self, start_date=None, end_date=None):
        return [
            {
                "uid": "P2601.DCE",
                "contract": "P2601",
                "start": "2026-01-01",
                "end": "2026-01-31",
                "end_ts": _ms("2026-01-31 15:00"),
                "last_trade_ts": _ms("2026-01-31 15:00"),
            },
            {
                "uid": "P2602.DCE",
                "contract": "P2602",
                "start": "2026-01-20",
                "end": "2026-02-28",
                "end_ts": _ms("2026-02-28 15:00"),
                "last_trade_ts": _ms("2026-02-28 15:00"),
            },
        ]


class _CoverageOnlyTermProduct(_TermProduct):
    def get_contract_list(self, start_date=None, end_date=None):
        return [{
            "uid": "P2601.DCE",
            "contract": "P2601",
            "start": "2026-01-01",
            "end": "2026-01-31",
            "end_ts": _ms("2026-01-31 15:00"),
        }]


def test_term_structure_registers_force_close_event_before_expiry():
    strategy = Strategy(alias="A")
    product = _TermProduct()
    account = AccountState(strategy_configs={
        strategy: StrategyConfig(
            strategy=strategy,
            field_values={
                RunWindowModule.start_date: "2026-01-01",
                RunWindowModule.start_time: "09:00",
                RunWindowModule.end_date: "2026-02-05",
                RunWindowModule.end_time: "15:00",
                RunWindowModule.timezone: "Asia/Shanghai",
                DeliveryForceCloseModule.force_close_before_expiry: "2d",
            },
        ),
    })
    account.run_window_envelope = strategy_run_window_datetimes(account.config_for(strategy))
    queue = EventQueue()
    captured: list[EventDraft] = []
    queue.set_dispatcher(EventKind.ORDER_NOTICE, lambda batch: captured.extend(batch))
    ctx = FlowContext(timestamp=None, event_queue=queue, active_strategies=frozenset({strategy}))
    ctx.set_for(ProductSelectionModule.products, strategy, frozenset({product}))

    _expand_term_structure(account, ctx)
    _register_force_close_notices(account, ctx)
    queue.run_until_drained()

    assert captured
    assert captured[0].timestamp == pd.Timestamp("2026-01-29 15:00", tz="Asia/Shanghai")
    assert captured[0].payload["notice_type"] == "force_close"
    assert captured[0].payload["contract_object"] == _Contract("P2601.DCE")


def test_term_structure_does_not_treat_coverage_end_as_lifecycle_date():
    strategy = Strategy(alias="A")
    product = _CoverageOnlyTermProduct()
    account = AccountState(strategy_configs={
        strategy: StrategyConfig(
            strategy=strategy,
            field_values={
                RunWindowModule.start_date: "2026-01-01",
                RunWindowModule.start_time: "09:00",
                RunWindowModule.end_date: "2026-02-05",
                RunWindowModule.end_time: "15:00",
                RunWindowModule.timezone: "Asia/Shanghai",
                DeliveryForceCloseModule.force_close_before_expiry: "2d",
                RolloverModule.rollover_policy: "date_before_expiry",
                RolloverModule.rollover_before_expiry: "5d",
            },
        ),
    })
    account.run_window_envelope = strategy_run_window_datetimes(account.config_for(strategy))
    queue = EventQueue()
    captured: list[EventDraft] = []
    queue.set_dispatcher(EventKind.ORDER_NOTICE, lambda batch: captured.extend(batch))
    ctx = FlowContext(timestamp=None, event_queue=queue, active_strategies=frozenset({strategy}))
    ctx.set_for(ProductSelectionModule.products, strategy, frozenset({product}))

    _expand_term_structure(account, ctx)
    _register_force_close_notices(account, ctx)
    _register_rollover_notices(account, ctx)
    queue.run_until_drained()

    assert captured == []


def test_term_structure_force_close_offset_accepts_intraday_window():
    strategy = Strategy(alias="A")
    product = _TermProduct()
    account = AccountState(strategy_configs={
        strategy: StrategyConfig(
            strategy=strategy,
            field_values={
                RunWindowModule.start_date: "2026-01-01",
                RunWindowModule.start_time: "09:00",
                RunWindowModule.end_date: "2026-02-05",
                RunWindowModule.end_time: "15:00",
                RunWindowModule.timezone: "Asia/Shanghai",
                DeliveryForceCloseModule.force_close_before_expiry: "5min",
            },
        ),
    })
    account.run_window_envelope = strategy_run_window_datetimes(account.config_for(strategy))
    queue = EventQueue()
    captured: list[EventDraft] = []
    queue.set_dispatcher(EventKind.ORDER_NOTICE, lambda batch: captured.extend(batch))
    ctx = FlowContext(timestamp=None, event_queue=queue, active_strategies=frozenset({strategy}))
    ctx.set_for(ProductSelectionModule.products, strategy, frozenset({product}))

    _expand_term_structure(account, ctx)
    _register_force_close_notices(account, ctx)
    queue.run_until_drained()

    assert captured
    assert captured[0].timestamp == pd.Timestamp("2026-01-31 14:55", tz="Asia/Shanghai")


def test_force_close_event_emits_reverse_order_for_existing_position():
    strategy = Strategy(alias="A")
    contract = _Contract("P2601.DCE")
    account = AccountState(strategy_configs={
        strategy: StrategyConfig(strategy=strategy),
    })
    from tools.testers.backtest.engines.native.ledger import Ledger

    ledger = Ledger(strategy=strategy, base_currency="CNY")
    ledger.set(LedgerModule.positions, {contract: ProductPosition(quantity=3)})
    account.ledgers[strategy] = ledger
    queue = EventQueue()
    order_events: list[EventDraft] = []
    queue.set_dispatcher(EventKind.ORDER, lambda batch: order_events.extend(batch))
    ts = pd.Timestamp("2026-01-29 15:00")
    draft = EventDraft(EventKind.ORDER_NOTICE, ts, strategy, payload={
        "notice_type": "force_close",
        "contract_object": contract,
    })
    ctx = FlowContext(
        timestamp=ts,
        event_queue=queue,
        active_strategies=frozenset({strategy}),
        drafts_by_strategy={strategy: [draft]},
    )

    _handle_delivery_force_close_notice(account, ctx)
    queue.run_until_drained()

    assert len(order_events) == 1
    order = order_events[0].payload
    assert order.instrument == contract
    assert order.quantity == -3
    assert order.get("reason") == "term_structure_force_close"


def test_signal_target_weights_map_abstract_product_to_current_contract():
    strategy = Strategy(alias="A")
    product = _TwoContractTermProduct()
    account = AccountState(strategy_configs={
        strategy: StrategyConfig(
            strategy=strategy,
            field_values={
                RunWindowModule.start_date: "2026-01-01",
                RunWindowModule.start_time: "09:00",
                RunWindowModule.end_date: "2026-02-05",
                RunWindowModule.end_time: "15:00",
                RunWindowModule.timezone: "Asia/Shanghai",
                DeliveryForceCloseModule.force_close_before_expiry: "2d",
                RolloverModule.rollover_policy: "date_before_expiry",
                RolloverModule.rollover_before_expiry: "5d",
            },
        ),
    })
    account.run_window_envelope = strategy_run_window_datetimes(account.config_for(strategy))
    ctx = FlowContext(
        timestamp=pd.Timestamp("2026-01-10 09:01"),
        event_queue=EventQueue(),
        active_strategies=frozenset({strategy}),
    )
    ctx.set_for(ProductSelectionModule.products, strategy, frozenset({product}))

    _expand_term_structure(account, ctx)
    ctx.set_for(GroupMembershipModule.target_weights, strategy, {product: 1.0})
    _resolve_tradable_target_weights(account, ctx)

    weights = ctx.get_for(GroupMembershipModule.target_weights, strategy)
    assert weights == {_Contract("P2601.DCE"): 1.0}


def test_signal_target_weights_roll_to_next_contract_after_rollover_notice_time():
    strategy = Strategy(alias="A")
    product = _TwoContractTermProduct()
    account = AccountState(strategy_configs={
        strategy: StrategyConfig(
            strategy=strategy,
            field_values={
                RunWindowModule.start_date: "2026-01-01",
                RunWindowModule.start_time: "09:00",
                RunWindowModule.end_date: "2026-02-05",
                RunWindowModule.end_time: "15:00",
                RunWindowModule.timezone: "Asia/Shanghai",
                DeliveryForceCloseModule.force_close_before_expiry: "2d",
                RolloverModule.rollover_policy: "date_before_expiry",
                RolloverModule.rollover_before_expiry: "5d",
            },
        ),
    })
    account.run_window_envelope = strategy_run_window_datetimes(account.config_for(strategy))
    ctx = FlowContext(
        timestamp=pd.Timestamp("2026-01-26 15:01"),
        event_queue=EventQueue(),
        active_strategies=frozenset({strategy}),
    )
    ctx.set_for(ProductSelectionModule.products, strategy, frozenset({product}))

    _expand_term_structure(account, ctx)
    ctx.set_for(GroupMembershipModule.target_weights, strategy, {product: 1.0})
    _resolve_tradable_target_weights(account, ctx)

    weights = ctx.get_for(GroupMembershipModule.target_weights, strategy)
    assert weights == {_Contract("P2602.DCE"): 1.0}


def test_rollover_module_registers_rollover_notice_independently():
    strategy = Strategy(alias="A")
    product = _TermProduct()
    account = AccountState(strategy_configs={
        strategy: StrategyConfig(
            strategy=strategy,
            field_values={
                RunWindowModule.start_date: "2026-01-01",
                RunWindowModule.start_time: "09:00",
                RunWindowModule.end_date: "2026-02-05",
                RunWindowModule.end_time: "15:00",
                RunWindowModule.timezone: "Asia/Shanghai",
                RolloverModule.rollover_policy: "date_before_expiry",
                RolloverModule.rollover_before_expiry: "5d",
            },
        ),
    })
    account.run_window_envelope = strategy_run_window_datetimes(account.config_for(strategy))
    queue = EventQueue()
    captured: list[EventDraft] = []
    queue.set_dispatcher(EventKind.ORDER_NOTICE, lambda batch: captured.extend(batch))
    ctx = FlowContext(timestamp=None, event_queue=queue, active_strategies=frozenset({strategy}))
    ctx.set_for(ProductSelectionModule.products, strategy, frozenset({product}))

    _expand_term_structure(account, ctx)
    _register_rollover_notices(account, ctx)
    queue.run_until_drained()

    assert captured
    assert captured[0].timestamp == pd.Timestamp("2026-01-26 15:00", tz="Asia/Shanghai")
    assert captured[0].payload["notice_type"] == "rollover"
    assert captured[0].payload["notice_reason"] == "date_before_expiry"


def test_rollover_day_window_uses_trading_axis_not_calendar_days():
    strategy = Strategy(alias="A")
    product = _TermProduct()
    account = AccountState(strategy_configs={
        strategy: StrategyConfig(
            strategy=strategy,
            field_values={
                RunWindowModule.start_date: "2026-01-01",
                RunWindowModule.start_time: "09:00",
                RunWindowModule.end_date: "2026-02-05",
                RunWindowModule.end_time: "15:00",
                RunWindowModule.timezone: "Asia/Shanghai",
                RolloverModule.rollover_policy: "date_before_expiry",
                RolloverModule.rollover_before_expiry: "5d",
            },
        ),
    })
    account.run_window_envelope = strategy_run_window_datetimes(account.config_for(strategy))
    axis = pd.DatetimeIndex([
        pd.Timestamp("2026-01-21 15:00", tz="Asia/Shanghai"),
        pd.Timestamp("2026-01-22 15:00", tz="Asia/Shanghai"),
        pd.Timestamp("2026-01-23 15:00", tz="Asia/Shanghai"),
        pd.Timestamp("2026-01-27 15:00", tz="Asia/Shanghai"),
        pd.Timestamp("2026-01-28 15:00", tz="Asia/Shanghai"),
        pd.Timestamp("2026-01-29 15:00", tz="Asia/Shanghai"),
        pd.Timestamp("2026-01-30 15:00", tz="Asia/Shanghai"),
        pd.Timestamp("2026-01-31 15:00", tz="Asia/Shanghai"),
    ])
    account.current_prices_table = pd.DataFrame({"P2601.DCE": range(len(axis))}, index=axis)
    queue = EventQueue()
    captured: list[EventDraft] = []
    queue.set_dispatcher(EventKind.ORDER_NOTICE, lambda batch: captured.extend(batch))
    ctx = FlowContext(timestamp=None, event_queue=queue, active_strategies=frozenset({strategy}))
    ctx.set_for(ProductSelectionModule.products, strategy, frozenset({product}))

    _expand_term_structure(account, ctx)
    _register_rollover_notices(account, ctx)
    queue.run_until_drained()

    assert captured
    assert captured[0].timestamp == pd.Timestamp("2026-01-23 15:00", tz="Asia/Shanghai")
