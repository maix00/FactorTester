"""Ledger and cash-pool initialization."""

from __future__ import annotations

from collections import deque

from tools.data.types.data_money import DataMoney
from tools.testers.backtest.engines.native.position import ProductPosition
from tools.testers.backtest.modules.cash_pool import (
    CashPoolModule,
    cash_for_ledger,
    ensure_cash_pool_config_for_strategy_ledger,
    set_cash_for_ledger_pool,
)
from tools.testers.backtest.modules.minor_unit import (
    resolve_use_minor_units,
)
from tools.testers.backtest.modules.strategy_book import (
    assign_ledger_for_strategy,
    cash_pool_id_for_ledger,
)
from tools.testers.backtest.modules.trading_rule import (
    _resolve_method,
    _resolve_use_int_position,
)


def initialize_ledgers(state, ctx) -> None:
    from tools.testers.backtest.engines.native.ledger import LedgerState
    from tools.testers.backtest.modules.ledger_module import LedgerModule
    from tools.testers.backtest.modules.margin import (
        MarginModule,
        _resolve_margin_mode_from_ledger_config,
    )

    for strategy, strategy_config in state.strategy_configs.items():
        ledger_key = assign_ledger_for_strategy(state, strategy, strategy_config)
        ledger_id = ledger_key.name
        ledger_config = state.ledger_config_for(ledger_key)
        pool_config = ensure_cash_pool_config_for_strategy_ledger(
            state, strategy_config, ledger_key,
            source=f"strategy {getattr(strategy, 'alias', strategy)!r}",
        )
        base_currency = pool_config.base_currency or "CNY"
        account_currency = ledger_config.account_currency or base_currency
        use_minor_units = resolve_use_minor_units(strategy_config)
        ledger = state.ledgers.get(ledger_key) or LedgerState(
            strategy=strategy, base_currency=account_currency, ledger_id=ledger_id,
        )
        # ``ledger_config_for`` may have been resolved from the identity before
        # this LedgerState existed.  Pin the same immutable pre-replay config
        # on the materialized state for hot ORDER-stage lookups.
        object.__setattr__(ledger, "_resolved_ledger_config", ledger_config)
        existing_cash = cash_for_ledger(state, ledger)
        if existing_cash is None:
            set_cash_for_ledger_pool(state, ledger, DataMoney.from_major(
                0.0, currency=account_currency, use_minor_units=use_minor_units,
            ))
        else:
            require_matching_cash_pool_config(
                ledger, strategy, ledger_id, existing_cash=existing_cash,
                account_currency=account_currency,
                use_minor_units=use_minor_units,
                cash_pool_id=cash_pool_id_for_ledger(state, ledger),
            )
        positions = ledger.get(LedgerModule.positions, {})
        initial_quantity = 0 if _resolve_use_int_position(strategy_config, ledger_config) else 0.0
        for product in products_for_backtest_window(state, ctx, strategy):
            if product in positions:
                continue
            method = _resolve_method(strategy_config, product, ledger_config=ledger_config)
            positions[product] = (
                ProductPosition(quantity=initial_quantity, average_cost=0.0, margin_reserved=None)
                if method == "WeightAverage"
                else ProductPosition(quantity=initial_quantity, lots=deque(), margin_reserved=None)
            )
        ledger.set(LedgerModule.positions, positions)
        if _resolve_margin_mode_from_ledger_config(ledger_config) not in {"none", "zero"}:
            for ref in (
                MarginModule.margin_requirement, MarginModule.margin_reserved,
                MarginModule.margin_deficit, MarginModule.margin_excess,
                MarginModule.margin_utilization, MarginModule.margin_limit_excess,
            ):
                ledger.set(ref, 0.0)
        state.ledgers[ledger_key] = ledger

    _fund_cash_pools_once(state)


def _fund_cash_pools_once(state) -> None:
    from tools.testers.backtest.modules.cash_pool import cash_pool_store_for
    from tools.testers.backtest.modules.strategy_book import cash_pool_id_for_ledger

    store = cash_pool_store_for(state)
    ledgers_by_pool: dict[str, list] = {}
    for ledger in state.ledgers.values():
        ledgers_by_pool.setdefault(cash_pool_id_for_ledger(state, ledger), []).append(ledger)
    for pool_id, ledgers in ledgers_by_pool.items():
        if pool_id in store.reserve_by_pool:
            continue
        config = store.config_by_pool.get(pool_id, None)
        base_currency = (config.base_currency if config else None) or "CNY"
        initial_capital = float((config.initial_capital_major if config else None) or 0.0)
        base_ledger = next((item for item in ledgers if item.base_currency == base_currency), None)
        if base_ledger is None:
            store.set_reserve(pool_id, DataMoney.from_major(
                initial_capital, currency=base_currency, use_minor_units=False,
            ), CashPoolModule.cash)
            continue
        current = cash_for_ledger(state, base_ledger)
        set_cash_for_ledger_pool(state, base_ledger, DataMoney.from_major(
            initial_capital, currency=base_currency,
            use_minor_units=bool(getattr(current, "use_minor_units", False)),
        ))
        store.set_reserve(pool_id, DataMoney.from_major(
            0.0, currency=base_currency, use_minor_units=False,
        ), CashPoolModule.cash)


def products_for_backtest_window(state, ctx, strategy) -> frozenset:
    from tools.testers.backtest.modules.market_data import market_data_store_for
    from tools.testers.backtest.modules.product_selection import ProductSelectionModule

    products = frozenset(ctx.get_for(ProductSelectionModule.products, strategy, frozenset()))
    included = market_data_store_for(state).included_products
    if included is None:
        return products
    return frozenset(product for product in products if product in included)


def require_matching_cash_pool_config(
    ledger, strategy, ledger_id: str, *, existing_cash, account_currency: str,
    use_minor_units: bool, cash_pool_id: str,
) -> None:
    existing_currency = getattr(existing_cash, "currency", ledger.base_currency)
    prefix = (
        f"strategy {getattr(strategy, 'alias', strategy)!r} shares ledger {ledger_id!r} "
        f"in cash_pool {cash_pool_id!r}"
    )
    if existing_currency != account_currency:
        raise ValueError(
            f"{prefix} with account_currency={account_currency!r}, but that ledger was already "
            f"established with account_currency={existing_currency!r}."
        )
    if existing_cash.use_minor_units != use_minor_units:
        raise ValueError(
            f"{prefix} with use_minor_units={use_minor_units}, but that cash pool was already "
            f"established with use_minor_units={existing_cash.use_minor_units} -- give this "
            "strategy its own cash pool instead."
        )
