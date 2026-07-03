"""FeeModule — transaction cost, applied as a FlowOverride on
LedgerModule.cash_update.

Market data ownership stays in MarketDataModule: it supplies CTP/OpenCTP-style
fee fields through FieldHistory. FeeModule only decides which fee leg applies
to the order and performs the arithmetic.
"""

from __future__ import annotations

from typing import Any, ClassVar, cast

from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.flow import FlowOverride
from tools.testers.backtest.modules.custom_product import custom_product_editor_definition
from tools.testers.backtest.modules.engine import engine_mode_for
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.market_data import (
    MarketDataModule,
    contract_multiplier_from_fields,
    historical_fields_for_product,
)
from tools.testers.backtest.modules.order_flow import order_flow_store_for
from tools.testers.backtest.modules.trading_rule import _resolve_method


_FEE_FIELDS = (
    "OpenRatioByMoney",
    "OpenRatioByVolume",
    "CloseRatioByMoney",
    "CloseRatioByVolume",
    "CloseTodayRatioByMoney",
    "CloseTodayRatioByVolume",
)

_CUSTOM_FEE_FIELDS = (
    {"value": "OpenRatioByMoney", "label": "开仓费率", "unit": "ratio", "value_type": "number", "allow_time_range": True},
    {"value": "OpenRatioByVolume", "label": "开仓固定费", "unit": "currency/lot", "value_type": "number", "allow_time_range": True},
    {"value": "CloseRatioByMoney", "label": "平仓费率", "unit": "ratio", "value_type": "number", "allow_time_range": True},
    {"value": "CloseRatioByVolume", "label": "平仓固定费", "unit": "currency/lot", "value_type": "number", "allow_time_range": True},
    {"value": "CloseTodayRatioByMoney", "label": "平今费率", "unit": "ratio", "value_type": "number", "allow_time_range": True},
    {"value": "CloseTodayRatioByVolume", "label": "平今固定费", "unit": "currency/lot", "value_type": "number", "allow_time_range": True},
)


class FeeModule(ExecutableModule):
    key: ClassVar[str] = "transaction_cost"
    label: ClassVar[str] = "交易费用"

    fee_mode: ClassVar[FieldRef[str]] = FieldRef("fee_mode")
    fixed_fee_rate: ClassVar[FieldRef[float]] = FieldRef("fixed_fee_rate")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "fee_mode": FieldDefinition(
            public=True, label="费用", default="auto", control_template="select", tab="cost",
            options=(
                ("auto", "自动"),
                ("exact", "严格交易规则"),
                ("custom", "自定义品种/合约"),
                ("close_yesterday", "按平昨"),
                ("close_today", "按平今"),
                ("fixed", "固定费率"),
                ("zero", "不计费用"),
            ),
            editable_when={"engine_mode": ("custom",)},
            default_when={"engine_mode": {"basic": "zero", "auto": "auto", "exact": "exact"}},
            chip_template="费用: {value}", tab_label="费用", tab_order=100,
        ),
        "fixed_fee_rate": FieldDefinition(
            public=True, label="固定费率", default=0.0, control_template="number", tab="cost",
            visible_when={"fee_mode": ("fixed",)},
            chip_template="固定费率: {value}", tab_label="费用", tab_order=100,
        ),
        "fee_custom_product_fields": custom_product_editor_definition(
            label="自定义费用字段",
            tab="cost",
            tab_label="费用",
            tab_order=100,
            module_filter="fee",
            visible_when={"engine_mode": ("custom",), "fee_mode": ("custom",)},
            display_order=95,
            fields=_CUSTOM_FEE_FIELDS,
        ),
    }

    overrides: ClassVar[tuple[FlowOverride, ...]] = (
        FlowOverride(
            flow_names=(LedgerModule.cash_update.name,),
            extra_inputs=(fee_mode, fixed_fee_rate),
            compute=lambda state, ctx, base_compute: _apply_fee(state, ctx, base_compute),
        ),
    )


