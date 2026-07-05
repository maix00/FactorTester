"""Exchange-level clearing rule defaults.

These defaults fill the gap between static Product identity and time-varying
FieldHistory rows. Data sources register exchange defaults here; MarketData
resolves them only when a product/contract has no more specific historical
field value.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Mapping, cast


@dataclass(frozen=True)
class ExchangeClearingRule:
    exchange_id: str
    fields: Mapping[str, object] = field(default_factory=dict)
    provider: str = ""
    label: str = ""
    note: str = ""
    field_labels: Mapping[str, str] = field(default_factory=dict)
    field_notes: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ExchangeTradingRule:
    exchange_id: str
    tradability_policy: str = "valid_close_price"
    provider: str = ""
    label: str = ""
    note: str = ""
    field_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class OrderTradeConstraint:
    """Side-aware market microstructure constraint for one product timestamp.

    ``tradable`` answers whether the product has any executable market state at
    this timestamp. ``can_buy``/``can_sell`` are side-specific gates: a locked
    upper-limit bar can still be sellable while buys should be rejected.
    """

    tradable: bool
    can_buy: bool
    can_sell: bool
    reason: str = ""
    limit_up_price: float | None = None
    limit_down_price: float | None = None


_EXCHANGE_RULES: dict[str, ExchangeClearingRule] = {}
_EXCHANGE_TRADING_RULES: dict[str, ExchangeTradingRule] = {}
_PRODUCT_EXCHANGE_CANDIDATES_CACHE_MAX = 4096
_PRODUCT_EXCHANGE_CANDIDATES_CACHE: OrderedDict[int, tuple[Any, tuple[str, ...]]] = OrderedDict()
_KNOWN_TRADABILITY_POLICIES = frozenset({
    "always",
    "valid_close_price",
    "valid_close_and_positive_volume",
    "valid_close_and_price_limits",
    "valid_close_with_price_limits",
})


def register_exchange_clearing_rule(rule: ExchangeClearingRule) -> ExchangeClearingRule:
    """Register or replace one exchange-level clearing-rule default."""
    exchange_id = _normalise_exchange_id(rule.exchange_id)
    if not exchange_id:
        raise ValueError("exchange_id is required")
    normalised = ExchangeClearingRule(
        exchange_id=exchange_id,
        fields=dict(rule.fields),
        provider=rule.provider,
        label=rule.label,
        note=rule.note,
        field_labels={str(key): str(value) for key, value in rule.field_labels.items()},
        field_notes={str(key): str(value) for key, value in rule.field_notes.items()},
    )
    _EXCHANGE_RULES[exchange_id] = normalised
    return normalised


def exchange_clearing_rule(exchange_id: object) -> ExchangeClearingRule | None:
    return _EXCHANGE_RULES.get(_normalise_exchange_id(exchange_id))


def exchange_rule_defaults_for_product(
    product: Any,
    field_names: tuple[object, ...],
) -> dict[str, object]:
    """Return exchange defaults for requested fields of a product.

    Product/contract-level FieldHistory remains authoritative. This helper is
    only a provider of missing exchange defaults.
    """
    if not field_names:
        return {}
    requested = {str(name) for name in field_names}
    for exchange_id in _product_exchange_candidates(product):
        rule = exchange_clearing_rule(exchange_id)
        if rule is None:
            continue
        return {
            name: value
            for name, value in rule.fields.items()
            if str(name) in requested
        }
    return {}


def registered_exchange_clearing_rules() -> dict[str, ExchangeClearingRule]:
    return dict(_EXCHANGE_RULES)


def register_exchange_trading_rule(rule: ExchangeTradingRule) -> ExchangeTradingRule:
    exchange_id = _normalise_exchange_id(rule.exchange_id)
    if not exchange_id:
        raise ValueError("exchange_id is required")
    policy = str(rule.tradability_policy or "valid_close_price")
    if policy not in _KNOWN_TRADABILITY_POLICIES:
        allowed = ", ".join(sorted(_KNOWN_TRADABILITY_POLICIES))
        raise ValueError(f"unsupported tradability_policy {policy!r}; expected one of: {allowed}")
    normalised = ExchangeTradingRule(
        exchange_id=exchange_id,
        tradability_policy=policy,
        provider=rule.provider,
        label=rule.label,
        note=rule.note,
        field_names=tuple(str(name) for name in rule.field_names),
    )
    _EXCHANGE_TRADING_RULES[exchange_id] = normalised
    return normalised


def exchange_trading_rule(exchange_id: object) -> ExchangeTradingRule | None:
    return _EXCHANGE_TRADING_RULES.get(_normalise_exchange_id(exchange_id))


def exchange_trading_rule_for_product(product: Any) -> ExchangeTradingRule | None:
    for exchange_id in _product_exchange_candidates(product):
        rule = exchange_trading_rule(exchange_id)
        if rule is not None:
            return rule
    return None


def registered_exchange_trading_rules() -> dict[str, ExchangeTradingRule]:
    return dict(_EXCHANGE_TRADING_RULES)


def exchange_tradable_status_for_snapshot(snapshot: Mapping[str, Mapping[Any, object]]) -> dict[Any, bool]:
    """Infer per-product tradability from exchange-registered trading rules.

    This is deliberately a market-mechanics gate, not a factor-membership
    decision. Current LocalCNFutures semantics use a conservative
    ``valid_close_price`` policy: if the event snapshot has no usable close
    price for a product, do not attempt orders for it. Later halt/limit rules
    can extend this object without changing OrderBook/GroupMembership.
    """
    return {
        product: constraint.tradable
        for product, constraint in exchange_order_constraints_for_snapshot(snapshot).items()
    }


def exchange_order_constraints_for_snapshot(
    snapshot: Mapping[str, Mapping[Any, object]],
) -> dict[Any, OrderTradeConstraint]:
    """Resolve side-aware order constraints from exchange trading rules."""
    close_prices = snapshot.get("close") or {}
    constraints: dict[Any, OrderTradeConstraint] = {}
    for product, close_price in close_prices.items():
        rule = exchange_trading_rule_for_product(product)
        policy = rule.tradability_policy if rule is not None else "valid_close_price"
        constraints[product] = _constraint_by_policy(policy, product, snapshot, close_price)
    return constraints


def exchange_rule_manifest_for_product(
    product: Any,
    field_names: tuple[object, ...] | None = None,
) -> dict[str, object] | None:
    """Return the exchange clearing-rule metadata that applies to a product."""
    requested = {str(name) for name in field_names} if field_names is not None else None
    for exchange_id in _product_exchange_candidates(product):
        rule = exchange_clearing_rule(exchange_id)
        if rule is None:
            continue
        fields = [
            {
                "key": str(name),
                "value": value,
                "label": rule.field_labels.get(str(name), str(name)),
                "note": rule.field_notes.get(str(name), ""),
            }
            for name, value in rule.fields.items()
            if requested is None or str(name) in requested
        ]
        return {
            "exchange_id": rule.exchange_id,
            "provider": rule.provider,
            "label": rule.label,
            "note": rule.note,
            "fields": fields,
        }
    return None


def exchange_trading_rule_manifest_for_product(product: Any) -> dict[str, object] | None:
    rule = exchange_trading_rule_for_product(product)
    if rule is None:
        return None
    return {
        "exchange_id": rule.exchange_id,
        "provider": rule.provider,
        "label": rule.label,
        "note": rule.note,
        "tradability_policy": rule.tradability_policy,
        "field_names": list(rule.field_names),
    }


def _product_exchange_candidates(product: Any) -> tuple[str, ...]:
    if product is None:
        return ()
    cache_key = id(product)
    cached = _PRODUCT_EXCHANGE_CANDIDATES_CACHE.get(cache_key)
    if cached is not None and cached[0] is product:
        _PRODUCT_EXCHANGE_CANDIDATES_CACHE.move_to_end(cache_key)
        return cached[1]
    candidates: list[str] = []
    for attr_name in ("exchange_id", "exchange", "exchange_code", "market"):
        value = getattr(product, attr_name, None)
        if value:
            candidates.append(str(value))
    text_values = [
        getattr(product, "alias", None),
        getattr(product, "name", None),
        str(product) if product is not None else None,
    ]
    for text in text_values:
        if not text:
            continue
        suffix = _exchange_suffix(str(text))
        if suffix:
            candidates.append(suffix)
    result = tuple(dict.fromkeys(_normalise_exchange_id(item) for item in candidates if item))
    _PRODUCT_EXCHANGE_CANDIDATES_CACHE[cache_key] = (product, result)
    _PRODUCT_EXCHANGE_CANDIDATES_CACHE.move_to_end(cache_key)
    while len(_PRODUCT_EXCHANGE_CANDIDATES_CACHE) > _PRODUCT_EXCHANGE_CANDIDATES_CACHE_MAX:
        _PRODUCT_EXCHANGE_CANDIDATES_CACHE.popitem(last=False)
    return result


def _exchange_suffix(value: str) -> str:
    if "." in value:
        return value.rsplit(".", 1)[-1].split("@", 1)[0]
    if "|" in value:
        parts = value.split("|")
        return str(parts[0]) if parts else ""
    return ""


def _normalise_exchange_id(value: object) -> str:
    raw = str(value or "").strip().upper()
    aliases = {
        "SHF": "SHFE",
        "CZC": "CZCE",
        "CFE": "CFFEX",
        "GFE": "GFEX",
    }
    return aliases.get(raw, raw)


def _tradable_by_policy(
    policy: str,
    product: Any,
    snapshot: Mapping[str, Mapping[Any, object]],
    close_price: object,
) -> bool:
    return _constraint_by_policy(policy, product, snapshot, close_price).tradable


def _constraint_by_policy(
    policy: str,
    product: Any,
    snapshot: Mapping[str, Mapping[Any, object]],
    close_price: object,
) -> OrderTradeConstraint:
    if policy == "always":
        return OrderTradeConstraint(True, True, True)
    if policy == "valid_close_and_positive_volume":
        volume = (snapshot.get("volume") or {}).get(product)
        tradable = _usable_number(close_price) and _usable_number(volume)
        return OrderTradeConstraint(
            tradable,
            tradable,
            tradable,
            "" if tradable else "缺少有效价格或成交量",
        )
    if policy in {"valid_close_and_price_limits", "valid_close_with_price_limits"}:
        return _price_limit_constraint(product, snapshot, close_price)
    # Default policy for exchange snapshots without explicit halt/limit fields.
    tradable = _usable_number(close_price)
    return OrderTradeConstraint(tradable, tradable, tradable, "" if tradable else "缺少有效价格")


def _price_limit_constraint(
    product: Any,
    snapshot: Mapping[str, Mapping[Any, object]],
    close_price: object,
) -> OrderTradeConstraint:
    if not _usable_number(close_price):
        return OrderTradeConstraint(False, False, False, "缺少有效价格")
    close = float(cast(Any, close_price))
    upper = _number_or_none((snapshot.get("upper_limit") or {}).get(product))
    lower = _number_or_none((snapshot.get("lower_limit") or {}).get(product))
    can_buy = True
    can_sell = True
    reasons: list[str] = []
    if upper is not None and upper > 0 and close >= upper:
        can_buy = False
        reasons.append("触及涨停，买入方向不可成交")
    if lower is not None and lower > 0 and close <= lower:
        can_sell = False
        reasons.append("触及跌停，卖出方向不可成交")
    return OrderTradeConstraint(
        tradable=can_buy or can_sell,
        can_buy=can_buy,
        can_sell=can_sell,
        reason="；".join(reasons),
        limit_up_price=upper,
        limit_down_price=lower,
    )


def _usable_number(value: object) -> bool:
    try:
        number = float(cast(Any, value))
        return value is not None and number > 0.0 and number == number
    except (TypeError, ValueError):
        return False


def _number_or_none(value: object) -> float | None:
    try:
        if value is None:
            return None
        number = float(cast(Any, value))
        if number != number:
            return None
        return number
    except (TypeError, ValueError):
        return None
