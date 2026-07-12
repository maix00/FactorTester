"""MarginModule — margin rule settings shared by native position accounting.

Margin is deliberately independent from TradingRuleModule: engine mode chooses
the broad rule strictness, while margin mode chooses how much equity a position
occupies.
"""

from __future__ import annotations

from typing import Any, ClassVar, cast

import pandas as pd

from .base import ExecutableModule, FieldDefinition, FieldRef
from .custom_product import custom_product_editor_definition
from .engine import engine_mode_for
from tools.data.types.data_money import DataMoney
from tools.data.types.time_index import DataIndex
from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.flow import Flow, Phase

_CUSTOM_MARGIN_FIELDS = (
    {
        "value": "LongMarginRatioByMoney",
        "label": "多头保证金率",
        "unit": "ratio",
        "value_type": "number",
        "allow_time_range": True,
    },
    {
        "value": "ShortMarginRatioByMoney",
        "label": "空头保证金率",
        "unit": "ratio",
        "value_type": "number",
        "allow_time_range": True,
    },
    {
        "value": "LongMarginRatioByVolume",
        "label": "多头每手保证金",
        "unit": "currency/lot",
        "value_type": "number",
        "allow_time_range": True,
    },
    {
        "value": "ShortMarginRatioByVolume",
        "label": "空头每手保证金",
        "unit": "currency/lot",
        "value_type": "number",
        "allow_time_range": True,
    },
)


