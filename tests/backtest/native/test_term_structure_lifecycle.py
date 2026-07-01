from __future__ import annotations

import pandas as pd

from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.ledger import AccountState, ProductPosition, StrategyConfig
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.product_selection import (
    ProductSelectionModule,
    TermStructureExpandModule,
    _expand_term_structure,
    _handle_term_structure_notice,
)
from tools.testers.backtest.modules.run_window import RunWindowModule, strategy_run_window_datetimes


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
            "end_ts": int(pd.Timestamp("2026-01-31 15:00").timestamp() * 1000),
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
                TermStructureExpandModule.force_close_before_expiry: "2d",
            },
        ),
    })
    account.run_window_envelope = strategy_run_window_datetimes(account.config_for(strategy))
    queue = EventQueue()
    captured: list[EventDraft] = []
    queue.set_dispatcher(EventKind.ORDER_NOTICE, lambda batch: captured.extend(batch))
    ctx = FlowContext(timestamp=None, event_queue=queue)
    ctx.set_for(ProductSelectionModule.products, strategy, frozenset({product}))

    _expand_term_structure(account, ctx)
    queue.run_until_drained()

    assert captured
    assert captured[0].timestamp == pd.Timestamp("2026-01-29 15:00")
    assert captured[0].payload["notice_type"] == "force_close"
    assert captured[0].payload["contract_object"] == _Contract("P2601.DCE")


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

    _handle_term_structure_notice(account, ctx)
    queue.run_until_drained()

    assert len(order_events) == 1
    order = order_events[0].payload
    assert order.instrument == contract
    assert order.quantity == -3
    assert order.get("reason") == "term_structure_force_close"
