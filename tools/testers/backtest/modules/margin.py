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
from tools.testers.backtest.engines.native.order import OrderStatus

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
    margin_utilization: ClassVar[FieldRef[float]] = FieldRef("margin_utilization")
    margin_limit_excess: ClassVar[FieldRef[float]] = FieldRef("margin_limit_excess")
    margin_liquidation_orders: ClassVar[FieldRef[Any]] = FieldRef("margin_liquidation_orders")

    _ledger_cash_ref: ClassVar[FieldRef[Any]] = FieldRef("cash", owner="CashPoolModule")
    _ledger_positions_ref: ClassVar[FieldRef[Any]] = FieldRef("positions", owner="LedgerModule")
    _cash_reserve_ratio_ref: ClassVar[FieldRef[float]] = FieldRef("cash_reserve_ratio", owner="StrategyBookModule")
    _cash_reserve_major_ref: ClassVar[FieldRef[float]] = FieldRef("cash_reserve_major", owner="StrategyBookModule")
    _max_margin_utilization_ref: ClassVar[FieldRef[float]] = FieldRef(
        "max_margin_utilization", owner="MarginBudgetModule",
    )
    _accounting_mode_ref: ClassVar[FieldRef[str]] = FieldRef("accounting_mode", owner="TradingRuleModule")
    _cost_basis_method_ref: ClassVar[FieldRef[str]] = FieldRef("cost_basis_method", owner="TradingRuleModule")
    _daily_mark_to_market_enabled_ref: ClassVar[FieldRef[Any]] = FieldRef(
        "daily_mark_to_market_enabled", owner="TradingRuleModule",
    )
    fields: ClassVar[dict[str, FieldDefinition]] = {
        "margin_mode": FieldDefinition(
            public=True, label="保证金模式", default="auto", editor="select", tab="margin",
            options=(
                ("auto", "按市场规则自动"),
                ("exact", "严格历史规则"),
                ("custom", "自定义品种/合约"),
                ("fixed", "固定比例"),
                ("none", "关闭"),
            ),
            editable_if={"engine_mode": ("auto", "custom")},
            default_if={"engine_mode": {"basic": "none", "auto": "auto", "exact": "exact"}},
            chip_template="保证金模式: {value}", tab_label="保证金", tab_order=160,
        ),
        "fixed_margin_ratio": FieldDefinition(
            public=True, label="保证金率", default=1.0, editor="number", tab="margin",
            visible_if={"margin_mode": ("fixed",)},
            chip_template="保证金率: {value}", tab_label="保证金", tab_order=160,
        ),
        "collateral_fraction": FieldDefinition(
            public=True, label="抵押比例", default=1.0, editor="number", tab="margin",
            visible_if={"margin_mode": ("fixed", "auto", "exact", "custom")},
            chip_template="抵押比例: {value}", tab_label="保证金", tab_order=160,
        ),
        "margin_call_mode": FieldDefinition(
            public=True, label="保证金追缴", default="auto", editor="select", tab="margin",
            options=(
                ("auto", "按账本规则自动"),
                ("warn", "只提示"),
                ("liquidate", "自动强平"),
                ("off", "关闭"),
            ),
            visible_if={"margin_mode": ("fixed", "auto", "exact", "custom")},
            editable_if={"engine_mode": ("custom",)},
            default_if={"engine_mode": {"basic": "off", "auto": "auto", "exact": "liquidate"}},
            chip_template="保证金追缴: {value}", tab_label="保证金", tab_order=160,
        ),
        "liquidation_target_buffer": FieldDefinition(
            public=True, label="强平缓冲", default=0.0, editor="number", tab="margin",
            visible_if={"margin_call_mode": ("liquidate", "auto")},
            minimum=0.0, maximum=1.0, step=0.01,
            chip_template="强平缓冲: {value}", tab_label="保证金", tab_order=160,
        ),
        "margin_custom_product_fields": custom_product_editor_definition(
            label="自定义保证金字段",
            tab="margin",
            tab_label="保证金",
            tab_order=160,
            module_filter="margin",
            visible_if={"engine_mode": ("custom",), "margin_mode": ("custom",)},
            display_order=95,
            fields=_CUSTOM_MARGIN_FIELDS,
        ),
        "margin_check_events": FieldDefinition(public=False),
        "margin_requirement": FieldDefinition(public=False),
        "margin_reserved": FieldDefinition(public=False),
        "margin_deficit": FieldDefinition(public=False),
        "margin_excess": FieldDefinition(public=False),
        "margin_utilization": FieldDefinition(public=False),
        "margin_limit_excess": FieldDefinition(public=False),
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
            _cash_reserve_ratio_ref,
            _cash_reserve_major_ref,
            _max_margin_utilization_ref,
            _accounting_mode_ref,
            _cost_basis_method_ref,
            _daily_mark_to_market_enabled_ref,
            FieldRef("current_prices", owner="MarketDataModule"),
            FieldRef("current_market_snapshot", owner="MarketDataModule"),
            FieldRef("current_historical_fields", owner="MarketDataModule"),
        ),
        outputs=(
            _ledger_cash_ref, _ledger_positions_ref, margin_requirement,
            margin_reserved, margin_deficit, margin_excess,
            margin_utilization, margin_limit_excess,
        ),
        phase=Phase.PER_EVENT,
        event_kind=EventKind.LEDGER,
        order=60,
        description="处理保证金要求变化",
        event_payload_inputs=("margin_check",),
        compute=lambda state, ctx: _apply_margin_requirement_change(state, ctx),
    )
    handle_margin_liquidation_notice: ClassVar[Flow] = Flow(
        "handle_margin_liquidation_notice",
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
            margin_deficit,
        ),
        outputs=(margin_liquidation_orders,),
        phase=Phase.PER_EVENT,
        event_kind=EventKind.TRADE_INTENT,
        order=70,
        description="处理保证金强平通知",
        event_payload_inputs=("margin_liquidation",),
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
        return _normalize_margin_mode(getattr(ledger_config, "margin_mode", None) or "auto")
    if engine_mode == "exact":
        return "exact"
    return _normalize_margin_mode(getattr(ledger_config, "margin_mode", None) or "auto")


