"""Freeze one strategy/product ledger route for a signal timestamp."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from tools.testers.backtest.engines.native.ledger import Ledger, ledger_identity


@dataclass(frozen=True)
class RoutingDecision:
    strategy: Any
    product: Any
    ledger: Ledger
    timestamp: Any = None
    source: str = "default"


def freeze_product_route(
    state: Any,
    strategy: Any,
    product: Any,
    *,
    timestamp: Any = None,
    order: Any = None,
) -> RoutingDecision:
    """Resolve once and reuse the same route through sizing and construction."""

    store = _strategy_book_store(state)
    explicit = _explicit_ledger(order)
    # The default route is static for a strategy/product pair.  Avoid creating
    # and hashing a timestamp-keyed decision on every sizing/construction pass;
    # custom order-routing policies remain timestamp-scoped below.
    static_mode = explicit is None and store.policies.order_routing is None
    if static_mode:
        static_cache = getattr(state, "strategy_static_routing_decisions", None)
        if static_cache is None:
            static_cache = {}
            setattr(state, "strategy_static_routing_decisions", static_cache)
        identity_cache = getattr(state, "strategy_static_routing_identity_decisions", None)
        if identity_cache is None:
            identity_cache = {}
            setattr(state, "strategy_static_routing_identity_decisions", identity_cache)
        identity_key = (id(strategy), id(product))
        identity_entry = identity_cache.get(identity_key)
        if (
            identity_entry is not None
            and identity_entry[0] is strategy
            and identity_entry[1] is product
        ):
            cached = identity_entry[2]
            return RoutingDecision(strategy, product, cached.ledger, timestamp, cached.source)
        static_key = (strategy, product)
        if static_key in static_cache:
            cached = static_cache[static_key]
            identity_cache[identity_key] = (strategy, product, cached)
            return RoutingDecision(strategy, product, cached.ledger, timestamp, cached.source)
        cache = None
        key = None
    else:
        static_cache = None
        static_key = None
        key = (strategy, product, _timestamp_key(timestamp))
        cache = getattr(state, "strategy_routing_decisions", None)
        if cache is None:
            cache = {}
            setattr(state, "strategy_routing_decisions", cache)
        if explicit is None and key in cache:
            return cache[key]

    if explicit is not None:
        ledger, source = explicit
    elif store.policies.order_routing is not None:
        route_order = order or SimpleNamespace(strategy=strategy, instrument=product, fields={})
        ledger = ledger_identity(str(store.policies.order_routing(state, route_order)))
        source = "order_routing_policy"
    else:
        ledger = store.product_ledger_by_strategy.get(
            (strategy, product), store.default_ledger_for_strategy(state, strategy),
        )
        source = "product_or_default"

    allowed = store.ledgers_for_strategy(state, strategy)
    if ledger not in allowed:
        alias = getattr(strategy, "alias", strategy)
        raise ValueError(
            f"strategy {alias!r} cannot route order to undeclared ledger_id {ledger.name!r}"
        )
    decision = RoutingDecision(strategy, product, ledger, timestamp, source)
    if static_mode:
        assert static_cache is not None and static_key is not None
        static_cache[static_key] = decision
        identity_cache[identity_key] = (strategy, product, decision)
    else:
        assert cache is not None and key is not None
        cache[key] = decision
    return decision


def _strategy_book_store(state: Any) -> Any:
    from tools.testers.backtest.modules.strategy_book import strategy_book_store_for

    return strategy_book_store_for(state)


def _explicit_ledger(order: Any) -> tuple[Ledger, str] | None:
    fields = getattr(order, "fields", {}) if order is not None else {}
    value = fields.get("ledger_id") if isinstance(fields, dict) else None
    if value in (None, ""):
        return None
    return ledger_identity(str(value)), "order_field"


def _timestamp_key(timestamp: Any) -> str:
    return "" if timestamp is None else str(timestamp)
