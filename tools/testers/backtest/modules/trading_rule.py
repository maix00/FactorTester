"""TradingRuleModule — cost-basis method + position-quantity type."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, ClassVar, Literal, cast

from tools.data.types.data_money import DataMoney
from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.backtest.modules.custom_product import custom_product_editor_definition
from tools.testers.backtest.modules.engine import EngineModule, engine_mode_for

if TYPE_CHECKING:
    from tools.products.Product import Product
    from tools.testers.backtest.engines.native.ledger import Ledger, StrategyConfig

AccountingMode = Literal["Basic", "Custom", "Auto"]
CostBasisMethod = Literal["WeightAverage", "FIFO", "LIFO", "HIFO", "DailyMarkToMarket"]

_VALID_COST_BASIS_METHODS = {"WeightAverage", "FIFO", "LIFO", "HIFO", "DailyMarkToMarket"}
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
            ("DailyMarkToMarket", "逐日盯市"),
        ),
        "allow_time_range": False,
    },
)


class TradingRuleModule(ExecutableModule):
    key: ClassVar[str] = "trading_rule"
    label: ClassVar[str] = "记账规则"

    accounting_mode: ClassVar[FieldRef[AccountingMode]] = FieldRef("accounting_mode")
    cost_basis_method: ClassVar[FieldRef[CostBasisMethod]] = FieldRef("cost_basis_method")
    use_int_position: ClassVar[FieldRef[bool]] = FieldRef("use_int_position")

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
                      ("LIFO", "后进先出"), ("HIFO", "高进先出"),
                      ("DailyMarkToMarket", "逐日盯市")),
            editable_when={"engine_mode": ("custom",), "accounting_mode": ("Custom",)},
            chip_template="成本法: {value}", tab_label="记账规则", tab_order=180,
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
    }


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
        return strategy_config.get(TradingRuleModule.cost_basis_method, "WeightAverage")
    return infer_auto_cost_basis_method(historical_fields, require_exact=require_exact, product=product)


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
        if method not in _VALID_COST_BASIS_METHODS:
            raise ValueError(f"unsupported CostBasisMethod for {product}: {method}")
        return cast(CostBasisMethod, method)
    if require_exact:
        raise KeyError(f"exact accounting requires historical CostBasisMethod for {product}")
    if _has_daily_mark_to_market_indicator(fields):
        return "DailyMarkToMarket"
    if _has_any_fee_field(fields):
        return "FIFO"
    return "WeightAverage"


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
    # DailyMarkToMarket: no per-lot/average-cost bookkeeping; settlement
    # reads MarketDataModule.settlement_price directly, nothing to write here.


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
    elif method == "DailyMarkToMarket":
        # realized P&L is "fill price - last settlement price", not the
        # original entry price — daily settlement already swept prior
        # floating P&L into cash.
        realized = 0.0  # placeholder: requires MarketDataModule.settlement_price,
                          # wired in the daily-settlement Flow (not built this round)
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
                    current_prices: dict) -> "DataMoney":
    from .ledger_module import LedgerModule

    positions = ledger.get(LedgerModule.positions, {})
    total = 0.0
    for product, entry in positions.items():
        if entry.quantity == 0:
            continue
        method = _resolve_method(strategy_config, product)
        price = current_prices.get(product)
        if price is None:
            continue
        if method == "WeightAverage" and entry.average_cost is not None:
            total += entry.quantity * (price - entry.average_cost)
        elif method in ("FIFO", "LIFO", "HIFO") and entry.lots:
            for lot in entry.lots:
                total += lot.quantity * (price - lot.entry_price) * lot.multiplier
        # DailyMarkToMarket: floating P&L relative to last settlement price,
        # not implemented this round (requires MarketDataModule.settlement_price)
    return DataMoney.from_major(total, currency=ledger.base_currency, use_minor_units=False)