class MarginModule(ExecutableModule):
    key: ClassVar[str] = "margin"
    label: ClassVar[str] = "保证金"

    margin_mode: ClassVar[FieldRef[str]] = FieldRef("margin_mode")
    fixed_margin_ratio: ClassVar[FieldRef[float]] = FieldRef("fixed_margin_ratio")
    collateral_fraction: ClassVar[FieldRef[float]] = FieldRef("collateral_fraction")
    margin_call_mode: ClassVar[FieldRef[str]] = FieldRef("margin_call_mode")
    liquidation_target_buffer: ClassVar[FieldRef[float]] = FieldRef("liquidation_target_buffer")

    margin_check_events: ClassVar[FieldRef[Any]] = FieldRef("margin_check_events")
    margin_requirement: ClassVar[FieldRef[float]] = FieldRef("margin_requirement")
    margin_reserved: ClassVar[FieldRef[float]] = FieldRef("margin_reserved")
    margin_deficit: ClassVar[FieldRef[float]] = FieldRef("margin_deficit")
    margin_excess: ClassVar[FieldRef[float]] = FieldRef("margin_excess")
    margin_liquidation_orders: ClassVar[FieldRef[Any]] = FieldRef("margin_liquidation_orders")

    _ledger_cash_ref: ClassVar[FieldRef[Any]] = FieldRef("cash", owner="LedgerModule")
    _ledger_positions_ref: ClassVar[FieldRef[Any]] = FieldRef("positions", owner="LedgerModule")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "margin_mode": FieldDefinition(
            public=True, label="保证金模式", default="auto", control_template="select", tab="margin",
            options=(
                ("auto", "按市场规则自动"),
                ("exact", "严格历史规则"),
                ("custom", "自定义品种/合约"),
                ("fixed", "固定比例"),
                ("none", "关闭"),
            ),
            editable_when={"engine_mode": ("auto", "custom")},
            default_when={"engine_mode": {"basic": "none", "auto": "auto", "exact": "exact"}},
            chip_template="保证金模式: {value}", tab_label="保证金", tab_order=160,
        ),
        "fixed_margin_ratio": FieldDefinition(
            public=True, label="保证金率", default=1.0, control_template="number", tab="margin",
            visible_when={"margin_mode": ("fixed",)},
            chip_template="保证金率: {value}", tab_label="保证金", tab_order=160,
        ),
        "collateral_fraction": FieldDefinition(
            public=True, label="抵押比例", default=1.0, control_template="number", tab="margin",
            visible_when={"margin_mode": ("fixed", "auto", "exact", "custom")},
            chip_template="抵押比例: {value}", tab_label="保证金", tab_order=160,
        ),
        "margin_call_mode": FieldDefinition(
            public=True, label="保证金追缴", default="auto", control_template="select", tab="margin",
            options=(
                ("auto", "按账本规则自动"),
                ("warn", "只提示"),
                ("liquidate", "自动强平"),
                ("off", "关闭"),
            ),
            visible_when={"margin_mode": ("fixed", "auto", "exact", "custom")},
            editable_when={"engine_mode": ("custom",)},
            default_when={"engine_mode": {"basic": "off", "auto": "auto", "exact": "liquidate"}},
            chip_template="保证金追缴: {value}", tab_label="保证金", tab_order=160,
        ),
        "liquidation_target_buffer": FieldDefinition(
            public=True, label="强平缓冲", default=0.0, control_template="number", tab="margin",
            visible_when={"margin_call_mode": ("liquidate", "auto")},
            minimum=0.0, maximum=1.0, step=0.01,
            chip_template="强平缓冲: {value}", tab_label="保证金", tab_order=160,
        ),
        "margin_custom_product_fields": custom_product_editor_definition(
            label="自定义保证金字段",
            tab="margin",
            tab_label="保证金",
            tab_order=160,
            module_filter="margin",
            visible_when={"engine_mode": ("custom",), "margin_mode": ("custom",)},
            display_order=95,
            fields=_CUSTOM_MARGIN_FIELDS,
        ),
        "margin_check_events": FieldDefinition(public=False),
        "margin_requirement": FieldDefinition(public=False),
        "margin_reserved": FieldDefinition(public=False),
        "margin_deficit": FieldDefinition(public=False),
        "margin_excess": FieldDefinition(public=False),
        "margin_liquidation_orders": FieldDefinition(public=False),
    }

    register_margin_check_notices: ClassVar[Flow] = Flow(
        "register_margin_check_notices",
        inputs=(margin_mode, margin_call_mode),
        outputs=(margin_check_events,),
        phase=Phase.PRE_REPLAY,
        order=48,
        description="登记保证金检查通知",
        compute=lambda state, ctx: _register_margin_check_notices(state, ctx),
    )
    apply_margin_requirement_change: ClassVar[Flow] = Flow(
        "apply_margin_requirement_change",
        inputs=(
            _ledger_cash_ref,
            _ledger_positions_ref,
            margin_mode,
            fixed_margin_ratio,
            margin_call_mode,
            liquidation_target_buffer,
            FieldRef("current_prices", owner="MarketDataModule"),
            FieldRef("current_market_snapshot", owner="MarketDataModule"),
            FieldRef("current_historical_fields", owner="MarketDataModule"),
        ),
        outputs=(margin_requirement, margin_reserved, margin_deficit, margin_excess),
        phase=Phase.PER_EVENT,
        event_kind=EventKind.LEDGER,
        order=60,
        description="处理保证金要求变化",
        compute=lambda state, ctx: _apply_margin_requirement_change(state, ctx),
    )
    handle_margin_liquidation_notice: ClassVar[Flow] = Flow(
        "handle_margin_liquidation_notice",
        inputs=(_ledger_cash_ref, _ledger_positions_ref, margin_deficit),
        outputs=(margin_liquidation_orders,),
        phase=Phase.PER_EVENT,
        event_kind=EventKind.TRADE_INTENT,
        order=70,
        description="处理保证金强平通知",
        compute=lambda state, ctx: _handle_margin_liquidation_notice(state, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (
        register_margin_check_notices,
        apply_margin_requirement_change,
        handle_margin_liquidation_notice,
    )


def _resolve_margin_mode(strategy_config, ledger_config=None) -> str:
    engine_mode = engine_mode_for(strategy_config)
    if engine_mode == "basic":
        return "none"
    if engine_mode == "auto":
        return str(getattr(ledger_config, "margin_mode", None) or "auto")
    if engine_mode == "exact":
        return "exact"
    return str(getattr(ledger_config, "margin_mode", None) or "auto")


def _resolve_margin_mode_from_ledger_config(ledger_config=None) -> str:
    return str(getattr(ledger_config, "margin_mode", None) or "auto")


def _resolve_margin_ratio(strategy_config, market_margin_ratio: float | None, ledger_config=None) -> float:
    mode = _resolve_margin_mode(strategy_config, ledger_config)
    if mode == "none":
        return 0.0
    if mode == "fixed":
        return float(getattr(ledger_config, "fixed_margin_ratio", None) or 1.0)
    if mode == "exact" and market_margin_ratio is None:
        raise KeyError("exact margin mode requires historical long/short margin fields")
    return float(market_margin_ratio or 0.0)


def _resolve_margin_ratio_from_ledger_config(market_margin_ratio: float | None, ledger_config=None) -> float:
    mode = _resolve_margin_mode_from_ledger_config(ledger_config)
    if mode == "none":
        return 0.0
    if mode == "fixed":
        return float(getattr(ledger_config, "fixed_margin_ratio", None) or 1.0)
    if mode == "exact" and market_margin_ratio is None:
        raise KeyError("exact margin mode requires historical long/short margin fields")
    return float(market_margin_ratio or 0.0)


def product_uses_margin_accounting(fields: dict[str, object], ledger_config=None) -> bool:
    """Whether this product should be accounted through margin rather than cash notional.

    ``margin_mode`` is ledger-level policy, but auto/custom/exact must still be
    product-aware: a futures contract with margin fields uses margin; a cash
    equity/spot product without margin fields remains full-cash accounting.
    ``exact`` refuses futures-like rows that expose a multiplier but no margin
    rule, because that means the trading-rule data is incomplete.
    """
    mode = _resolve_margin_mode_from_ledger_config(ledger_config)
    if mode in {"none", "zero"}:
        return False
    if mode == "fixed":
        return True
    if _has_market_margin_fields(fields):
        return True
    if mode == "exact" and _has_contract_multiplier(fields):
        raise KeyError("exact margin mode requires historical long/short margin fields")
    return False


def _resolve_margin_call_mode_from_ledger_config(ledger_config=None) -> str:
    mode = str(getattr(ledger_config, "margin_call_mode", None) or "auto")
    if mode == "auto":
        margin_mode = _resolve_margin_mode_from_ledger_config(ledger_config)
        if margin_mode in {"none", "zero"}:
            return "off"
        return "liquidate"
    return mode


def _register_margin_check_notices(state: Any, ctx: Any) -> None:
    from tools.testers.backtest.modules.market_data import current_prices_table_for, market_data_store_for

    table = current_prices_table_for(state)
    if table is None or getattr(table, "empty", True):
        return
    timestamps = pd.DatetimeIndex(DataIndex(table.index).signal_index).unique().sort_values()
    if len(timestamps) == 0:
        return
    drafts: list[EventDraft] = []
    store = market_data_store_for(state)
    required_field_names: set[str] = set(getattr(store, "historical_field_names", ()) or ())
    for ledger in _ledgers_requiring_margin_checks(state, ctx, required_field_names):
        for timestamp in timestamps:
            drafts.append(EventDraft(
                EventKind.LEDGER,
                pd.Timestamp(timestamp) + pd.Timedelta(nanoseconds=2),
                payload={"kind": "margin_check", "ledger_id": ledger.name},
                ledger=ledger,
            ))
    ctx.set(MarginModule.margin_check_events, drafts)


def _ledgers_requiring_margin_checks(state: Any, ctx: Any, loaded_field_names: set[str]) -> set[Any]:
    ledgers: set[Any] = set()
    for strategy in ctx.active_strategies:
        ledger = state.ledger_for_strategy(strategy).ledger
        ledger_config = state.ledger_config_for(ledger)
        margin_mode = _resolve_margin_mode_from_ledger_config(ledger_config)
        if margin_mode in {"none", "zero"}:
            continue
        call_mode = _resolve_margin_call_mode_from_ledger_config(ledger_config)
        if call_mode == "off":
            continue
        if margin_mode in {"fixed", "custom", "exact"}:
            ledgers.add(ledger)
            continue
        if loaded_field_names & _margin_field_names():
            ledgers.add(ledger)
    return ledgers


def _margin_field_names() -> set[str]:
    return {
        "LongMarginRatioByMoney",
        "LongMarginRatioByVolume",
        "ShortMarginRatioByMoney",
        "ShortMarginRatioByVolume",
    }


def _has_market_margin_fields(fields: dict[str, object]) -> bool:
    return any(_number_or_none(fields.get(name)) not in (None, 0.0) for name in _margin_field_names())


def _has_contract_multiplier(fields: dict[str, object]) -> bool:
    multiplier = _number_or_none(fields.get("VolumeMultiple"))
    return multiplier not in (None, 0.0, 1.0)


def _apply_margin_requirement_change(state: Any, ctx: Any) -> None:
    from tools.testers.backtest.modules.ledger_module import LedgerModule
    from tools.testers.backtest.modules.cash_pool import cash_for_ledger, set_cash_for_ledger_pool
    from tools.testers.backtest.modules.strategy_book import available_cash_for_ledger

    for ledger, payload in _ledger_payloads(state, ctx, kind="margin_check"):
        ledger_config = state.ledger_config_for(ledger)
        if _resolve_margin_call_mode_from_ledger_config(ledger_config) == "off":
            continue
        cash = cash_for_ledger(state, ledger)
        if cash is None:
            raise KeyError(f"ledger {ledger.ledger_id!r} has no cash for margin requirement check")
        positions = ledger.get(LedgerModule.positions, {})
        total_required = 0.0
        total_reserved = 0.0
        requirements: dict[Any, float] = {}
        for product, entry in positions.items():
            quantity = float(getattr(entry, "quantity", 0.0) or 0.0)
            if abs(quantity) <= 1e-12:
                continue
            required = _required_margin_for_position(state, ctx, ledger_config, product, quantity)
            reserved = _entry_margin_major(entry)
            requirements[product] = required
            total_required += required
            total_reserved += reserved

        reserve_delta = total_required - total_reserved
        if reserve_delta < -1e-12:
            cash = cash + DataMoney.from_major(
                -reserve_delta,
                currency=cash.currency,
                use_minor_units=cash.use_minor_units,
            )
            for product, required in requirements.items():
                positions[product].margin_reserved = DataMoney.from_major(
                    required,
                    currency=cash.currency,
                    use_minor_units=cash.use_minor_units,
                )
            deficit = 0.0
        elif reserve_delta > 1e-12:
            usable = available_cash_for_ledger(state, ledger, cash.to_major(), reason="margin_requirement")
            paid = min(usable, reserve_delta)
            ratio = 1.0 if reserve_delta <= 0 else paid / reserve_delta
            for product, required in requirements.items():
                entry = positions[product]
                reserved = _entry_margin_major(entry)
                target = reserved + max(required - reserved, 0.0) * ratio
                if required < reserved:
                    target = required
                entry.margin_reserved = DataMoney.from_major(
                    target,
                    currency=cash.currency,
                    use_minor_units=cash.use_minor_units,
                )
            cash = cash - DataMoney.from_major(
                paid,
                currency=cash.currency,
                use_minor_units=cash.use_minor_units,
            )
            deficit = max(reserve_delta - paid, 0.0)
        else:
            for product, required in requirements.items():
                positions[product].margin_reserved = DataMoney.from_major(
                    required,
                    currency=cash.currency,
                    use_minor_units=cash.use_minor_units,
                )
            deficit = 0.0
        set_cash_for_ledger_pool(state, ledger, cash)
        ledger.set(LedgerModule.positions, positions)
        ledger.set(MarginModule.margin_requirement, total_required)
        reserved_after = _current_margin_reserved(positions)
        ledger.set(MarginModule.margin_reserved, reserved_after)
        ledger.set(MarginModule.margin_deficit, deficit)
        ledger.set(MarginModule.margin_excess, max(reserved_after - total_required, 0.0))
        if deficit > 1e-12 and _resolve_margin_call_mode_from_ledger_config(ledger_config) == "liquidate":
            ctx.set(MarginModule.margin_liquidation_orders, EventDraft(
                EventKind.TRADE_INTENT,
                cast(pd.Timestamp, ctx.timestamp) + pd.Timedelta(nanoseconds=1),
                payload={
                    "kind": "margin_liquidation",
                    "ledger_id": ledger.ledger_id,
                    "deficit": deficit,
                    "source": payload,
                },
                ledger=ledger.ledger,
            ))


def _handle_margin_liquidation_notice(state: Any, ctx: Any) -> None:
    from tools.testers.backtest.engines.native.order import Order
    from tools.testers.backtest.modules.ledger_module import LedgerModule

    for ledger, payload in _ledger_payloads(state, ctx, kind="margin_liquidation"):
        deficit = float(payload.get("deficit") or ledger.get(MarginModule.margin_deficit, 0.0) or 0.0)
        if deficit <= 1e-12:
            continue
        owner = _strategy_for_ledger(state, ledger.ledger)
        if owner is None:
            continue
        positions = ledger.get(LedgerModule.positions, {})
        orders = _liquidation_orders_for_deficit(state, ctx, ledger, owner, positions, deficit)
        if orders:
            ctx.set(MarginModule.margin_liquidation_orders, [
                EventDraft(
                    EventKind.ORDER,
                    cast(pd.Timestamp, ctx.timestamp) + pd.Timedelta(nanoseconds=1),
                    strategy=owner,
                    payload=order,
                    ledger=ledger.ledger,
                )
                for order in orders
            ])


def _liquidation_orders_for_deficit(
    state: Any,
    ctx: Any,
    ledger: Any,
    strategy: Any,
    positions: dict[Any, Any],
    deficit: float,
) -> list[Any]:
    from tools.testers.backtest.engines.native.order import Order

    ledger_config = state.ledger_config_for(ledger)
    remaining = deficit * (1.0 + float(getattr(ledger_config, "liquidation_target_buffer", None) or 0.0))
    candidates: list[tuple[float, Any, Any, float, float]] = []
    for product, entry in positions.items():
        quantity = float(getattr(entry, "quantity", 0.0) or 0.0)
        if abs(quantity) <= 1e-12:
            continue
        required = _required_margin_for_position(state, ctx, ledger_config, product, quantity)
        if required <= 0:
            continue
        candidates.append((required, product, entry, quantity, required / max(abs(quantity), 1e-12)))
    candidates.sort(key=lambda item: item[0], reverse=True)
    orders: list[Any] = []
    for required, product, _entry, quantity, margin_per_unit in candidates:
        if remaining <= 1e-12:
            break
        close_abs = min(abs(quantity), remaining / max(margin_per_unit, 1e-12))
        if close_abs <= 1e-12:
            continue
        order_quantity = -close_abs if quantity > 0 else close_abs
        order = Order(
            instrument=product,
            timestamp=cast(pd.Timestamp, ctx.timestamp),
            quantity=order_quantity,
            intent_quantity=order_quantity,
            strategy=strategy,
        )
        order.set("ledger_id", ledger.ledger_id)
        order.set("liquidation_reason", "margin_deficit")
        order.set("margin_deficit", deficit)
        orders.append(order)
        remaining -= close_abs * margin_per_unit
    return orders


def _required_margin_for_position(state: Any, ctx: Any, ledger_config: Any, product: Any, quantity: float) -> float:
    from tools.testers.backtest.modules.market_data import MarketDataModule, contract_multiplier_from_fields, historical_fields_for_product
    from tools.testers.backtest.modules.ledger_module import _market_margin_ratio

    historical_fields = ctx.get(MarketDataModule.current_historical_fields, {}) or {}
    fields = historical_fields_for_product(historical_fields, product)
    price = _margin_requirement_price(ctx, product)
    multiplier = contract_multiplier_from_fields(
        historical_fields,
        product,
        state=state,
        timestamp=ctx.timestamp,
    )
    market_ratio = _market_margin_ratio(fields, quantity, price, multiplier)
    ratio = _resolve_margin_ratio_from_ledger_config(market_ratio, ledger_config)
    return abs(quantity) * price * multiplier * ratio


def _margin_requirement_price(ctx: Any, product: Any) -> float:
    from tools.testers.backtest.modules.market_data import MarketDataModule

    snapshot = ctx.get(MarketDataModule.current_market_snapshot, {}) or {}
    for field in ("settlement", "close"):
        mapping = snapshot.get(field) or {}
        price = _positive_finite_price_or_none(_lookup_product_value(mapping, product))
        if price is not None:
            return price
    prices = ctx.get(MarketDataModule.current_prices, {}) or {}
    price = _positive_finite_price_or_none(_lookup_product_value(prices, product))
    if price is None:
        raise KeyError(f"margin requirement requires current price for {product}")
    return price


def _positive_finite_price_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    if pd.notna(number) and number > 0.0:
        return number
    return None


def _ledger_payloads(state: Any, ctx: Any, *, kind: str) -> list[tuple[Any, dict[str, Any]]]:
    from tools.testers.backtest.engines.native.ledger import ledger_identity

    result: list[tuple[Any, dict[str, Any]]] = []
    for ledger_key in ctx.active_ledgers:
        ledger = state.ledgers.get(ledger_identity(ledger_key))
        if ledger is None:
            continue
        for payload in ctx.payloads_for_ledger(ledger_key):
            if isinstance(payload, dict) and str(payload.get("kind") or "") == kind:
                result.append((ledger, payload))
    return result


def _strategy_for_ledger(state: Any, ledger: Any) -> Any | None:
    from tools.testers.backtest.modules.strategy_book import strategy_book_store_for

    store = strategy_book_store_for(state)
    for strategy in state.strategy_configs:
        if ledger in store.ledgers_for_strategy(state, strategy):
            return strategy
    return None


def _current_margin_reserved(positions: dict[Any, Any]) -> float:
    return sum(_entry_margin_major(entry) for entry in positions.values())


def _entry_margin_major(entry: Any) -> float:
    occupied = getattr(entry, "margin_reserved", None)
    if occupied is None:
        return 0.0
    return float(occupied.to_major())


def _lookup_product_value(mapping: Any, product: Any) -> float | None:
    if not isinstance(mapping, dict):
        return None
    for key in (product, getattr(product, "name", None), str(product)):
        if key is not None and key in mapping:
            value = mapping[key]
            return None if value is None else float(value)
    return None


def _number_or_none(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(cast(Any, value))
    except (TypeError, ValueError):
        return None
