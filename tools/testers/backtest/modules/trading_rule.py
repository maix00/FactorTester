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
    from tools.testers.backtest.engines.native.ledger import Ledger, StrategyConfig

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
    daily_mark_to_market_enabled: ClassVar[FieldRef[bool]] = FieldRef("daily_mark_to_market_enabled")
    use_int_position: ClassVar[FieldRef[bool]] = FieldRef("use_int_position")
    daily_mark_to_market_events: ClassVar[FieldRef[Any]] = FieldRef("daily_mark_to_market_events")

    _ledger_cash_ref: ClassVar[FieldRef[Any]] = FieldRef("cash", owner="LedgerModule")
    _ledger_positions_ref: ClassVar[FieldRef[Any]] = FieldRef("positions", owner="LedgerModule")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "accounting_mode": FieldDefinition(
            public=True, label="记账", default="Auto", control_template="select", tab="accounting",
            options=(("Basic", "基础"), ("Custom", "自定义"), ("Auto", "自动")),
            editable_when={"engine_mode": ("custom",)},
            default_when={"engine_mode": {"basic": "Basic", "auto": "Auto", "exact": "Auto"}},
            chip_template="记账: {value}", tab_label="记账规则", tab_order=180,
        ),
        "cost_basis_method": FieldDefinition(
            public=True, label="成本法", default="WeightAverage", control_template="select", tab="accounting",
            options=(("WeightAverage", "加权平均成本法"), ("FIFO", "先进先出"),
                      ("LIFO", "后进先出"), ("HIFO", "高进先出")),
            editable_when={"engine_mode": ("custom",), "accounting_mode": ("Custom",)},
            chip_template="成本法: {value}", tab_label="记账规则", tab_order=180,
        ),
        "daily_mark_to_market_enabled": FieldDefinition(
            public=True, label="逐日盯市", default=False, control_template="boolean", tab="accounting",
            editable_when={"engine_mode": ("custom",), "accounting_mode": ("Custom",)},
            default_when={"engine_mode": {"basic": False, "auto": True, "exact": True}},
            chip_template="逐日盯市: {value}", tab_label="记账规则", tab_order=180,
        ),
        "use_int_position": FieldDefinition(
            public=True, label="整数持仓", default=False, control_template="boolean", tab="accounting",
            editable_when={"engine_mode": ("custom",), "accounting_mode": ("Custom",)},
            chip_template="整数持仓: {value}", tab_label="记账规则", tab_order=180,
        ),
        "trading_rule_custom_product_fields": custom_product_editor_definition(
            label="自定义记账字段",
            tab="accounting",
            tab_label="记账规则",
            tab_order=180,
            module_filter="trading_rule",
            visible_when={"engine_mode": ("custom",), "accounting_mode": ("Custom",)},
            display_order=95,
            fields=_CUSTOM_TRADING_RULE_FIELDS,
        ),
        "daily_mark_to_market_events": FieldDefinition(public=False),
    }

    register_daily_mark_to_market_notices: ClassVar[Flow] = Flow(
        "register_daily_mark_to_market_notices",
        inputs=(EngineModule.engine_mode, accounting_mode, daily_mark_to_market_enabled),
        outputs=(daily_mark_to_market_events,),
        phase=Phase.PRE_REPLAY,
        order=47,
        description="登记逐日盯市通知",
        strategy_scoped=True,
        compute=lambda state, ctx: _register_daily_mark_to_market_notices(state, ctx),
    )
    apply_daily_mark_to_market: ClassVar[Flow] = Flow(
        "apply_daily_mark_to_market",
        inputs=(_ledger_cash_ref, _ledger_positions_ref),
        outputs=(_ledger_cash_ref, _ledger_positions_ref),
        phase=Phase.PER_EVENT,
        event_kind=EventKind.LEDGER_NOTICE,
        order=50,
        description="执行逐日盯市结算",
        compute=lambda state, ctx: _apply_daily_mark_to_market(state, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (
        register_daily_mark_to_market_notices,
        apply_daily_mark_to_market,
    )


def _effective_accounting_mode(strategy_config: "StrategyConfig") -> str:
    engine_mode = engine_mode_for(strategy_config)
    if engine_mode == "basic":
        return "Basic"
    if engine_mode == "custom":
        return strategy_config.get(TradingRuleModule.accounting_mode, "Auto")
    return "Auto"


def _resolve_method(
    strategy_config: "StrategyConfig",
    product: "Product",
    historical_fields: Mapping[str, object] | None = None,
    *,
    require_exact: bool = False,
) -> str:
    mode = _effective_accounting_mode(strategy_config)
    if mode == "Basic":
        return "WeightAverage"
    if mode == "Custom":
        method = strategy_config.get(TradingRuleModule.cost_basis_method, "WeightAverage")
        _validate_daily_mark_to_market_cost_basis(strategy_config, method, product)
        return method
    return infer_auto_cost_basis_method(historical_fields, require_exact=require_exact, product=product)


def _resolve_daily_mark_to_market_enabled(
    strategy_config: "StrategyConfig",
    product: "Product",
    historical_fields: Mapping[str, object] | None = None,
    *,
    require_exact: bool = False,
) -> bool:
    mode = _effective_accounting_mode(strategy_config)
    if mode == "Basic":
        return False
    fields = historical_fields or {}
    if mode == "Custom":
        enabled = bool(strategy_config.get(TradingRuleModule.daily_mark_to_market_enabled, False))
        if enabled:
            _validate_daily_mark_to_market_cost_basis(
                strategy_config,
                strategy_config.get(TradingRuleModule.cost_basis_method, "WeightAverage"),
                product,
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


def _validate_daily_mark_to_market_cost_basis(
    strategy_config: "StrategyConfig",
    method: str,
    product: object,
) -> None:
    if bool(strategy_config.get(TradingRuleModule.daily_mark_to_market_enabled, False)) and method == "WeightAverage":
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


def _resolve_use_int_position(strategy_config: "StrategyConfig") -> bool:
    mode = _effective_accounting_mode(strategy_config)
    if mode == "Basic":
        return False
    if mode == "Auto":
        return True
    return strategy_config.get(TradingRuleModule.use_int_position, False)


def open_position(
    ledger: "Ledger", strategy_config: "StrategyConfig", product: "Product",
    quantity: float, entry_price: float, multiplier: float,
    market_margin_ratio: float = 1.0,
) -> None:
    from .ledger_module import LedgerModule
    from .margin import _resolve_margin_ratio
    from tools.testers.backtest.engines.native.ledger import Lot, apply_quantity_delta

    positions = ledger.get(LedgerModule.positions, {})
    entry = positions[product]
    apply_quantity_delta(entry, quantity)

    margin_ratio = _resolve_margin_ratio(strategy_config, market_margin_ratio)
    notional = abs(entry.quantity) * entry_price * multiplier
    entry.equity_occupied = DataMoney.from_major(
        notional * margin_ratio, currency=ledger.base_currency, use_minor_units=False)

    method = _resolve_method(strategy_config, product)
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
    ledger: "Ledger", strategy_config: "StrategyConfig", product: "Product",
    quantity: float, fill_price: float, multiplier: float,
    market_margin_ratio: float = 1.0,
) -> "DataMoney":
    from .ledger_module import LedgerModule
    from .margin import _resolve_margin_ratio
    from tools.testers.backtest.engines.native.ledger import apply_quantity_delta

    positions = ledger.get(LedgerModule.positions, {})
    entry = positions[product]
    prior_quantity = entry.quantity
    apply_quantity_delta(entry, -quantity)

    margin_ratio = _resolve_margin_ratio(strategy_config, market_margin_ratio)
    notional = abs(entry.quantity) * fill_price * multiplier
    entry.equity_occupied = DataMoney.from_major(
        notional * margin_ratio, currency=ledger.base_currency, use_minor_units=False)

    method = _resolve_method(strategy_config, product)
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


def mark_to_market(ledger: "Ledger", strategy_config: "StrategyConfig",
                    current_prices: dict, historical_fields: dict[object, dict[str, object]] | None = None) -> "DataMoney":
    from .ledger_module import LedgerModule
    from .market_data import contract_multiplier_from_fields, historical_fields_for_product

    positions = ledger.get(LedgerModule.positions, {})
    total = 0.0
    require_exact = engine_mode_for(strategy_config) == "exact"
    for product, entry in positions.items():
        if entry.quantity == 0:
            continue
        fields = historical_fields_for_product(historical_fields, product)
        method = _resolve_method(strategy_config, product, fields, require_exact=require_exact)
        price = _lookup_product_value(current_prices, product)
        if price is None:
            continue
        multiplier = contract_multiplier_from_fields(historical_fields or {}, product)
        if _resolve_daily_mark_to_market_enabled(
            strategy_config,
            product,
            fields,
            require_exact=require_exact,
        ):
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
    from tools.testers.backtest.modules.market_data import current_prices_table_for

    table = current_prices_table_for(state)
    if table is None or getattr(table, "empty", True):
        return
    last_rows = DataIndex.trading_day_last_event_times_from_index(table.index)
    if len(last_rows) == 0:
        return
    drafts: list[EventDraft] = []
    for strategy in ctx.active_strategies:
        for trading_day, last_event_time in last_rows.items():
            notice_time = pd.Timestamp(last_event_time) + pd.Timedelta(nanoseconds=1)
            drafts.append(
                EventDraft(
                    EventKind.LEDGER_NOTICE,
                    notice_time,
                    strategy,
                    payload={
                        "kind": "daily_mark_to_market",
                        "trading_day": _trading_day_text(trading_day),
                    },
                )
            )
    ctx.set(TradingRuleModule.daily_mark_to_market_events, drafts)


def _trading_day_text(value: object) -> str:
    timestamp = pd.Timestamp(cast(Any, value))
    return str(timestamp.date())


def _apply_daily_mark_to_market(state: Any, ctx: Any) -> None:
    from tools.testers.backtest.modules.market_data import (
        MarketDataModule,
        historical_fields_for_product,
        contract_multiplier_from_fields,
    )

    snapshot = ctx.get(MarketDataModule.current_market_snapshot, {})
    settlement_prices = snapshot.get("settlement") or snapshot.get("close") or {}
    close_prices = snapshot.get("close", {})
    for strategy in ctx.active_strategies:
        config = state.config_for(strategy)
        ledger = state.ledger_for_strategy(strategy)
        cash = ledger.get(TradingRuleModule._ledger_cash_ref)
        positions = ledger.get(TradingRuleModule._ledger_positions_ref, {})
        historical_fields = ctx.get_for(
            MarketDataModule.current_historical_fields,
            strategy,
            ctx.get(MarketDataModule.current_historical_fields, {}),
        )
        for product, entry in positions.items():
            quantity = float(entry.quantity or 0.0)
            if abs(quantity) <= 1e-12:
                continue
            fields = historical_fields_for_product(historical_fields, product)
            if not _resolve_daily_mark_to_market_enabled(
                config,
                product,
                fields,
                require_exact=engine_mode_for(config) == "exact",
            ):
                continue
            settlement = _settlement_price_for_product(
                product,
                fields,
                settlement_prices,
                close_prices,
                require_exact=engine_mode_for(config) == "exact",
            )
            previous_settlement = _previous_settlement_for_product(
                product,
                entry,
                fields,
                settlement,
                require_exact=engine_mode_for(config) == "exact",
            )
            multiplier = contract_multiplier_from_fields(historical_fields, product)
            before_margin = _entry_margin_major(entry)
            after_margin = abs(quantity) * settlement * multiplier * _margin_ratio_for_position(
                config, fields, quantity, settlement, multiplier)
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
            cash_delta = pnl - (after_margin - before_margin)
            cash = cash + DataMoney.from_major(
                cash_delta,
                currency=cash.currency,
                use_minor_units=cash.use_minor_units,
            )
            entry.equity_occupied = DataMoney.from_major(
                after_margin,
                currency=cash.currency,
                use_minor_units=cash.use_minor_units,
            )
            entry.settlement_price = settlement
            from tools.testers.backtest.modules.fee import _resolve_fee_mode
            _reset_lots_to_daily_settlement(
                entry,
                settlement,
                multiplier,
                track_today=_resolve_fee_mode(config) in {"auto", "custom", "exact"},
            )
        ledger.set(TradingRuleModule._ledger_cash_ref, cash)
        ledger.set(TradingRuleModule._ledger_positions_ref, positions)


def _settlement_price_for_product(
    product: Any,
    fields: Mapping[str, object],
    settlement_prices: Mapping[Any, float],
    close_prices: Mapping[Any, float],
    *,
    require_exact: bool,
) -> float:
    value = _lookup_product_value(settlement_prices, product)
    if value is not None:
        return value
    for field_name in ("SettlementPrice", "LastSettlementPrice"):
        field_value = _number_or_none(fields.get(field_name))
        if field_value is not None:
            return field_value
    if require_exact:
        raise KeyError(f"exact daily mark-to-market requires settlement price for {product}")
    fallback = _lookup_product_value(close_prices, product)
    if fallback is not None:
        return fallback
    raise KeyError(f"daily mark-to-market requires price for {product}")


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
        field_value = _number_or_none(fields.get(field_name))
        if field_value is not None:
            return field_value
    if require_exact:
        raise KeyError(f"exact daily mark-to-market requires previous settlement price for {product}")
    return current_settlement


def _daily_mark_to_market_basis(entry: Any, fallback: float) -> float:
    """Current blended basis for a position under daily mark-to-market.

    DMTM reuses the lot-based cost record. Yesterday-and-earlier lots are
    reset to settlement by the LEDGER_NOTICE flow; intraday lots keep their
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
    from tools.testers.backtest.engines.native.ledger import Lot

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
    strategy_config: "StrategyConfig",
    fields: Mapping[str, object],
    quantity: float,
    price: float,
    multiplier: float,
) -> float:
    from tools.testers.backtest.modules.margin import _resolve_margin_ratio

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
    ratio = _resolve_margin_ratio(strategy_config, market_ratio)
    return float(1.0 if ratio is None else ratio)


def _entry_margin_major(entry: Any) -> float:
    equity_occupied = getattr(entry, "equity_occupied", None)
    if equity_occupied is None:
        return 0.0
    return float(equity_occupied.to_major())


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


def _position_sign(value: float | int) -> float:
    return 1.0 if float(value) >= 0 else -1.0
