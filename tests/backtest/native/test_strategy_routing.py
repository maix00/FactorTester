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


def test_default_product_route_is_cached_without_timestamp_scope():
    strategy = Strategy(alias="route-default")
    state = SimpleNamespace()
    store = strategy_book_store_for(state)
    store.register_strategy_ledgers(
        strategy,
        ("book-a",),
        default_ledger_id="book-a",
    )

    first = freeze_product_route(state, strategy, "P1", timestamp="t1")
    second = freeze_product_route(state, strategy, "P1", timestamp="t2")

    assert first.ledger == second.ledger == ledger_identity("book-a")
    assert first.timestamp == "t1"
    assert second.timestamp == "t2"
    assert len(state.strategy_static_routing_decisions) == 1


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


def test_cash_pool_lookup_uses_registered_reverse_index_without_scanning_ledgers():
    first = Strategy(alias="first")
    second = Strategy(alias="second")
    state = SimpleNamespace()
    store = strategy_book_store_for(state)
    store.register_strategy_ledgers(
        first,
        ("book-a",),
        default_ledger_id="book-a",
        cash_pool_ids_by_ledger={"book-a": "shared"},
    )
    store.register_strategy_ledgers(
        second,
        ("book-b",),
        default_ledger_id="book-b",
        cash_pool_ids_by_ledger={"book-b": "shared"},
    )

    class NoItemsDict(dict):
        def items(self):
            raise AssertionError("cash-pool lookup scanned all ledgers")

    store.cash_pool_by_ledger = NoItemsDict(store.cash_pool_by_ledger)

    assert store.ledgers_for_cash_pool("shared") == {
        ledger_identity("book-a"),
        ledger_identity("book-b"),
    }
