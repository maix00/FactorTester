"""Exchange-field fee calculation for one atomic Order."""

from __future__ import annotations

from tools.testers.backtest.engines.native.order import OrderOffset

from .constants import FEE_FIELDS
from .lot_split import split_close_today_yesterday, split_open_close_quantity
from .mode import number


def market_fee_cost(
    order, *, price: float, fields: dict[str, object], position,
    fee_mode: str, cost_basis_method: str = "FIFO",
) -> float:
    missing = missing_market_fee_fields(fields)
    if missing and requires_complete_fee_fields(fee_mode):
        raise KeyError(
            f"market fee requires MarketDataModule historical fields for "
            f"{order.instrument}: missing {', '.join(missing)}"
        )
    if not fields or not has_any_fee_field(fields):
        return 0.0
    multiplier = number(fields.get("VolumeMultiple"), 1.0)
    explicit = explicit_offset_quantities(order)
    if explicit is None:
        open_qty, close_qty = split_open_close_quantity(
            float(order.quantity),
            float(getattr(position, "quantity", 0.0)),
        )
        close_today, close_yesterday = split_close_today_yesterday(
            float(order.quantity), position, close_qty,
            fee_mode, cost_basis_method,
        )
    else:
        open_qty, close_qty, close_today, close_yesterday = explicit
    open_fee = fee_part(
        open_qty, price=price, multiplier=multiplier,
        ratio=number(fields.get("OpenRatioByMoney"), 0.0),
        fixed=number(fields.get("OpenRatioByVolume"), 0.0),
    )
    close_fee = fee_part(
        close_yesterday, price=price, multiplier=multiplier,
        ratio=number(fields.get("CloseRatioByMoney"), 0.0),
        fixed=number(fields.get("CloseRatioByVolume"), 0.0),
    )
    today_fee = fee_part(
        close_today, price=price, multiplier=multiplier,
        ratio=number(fields.get("CloseTodayRatioByMoney"), 0.0),
        fixed=number(fields.get("CloseTodayRatioByVolume"), 0.0),
    )
    order.set("fee_open_quantity", open_qty)
    order.set("fee_close_quantity", close_qty)
    order.set("fee_close_today_quantity", close_today)
    order.set("fee_close_yesterday_quantity", close_yesterday)
    order.set("fee_close_today", bool(close_today and not close_yesterday))
    return open_fee + close_fee + today_fee


def explicit_offset_quantities(order):
    quantity = abs(float(order.quantity))
    if order.offset is OrderOffset.OPEN:
        return quantity, 0.0, 0.0, 0.0
    if order.offset is OrderOffset.CLOSE_TODAY:
        return 0.0, quantity, quantity, 0.0
    if order.offset is OrderOffset.CLOSE_YESTERDAY:
        return 0.0, quantity, 0.0, quantity
    return None


def requires_complete_fee_fields(mode: str) -> bool:
    return mode in {"exact", "custom", "close_today", "close_yesterday"}


def missing_market_fee_fields(fields: dict[str, object]) -> list[str]:
    missing = [field for field in FEE_FIELDS if field not in fields]
    if "VolumeMultiple" not in fields:
        missing.append("VolumeMultiple")
    return missing


def has_any_fee_field(fields: dict[str, object]) -> bool:
    return any(field in fields for field in FEE_FIELDS)


def fee_part(
    quantity: float, *, price: float, multiplier: float,
    ratio: float, fixed: float,
) -> float:
    return abs(float(quantity)) * (price * multiplier * ratio + fixed)
