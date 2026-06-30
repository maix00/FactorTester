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
from tools.testers.backtest.modules.engine import engine_mode_for
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.market_data import MarketDataModule


_FEE_FIELDS = (
    "OpenRatioByMoney",
    "OpenRatioByVolume",
    "CloseRatioByMoney",
    "CloseRatioByVolume",
    "CloseTodayRatioByMoney",
    "CloseTodayRatioByVolume",
)


class FeeModule(ExecutableModule):
    key: ClassVar[str] = "transaction_cost"
    label: ClassVar[str] = "交易费用"

    fee_mode: ClassVar[FieldRef[str]] = FieldRef("fee_mode")
    fixed_fee_rate: ClassVar[FieldRef[float]] = FieldRef("fixed_fee_rate")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "fee_mode": FieldDefinition(
            public=True, default="auto", control_template="select", tab="cost",
            options=(
                ("auto", "自动"),
                ("exact", "严格历史规则"),
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
            public=True, default=0.0, control_template="number", tab="cost",
            visible_when={"fee_mode": ("fixed",)},
            chip_template="固定费率: {value}", tab_label="费用", tab_order=100,
        ),
    }

    overrides: ClassVar[tuple[FlowOverride, ...]] = (
        FlowOverride(
            flow_names=(LedgerModule.cash_update.name,),
            extra_inputs=(fee_mode, fixed_fee_rate),
            compute=lambda account, ctx, base_compute: _apply_fee(account, ctx, base_compute),
        ),
    )


def _resolve_fixed_fee_cost(mode: str, fixed_rate: float, quantity: float, price: float) -> float | None:
    if mode in {"zero", "none"}:
        return 0.0
    if mode == "fixed":
        return abs(quantity) * price * fixed_rate
    return None


def _apply_fee(account, ctx, base_compute) -> None:
    prices = ctx.get(MarketDataModule.current_prices)
    for strategy in ctx.active_strategies:
        # mode/custom_rate are strategy-level (not order-level) -- resolved
        # once per strategy, not once per order, even when a strategy has
        # several simultaneous orders in this batch.
        config = account.config_for(strategy)
        mode = _resolve_fee_mode(config)
        fixed_rate = _strategy_value(config, FeeModule.fixed_fee_rate, 0.0)
        historical_fields = ctx.get_for(
            MarketDataModule.current_historical_fields,
            strategy,
            ctx.get(MarketDataModule.current_historical_fields, {}),
        )
        positions = account.ledgers[strategy].get(LedgerModule.positions, {})
        for order in ctx.payloads_for(strategy):
            price = order.get("effective_price", prices[order.instrument])
            fixed_fee = _resolve_fixed_fee_cost(mode, float(fixed_rate or 0.0), order.quantity, price)
            if fixed_fee is not None:
                order.set("fee_cost", fixed_fee)
                continue
            fields = historical_fields.get(str(order.instrument), {})
            order.set(
                "fee_cost",
                _market_fee_cost(
                    order,
                    price=float(price),
                    fields=fields,
                    current_quantity=float(getattr(positions.get(order.instrument), "quantity", 0.0)),
                    fee_mode=mode,
                ),
            )
    base_compute(account, ctx)


def _market_fee_cost(order, *, price: float, fields: dict[str, object], current_quantity: float, fee_mode: str) -> float:
    missing = [field for field in _FEE_FIELDS if field not in fields]
    if "VolumeMultiple" not in fields:
        missing.append("VolumeMultiple")
    if missing:
        raise KeyError(
            f"market fee requires MarketDataModule historical fields for {order.instrument}: "
            f"missing {', '.join(missing)}"
        )
    multiplier = _number(fields.get("VolumeMultiple"), 1.0)
    quantity = float(order.quantity)
    open_qty, close_qty = _split_open_close_quantity(quantity, current_quantity)
    close_today = _is_close_today(order, fee_mode)
    close_money_field = "CloseTodayRatioByMoney" if close_today else "CloseRatioByMoney"
    close_volume_field = "CloseTodayRatioByVolume" if close_today else "CloseRatioByVolume"
    open_fee = _fee_part(
        open_qty,
        price=price,
        multiplier=multiplier,
        ratio=_number(fields.get("OpenRatioByMoney"), 0.0),
        fixed=_number(fields.get("OpenRatioByVolume"), 0.0),
    )
    close_fee = _fee_part(
        close_qty,
        price=price,
        multiplier=multiplier,
        ratio=_number(fields.get(close_money_field), 0.0),
        fixed=_number(fields.get(close_volume_field), 0.0),
    )
    order.set("fee_open_quantity", open_qty)
    order.set("fee_close_quantity", close_qty)
    order.set("fee_close_today", close_today)
    return open_fee + close_fee


def _split_open_close_quantity(quantity: float, current_quantity: float) -> tuple[float, float]:
    if quantity == 0:
        return 0.0, 0.0
    if current_quantity == 0 or (quantity > 0) == (current_quantity > 0):
        return abs(quantity), 0.0
    close_qty = min(abs(quantity), abs(current_quantity))
    open_qty = max(0.0, abs(quantity) - close_qty)
    return open_qty, close_qty


def _is_close_today(order, policy: str) -> bool:
    if policy == "close_today":
        return True
    if policy == "auto":
        return bool(order.get("close_today", False))
    return False


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
