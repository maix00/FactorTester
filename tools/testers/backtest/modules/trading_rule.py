"""TradingRuleModule — cost-basis method + position-quantity type."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar, Literal, cast

import pandas as pd

from tools.data.types.time_index import DataIndex
from tools.data.types.data_money import DataMoney
from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.modules.custom_product import custom_product_editor_definition
from tools.testers.backtest.modules.engine import EngineModule, engine_mode_for

if TYPE_CHECKING:
    from tools.products.Product import Product
    from tools.testers.backtest.engines.native.config import StrategyConfig
    from tools.testers.backtest.engines.native.ledger import LedgerState

AccountingMode = Literal["Basic", "Custom", "Auto"]
CostBasisMethod = Literal["WeightAverage", "FIFO", "LIFO", "HIFO"]

_VALID_COST_BASIS_METHODS = {"WeightAverage", "FIFO", "LIFO", "HIFO"}
_FEE_FIELDS = (
    "OpenRatioByMoney",
    "OpenRatioByVolume",
    "CloseRatioByMoney",
    "CloseRatioByVolume",
    "CloseTodayRatioByMoney",
    "CloseTodayRatioByVolume",
)
_CLOSE_FEE_PAIRS = (
    ("CloseRatioByMoney", "CloseTodayRatioByMoney"),
    ("CloseRatioByVolume", "CloseTodayRatioByVolume"),
)
_SETTLEMENT_FIELDS = (
    "SettlementPrice",
    "PreSettlementPrice",
    "LastSettlementPrice",
)

_CUSTOM_TRADING_RULE_FIELDS = (
    {
        "value": "CostBasisMethod",
        "label": "成本法",
        "unit": "enum",
        "value_type": "select",
        "value_options": (
            ("WeightAverage", "加权平均成本法"),
            ("FIFO", "先进先出"),
            ("LIFO", "后进先出"),
            ("HIFO", "高进先出"),
        ),
        "allow_time_range": False,
    },
    {
        "value": "DailyMarkToMarketEnabled",
        "label": "逐日盯市",
        "unit": "bool",
        "value_type": "boolean",
        "allow_time_range": False,
    },
)


class TradingRuleModule(ExecutableModule):
    key: ClassVar[str] = "trading_rule"
    label: ClassVar[str] = "记账规则"

    accounting_mode: ClassVar[FieldRef[AccountingMode]] = FieldRef("accounting_mode")
    cost_basis_method: ClassVar[FieldRef[CostBasisMethod]] = FieldRef("cost_basis_method")
    daily_mark_to_market_enabled: ClassVar[FieldRef[str]] = FieldRef("daily_mark_to_market_enabled")
    use_int_position: ClassVar[FieldRef[str]] = FieldRef("use_int_position")
    daily_mark_to_market_events: ClassVar[FieldRef[Any]] = FieldRef("daily_mark_to_market_events")
    resolved_daily_mark_to_market: ClassVar[FieldRef[Any]] = FieldRef("resolved_daily_mark_to_market")

    _cash_pool_cash_ref: ClassVar[FieldRef[Any]] = FieldRef("cash", owner="CashPoolModule")
    _ledger_positions_ref: ClassVar[FieldRef[Any]] = FieldRef("positions", owner="LedgerModule")
    _fee_mode_ref: ClassVar[FieldRef[str]] = FieldRef("fee_mode", owner="FeeModule")
    _margin_mode_ref: ClassVar[FieldRef[str]] = FieldRef("margin_mode", owner="MarginModule")
    _margin_call_mode_ref: ClassVar[FieldRef[str]] = FieldRef("margin_call_mode", owner="MarginModule")
    _margin_deficit_ref: ClassVar[FieldRef[float]] = FieldRef("margin_deficit", owner="MarginModule")
    _margin_liquidation_orders_ref: ClassVar[FieldRef[Any]] = FieldRef(
        "margin_liquidation_orders",
        owner="MarginModule",
    )
    _current_market_snapshot_ref: ClassVar[FieldRef[Any]] = FieldRef(
        "current_market_snapshot", owner="MarketDataModule",
    )
    _current_historical_fields_ref: ClassVar[FieldRef[Any]] = FieldRef(
        "current_historical_fields", owner="MarketDataModule",
    )
    _market_price_tables_ref: ClassVar[FieldRef[Any]] = FieldRef(
        "price_tables", owner="MarketDataModule",
    )

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "accounting_mode": FieldDefinition(
            public=True, label="记账", default="Auto", editor="select", tab="accounting",
            options=(("Basic", "基础"), ("Custom", "自定义"), ("Auto", "自动")),
            editable_if={"engine_mode": ("custom",)},
            default_if={"engine_mode": {"basic": "Basic", "auto": "Auto", "exact": "Auto"}},
            chip_template="记账: {value}", tab_label="记账规则", tab_order=180,
        ),
        "cost_basis_method": FieldDefinition(
            public=True, label="成本法", default="auto", editor="select", tab="accounting",
            options=(("auto", "按市场规则自动"), ("WeightAverage", "加权平均成本法"), ("FIFO", "先进先出"),
                      ("LIFO", "后进先出"), ("HIFO", "高进先出")),
            editable_if={"engine_mode": ("custom",), "accounting_mode": ("Custom",)},
            default_if={"engine_mode": {"basic": "WeightAverage"}},
            chip_template="成本法: {value}", tab_label="记账规则", tab_order=180,
        ),
        "daily_mark_to_market_enabled": FieldDefinition(
            public=True, label="逐日盯市", default="auto", editor="select", tab="accounting",
            options=(("auto", "按市场规则自动"), ("true", "开启"), ("false", "关闭")),
            editable_if={"engine_mode": ("custom",), "accounting_mode": ("Custom",)},
            default_if={"engine_mode": {"basic": "false"}},
            chip_template="逐日盯市: {value}", tab_label="记账规则", tab_order=180,
        ),
        "use_int_position": FieldDefinition(
            public=True, label="整数持仓", default="auto", editor="select", tab="accounting",
            options=(("auto", "按执行规则自动"), ("true", "开启"), ("false", "关闭")),
            editable_if={"engine_mode": ("custom",), "accounting_mode": ("Custom",)},
            default_if={"engine_mode": {"basic": "false"}},
            chip_template="整数持仓: {value}", tab_label="记账规则", tab_order=180,
        ),
        "trading_rule_custom_product_fields": custom_product_editor_definition(
            label="自定义记账字段",
            tab="accounting",
            tab_label="记账规则",
            tab_order=180,
            module_filter="trading_rule",
            visible_if={"engine_mode": ("custom",), "accounting_mode": ("Custom",)},
            display_order=95,
            fields=_CUSTOM_TRADING_RULE_FIELDS,
        ),
        "daily_mark_to_market_events": FieldDefinition(public=False),
        "resolved_daily_mark_to_market": FieldDefinition(public=False),
    }

    register_daily_mark_to_market_notices: ClassVar[Flow] = Flow(
        "register_daily_mark_to_market_notices",
        inputs=(EngineModule.engine_mode, accounting_mode, _market_price_tables_ref),
        outputs=(daily_mark_to_market_events,),
        phase=Phase.PRE_REPLAY,
        order=47,
        description="登记逐日盯市通知",
        compute=lambda state, ctx: _register_daily_mark_to_market_notices(state, ctx),
    )
    apply_daily_mark_to_market: ClassVar[Flow] = Flow(
        "apply_daily_mark_to_market",
        inputs=(
            _cash_pool_cash_ref,
            _ledger_positions_ref,
            _current_market_snapshot_ref,
            _current_historical_fields_ref,
            accounting_mode,
            daily_mark_to_market_enabled,
            cost_basis_method,
            _fee_mode_ref,
            _margin_mode_ref,
            _margin_call_mode_ref,
            _margin_deficit_ref,
        ),
        outputs=(
            _cash_pool_cash_ref,
            _ledger_positions_ref,
            _margin_deficit_ref,
            _margin_liquidation_orders_ref,
            resolved_daily_mark_to_market,
        ),
        phase=Phase.PER_EVENT,
        event_kind=EventKind.LEDGER,
        order=50,
        description="执行逐日盯市结算",
        event_payload_inputs=("daily_mark_to_market",),
        compute=lambda state, ctx: _apply_daily_mark_to_market(state, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (
        register_daily_mark_to_market_notices,
        apply_daily_mark_to_market,
    )


def _effective_accounting_mode(strategy_config: "StrategyConfig", ledger_config=None) -> str:
    engine_mode = engine_mode_for(strategy_config)
    if engine_mode == "basic":
        return "Basic"
    if engine_mode == "custom":
        return getattr(ledger_config, "accounting_mode", None) or "Auto"
    return "Auto"


def _resolve_method(
    strategy_config: "StrategyConfig",
    product: "Product",
    historical_fields: Mapping[str, object] | None = None,
    *,
    require_exact: bool = False,
    ledger_config=None,
) -> str:
    mode = _effective_accounting_mode(strategy_config, ledger_config)
    if mode == "Basic":
        return "WeightAverage"
    if mode == "Custom":
        method = _configured_cost_basis_method(ledger_config)
        if method is None:
            method = infer_auto_cost_basis_method(
                historical_fields,
                require_exact=require_exact,
                product=product,
            )
        _validate_daily_mark_to_market_cost_basis(
            strategy_config, method, product, ledger_config=ledger_config,
        )
        return method
    return infer_auto_cost_basis_method(historical_fields, require_exact=require_exact, product=product)


def _resolve_daily_mark_to_market_enabled(
    strategy_config: "StrategyConfig",
    product: "Product",
    historical_fields: Mapping[str, object] | None = None,
    *,
    require_exact: bool = False,
    ledger_config=None,
) -> bool:
    mode = _effective_accounting_mode(strategy_config, ledger_config)
    if mode == "Basic":
        return False
    fields = historical_fields or {}
    if mode == "Custom":
        configured = _configured_tristate_bool(
            getattr(ledger_config, "daily_mark_to_market_enabled", None),
        )
        enabled = configured
        if enabled is None:
            enabled = _infer_daily_mark_to_market_enabled(
                fields, require_exact=require_exact, product=product,
            )
        if enabled:
            _validate_daily_mark_to_market_cost_basis(
                strategy_config,
                _resolve_method(
                    strategy_config, product, fields,
                    require_exact=require_exact, ledger_config=ledger_config,
                ),
                product,
                ledger_config=ledger_config,
            )
        return enabled
    explicit = fields.get("DailyMarkToMarketEnabled")
    if explicit not in (None, ""):
        return _bool_field(explicit)
    # Legacy historical data wrote DailyMarkToMarket as if it were a cost-basis
    # method. Runtime treats that as FIFO lots plus daily settlement.
    if str(fields.get("CostBasisMethod") or "") == "DailyMarkToMarket":
        return True
    if _has_daily_mark_to_market_indicator(fields):
        return True
    if require_exact:
        raise KeyError(f"exact accounting requires DailyMarkToMarketEnabled for {product}")
    return False


def _resolve_daily_mark_to_market_enabled_for_ledger(
    product: "Product",
    historical_fields: Mapping[str, object] | None = None,
    *,
    ledger_config=None,
) -> bool:
    mode = str(getattr(ledger_config, "accounting_mode", None) or "Auto")
    if mode == "Basic":
        return False
    fields = historical_fields or {}
    if _ledger_config_disables_daily_mark_to_market(ledger_config):
        return False
    if mode == "Custom":
        configured = _configured_tristate_bool(
            getattr(ledger_config, "daily_mark_to_market_enabled", None),
        )
        if configured is None:
            configured = _infer_daily_mark_to_market_enabled(
                fields,
                require_exact=_ledger_requires_exact(ledger_config),
                product=product,
            )
        enabled = configured
        if enabled:
            method = _configured_cost_basis_method(ledger_config)
            if method is None:
                method = infer_auto_cost_basis_method(
                    fields,
                    require_exact=_ledger_requires_exact(ledger_config),
                    product=product,
                )
            _validate_daily_mark_to_market_ledger_config(
                product, method=method, ledger_config=ledger_config,
            )
        return enabled
    explicit_field = fields.get("DailyMarkToMarketEnabled")
    if explicit_field not in (None, ""):
        return _bool_field(explicit_field)
    if str(fields.get("CostBasisMethod") or "") == "DailyMarkToMarket":
        return True
    if _has_daily_mark_to_market_indicator(fields):
        return True
    if _ledger_requires_exact(ledger_config):
        raise KeyError(f"exact accounting requires DailyMarkToMarketEnabled for {product}")
    return False


def _ledger_config_disables_daily_mark_to_market(ledger_config=None) -> bool:
    configured = _configured_tristate_bool(
        getattr(ledger_config, "daily_mark_to_market_enabled", None),
    )
    if configured is True:
        return False
    margin_mode = str(getattr(ledger_config, "margin_mode", "") or "").lower()
    return margin_mode in {"off", "none", "zero"}


def _ledger_requires_exact(ledger_config=None) -> bool:
    return str(getattr(ledger_config, "margin_mode", "") or "").lower() == "exact"


def _validate_daily_mark_to_market_cost_basis(
    strategy_config: "StrategyConfig",
    method: str,
    product: object,
    *,
    ledger_config=None,
) -> None:
    if _configured_tristate_bool(
        getattr(ledger_config, "daily_mark_to_market_enabled", None),
    ) is True and method == "WeightAverage":
        raise ValueError(
            f"Daily mark-to-market requires a lot-based cost basis for {product}; "
            "use FIFO, LIFO, or HIFO instead of WeightAverage"
        )


def _validate_daily_mark_to_market_ledger_config(
    product: object, *, method: str, ledger_config=None,
) -> None:
    if method == "WeightAverage":
        raise ValueError(
            f"Daily mark-to-market requires a lot-based cost basis for {product}; "
            "use FIFO, LIFO, or HIFO instead of WeightAverage"
        )


def infer_auto_cost_basis_method(
    historical_fields: Mapping[str, object] | None,
    *,
    require_exact: bool = False,
    product: object | None = None,
) -> CostBasisMethod:
    fields = historical_fields or {}
    explicit = fields.get("CostBasisMethod")
    if explicit not in (None, ""):
        method = str(explicit)
        if method == "DailyMarkToMarket":
            return "FIFO"
        if method not in _VALID_COST_BASIS_METHODS:
            raise ValueError(f"unsupported CostBasisMethod for {product}: {method}")
        return cast(CostBasisMethod, method)
    if require_exact:
        raise KeyError(f"exact accounting requires historical CostBasisMethod for {product}")
    if _has_daily_mark_to_market_indicator(fields):
        return "FIFO"
    if _has_any_fee_field(fields):
        return "FIFO"
    return "WeightAverage"


def _configured_cost_basis_method(ledger_config=None) -> CostBasisMethod | None:
    raw = getattr(ledger_config, "cost_basis_method", None)
    if raw in (None, "", "auto", "Auto"):
        return None
    method = str(raw)
    if method not in _VALID_COST_BASIS_METHODS:
        raise ValueError(f"unsupported configured cost basis method: {method!r}")
    return cast(CostBasisMethod, method)


def _configured_tristate_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"", "auto", "automatic"}:
        return None
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    raise ValueError(f"invalid tri-state boolean value: {value!r}")


def _infer_daily_mark_to_market_enabled(
    fields: Mapping[str, object], *, require_exact: bool, product: object,
) -> bool:
    explicit = fields.get("DailyMarkToMarketEnabled")
    if explicit not in (None, ""):
        return _bool_field(explicit)
    if str(fields.get("CostBasisMethod") or "") == "DailyMarkToMarket":
        return True
    if _has_daily_mark_to_market_indicator(fields):
        return True
    if require_exact:
        raise KeyError(f"exact accounting requires DailyMarkToMarketEnabled for {product}")
    return False


def _bool_field(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "enabled"}


def _has_any_fee_field(fields: Mapping[str, object]) -> bool:
    return any(name in fields for name in _FEE_FIELDS)


def _has_daily_mark_to_market_indicator(fields: Mapping[str, object]) -> bool:
    return any(field in fields for field in _SETTLEMENT_FIELDS) or any(
        today_field in fields for _, today_field in _CLOSE_FEE_PAIRS
    )


def _resolve_use_int_position(strategy_config: "StrategyConfig", ledger_config=None) -> bool:
    mode = _effective_accounting_mode(strategy_config, ledger_config)
    if mode == "Basic":
        return False
    if mode == "Auto":
        return True
    configured = _configured_tristate_bool(
        getattr(ledger_config, "use_int_position", None),
    )
    # `auto` retains the native whole-contract policy.  It is deliberately
    # resolved here, rather than represented by the field default, so the
    # RunSpec never lies about an inferred value.
    return True if configured is None else configured


def open_position(
    ledger: "LedgerState", strategy_config: "StrategyConfig", product: "Product",
    quantity: float, entry_price: float, multiplier: float,
    market_margin_ratio: float = 1.0,
    ledger_config=None,
) -> None:
    from .ledger_module import LedgerModule
    from .margin import _resolve_margin_ratio
    from tools.testers.backtest.engines.native.position import Lot, apply_quantity_delta

    positions = ledger.get(LedgerModule.positions, {})
    entry = positions[product]
    apply_quantity_delta(entry, quantity)

    margin_ratio = _resolve_margin_ratio(strategy_config, market_margin_ratio, ledger_config)
    notional = abs(entry.quantity) * entry_price * multiplier
    entry.margin_reserved = DataMoney.from_major(
        notional * margin_ratio, currency=ledger.base_currency, use_minor_units=False)

    method = _resolve_method(strategy_config, product, ledger_config=ledger_config)
    if method == "WeightAverage":
        prior_cost = entry.average_cost or 0.0
        prior_quantity = entry.quantity - quantity
        if (prior_quantity >= 0 and quantity >= 0) or (prior_quantity <= 0 and quantity <= 0):
            # adding to (or opening) a position in the same direction:
            # blend cost basis by notional-weighted average
            total_quantity = prior_quantity + quantity
            entry.average_cost = (
                (abs(prior_quantity) * prior_cost + abs(quantity) * entry_price) / abs(total_quantity)
                if total_quantity != 0 else 0.0
            )
        # reducing/flipping a position is a close, not an open — close_position handles cost basis there
    elif method in ("FIFO", "LIFO", "HIFO"):
        entry.lots.append(Lot(quantity=quantity, entry_price=entry_price, multiplier=multiplier))


def close_position(
    ledger: "LedgerState", strategy_config: "StrategyConfig", product: "Product",
    quantity: float, fill_price: float, multiplier: float,
    market_margin_ratio: float = 1.0,
    ledger_config=None,
) -> "DataMoney":
    from .ledger_module import LedgerModule
    from .margin import _resolve_margin_ratio
    from tools.testers.backtest.engines.native.position import apply_quantity_delta

    positions = ledger.get(LedgerModule.positions, {})
    entry = positions[product]
    apply_quantity_delta(entry, -quantity)

    margin_ratio = _resolve_margin_ratio(strategy_config, market_margin_ratio, ledger_config)
    notional = abs(entry.quantity) * fill_price * multiplier
    entry.margin_reserved = DataMoney.from_major(
        notional * margin_ratio, currency=ledger.base_currency, use_minor_units=False)

    method = _resolve_method(strategy_config, product, ledger_config=ledger_config)
    realized = 0.0
    if method == "WeightAverage":
        cost = entry.average_cost or 0.0
        realized = quantity * (fill_price - cost) * multiplier
        # average_cost of the remaining position is unchanged
    elif method == "FIFO":
        realized = _consume_lots(entry.lots, quantity, fill_price, multiplier, from_front=True)
    elif method == "LIFO":
        realized = _consume_lots(entry.lots, quantity, fill_price, multiplier, from_front=False)
    elif method == "HIFO":
        realized = _consume_lots_hifo(entry.lots, quantity, fill_price, multiplier)
    return DataMoney.from_major(realized, currency=ledger.base_currency, use_minor_units=False)


def _consume_lots(lots, quantity: float, fill_price: float, multiplier: float, *, from_front: bool) -> float:
    remaining = quantity
    realized = 0.0
    while remaining > 1e-12 and lots:
        lot = lots[0] if from_front else lots[-1]
        take = min(remaining, abs(lot.quantity))
        realized += take * (fill_price - lot.entry_price) * multiplier
        lot.quantity -= take if lot.quantity > 0 else -take
        remaining -= take
        if abs(lot.quantity) <= 1e-12:
            lots.popleft() if from_front else lots.pop()
    return realized


def _consume_lots_hifo(lots, quantity: float, fill_price: float, multiplier: float) -> float:
    remaining = quantity
    realized = 0.0
    while remaining > 1e-12 and lots:
        lot = max(lots, key=lambda l: l.entry_price)
        take = min(remaining, abs(lot.quantity))
        realized += take * (fill_price - lot.entry_price) * multiplier
        lot.quantity -= take if lot.quantity > 0 else -take
        remaining -= take
        if abs(lot.quantity) <= 1e-12:
            lots.remove(lot)
    return realized


def mark_to_market(
    ledger: "LedgerState",
    strategy_config: "StrategyConfig",
    current_prices: dict,
    historical_fields: dict[object, dict[str, object]] | None = None,
    *,
    ledger_config=None,
    state: Any | None = None,
    timestamp: Any | None = None,
) -> "DataMoney":
    from .ledger_module import LedgerModule
    from .market_data import contract_multiplier_from_fields, historical_fields_for_product

    positions = ledger.get(LedgerModule.positions, {})
    total = 0.0
    require_exact = engine_mode_for(strategy_config) == "exact"
    for product, entry in positions.items():
        if entry.quantity == 0:
            continue
        fields = historical_fields_for_product(historical_fields, product)
        method = _resolve_method(strategy_config, product, fields, require_exact=require_exact, ledger_config=ledger_config)
        price = _lookup_product_value(current_prices, product)
        if price is None:
            raise KeyError(
                f"current price missing for held product {product}; "
                "mark_to_market expects MarketDataModule.current_prices to be causal-ffilled"
            )
        multiplier = contract_multiplier_from_fields(
            historical_fields or {},
            product,
            state=state,
            timestamp=timestamp,
        )
        if _resolve_daily_mark_to_market_enabled_for_ledger(product, fields, ledger_config=ledger_config):
            basis = _previous_settlement_for_product(
                product,
                entry,
                fields,
                price,
                require_exact=require_exact,
            )
            total += _mark_to_market_money_difference(
                price,
                basis,
                multiplier,
                float(entry.quantity),
                fields=fields,
                product=product,
                currency=ledger.base_currency,
                use_minor_units=True,
            )
        elif method == "WeightAverage" and entry.average_cost is not None:
            total += entry.quantity * (price - entry.average_cost) * multiplier
        elif method in ("FIFO", "LIFO", "HIFO") and entry.lots:
            for lot in entry.lots:
                total += lot.quantity * (price - lot.entry_price) * lot.multiplier
    return DataMoney.from_major(total, currency=ledger.base_currency, use_minor_units=False)


def _register_daily_mark_to_market_notices(state: Any, ctx: Any) -> None:
    table = _daily_mark_to_market_notice_table(state)
    if table is None or getattr(table, "empty", True):
        return
    last_rows = DataIndex.trading_day_last_event_times_from_index(table.index)
    if len(last_rows) == 0:
        return
    drafts: list[EventDraft] = []
    ledgers: set[Any] = set()
    for strategy in ctx.active_strategies:
        ledgers.add(state.ledger_for_strategy(strategy).ledger)
    for ledger in ledgers:
        for trading_day, last_event_time in last_rows.items():
            notice_time = pd.Timestamp(last_event_time) + pd.Timedelta(nanoseconds=1)
            drafts.append(
                EventDraft(
                    EventKind.LEDGER,
                    notice_time,
                    payload={
                        "kind": "daily_mark_to_market",
                        "trading_day": _trading_day_text(trading_day),
                        "ledger_id": ledger.name,
                    },
                    ledger=ledger,
                )
            )
    ctx.set(TradingRuleModule.daily_mark_to_market_events, drafts)


def _daily_mark_to_market_notice_table(state: Any) -> Any:
    from tools.testers.backtest.modules.market_data import (
        current_prices_table_for,
        dmtm_event_table_for,
        market_price_tables_for,
    )

    # DMTM must use the source trading-day/event axis.  The causal price table
    # is flattened to timestamps and therefore cannot distinguish a night bar
    # from the following day session belonging to the same trading day.
    event_table = dmtm_event_table_for(state)
    if event_table is not None and not getattr(event_table, "empty", True):
        return event_table

    tables = market_price_tables_for(state)
    if isinstance(tables, Mapping):
        close_table = tables.get("close")
        if close_table is not None and not getattr(close_table, "empty", True):
            return close_table
    return current_prices_table_for(state)


def _trading_day_text(value: object) -> str:
    timestamp = pd.Timestamp(cast(Any, value))
    return str(timestamp.date())


def _apply_daily_mark_to_market(state: Any, ctx: Any) -> None:
    from tools.testers.backtest.modules.market_data import (
        historical_fields_for_product,
        contract_multiplier_from_fields,
    )
    from tools.testers.backtest.modules.cash_pool import cash_for_ledger, set_cash_for_ledger_pool

    snapshot = ctx.get(TradingRuleModule._current_market_snapshot_ref, {})
    settlement_prices = snapshot.get("settlement") or {}
    close_prices = snapshot.get("close", {})
    resolved_dmtm: dict[str, dict[str, dict[str, object]]] = {}
    for ledger in _ledger_targets(state, ctx):
        ledger_config = state.ledger_config_for(ledger)
        cash = cash_for_ledger(state, ledger)
        if cash is None:
            raise KeyError(f"ledger {ledger.ledger_id!r} has no cash for daily mark-to-market")
        positions = ledger.get(TradingRuleModule._ledger_positions_ref, {})
        historical_fields = ctx.get(TradingRuleModule._current_historical_fields_ref, {}) or {}
        for product, entry in positions.items():
            quantity = float(entry.quantity or 0.0)
            if abs(quantity) <= 1e-12:
                continue
            fields = historical_fields_for_product(historical_fields, product)
            enabled = _resolve_daily_mark_to_market_enabled_for_ledger(
                product, fields, ledger_config=ledger_config,
            )
            strategy_config = _strategy_config_for_ledger(state, ledger)
            if strategy_config is not None:
                cost_basis_method = _resolve_method(
                    strategy_config,
                    product,
                    fields,
                    require_exact=engine_mode_for(strategy_config) == "exact",
                    ledger_config=ledger_config,
                )
            else:
                cost_basis_method = infer_auto_cost_basis_method(fields, product=product)
            configured_dmtm = _configured_tristate_bool(
                getattr(ledger_config, "daily_mark_to_market_enabled", None),
            )
            source = (
                "ledger_config.daily_mark_to_market_enabled"
                if configured_dmtm is not None
                else _daily_mark_to_market_resolution_source(fields)
            )
            resolved_dmtm.setdefault(str(ledger.ledger_id), {})[str(product)] = {
                "enabled": enabled,
                "source": source,
                "cost_basis_method": cost_basis_method,
            }
            if not enabled:
                continue
            settlement, settlement_source = _settlement_price_for_product(
                product,
                fields,
                settlement_prices,
                close_prices,
                require_exact=_ledger_requires_exact(ledger_config),
                timestamp=ctx.timestamp,
                trading_day=_daily_mark_to_market_trading_day(ctx, ledger),
            )
            if settlement_source == "close":
                _record_daily_mark_to_market_fallback(
                    state,
                    product=product,
                    ledger=ledger,
                    timestamp=ctx.timestamp,
                    source="settlement",
                    fallback="close",
                    reason="结算价不可用",
                )
            previous_settlement = _previous_settlement_for_product(
                product,
                entry,
                fields,
                settlement,
                require_exact=_ledger_requires_exact(ledger_config),
            )
            multiplier = contract_multiplier_from_fields(
                historical_fields,
                product,
                state=state,
                timestamp=ctx.timestamp,
            )
            pnl = _mark_to_market_money_difference(
                settlement,
                previous_settlement,
                multiplier,
                quantity,
                fields=fields,
                product=product,
                currency=cash.currency,
                use_minor_units=cash.use_minor_units,
            )
            cash = cash + DataMoney.from_major(
                pnl,
                currency=cash.currency,
                use_minor_units=cash.use_minor_units,
            )
            cash = _pin_cash_and_emit_margin_deficit_notice(ledger, cash, ctx, ledger_config)
            entry.settlement_price = settlement
            from tools.testers.backtest.modules.fee import _resolve_fee_mode_from_ledger_config
            _reset_lots_to_daily_settlement(
                entry,
                settlement,
                multiplier,
                track_today=_resolve_fee_mode_from_ledger_config(ledger_config) in {"auto", "custom", "exact"},
            )
        set_cash_for_ledger_pool(state, ledger, cash)
        ledger.set(TradingRuleModule._ledger_positions_ref, positions)
    ctx.set(TradingRuleModule.resolved_daily_mark_to_market, resolved_dmtm)


def _daily_mark_to_market_resolution_source(fields: Mapping[str, object]) -> str:
    if fields.get("DailyMarkToMarketEnabled") not in (None, ""):
        return "historical.DailyMarkToMarketEnabled"
    if str(fields.get("CostBasisMethod") or "") == "DailyMarkToMarket":
        return "historical.CostBasisMethod"
    if _has_daily_mark_to_market_indicator(fields):
        return "historical.settlement_fields"
    return "auto_default"


def _pin_cash_and_emit_margin_deficit_notice(
    ledger: Any,
    cash: DataMoney,
    ctx: Any,
    ledger_config: Any,
) -> DataMoney:
    cash_major = cash.to_major()
    if cash_major >= -1e-12:
        if cash_major < 0:
            return DataMoney.from_major(0, currency=cash.currency, use_minor_units=cash.use_minor_units)
        return cash
    shortfall = -cash_major
    from tools.testers.backtest.modules.margin import MarginModule, _resolve_margin_call_mode_from_ledger_config

    existing = float(ledger.get(MarginModule.margin_deficit, 0.0) or 0.0)
    ledger.set(MarginModule.margin_deficit, existing + shortfall)
    if _resolve_margin_call_mode_from_ledger_config(ledger_config) == "liquidate":
        ctx.set(MarginModule.margin_liquidation_orders, EventDraft(
            EventKind.TRADE_INTENT,
            cast(pd.Timestamp, ctx.timestamp) + pd.Timedelta(nanoseconds=1),
            payload={
                "kind": "margin_liquidation",
                "ledger_id": ledger.ledger_id,
                "deficit": existing + shortfall,
                "source": {"kind": "daily_mark_to_market"},
            },
            ledger=ledger.ledger,
        ))
    return DataMoney.from_major(0, currency=cash.currency, use_minor_units=cash.use_minor_units)


def _ledger_targets(state: Any, ctx: Any) -> list[Any]:
    from tools.testers.backtest.engines.native.ledger import ledger_identity

    targets: list[Any] = []
    seen: set[Any] = set()
    active_ledgers = ctx.active_ledgers or frozenset(getattr(state, "ledgers", {}))
    for ledger in active_ledgers:
        payloads = [
            payload
            for payload in ctx.payloads_for_ledger(ledger, kind="daily_mark_to_market")
            if isinstance(payload, dict)
        ]
        if not payloads:
            if getattr(ctx, "event_kind", None) is EventKind.LEDGER:
                continue
            target_ledger = state.ledgers.get(ledger_identity(ledger))
            if target_ledger is not None:
                key = target_ledger.ledger
                if key not in seen:
                    seen.add(key)
                    targets.append(target_ledger)
            continue
        for payload in payloads:
            if str(payload.get("kind") or "") != "daily_mark_to_market":
                continue
            ledger_id = payload.get("ledger_id")
            if ledger_id in (None, ""):
                target_ledger = state.ledgers.get(ledger_identity(ledger))
                if target_ledger is None:
                    raise KeyError(f"daily mark-to-market notice references unknown ledger={ledger!r}")
                key = target_ledger.ledger
                if key not in seen:
                    seen.add(key)
                    targets.append(target_ledger)
                continue
            target_ledger = state.ledgers.get(ledger_identity(str(ledger_id)))
            if target_ledger is None:
                raise KeyError(f"daily mark-to-market notice references unknown ledger_id={ledger_id!r}")
            key = target_ledger.ledger
            if key not in seen:
                seen.add(key)
                targets.append(target_ledger)
    return targets


def _strategy_config_for_ledger(state: Any, ledger: Any):
    """Return the strategy config whose ledger policy is being replayed."""
    ledger_key = getattr(ledger, "ledger", ledger)
    for strategy in getattr(state, "strategy_configs", {}):
        candidate = state.ledger_for_strategy(strategy)
        if getattr(candidate, "ledger", candidate) == ledger_key:
            return state.config_for(strategy)
    return None


def _daily_mark_to_market_trading_day(ctx: Any, ledger: Any) -> str | None:
    ledger_key = getattr(ledger, "ledger", ledger)
    payloads = ctx.payloads_for_ledger(ledger_key, kind="daily_mark_to_market")
    if not payloads and ledger_key is not ledger:
        payloads = ctx.payloads_for_ledger(ledger, kind="daily_mark_to_market")
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        trading_day = payload.get("trading_day")
        if trading_day not in (None, ""):
            return str(trading_day)
    return None


def _settlement_price_for_product(
    product: Any,
    fields: Mapping[str, object],
    settlement_prices: Mapping[Any, float],
    close_prices: Mapping[Any, float],
    *,
    require_exact: bool,
    timestamp: Any | None = None,
    trading_day: str | None = None,
    source: str = "market_snapshot.settlement",
) -> tuple[float, str]:
    value = _positive_number_or_none(_lookup_product_value(settlement_prices, product))
    if value is not None:
        return value, "settlement"
    for field_name in ("SettlementPrice", "LastSettlementPrice"):
        field_value = _positive_number_or_none(fields.get(field_name))
        if field_value is not None:
            return field_value, field_name
    fallback = _positive_number_or_none(_lookup_product_value(close_prices, product))
    if fallback is not None:
        return fallback, "close"
    if require_exact:
        context = _settlement_missing_context(
            timestamp=timestamp,
            trading_day=trading_day,
            source=source,
        )
        raise KeyError(f"exact daily mark-to-market requires settlement price for {product}{context}")
    raise KeyError(f"daily mark-to-market requires price for {product}")


def _settlement_missing_context(
    *,
    timestamp: Any | None,
    trading_day: str | None,
    source: str,
) -> str:
    parts: list[str] = []
    if timestamp is not None:
        parts.append(f"timestamp={timestamp}")
    if trading_day:
        parts.append(f"trading_day={trading_day}")
    if source:
        parts.append(f"source={source}")
    return "" if not parts else " (" + ", ".join(parts) + ")"


def _record_daily_mark_to_market_fallback(
    state: Any,
    *,
    product: Any,
    ledger: Any,
    timestamp: Any,
    source: str,
    fallback: str,
    reason: str,
) -> None:
    from tools.testers.backtest.modules.runtime_info import record_runtime_fallback_interval

    record_runtime_fallback_interval(
        state,
        code="daily_mark_to_market_price_fallback",
        type="记账规则",
        status="已降级",
        product=product,
        timestamp=timestamp,
        source=source,
        fallback=fallback,
        reason=reason,
    )


def _previous_settlement_for_product(
    product: Any,
    entry: Any,
    fields: Mapping[str, object],
    current_settlement: float,
    *,
    require_exact: bool,
) -> float:
    basis = _daily_mark_to_market_basis(entry, current_settlement)
    if getattr(entry, "lots", None):
        return basis
    if entry.settlement_price is not None:
        return basis
    for field_name in ("PreSettlementPrice", "LastSettlementPrice"):
        field_value = _positive_number_or_none(fields.get(field_name))
        if field_value is not None:
            return field_value
    if require_exact:
        raise KeyError(f"exact daily mark-to-market requires previous settlement price for {product}")
    average_cost = _positive_number_or_none(getattr(entry, "average_cost", None))
    if average_cost is not None:
        return average_cost
    raise KeyError(f"daily mark-to-market requires previous settlement price or position basis for {product}")


def _daily_mark_to_market_basis(entry: Any, fallback: float) -> float:
    """Current blended basis for a position under daily mark-to-market.

    DMTM reuses the lot-based cost record. Yesterday-and-earlier lots are
    reset to settlement by the LEDGER flow; intraday lots keep their
    fill price until that reset. `average_cost` is intentionally not read.
    """
    lots = getattr(entry, "lots", None)
    if lots:
        total_abs = sum(abs(float(getattr(lot, "quantity", 0.0) or 0.0)) for lot in lots)
        if total_abs > 1e-12:
            return sum(
                abs(float(lot.quantity)) * float(lot.entry_price)
                for lot in lots
            ) / total_abs
    if entry.settlement_price is not None:
        return float(entry.settlement_price)
    return float(fallback)


def _reset_lots_to_daily_settlement(
    entry: Any,
    settlement: float,
    multiplier: float,
    *,
    track_today: bool,
) -> None:
    from tools.testers.backtest.engines.native.position import Lot

    quantity = float(entry.quantity or 0.0)
    if abs(quantity) <= 1e-12:
        entry.lots = deque()
        return
    entry.lots = deque([
        Lot(
            quantity=quantity,
            entry_price=settlement,
            multiplier=multiplier,
            is_today=False if track_today else None,
        )
    ])


def _margin_ratio_for_position(
    fields: Mapping[str, object],
    quantity: float,
    price: float,
    multiplier: float,
    ledger_config=None,
) -> float:
    from tools.testers.backtest.modules.margin import _resolve_margin_ratio_from_ledger_config

    if quantity < 0:
        by_money = fields.get("ShortMarginRatioByMoney")
        by_volume = fields.get("ShortMarginRatioByVolume")
    else:
        by_money = fields.get("LongMarginRatioByMoney")
        by_volume = fields.get("LongMarginRatioByVolume")
    market_ratio = _number_or_none(by_money)
    if market_ratio is None:
        fixed = _number_or_none(by_volume)
        denominator = abs(price * multiplier)
        if fixed is not None and denominator > 0:
            market_ratio = fixed / denominator
    ratio = _resolve_margin_ratio_from_ledger_config(market_ratio, ledger_config)
    return float(1.0 if ratio is None else ratio)


def _entry_margin_major(entry: Any) -> float:
    margin_reserved = getattr(entry, "margin_reserved", None)
    if margin_reserved is None:
        return 0.0
    return float(margin_reserved.to_major())


def _mark_to_market_money_difference(
    current_price: float,
    basis_price: float,
    multiplier: float,
    quantity: float,
    *,
    fields: Mapping[str, object],
    product: Any,
    currency: str,
    use_minor_units: bool,
) -> float:
    if _money_calculation_policy(fields, product) != "per_contract_price_point":
        return float(quantity) * (float(current_price) - float(basis_price)) * float(multiplier)
    return _per_contract_price_point_money_difference(
        current_price,
        basis_price,
        multiplier,
        quantity,
        currency=currency,
        use_minor_units=use_minor_units,
    )


def _money_calculation_policy(fields: Mapping[str, object], product: Any) -> str:
    """"aggregate" (default, matches published CN-futures clearing rules and
    CME's own variation-margin procedure: carry full precision through the
    formula and round to the settlement currency's minor unit exactly once,
    at the final money amount -- see DataMoney.from_major). "per_contract_price_point"
    is for the narrower case of a market that defines its tick value as an
    already-rounded per-contract constant (e.g. a fixed $/tick figure in a
    contract spec) rather than a derived price*multiplier; it is an opt-in
    override via MarketDataModule historical fields, not a second general
    rounding convention -- only DailyMarkToMarket P&L honors it today, not
    the WeightAverage/FIFO/LIFO/HIFO trade-cost or margin-fill cash legs."""
    value = fields.get("MoneyCalculationPolicy") or fields.get("money_calculation_policy")
    policy = str(value or "aggregate").strip().lower()
    if policy in {"per_contract_price_point", "per-contract-price-point", "cme_price_point"}:
        return "per_contract_price_point"
    if policy in {"aggregate", "cn_futures_aggregate", "total_amount"}:
        return "aggregate"
    raise ValueError(f"unsupported MoneyCalculationPolicy for {product}: {value}")


def _per_contract_price_point_money_difference(
    current_price: float,
    basis_price: float,
    multiplier: float,
    quantity: float,
    *,
    currency: str,
    use_minor_units: bool,
) -> float:
    current_value = DataMoney.from_major(
        float(current_price) * float(multiplier),
        currency=currency,
        use_minor_units=use_minor_units,
    ).to_major()
    basis_value = DataMoney.from_major(
        float(basis_price) * float(multiplier),
        currency=currency,
        use_minor_units=use_minor_units,
    ).to_major()
    return float(quantity) * (float(current_value) - float(basis_value))


def _lookup_product_value(values: Mapping[Any, float], product: Any) -> float | None:
    if product in values:
        return float(values[product])
    keys = _product_keys(product)
    for candidate, value in values.items():
        if keys & _product_keys(candidate):
            return float(value)
    return None


def _product_keys(product: Any) -> set[str]:
    keys: set[str] = set()
    for value in (
        product,
        getattr(product, "name", None),
        getattr(product, "alias", None),
        getattr(product, "symbol", None),
        getattr(product, "code", None),
    ):
        if value is not None and str(value).strip():
            keys.add(str(value).strip())
    return keys


def _number_or_none(value: object) -> float | None:
    try:
        if value is None or value == "":
            return None
        number = float(cast(Any, value))
    except (TypeError, ValueError):
        return None
    return None if number != number else number


def _positive_number_or_none(value: object) -> float | None:
    number = _number_or_none(value)
    if number is None or number <= 0:
        return None
    return number


def _position_sign(value: float | int) -> float:
    return 1.0 if float(value) >= 0 else -1.0