def _resolve_fixed_fee_cost(
    mode: str,
    fixed_rate: float,
    quantity: float,
    price: float,
    multiplier: float,
) -> float | None:
    if mode in {"zero", "none"}:
        return 0.0
    if mode == "fixed":
        return abs(quantity) * price * multiplier * fixed_rate
    return None


def _apply_fee(state, ctx, base_compute) -> None:
    prices = ctx.get(MarketDataModule.current_prices)
    store = order_flow_store_for(state)
    for strategy in ctx.active_strategies:
        # mode/custom_rate are strategy-level (not order-level) -- resolved
        # once per strategy, not once per order, even when a strategy has
        # several simultaneous orders in this batch.
        config = state.config_for(strategy)
        mode = _resolve_fee_mode(config)
        fixed_rate = _strategy_value(config, FeeModule.fixed_fee_rate, 0.0)
        historical_fields = ctx.get_for(
            MarketDataModule.current_historical_fields,
            strategy,
            ctx.get(MarketDataModule.current_historical_fields, {}),
        )
        positions = state.ledgers[strategy].get(LedgerModule.positions, {})
        for order in ctx.payloads_for(strategy):
            if order.get("reject_reason"):
                continue
            price = order.get("effective_price", prices[order.instrument])
            multiplier = contract_multiplier_from_fields(historical_fields, order.instrument)
            fixed_fee = _resolve_fixed_fee_cost(
                mode,
                float(fixed_rate or 0.0),
                order.quantity,
                price,
                multiplier,
            )
            if fixed_fee is not None:
                order.set("fee_cost", fixed_fee)
                store.record(
                    order,
                    step="fee",
                    label="计算手续费",
                    timestamp=ctx.timestamp,
                    details={"mode": mode, "fixed_rate": float(fixed_rate or 0.0)},
                )
                continue
            fields = historical_fields_for_product(historical_fields, order.instrument)
            cost_basis_method = _resolve_method(
                config,
                order.instrument,
                fields,
                require_exact=engine_mode_for(config) == "exact",
            )
            order.set(
                "fee_cost",
                _market_fee_cost(
                    order,
                    price=float(price),
                    fields=fields,
                    position=positions.get(order.instrument),
                    fee_mode=mode,
                    cost_basis_method=cost_basis_method,
                ),
            )
            store.record(
                order,
                step="fee",
                label="计算手续费",
                timestamp=ctx.timestamp,
                details={"mode": mode},
            )
    base_compute(state, ctx)


def _market_fee_cost(
    order,
    *,
    price: float,
    fields: dict[str, object],
    position: object | None,
    fee_mode: str,
    cost_basis_method: str = "FIFO",
) -> float:
    missing = [field for field in _FEE_FIELDS if field not in fields]
    if "VolumeMultiple" not in fields:
        missing.append("VolumeMultiple")
    if missing and _requires_complete_fee_fields(fee_mode):
        raise KeyError(
            f"market fee requires MarketDataModule historical fields for {order.instrument}: "
            f"missing {', '.join(missing)}"
        )
    if not fields or not _has_any_fee_field(fields):
        return 0.0
    multiplier = _number(fields.get("VolumeMultiple"), 1.0)
    quantity = float(order.quantity)
    current_quantity = float(getattr(position, "quantity", 0.0))
    open_qty, close_qty = _split_open_close_quantity(quantity, current_quantity)
    close_today_qty, close_yesterday_qty = _split_close_today_yesterday(
        quantity,
        position,
        close_qty,
        fee_mode,
        cost_basis_method,
    )
    open_fee = _fee_part(
        open_qty,
        price=price,
        multiplier=multiplier,
        ratio=_number(fields.get("OpenRatioByMoney"), 0.0),
        fixed=_number(fields.get("OpenRatioByVolume"), 0.0),
    )
    close_yesterday_fee = _fee_part(
        close_yesterday_qty,
        price=price,
        multiplier=multiplier,
        ratio=_number(fields.get("CloseRatioByMoney"), 0.0),
        fixed=_number(fields.get("CloseRatioByVolume"), 0.0),
    )
    close_today_fee = _fee_part(
        close_today_qty,
        price=price,
        multiplier=multiplier,
        ratio=_number(fields.get("CloseTodayRatioByMoney"), 0.0),
        fixed=_number(fields.get("CloseTodayRatioByVolume"), 0.0),
    )
    order.set("fee_open_quantity", open_qty)
    order.set("fee_close_quantity", close_qty)
    order.set("fee_close_today_quantity", close_today_qty)
    order.set("fee_close_yesterday_quantity", close_yesterday_qty)
    order.set("fee_close_today", bool(close_today_qty and not close_yesterday_qty))
    return open_fee + close_yesterday_fee + close_today_fee