def _resolve_margin_mode_from_ledger_config(ledger_config=None) -> str:
    return _normalize_margin_mode(getattr(ledger_config, "margin_mode", None) or "auto")


def _normalize_margin_mode(value: object) -> str:
    mode = str(value or "auto").lower()
    return "none" if mode == "off" else mode


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
    """Register price-driven risk checks on the complete market event axis.

    Margin requirements change sparsely, but utilization and liquidation
    thresholds also depend on current prices and equity. Keep every market
    timestamp here; ``dispatch_guard`` provides the safe fast path for ledgers
    with no position and no observable margin state.
    """
    from tools.testers.backtest.modules.market_data import (
        current_prices_table_for,
        market_data_store_for,
    )

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
        ledger_state = state.ledgers.get(ledger)
        if ledger_state is None:
            continue
        drafts.extend(
            _margin_check_draft(
                ledger,
                pd.Timestamp(timestamp) + pd.Timedelta(nanoseconds=2),
                source="market_risk",
            )
            for timestamp in timestamps
        )
    ctx.set(MarginModule.margin_check_events, drafts)


def _margin_check_draft(ledger: Any, timestamp: pd.Timestamp, *, source: str) -> EventDraft:
    return EventDraft(
        EventKind.LEDGER,
        timestamp,
        payload={
            "kind": "margin_check",
            "ledger_id": ledger.name,
            "source": source,
        },
        ledger=ledger,
        dispatch_guard=_margin_check_should_dispatch,
    )


def _ledgers_requiring_margin_checks(state: Any, ctx: Any, loaded_field_names: set[str]) -> set[Any]:
    ledgers: set[Any] = set()
    for strategy in ctx.active_strategies:
        ledger = state.ledger_for_strategy(strategy).ledger
        if _ledger_requires_margin_checks(state, ledger, loaded_field_names):
            ledgers.add(ledger)
    return ledgers


