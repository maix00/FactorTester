"""Margin-ratio resolution for fills and remaining positions."""

from __future__ import annotations

from typing import Any, cast


def resolved_margin_ratio_for_order(
    strategy_config, fields: dict[str, object],
    quantity: float, price: float, multiplier: float, ledger_config=None,
) -> float:
    from tools.testers.backtest.modules.margin import _resolve_margin_ratio

    ratio = _resolve_margin_ratio(
        strategy_config,
        market_margin_ratio(fields, quantity, price, multiplier),
        ledger_config,
    )
    return float(1.0 if ratio is None else ratio)


def resolved_margin_ratio_for_position_after_fill(
    strategy_config, fields: dict[str, object], new_quantity: float,
    price: float, multiplier: float, ledger_config=None,
) -> float:
    if abs(new_quantity) <= 1e-12:
        return 0.0
    return resolved_margin_ratio_for_order(
        strategy_config, fields, new_quantity, price, multiplier, ledger_config,
    )


def market_margin_ratio(
    fields: dict[str, object], quantity: float, price: float, multiplier: float,
) -> float | None:
    if quantity < 0:
        by_money = fields.get("ShortMarginRatioByMoney")
        by_volume = fields.get("ShortMarginRatioByVolume")
    else:
        by_money = fields.get("LongMarginRatioByMoney")
        by_volume = fields.get("LongMarginRatioByVolume")
    ratio = number_or_none(by_money)
    if ratio is not None:
        return ratio
    fixed = number_or_none(by_volume)
    denominator = abs(price * multiplier)
    if fixed is not None and denominator > 0:
        return fixed / denominator
    return None


def entry_margin_major(entry) -> float:
    if entry.margin_reserved is None:
        return 0.0
    return float(entry.margin_reserved.to_major())


def position_margin_basis_price(entry, product: object | None = None) -> float:
    """Return the execution basis retained by the remaining open position."""
    lots = getattr(entry, "lots", None)
    if lots:
        weighted = [
            (
                abs(float(getattr(lot, "quantity", 0.0) or 0.0)),
                positive_number_or_none(getattr(lot, "entry_price", None)),
            )
            for lot in lots
        ]
        total = sum(quantity for quantity, price in weighted if price is not None)
        if total > 1e-12:
            return sum(
                quantity * float(price)
                for quantity, price in weighted
                if price is not None
            ) / total
    average_cost = positive_number_or_none(getattr(entry, "average_cost", None))
    if average_cost is not None:
        return average_cost
    # DMTM explicitly writes this field after consuming settlement.  Reading
    # the position state here does not make margin checks settlement consumers.
    settlement_basis = positive_number_or_none(
        getattr(entry, "settlement_price", None),
    )
    if settlement_basis is not None:
        return settlement_basis
    suffix = "" if product is None else f" for {product}"
    raise KeyError(f"margin requirement requires an executed position basis{suffix}")


def positive_number_or_none(value: object) -> float | None:
    number = number_or_none(value)
    return number if number is not None and number > 0.0 else None


def number_or_none(value: object) -> float | None:
    try:
        return None if value is None else float(cast(Any, value))
    except (TypeError, ValueError):
        return None
