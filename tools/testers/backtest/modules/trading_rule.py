"""TradingRuleModule — cost-basis method + position-quantity type + margin
constraints, merged into one module (issue-114 step 5/1.4c). Not split into
CostBasisMethodModule/MarginModule subclasses: these are all parameters of
the same "how do we account for a position" concern, selected via
accounting_mode (Basic/Custom/Auto), not separate algorithms requiring
their own classes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Literal

from tools.data.types.data_money import DataMoney
from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef

if TYPE_CHECKING:
    from tools.products.Product import Product
    from tools.testers.backtest.engines.native.ledger import Ledger, StrategyConfig

AccountingMode = Literal["Basic", "Custom", "Auto"]
CostBasisMethod = Literal["WeightAverage", "FIFO", "LIFO", "HIFO", "DailyMarkToMarket"]
MarginMode = Literal["none", "fixed", "auto"]


class TradingRuleModule(ExecutableModule):
    key: ClassVar[str] = "trading_rule"
    label: ClassVar[str] = "记账与保证金"

    accounting_mode: ClassVar[FieldRef[AccountingMode]] = FieldRef("accounting_mode")
    cost_basis_method: ClassVar[FieldRef[CostBasisMethod]] = FieldRef("cost_basis_method")
    use_int_position: ClassVar[FieldRef[bool]] = FieldRef("use_int_position")
    margin_mode: ClassVar[FieldRef[MarginMode]] = FieldRef("margin_mode")
    fixed_margin_ratio: ClassVar[FieldRef[float]] = FieldRef("fixed_margin_ratio")
    collateral_fraction: ClassVar[FieldRef[float]] = FieldRef("collateral_fraction")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "accounting_mode": FieldDefinition(
            public=True, default="Basic", control_template="select", tab="accounting",
            options=(("Basic", "基础"), ("Custom", "自定义"), ("Auto", "自动")),
            chip_template="记账: {value}", tab_label="记账规则", tab_order=180,
        ),
        "cost_basis_method": FieldDefinition(
            public=True, default="WeightAverage", control_template="select", tab="accounting",
            options=(("WeightAverage", "加权平均成本法"), ("FIFO", "先进先出"),
                      ("LIFO", "后进先出"), ("HIFO", "高进先出"),
                      ("DailyMarkToMarket", "逐日盯市")),
            editable_when={"accounting_mode": ("Custom",)},
            chip_template="成本法: {value}", tab_label="记账规则", tab_order=180,
        ),
        "use_int_position": FieldDefinition(
            public=True, default=False, control_template="boolean", tab="accounting",
            editable_when={"accounting_mode": ("Custom",)},
            chip_template="整数持仓: {value}", tab_label="记账规则", tab_order=180,
        ),
        "margin_mode": FieldDefinition(
            public=True, default="none", control_template="select", tab="margin",
            options=(("none", "关闭"), ("fixed", "固定比例"), ("auto", "按市场规则自动")),
            editable_when={"accounting_mode": ("Custom",)},
            chip_template="保证金: {value}", tab_label="保证金", tab_order=160,
        ),
        "fixed_margin_ratio": FieldDefinition(
            public=True, default=1.0, control_template="number", tab="margin",
            visible_when={"margin_mode": ("fixed",)},
            chip_template="保证金率: {value}", tab_label="保证金", tab_order=160,
        ),
        "collateral_fraction": FieldDefinition(
            public=True, default=1.0, control_template="number", tab="margin",
            visible_when={"margin_mode": ("fixed", "auto")},
            chip_template="抵押比例: {value}", tab_label="保证金", tab_order=160,
        ),
    }


def _resolve_method(strategy_config: "StrategyConfig", product: "Product") -> str:
    mode = strategy_config.get(TradingRuleModule.accounting_mode, "Basic")
    if mode == "Basic":
        return "WeightAverage"
    if mode == "Custom":
        return strategy_config.get(TradingRuleModule.cost_basis_method, "WeightAverage")
    # Auto: derive from the product's own trading spec, not a per-product
    # "default_cost_basis_method" attribute (Product has no such field).
    # Real-world convention: margin-traded instruments (futures) settle
    # daily mark-to-market; non-margin instruments (equities/spot) default
    # to FIFO (the standard tax-lot accounting default absent any explicit
    # election, e.g. US IRS default method for securities).
    return "DailyMarkToMarket" if getattr(product, "is_margin_traded", False) else "FIFO"


def _resolve_use_int_position(strategy_config: "StrategyConfig") -> bool:
    mode = strategy_config.get(TradingRuleModule.accounting_mode, "Basic")
    if mode == "Basic":
        return False
    if mode == "Auto":
        return True
    return strategy_config.get(TradingRuleModule.use_int_position, False)


def _resolve_margin_mode(strategy_config: "StrategyConfig") -> str:
    mode = strategy_config.get(TradingRuleModule.accounting_mode, "Basic")
    if mode == "Basic":
        return "none"
    if mode == "Auto":
        return "auto"
    return strategy_config.get(TradingRuleModule.margin_mode, "none")


def _resolve_margin_ratio(strategy_config: "StrategyConfig", market_margin_ratio: float) -> float:
    mode = _resolve_margin_mode(strategy_config)
    if mode == "none":
        return 1.0
    if mode == "fixed":
        return strategy_config.get(TradingRuleModule.fixed_margin_ratio, 1.0)
    return market_margin_ratio  # mode == "auto"


def open_position(
    ledger: "Ledger", strategy_config: "StrategyConfig", product: "Product",
    quantity: float, entry_price: float, multiplier: float,
    market_margin_ratio: float = 1.0,
) -> None:
    from .ledger_module import LedgerModule
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