def _split_open_close_quantity(quantity: float, current_quantity: float) -> tuple[float, float]:
    if quantity == 0:
        return 0.0, 0.0
    if current_quantity == 0 or (quantity > 0) == (current_quantity > 0):
        return abs(quantity), 0.0
    close_qty = min(abs(quantity), abs(current_quantity))
    open_qty = max(0.0, abs(quantity) - close_qty)
    return open_qty, close_qty


def _split_close_today_yesterday(
    quantity: float,
    position: object | None,
    close_qty: float,
    policy: str,
    cost_basis_method: str,
) -> tuple[float, float]:
    if close_qty <= 1e-12:
        return 0.0, 0.0
    if policy == "close_today":
        return close_qty, 0.0
    if policy == "close_yesterday":
        return 0.0, close_qty
    if policy != "auto":
        return 0.0, close_qty
    lots = getattr(position, "lots", None)
    if not lots:
        return 0.0, close_qty
    remaining = close_qty
    today = 0.0
    yesterday = 0.0
    ordered_lots = _ordered_lots_for_close(lots, cost_basis_method)
    # Fee estimation follows the same close order as the ledger. If lots have
    # no DMTM marker, treat them as yesterday/ordinary close.
    for lot in ordered_lots:
        if remaining <= 1e-12:
            break
        take = min(remaining, abs(float(getattr(lot, "quantity", 0.0) or 0.0)))
        if bool(getattr(lot, "is_today", False)):
            today += take
        else:
            yesterday += take
        remaining -= take
    yesterday += max(0.0, remaining)
    return today, yesterday


def _ordered_lots_for_close(lots, cost_basis_method: str):
    if cost_basis_method == "LIFO":
        return list(reversed(lots))
    if cost_basis_method == "HIFO":
        return sorted(lots, key=lambda lot: getattr(lot, "entry_price", 0.0), reverse=True)
    return list(lots)


def _requires_complete_fee_fields(mode: str) -> bool:
    return mode in {"exact", "custom", "close_today", "close_yesterday"}


def _has_any_fee_field(fields: dict[str, object]) -> bool:
    return any(field in fields for field in _FEE_FIELDS)


def _fee_part(quantity: float, *, price: float, multiplier: float, ratio: float, fixed: float) -> float:
    qty = abs(float(quantity))
    return qty * (price * multiplier * ratio + fixed)


def _normalise_fee_mode(value: object) -> str:
    mode = str(value or "auto")
    legacy = {
        "none": "zero",
        "market": "auto",
    }
    return legacy.get(mode, mode)


def _resolve_fee_mode(config) -> str:
    engine_mode = engine_mode_for(config)
    if engine_mode == "basic":
        return "zero"
    if engine_mode == "auto":
        return "auto"
    if engine_mode == "exact":
        return "exact"
    return _normalise_fee_mode(config.get(FeeModule.fee_mode, "auto"))


def _strategy_value(config, ref: FieldRef, default: Any) -> Any:
    value = config.get(ref, None)
    if value is not None:
        return value
    return default


def _number(value: object, default: float) -> float:
    if value in (None, ""):
        return default
    number = float(cast(Any, value))
    return default if number != number else number  # NaN check without importing math
