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
from tools.testers.backtest.modules.strategy_book import (
    StrategyBookModule,
    assign_ledger_for_strategy,
    cash_pool_id_for_ledger,
)
from tools.testers.backtest.modules.cash_pool import CashPoolModule, cash_for_ledger, set_cash_for_ledger_pool
from tools.testers.backtest.modules.trading_rule import (
    TradingRuleModule, _consume_lots, _consume_lots_hifo, _resolve_method,
    _resolve_use_int_position, mark_to_market, _resolve_daily_mark_to_market_enabled_for_ledger,
)


class LedgerModule(ExecutableModule):
    key: ClassVar[str] = "portfolio_capital"  # matches the existing frontend
        # SettingModule("portfolio_capital", "组合资金", ...) -- same concept
    label: ClassVar[str] = "账本"

    cash: ClassVar[FieldRef[Any]] = CashPoolModule.cash
    positions: ClassVar[FieldRef[Any]] = FieldRef("positions")
    equity: ClassVar[FieldRef[float]] = FieldRef("equity")
    initial_capital_major: ClassVar[FieldRef[float]] = CashPoolModule.initial_capital_major
    base_currency: ClassVar[FieldRef[str]] = CashPoolModule.base_currency
    currency_conversion_fee_rate: ClassVar[FieldRef[float]] = CashPoolModule.currency_conversion_fee_rate

    fields: ClassVar[dict[str, FieldDefinition]] = {}

    initialize_ledgers: ClassVar[Flow] = Flow(
        "initialize_ledgers",
        inputs=(EngineModule.engine_mode, TradingRuleModule.accounting_mode, TradingRuleModule.cost_basis_method,
                 TradingRuleModule.use_int_position, MinorUnitModule.use_minor_units, ProductSelectionModule.products,
                 StrategyBookModule.strategy_book_mode),
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
    from tools.testers.backtest.engines.native.ledger import LedgerState

    for strategy, strategy_config in state.strategy_configs.items():
        ledger_key = assign_ledger_for_strategy(state, strategy, strategy_config)
        ledger_id = ledger_key.name
        ledger_config = state.ledger_config_for(ledger_key)
        initial_capital = float(ledger_config.initial_capital_major or 0.0)
        base_currency = ledger_config.base_currency or "CNY"
        # MinorUnitModule.use_minor_units default_when locks this to False
        # for engine_mode="basic" and True otherwise (auto/custom/exact) --
        # read the resolved field, don't re-decide the policy here.
        use_minor_units = bool(strategy_config.get(MinorUnitModule.use_minor_units, True))
        ledger = state.ledgers.get(ledger_key)
        if ledger is None:
            ledger = LedgerState(strategy=strategy, base_currency=base_currency, ledger_id=ledger_id)
        existing_cash = cash_for_ledger(state, ledger)
        if existing_cash is None:
            set_cash_for_ledger_pool(state, ledger, DataMoney.from_major(
                initial_capital, currency=base_currency, use_minor_units=use_minor_units))
        else:
            # Ledgers in the same StrategyBook cash pool share one cash object.
            # They must therefore agree on currency and minor-unit policy; any
            # cross-currency movement must be represented by explicit FX events,
            # not by silently sharing a cash pool.
            _require_matching_cash_pool_config(
                ledger, strategy, ledger_id,
                existing_cash=existing_cash,
                base_currency=base_currency, initial_capital=initial_capital,
                use_minor_units=use_minor_units,
                cash_pool_id=cash_pool_id_for_ledger(state, ledger),
            )

        use_int = _resolve_use_int_position(strategy_config, ledger_config)
        initial_quantity = 0 if use_int else 0.0
        from tools.testers.backtest.modules.margin import MarginModule, _resolve_margin_mode_from_ledger_config

        margin_mode = _resolve_margin_mode_from_ledger_config(ledger_config)
        positions = ledger.get(LedgerModule.positions, {})
        products = _products_for_backtest_window(state, ctx, strategy)
        for product in products:
            if product in positions:
                continue
            method = _resolve_method(strategy_config, product, ledger_config=ledger_config)
            if method == "WeightAverage":
                positions[product] = ProductPosition(
                    quantity=initial_quantity, average_cost=0.0, margin_reserved=None)
            else:
                positions[product] = ProductPosition(
                    quantity=initial_quantity, lots=deque(), margin_reserved=None)
        ledger.set(LedgerModule.positions, positions)
        if margin_mode not in {"none", "zero"}:
            ledger.set(MarginModule.margin_requirement, 0.0)
            ledger.set(MarginModule.margin_reserved, 0.0)
            ledger.set(MarginModule.margin_deficit, 0.0)
            ledger.set(MarginModule.margin_excess, 0.0)
        state.ledgers[ledger_key] = ledger


def _require_matching_cash_pool_config(
    ledger,
    strategy,
    ledger_id: str,
    *,
    existing_cash,
    base_currency: str,
    initial_capital: float,
    use_minor_units: bool,
    cash_pool_id: str,
) -> None:
    existing_currency = getattr(existing_cash, "currency", ledger.base_currency)
    if existing_currency != base_currency:
        raise ValueError(
            f"strategy {getattr(strategy, 'alias', strategy)!r} shares ledger {ledger_id!r} "
            f"in cash_pool {cash_pool_id!r} with base_currency={base_currency!r}, but that cash pool was already established "
            f"with base_currency={existing_currency!r} -- a shared cash pool is one pool of "
            f"money in one currency; route cross-currency movement through FX trade events "
            f"instead of sharing one cash pool."
        )
    if existing_cash.use_minor_units != use_minor_units:
        raise ValueError(
            f"strategy {getattr(strategy, 'alias', strategy)!r} shares ledger {ledger_id!r} "
            f"in cash_pool {cash_pool_id!r} with use_minor_units={use_minor_units}, but that cash pool was already established "
            f"with use_minor_units={existing_cash.use_minor_units} -- give this strategy its own "
            f"cash pool instead of joining one with a different minor-unit policy."
        )
    if abs(existing_cash.to_major() - initial_capital) > 1e-6:
        raise ValueError(
            f"strategy {getattr(strategy, 'alias', strategy)!r} shares ledger {ledger_id!r} "
            f"in cash_pool {cash_pool_id!r} with initial_capital_major={initial_capital!r}, but that cash pool was already funded "
            f"with {existing_cash.to_major()!r} -- a cash pool is funded once; every strategy "
            f"joining it must declare the same initial_capital_major (it is not summed or "
            f"overwritten per strategy)."
        )


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
        ledger = state.ledger_for_strategy(strategy)
        cash = cash_for_ledger(state, ledger)
        positions = ledger.get(LedgerModule.positions, {})
        historical_fields = ctx.get_for(
            MarketDataModule.current_historical_fields,
            strategy,
            ctx.get(MarketDataModule.current_historical_fields, {}),
        )
        config = state.config_for(strategy)
        ledger_config = state.ledger_config_for(ledger)
        margin_occupied = sum(
            entry.margin_reserved.to_major()
            for entry in positions.values()
            if entry.margin_reserved is not None and entry.margin_reserved.to_major() > 0
        )
        if margin_occupied > 0:
            floating_pnl = mark_to_market(
                ledger,
                config,
                prices,
                historical_fields,
                ledger_config=ledger_config,
            ).to_major()
            ctx.set_for(LedgerModule.equity, strategy, cash.to_major() + margin_occupied + floating_pnl)
            continue
        market_value = sum(
            contract_notional(_required_current_price(prices, product, ctx.timestamp), entry.quantity, historical_fields, product)
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
        historical_fields = ctx.get_for(
            MarketDataModule.current_historical_fields,
            strategy,
            ctx.get(MarketDataModule.current_historical_fields, {}),
        )
        for order in ctx.payloads_for(strategy):
            if order.status == OrderStatus.CANCELLED or order.get("reject_reason"):
                continue  # terminal before accounting -- no ledger effect
            ledger = state.ledger_for(order)
            ledger_config = state.ledger_config_for(ledger)
            positions = ledger.get(LedgerModule.positions, {})
            cash = cash_for_ledger(state, ledger)
            price = order.get("effective_price", prices[order.instrument])
            fee_cost = order.get("fee_cost", 0.0)
            cash_before = cash.to_major()
            if _uses_margin_accounting(state.config_for(strategy), historical_fields, order.instrument, ledger_config):
                cash = _apply_margin_accounting_fill(
                    cash,
                    positions,
                    state.config_for(strategy),
                    order.instrument,
                    quantity=float(order.quantity),
                    price=float(price),
                    fee_cost=float(fee_cost or 0.0),
                    historical_fields=historical_fields,
                    ledger_config=ledger_config,
                )
            else:
                _apply_cash_accounting_position_fill(
                    positions,
                    state.config_for(strategy),
                    order.instrument,
                    quantity=float(order.quantity),
                    price=float(price),
                    historical_fields=historical_fields,
                    ledger_config=ledger_config,
                )
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
            set_cash_for_ledger_pool(state, ledger, cash)
            _sync_ledger_margin_reserved(ledger, positions)


def _uses_margin_accounting(strategy_config, historical_fields: dict, product, ledger_config=None) -> bool:
    from tools.testers.backtest.modules.margin import product_uses_margin_accounting

    fields = historical_fields_for_product(historical_fields, product)
    return product_uses_margin_accounting(fields, ledger_config)


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
    ledger_config=None,
) -> DataMoney:
    fields = historical_fields_for_product(historical_fields, product)
    multiplier = contract_multiplier_from_fields(historical_fields, product)
    entry = positions.setdefault(product, ProductPosition(quantity=0.0, average_cost=0.0))
    before_margin = _entry_margin_major(entry)
    prior_quantity = float(entry.quantity or 0.0)
    new_quantity = prior_quantity + quantity

    method = _resolve_method(
        strategy_config, product, fields,
        require_exact=engine_mode_for(strategy_config) == "exact",
        ledger_config=ledger_config,
    )
    from tools.testers.backtest.modules.fee import _resolve_fee_mode
    fee_mode = _resolve_fee_mode(strategy_config, ledger_config)
    daily_mark_to_market = _resolve_daily_mark_to_market_enabled_for_ledger(
        product,
        fields,
        ledger_config=ledger_config,
    )
    if method in ("FIFO", "LIFO", "HIFO"):
        # Lot-based methods keep the lot queue as the cost-basis record --
        # mark_to_market reads entry.lots for floating P&L, so the fill
        # must maintain it; average_cost stays untouched (it would imply
        # a weighted-average basis that doesn't exist under these methods).
        realized = _apply_lot_fill(
            entry,
            method,
            quantity,
            price,
            multiplier,
            is_today=True if daily_mark_to_market and fee_mode in {"auto", "custom", "exact"} else None,
        )
        if abs(new_quantity) <= 1e-12:
            new_quantity = 0.0
    else:
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
    after_margin = abs(new_quantity) * price * multiplier * _resolved_margin_ratio_for_position_after_fill(
        strategy_config,
        fields,
        new_quantity,
        price,
        multiplier,
        ledger_config,
    )
    entry.margin_reserved = DataMoney.from_major(
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


def _apply_cash_accounting_position_fill(
    positions: dict,
    strategy_config,
    product,
    *,
    quantity: float,
    price: float,
    historical_fields: dict,
    ledger_config=None,
) -> None:
    fields = historical_fields_for_product(historical_fields, product)
    multiplier = contract_multiplier_from_fields(historical_fields, product)
    entry = positions.setdefault(product, ProductPosition(quantity=0.0, average_cost=0.0))
    prior_quantity = float(entry.quantity or 0.0)
    new_quantity = prior_quantity + quantity
    method = _resolve_method(
        strategy_config,
        product,
        fields,
        require_exact=engine_mode_for(strategy_config) == "exact",
        ledger_config=ledger_config,
    )
    if method in ("FIFO", "LIFO", "HIFO"):
        _apply_lot_fill(entry, method, quantity, price, multiplier, is_today=None)
        if abs(new_quantity) <= 1e-12:
            new_quantity = 0.0
    else:
        prior_cost = float(entry.average_cost or price)
        if prior_quantity == 0 or _same_direction(prior_quantity, quantity):
            entry.average_cost = _weighted_average_cost(prior_quantity, prior_cost, quantity, price)
        elif abs(new_quantity) <= 1e-12:
            entry.average_cost = 0.0
            new_quantity = 0.0
        elif abs(quantity) > abs(prior_quantity):
            entry.average_cost = price
    entry.quantity = int(round(new_quantity)) if isinstance(entry.quantity, int) else new_quantity


def _sync_ledger_margin_reserved(ledger, positions: dict) -> None:
    from tools.testers.backtest.modules.margin import MarginModule

    reserved = sum(_entry_margin_major(entry) for entry in positions.values())
    if ledger.get(MarginModule.margin_requirement, None) is None and reserved <= 0:
        return
    ledger.set(MarginModule.margin_reserved, reserved)
    required = float(ledger.get(MarginModule.margin_requirement, reserved) or 0.0)
    deficit = float(ledger.get(MarginModule.margin_deficit, 0.0) or 0.0)
    ledger.set(MarginModule.margin_excess, max(reserved - required, 0.0))
    if reserved >= required:
        ledger.set(MarginModule.margin_deficit, 0.0)
    else:
        ledger.set(MarginModule.margin_deficit, deficit)


def _apply_lot_fill(
    entry: ProductPosition,
    method: str,
    quantity: float,
    price: float,
    multiplier: float,
    *,
    is_today: bool | None = None,
) -> float:
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
        entry.lots.append(Lot(quantity=quantity, entry_price=price, multiplier=multiplier, is_today=is_today))
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
        entry.lots.append(Lot(
            quantity=flip_abs * _sign(quantity),
            entry_price=price,
            multiplier=multiplier,
            is_today=is_today,
        ))
    return realized


def _resolved_margin_ratio_for_order(
    strategy_config, fields: dict[str, object], quantity: float, price: float, multiplier: float, ledger_config=None,
) -> float:
    from tools.testers.backtest.modules.margin import _resolve_margin_ratio

    market_ratio = _market_margin_ratio(fields, quantity, price, multiplier)
    ratio = _resolve_margin_ratio(strategy_config, market_ratio, ledger_config)
    return float(1.0 if ratio is None else ratio)


def _resolved_margin_ratio_for_position_after_fill(
    strategy_config,
    fields: dict[str, object],
    new_quantity: float,
    price: float,
    multiplier: float,
    ledger_config=None,
) -> float:
    if abs(new_quantity) <= 1e-12:
        return 0.0
    # Margin is a property of the remaining position, not of the order used to
    # reach it. A sell that reduces a long position must still use the long
    # margin fields for the remaining long exposure; a buy reducing a short
    # must still use the short fields. If the order flips the position, the
    # new_quantity sign naturally selects the new side.
    return _resolved_margin_ratio_for_order(
        strategy_config,
        fields,
        new_quantity,
        price,
        multiplier,
        ledger_config,
    )


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
    if entry.margin_reserved is None:
        return 0.0
    return float(entry.margin_reserved.to_major())


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


def _required_current_price(prices: dict, product, timestamp) -> float:
    if isinstance(prices, dict) and product in prices:
        return float(prices[product])
    raise KeyError(
        f"current price missing for held product {product} at {timestamp}; "
        "current_prices is expected to be causal-ffilled by MarketDataModule, "
        "so this usually means the position product was not included in the loaded market-data universe"
    )