def _ledger_requires_margin_checks(state: Any, ledger: Any, loaded_field_names: set[str]) -> bool:
    ledger_config = state.ledger_config_for(ledger)
    margin_mode = _resolve_margin_mode_from_ledger_config(ledger_config)
    if margin_mode in {"none", "zero"}:
        return False
    if _resolve_margin_call_mode_from_ledger_config(ledger_config) == "off":
        return False
    return margin_mode in {"fixed", "custom", "exact"} or bool(
        loaded_field_names & _margin_field_names()
    )


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
    from tools.testers.backtest.modules.cash_pool import (
        cash_amount_to_pool_base,
        cash_for_ledger,
        cash_pool_cash_major,
        set_cash_for_ledger_pool,
    )
    from tools.testers.backtest.modules.strategy_book import available_cash_for_ledger

    evaluated: list[tuple[Any, dict[str, Any], Any, float, float, float]] = []
    for ledger, payload in _ledger_payloads(state, ctx, kind="margin_check"):
        ledger_config = state.ledger_config_for(ledger)
        if _resolve_margin_call_mode_from_ledger_config(ledger_config) == "off":
            continue
        if _margin_check_is_inert(ledger):
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
            required = _required_margin_for_position(
                state, ctx, ledger_config, product, entry,
            )
            reserved = _entry_margin_major(entry)
            requirements[product] = required
            total_required += required
            total_reserved += reserved

        reserve_delta = total_required - total_reserved
        reservations_changed = any(
            abs(required - _entry_margin_major(positions[product])) > 1e-12
            for product, required in requirements.items()
        )
        cash_changed = False
        if reserve_delta < -1e-12:
            cash = cash + DataMoney.from_major(
                -reserve_delta,
                currency=cash.currency,
                use_minor_units=cash.use_minor_units,
            )
            cash_changed = True
            for product, required in requirements.items():
                positions[product].margin_reserved = DataMoney.from_major(
                    required,
                    currency=cash.currency,
                    use_minor_units=cash.use_minor_units,
                )
            deficit = 0.0
        elif reserve_delta > 1e-12:
            pool_cash = cash_pool_cash_major(
                state, ledger, timestamp=ctx.timestamp,
                include_conversion_cost=True,
            )
            usable = available_cash_for_ledger(
                state, ledger, pool_cash, reason="margin_requirement",
            )
            required_in_pool = -cash_amount_to_pool_base(
                state, ledger, -reserve_delta, timestamp=ctx.timestamp,
                include_conversion_cost=True,
            )
            paid_in_pool = min(usable, required_in_pool)
            ratio = 1.0 if required_in_pool <= 0 else paid_in_pool / required_in_pool
            paid = reserve_delta * ratio
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
            cash_changed = paid > 1e-12
            deficit = max(reserve_delta - paid, 0.0)
        elif reservations_changed:
            for product, required in requirements.items():
                positions[product].margin_reserved = DataMoney.from_major(
                    required,
                    currency=cash.currency,
                    use_minor_units=cash.use_minor_units,
                )
            deficit = 0.0
        else:
            deficit = 0.0
        if cash_changed:
            set_cash_for_ledger_pool(state, ledger, cash)
        if reservations_changed:
            ledger.set(LedgerModule.positions, positions)
        ledger.set(MarginModule.margin_requirement, total_required)
        reserved_after = _current_margin_reserved(positions)
        ledger.set(MarginModule.margin_reserved, reserved_after)
        evaluated.append((
            ledger, payload, ledger_config, total_required, reserved_after, deficit,
        ))

    if not evaluated:
        return
    from tools.testers.backtest.modules.margin_risk.utilization import margin_limit_states

    limit_states = margin_limit_states(
        state, ctx, {ledger.ledger: required for ledger, _, _, required, _, _ in evaluated},
    )
    for ledger, payload, ledger_config, total_required, reserved_after, deficit in evaluated:
        utilization, limit_excess = limit_states[ledger.ledger]
        deficit = max(deficit, limit_excess)
        ledger.set(MarginModule.margin_deficit, deficit)
        ledger.set(MarginModule.margin_excess, max(reserved_after - total_required, 0.0))
        ledger.set(MarginModule.margin_utilization, utilization)
        ledger.set(MarginModule.margin_limit_excess, limit_excess)
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


def _margin_check_is_inert(ledger: Any) -> bool:
    """Fast path matching the market-data materialization guard."""
    from tools.testers.backtest.modules.ledger_module import LedgerModule

    positions = ledger.get(LedgerModule.positions, {}) or {}
    if any(abs(float(getattr(entry, "quantity", 0.0) or 0.0)) > 1e-12 for entry in positions.values()):
        return False
    refs = (
        MarginModule.margin_requirement,
        MarginModule.margin_reserved,
        MarginModule.margin_deficit,
        MarginModule.margin_excess,
        MarginModule.margin_utilization,
        MarginModule.margin_limit_excess,
    )
    return all(abs(float(ledger.get(ref, 0.0) or 0.0)) <= 1e-12 for ref in refs)


