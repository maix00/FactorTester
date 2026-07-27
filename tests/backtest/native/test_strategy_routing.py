from types import SimpleNamespace

from tools.testers.backtest.engines.native.ledger import ledger_identity
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.strategy_book import (
    StrategyBookPolicies,
    strategy_book_store_for,
)
from tools.testers.backtest.modules.strategy_routing import freeze_product_route


def test_product_route_is_frozen_for_one_signal_timestamp():
    strategy = Strategy(alias="route")
    state = SimpleNamespace()
    store = strategy_book_store_for(state)
    store.register_strategy_ledgers(
        strategy,
        ("book-a", "book-b"),
        default_ledger_id="book-a",
    )
    calls = []
    store.policies = StrategyBookPolicies(
        order_routing=lambda _state, order: calls.append(order.instrument) or "book-b",
    )

    first = freeze_product_route(state, strategy, "P1", timestamp="t1")
    second = freeze_product_route(state, strategy, "P1", timestamp="t1")

    assert first is second
    assert first.ledger == ledger_identity("book-b")
    assert calls == ["P1"]


def test_explicit_order_ledger_wins_over_late_routing_policy():
    strategy = Strategy(alias="route-explicit")
    state = SimpleNamespace()
    store = strategy_book_store_for(state)
    store.register_strategy_ledgers(
        strategy,
        ("book-a", "book-b"),
        default_ledger_id="book-a",
    )
    store.policies = StrategyBookPolicies(
        order_routing=lambda _state, _order: "book-b",
    )
    order = SimpleNamespace(
        strategy=strategy,
        instrument="P1",
        fields={"ledger_id": "book-a"},
    )

    assert store.ledger_for_order(state, order) == ledger_identity("book-a")
