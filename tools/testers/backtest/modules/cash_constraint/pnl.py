"""Non-mutating realized-PnL estimates for buying-power bounds."""

from __future__ import annotations


def realized_pnl_estimate(
    strategy_config,
    positions: dict,
    order,
    price: float,
    historical_fields: dict,
    ledger_config,
    *,
    product_fields: dict[str, object] | None = None,
) -> float:
    from tools.testers.backtest.modules.engine import engine_mode_for
    from tools.testers.backtest.modules.ledger_module import _resolve_method, _same_direction
    from tools.testers.backtest.modules.market_data import (
        contract_multiplier_from_product_fields,
        historical_fields_for_product,
    )

    entry = positions.get(order.instrument)
    if entry is None:
        return 0.0
    prior_quantity = float(getattr(entry, "quantity", 0.0) or 0.0)
    quantity = float(order.quantity)
    if prior_quantity == 0 or _same_direction(prior_quantity, quantity):
        return 0.0
    fields = (
        product_fields
        if product_fields is not None
        else historical_fields_for_product(historical_fields, order.instrument)
    )
    multiplier = contract_multiplier_from_product_fields(
        fields, product=order.instrument,
    )
    method = _resolve_method(
        strategy_config,
        order.instrument,
        fields,
        require_exact=engine_mode_for(strategy_config) == "exact",
        ledger_config=ledger_config,
    )
    close_abs = min(abs(quantity), abs(prior_quantity))
    if method in {"FIFO", "LIFO", "HIFO"} and getattr(entry, "lots", None) is not None:
        return _lot_pnl(entry.lots, method, close_abs, price, multiplier, prior_quantity)
    prior_cost = float(getattr(entry, "average_cost", None) or price)
    sign = 1.0 if prior_quantity > 0 else -1.0
    return close_abs * (price - prior_cost) * sign * multiplier


def _lot_pnl(lots, method, close_abs, price, multiplier, prior_quantity) -> float:
    remaining = close_abs
    if method == "LIFO":
        iterator = reversed(lots)
    elif method == "HIFO":
        iterator = iter(sorted(
            lots,
            key=lambda lot: float(getattr(lot, "entry_price", 0.0)),
            reverse=True,
        ))
    else:
        iterator = iter(lots)
    raw = 0.0
    for lot in iterator:
        if remaining <= 1e-12:
            break
        take = min(remaining, abs(float(getattr(lot, "quantity", 0.0) or 0.0)))
        raw += take * (price - float(getattr(lot, "entry_price", price))) * multiplier
        remaining -= take
    return raw if prior_quantity > 0 else -raw