def _margin_check_should_dispatch(state: Any, draft: EventDraft) -> bool:
    """Keep a margin notice only when it can change observable ledger state."""
    from tools.testers.backtest.engines.native.ledger import ledger_identity

    ledger_key = draft.ledger
    if ledger_key is None and isinstance(draft.payload, dict):
        ledger_key = draft.payload.get("ledger_id")
    if ledger_key is None:
        return True
    ledger = state.ledgers.get(ledger_identity(ledger_key))
    if ledger is None:
        return True
    return not _margin_check_is_inert(ledger)


def _margin_limit_state(state: Any, ctx: Any, ledger: Any, required: float) -> tuple[float, float]:
    from tools.testers.backtest.modules.margin_risk.utilization import margin_limit_state

    return margin_limit_state(state, ctx, ledger, required)


def _handle_margin_liquidation_notice(state: Any, ctx: Any) -> None:
    from tools.testers.backtest.modules.group.execution_schedule import (
        resolve_next_execution_opportunity,
    )
    from tools.testers.backtest.modules.ledger_module import LedgerModule
    from tools.testers.backtest.modules.order_lifecycle import (
        create_order_attempt,
        order_status_event,
    )

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
            drafts: list[EventDraft] = []
            for order in orders:
                schedule = resolve_next_execution_opportunity(
                    state,
                    owner,
                    order.instrument,
                    after_timestamp=cast(pd.Timestamp, ctx.timestamp),
                )
                if schedule is None:
                    continue
                event_ts, market_ts, basis, model = schedule
                order.set("execution_price_basis", basis)
                order.set("matching_model", model)
                attempt = create_order_attempt(
                    state,
                    order,
                    timestamp=event_ts,
                    market_timestamp=market_ts,
                )
                emit_status_events = state.config_for(owner).uses_flow(
                    "strategy_runtime_on_order_status_event"
                )
                if emit_status_events:
                    drafts.append(order_status_event(order, timestamp=ctx.timestamp))
                order.status = OrderStatus.ACCEPTED
                if emit_status_events:
                    drafts.append(order_status_event(order, timestamp=event_ts))
                drafts.append(EventDraft(
                    EventKind.ORDER,
                    event_ts,
                    strategy=owner,
                    payload=attempt,
                    ledger=ledger.ledger,
                ))
            if drafts:
                ctx.set(MarginModule.margin_liquidation_orders, drafts)


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
        required = _required_margin_for_position(
            state, ctx, ledger_config, product, entry,
        )
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


def _required_margin_for_position(
    state: Any,
    ctx: Any,
    ledger_config: Any,
    product: Any,
    entry: Any,
) -> float:
    from tools.testers.backtest.modules.market_data import (
        MarketDataModule,
        contract_multiplier_from_product_fields,
        historical_fields_for_product,
    )
    from tools.testers.backtest.modules.ledger_module import _market_margin_ratio

    historical_fields = ctx.get(MarketDataModule.current_historical_fields, {}) or {}
    fields = historical_fields_for_product(historical_fields, product)
    quantity = float(getattr(entry, "quantity", 0.0) or 0.0)
    price = _position_margin_basis_price(entry, product)
    multiplier = contract_multiplier_from_product_fields(
        fields,
        state=state,
        product=product,
        timestamp=ctx.timestamp,
    )
    market_ratio = _market_margin_ratio(fields, quantity, price, multiplier)
    ratio = _resolve_margin_ratio_from_ledger_config(market_ratio, ledger_config)
    return abs(quantity) * price * multiplier * ratio


def _position_margin_basis_price(entry: Any, product: Any) -> float:
    """Return the actual transaction basis carried by an open position.

    Margin accounting freezes each fill using its final execution price
    (including slippage).  A later margin-ratio check may change the required
    ratio, but must not silently replace that transaction basis with a market
    close or settlement snapshot.  DMTM owns settlement and resets lots to the
    settlement price explicitly, so the same position basis remains sufficient
    after daily settlement.
    """
    from tools.testers.backtest.modules.ledger_impl.margin_ratios import (
        position_margin_basis_price,
    )

    return position_margin_basis_price(entry, product)


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
        for payload in ctx.payloads_for_ledger(ledger_key, kind=kind):
            if isinstance(payload, dict):
                result.append((ledger, payload))
    return result


def _strategy_for_ledger(state: Any, ledger: Any) -> Any | None:
    from tools.testers.backtest.engines.native.ledger import ledger_identity

    ledger_state = state.ledgers.get(ledger_identity(ledger))
    return None if ledger_state is None else ledger_state.strategy


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
