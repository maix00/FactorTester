"""LedgerModule — owns the Ledger field schema (cash/positions) AND the
mandatory baseline economic model (unlimited liquidity, fractional
positions, no margin). EngineModule/TradingRuleModule/FeeModule/etc. are optional layers
stacked on top via FlowOverride; this module's own Flows never depend on
them."""

from __future__ import annotations

from collections import deque
from typing import Any, ClassVar, cast

from tools.data.types.data_money import DataMoney
from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.engines.native.ledger import ProductPosition, apply_quantity_delta
from tools.testers.backtest.modules.market_data import MarketDataModule, contract_notional
from tools.testers.backtest.modules.market_data import (
    contract_multiplier_from_fields,
    historical_fields_for_product,
)
from tools.testers.backtest.modules.minor_unit import MinorUnitModule
from tools.testers.backtest.modules.order_flow import order_flow_store_for
from tools.testers.backtest.modules.product_selection import ProductSelectionModule
from tools.testers.backtest.modules.engine import EngineModule, engine_mode_for
from tools.testers.backtest.modules.trading_rule import (
    TradingRuleModule, _consume_lots, _consume_lots_hifo, _resolve_method,
    _resolve_use_int_position, mark_to_market,
)


class LedgerModule(ExecutableModule):
    key: ClassVar[str] = "portfolio_capital"  # matches the existing frontend
        # SettingModule("portfolio_capital", "组合资金", ...) -- same concept
    label: ClassVar[str] = "账本"

    cash: ClassVar[FieldRef[Any]] = FieldRef("cash")
    positions: ClassVar[FieldRef[Any]] = FieldRef("positions")
    equity: ClassVar[FieldRef[float]] = FieldRef("equity")
    initial_capital_major: ClassVar[FieldRef[float]] = FieldRef("initial_capital_major")
    base_currency: ClassVar[FieldRef[str]] = FieldRef("base_currency")
    currency_conversion_fee_rate: ClassVar[FieldRef[float]] = FieldRef("currency_conversion_fee_rate")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "initial_capital_major": FieldDefinition(
            public=True, label="初始资金", control_template="number", default=100_000_000.0, tab="capital",
            chip_template="初始资金: {value}", tab_label="资金", tab_order=50,
        ),
        "base_currency": FieldDefinition(
            public=True, label="币种", control_template="select", default="CNY", tab="capital",
            chip_template="币种: {value}", tab_label="资金", tab_order=50,
        ),
        "currency_conversion_fee_rate": FieldDefinition(
            public=True, label="换汇费率", control_template="number", default=0.0, tab="capital",
            minimum=0.0, step=0.000001,
            chip_template="换汇费率: {value}", tab_label="资金", tab_order=50,
        ),
    }

    initialize_ledgers: ClassVar[Flow] = Flow(
        "initialize_ledgers",
        inputs=(EngineModule.engine_mode, TradingRuleModule.accounting_mode, TradingRuleModule.cost_basis_method,
                 TradingRuleModule.use_int_position, MinorUnitModule.use_minor_units, ProductSelectionModule.products),
        outputs=(cash, positions),
        phase=Phase.PRE_REPLAY, order=41, after=(MarketDataModule.load_raw_market_data,),
        description="初始化交易账本",
        compute=lambda state, ctx: _initialize_ledgers(state, ctx),
    )
    equity_on_signal: ClassVar[Flow] = Flow(
        "equity_on_signal", inputs=(MarketDataModule.current_prices, MarketDataModule.current_historical_fields, cash, positions),
        outputs=(equity,), phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL,
        description="计算信号时点权益",
        order=10, compute=lambda state, ctx: _basic_equity(state, ctx),
    )
    cash_update: ClassVar[Flow] = Flow(
        "cash_update", inputs=(MarketDataModule.current_prices, MarketDataModule.current_historical_fields), outputs=(positions, cash),
        phase=Phase.PER_EVENT, event_kind=EventKind.ORDER, order=10,
        description="更新现金与持仓",
        compute=lambda state, ctx: _basic_cash_update(state, ctx),
    )
    equity_on_order: ClassVar[Flow] = Flow(
        "equity_on_order", inputs=(MarketDataModule.current_prices, MarketDataModule.current_historical_fields, cash, positions),
        outputs=(equity,), phase=Phase.PER_EVENT, event_kind=EventKind.ORDER,
        description="计算订单后权益",
        order=900, after=(cash_update,), compute=lambda state, ctx: _basic_equity(state, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (
        initialize_ledgers, equity_on_signal, cash_update, equity_on_order,
    )


def _initialize_ledgers(state, ctx) -> None:
    from tools.testers.backtest.engines.native.ledger import Ledger

    for strategy, strategy_config in state.strategy_configs.items():
        initial_capital = strategy_config.get(LedgerModule.initial_capital_major, 0.0)
        base_currency = strategy_config.get(LedgerModule.base_currency, "CNY")
        # MinorUnitModule.use_minor_units default_when locks this to False
        # for engine_mode="basic" and True otherwise (auto/custom/exact) --
        # read the resolved field, don't re-decide the policy here.
        use_minor_units = bool(strategy_config.get(MinorUnitModule.use_minor_units, True))
        ledger = Ledger(strategy=strategy, base_currency=base_currency)
        ledger.set(LedgerModule.cash, DataMoney.from_major(
            initial_capital, currency=base_currency, use_minor_units=use_minor_units))

        use_int = _resolve_use_int_position(strategy_config)
        initial_quantity = 0 if use_int else 0.0
        zero_equity_occupied = DataMoney.from_major(0, currency=base_currency, use_minor_units=use_minor_units)

        positions: dict = {}
        products = _products_for_backtest_window(state, ctx, strategy)
        for product in products:
            method = _resolve_method(strategy_config, product)
            if method == "WeightAverage":
                positions[product] = ProductPosition(
                    quantity=initial_quantity, average_cost=0.0, equity_occupied=zero_equity_occupied)
            elif method in ("FIFO", "LIFO", "HIFO"):
                positions[product] = ProductPosition(
                    quantity=initial_quantity, lots=deque(), equity_occupied=zero_equity_occupied)
            else:  # DailyMarkToMarket
                positions[product] = ProductPosition(
                    quantity=initial_quantity, equity_occupied=zero_equity_occupied)
        ledger.set(LedgerModule.positions, positions)
        state.ledgers[strategy] = ledger


def _products_for_backtest_window(state, ctx, strategy) -> frozenset:
    products = frozenset(ctx.get_for(ProductSelectionModule.products, strategy, frozenset()))
    from tools.testers.backtest.modules.market_data import market_data_store_for
    included = market_data_store_for(state).included_products
    if included is None:
        return products
    return frozenset(product for product in products if product in included)


def _basic_equity(state, ctx) -> None:
    prices = ctx.get(MarketDataModule.current_prices)
    for strategy in ctx.active_strategies:
        ledger = state.ledgers[strategy]
        cash = ledger.get(LedgerModule.cash)
        positions = ledger.get(LedgerModule.positions, {})
        historical_fields = ctx.get_for(
            MarketDataModule.current_historical_fields,
            strategy,
            ctx.get(MarketDataModule.current_historical_fields, {}),
        )
        margin_occupied = sum(
            entry.equity_occupied.to_major()
            for entry in positions.values()
            if entry.equity_occupied is not None and entry.equity_occupied.to_major() > 0
        )
        if margin_occupied > 0:
            floating_pnl = mark_to_market(
                ledger,
                state.config_for(strategy),
                prices,
                historical_fields,
            ).to_major()
            ctx.set_for(LedgerModule.equity, strategy, cash.to_major() + margin_occupied + floating_pnl)
            continue
        market_value = sum(
            contract_notional(prices[product], entry.quantity, historical_fields, product)
            for product, entry in positions.items()
        )
        ctx.set_for(LedgerModule.equity, strategy, cash.to_major() + market_value)


def _basic_cash_update(state, ctx) -> None:
    """`order.fields["effective_price"]`/`order.fields["fee_cost"]` are
    optional hooks for FlowOverride layers (SlippageModule/FeeModule,
    step 6) to set before this base computation runs — absent either, this
    degrades to "trade at the unadjusted market price, no fee", the same
    "field value is the parameter" pattern as TradingRuleModule's
    margin_mode="none".

    A strategy can have several simultaneous orders in this batch (one per
    product being rebalanced at this timestamp) -- all of them are applied
    to the same Ledger, fetched once per strategy rather than once per
    order to avoid repeated dict lookups."""
    from tools.testers.backtest.engines.native.order import OrderStatus

    prices = ctx.get(MarketDataModule.current_prices)
    store = order_flow_store_for(state)
    for strategy in ctx.active_strategies:
        ledger = state.ledgers[strategy]
        positions = ledger.get(LedgerModule.positions, {})
        cash = ledger.get(LedgerModule.cash)
        historical_fields = ctx.get_for(
            MarketDataModule.current_historical_fields,
            strategy,
            ctx.get(MarketDataModule.current_historical_fields, {}),
        )
        for order in ctx.payloads_for(strategy):
            if order.status == OrderStatus.CANCELLED or order.get("reject_reason"):
                continue  # terminal before accounting -- no ledger effect
            price = order.get("effective_price", prices[order.instrument])
            fee_cost = order.get("fee_cost", 0.0)
            cash_before = cash.to_major()
            if _uses_margin_accounting(state.config_for(strategy), historical_fields, order.instrument):
                cash = _apply_margin_accounting_fill(
                    cash,
                    positions,
                    state.config_for(strategy),
                    order.instrument,
                    quantity=float(order.quantity),
                    price=float(price),
                    fee_cost=float(fee_cost or 0.0),
                    historical_fields=historical_fields,
                )
            else:
                entry = positions.setdefault(order.instrument, ProductPosition())
                apply_quantity_delta(entry, order.quantity)
                trade_cost = DataMoney.from_major(
                    contract_notional(price, order.quantity, historical_fields, order.instrument) + fee_cost,
                    currency=cash.currency,
                    use_minor_units=cash.use_minor_units,
                )
                cash = cash - trade_cost
            store.record(
                order,
                step="ledger_update",
                label="更新账本",
                timestamp=ctx.timestamp,
                details={
                    "price": float(price),
                    "fee_cost": float(fee_cost or 0.0),
                    "cash_before": float(cash_before),
                    "cash_after": float(cash.to_major()),
                },
            )
        ledger.set(LedgerModule.positions, positions)
        ledger.set(LedgerModule.cash, cash)


def _uses_margin_accounting(strategy_config, historical_fields: dict, product) -> bool:
    from tools.testers.backtest.modules.margin import _resolve_margin_mode

    mode = _resolve_margin_mode(strategy_config)
    if mode in {"none", "zero"}:
        return False
    return True


def _apply_margin_accounting_fill(
    cash: DataMoney,
    positions: dict,
    strategy_config,
    product,
    *,
    quantity: float,
    price: float,
    fee_cost: float,
    historical_fields: dict,
) -> DataMoney:
    fields = historical_fields_for_product(historical_fields, product)
    multiplier = contract_multiplier_from_fields(historical_fields, product)
    margin_ratio = _resolved_margin_ratio_for_order(strategy_config, fields, quantity, price, multiplier)
    entry = positions.setdefault(product, ProductPosition(quantity=0.0, average_cost=0.0))
    before_margin = _entry_margin_major(entry)
    prior_quantity = float(entry.quantity or 0.0)
    new_quantity = prior_quantity + quantity

    method = _resolve_method(
        strategy_config, product, fields,
        require_exact=engine_mode_for(strategy_config) == "exact",
    )
    if method in ("FIFO", "LIFO", "HIFO"):
        # Lot-based methods keep the lot queue as the cost-basis record --
        # mark_to_market reads entry.lots for floating P&L, so the fill
        # must maintain it; average_cost stays untouched (it would imply
        # a weighted-average basis that doesn't exist under these methods).
        realized = _apply_lot_fill(entry, method, quantity, price, multiplier)
        if abs(new_quantity) <= 1e-12:
            new_quantity = 0.0
    else:
        # WeightAverage keeps a blended average_cost. DailyMarkToMarket
        # shares this arithmetic deliberately: the daily settlement flow
        # sweeps average_cost to the settlement price every day, so
        # "fill price - average_cost" here IS "fill price - last
        # settlement", the mark-to-market realized P&L.
        prior_cost = float(entry.average_cost or price)
        realized = 0.0
        if prior_quantity == 0 or _same_direction(prior_quantity, quantity):
            new_cost = _weighted_average_cost(prior_quantity, prior_cost, quantity, price)
        else:
            close_abs = min(abs(quantity), abs(prior_quantity))
            realized = close_abs * (price - prior_cost) * _sign(prior_quantity) * multiplier
            if abs(new_quantity) <= 1e-12:
                new_quantity = 0.0
                new_cost = 0.0
            elif abs(quantity) > abs(prior_quantity):
                new_cost = price
            else:
                new_cost = prior_cost
        entry.average_cost = new_cost

    entry.quantity = int(round(new_quantity)) if isinstance(entry.quantity, int) else new_quantity
    after_margin = abs(new_quantity) * price * multiplier * margin_ratio
    entry.equity_occupied = DataMoney.from_major(
        after_margin,
        currency=cash.currency,
        use_minor_units=cash.use_minor_units,
    )
    cash_delta = realized - fee_cost - (after_margin - before_margin)
    return cash + DataMoney.from_major(
        cash_delta,
        currency=cash.currency,
        use_minor_units=cash.use_minor_units,
    )


def _apply_lot_fill(entry: ProductPosition, method: str, quantity: float, price: float, multiplier: float) -> float:
    """Apply one fill to a lot-based (FIFO/LIFO/HIFO) position entry.

    Same-direction fills append a new lot. Opposite-direction fills consume
    existing lots per the method's order and realize P&L against each
    consumed lot's own entry price; a fill larger than the position flips
    it, opening the remainder as a fresh lot at the fill price."""
    from tools.testers.backtest.engines.native.ledger import Lot

    if entry.lots is None:
        entry.lots = deque()
    prior_quantity = float(entry.quantity or 0.0)
    if prior_quantity == 0 or _same_direction(prior_quantity, quantity):
        entry.lots.append(Lot(quantity=quantity, entry_price=price, multiplier=multiplier))
        return 0.0

    close_abs = min(abs(quantity), abs(prior_quantity))
    if method == "FIFO":
        raw = _consume_lots(entry.lots, close_abs, price, multiplier, from_front=True)
    elif method == "LIFO":
        raw = _consume_lots(entry.lots, close_abs, price, multiplier, from_front=False)
    else:
        raw = _consume_lots_hifo(entry.lots, close_abs, price, multiplier)
    # _consume_lots computes take*(fill - entry): the long-side sign. A short
    # position closing realizes (entry - fill) per lot instead.
    realized = raw if prior_quantity > 0 else -raw

    flip_abs = abs(quantity) - close_abs
    if flip_abs > 1e-12:
        entry.lots.append(Lot(quantity=flip_abs * _sign(quantity), entry_price=price, multiplier=multiplier))
    return realized


def _resolved_margin_ratio_for_order(strategy_config, fields: dict[str, object], quantity: float, price: float, multiplier: float) -> float:
    from tools.testers.backtest.modules.margin import _resolve_margin_ratio

    market_ratio = _market_margin_ratio(fields, quantity, price, multiplier)
    ratio = _resolve_margin_ratio(strategy_config, market_ratio)
    return float(1.0 if ratio is None else ratio)


def _market_margin_ratio(fields: dict[str, object], quantity: float, price: float, multiplier: float) -> float | None:
    if quantity < 0:
        by_money = fields.get("ShortMarginRatioByMoney")
        by_volume = fields.get("ShortMarginRatioByVolume")
    else:
        by_money = fields.get("LongMarginRatioByMoney")
        by_volume = fields.get("LongMarginRatioByVolume")
    ratio = _number_or_none(by_money)
    if ratio is not None:
        return ratio
    fixed = _number_or_none(by_volume)
    denominator = abs(price * multiplier)
    if fixed is not None and denominator > 0:
        return fixed / denominator
    return None


def _entry_margin_major(entry: ProductPosition) -> float:
    if entry.equity_occupied is None:
        return 0.0
    return float(entry.equity_occupied.to_major())


def _weighted_average_cost(prior_quantity: float, prior_cost: float, quantity: float, price: float) -> float:
    total = abs(prior_quantity) + abs(quantity)
    if total <= 1e-12:
        return 0.0
    return (abs(prior_quantity) * prior_cost + abs(quantity) * price) / total


def _same_direction(left: float, right: float) -> bool:
    return (left >= 0 and right >= 0) or (left <= 0 and right <= 0)


def _sign(value: float) -> float:
    return 1.0 if value >= 0 else -1.0


def _number_or_none(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(cast(Any, value))
    except (TypeError, ValueError):
        return None
