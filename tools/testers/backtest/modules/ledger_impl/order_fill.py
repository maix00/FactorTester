"""Settle one same-time ORDER batch into ledgers."""

from __future__ import annotations

from tools.data.types.data_money import DataMoney
from tools.testers.backtest.modules.cash_pool import (
    cash_pool_config_for_ledger,
    set_cash_for_ledger_pool,
)
from tools.testers.backtest.modules.market_data import (
    MarketDataModule,
    contract_multiplier_from_product_fields,
    historical_fields_for_product,
)
from tools.testers.backtest.modules.order_flow import order_flow_store_for
from tools.testers.backtest.modules.order_lifecycle import (
    order_status_event_if_enabled,
    record_fill_settlement,
)
from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.position_events import position_events_for_fill
from tools.testers.backtest.modules.strategy_book import cash_pool_id_for_ledger

from .balances import (
    entry_margin_major,
    margin_reserved_major,
    required_cash_for_ledger,
    sync_ledger_margin_reserved,
    uses_margin_accounting,
)
from .cash_accounting import apply_cash_accounting_position_fill
from .margin_accounting import apply_margin_accounting_fill
from .order_checks import prepare_order_fill, settlement_order


def apply_order_fill(state, ctx) -> None:
    """Settle reductions before increases across one timestamp batch."""
    from tools.testers.backtest.modules.ledger_module import LedgerModule

    prices = ctx.get(MarketDataModule.current_prices)
    audit_store = order_flow_store_for(state)
    historical_by_strategy = {
        strategy: ctx.get_for(
            MarketDataModule.current_historical_fields, strategy,
            ctx.get(MarketDataModule.current_historical_fields, {}),
        )
        for strategy in ctx.active_strategies
    }
    config_by_strategy = {
        strategy: state.config_for(strategy)
        for strategy in ctx.active_strategies
    }
    fill_prices_by_ledger: dict[str, dict[object, float]] = {}
    position_event_drafts: list[EventDraft] = []
    status_event_drafts: list[EventDraft] = []
    for strategy, order in settlement_order(state, ctx):
        if not prepare_order_fill(state, ctx, strategy, order, audit_store):
            status_event = order_status_event_if_enabled(
                state, order, timestamp=ctx.timestamp,
            )
            if status_event is not None and order.status.terminal:
                status_event_drafts.append(status_event)
            continue
        ledger = state.ledger_for(order)
        ledger_config = state.ledger_config_for(ledger)
        positions = ledger.get(LedgerModule.positions, {})
        previous_entry = positions.get(order.instrument)
        previous_product_reserved = (
            entry_margin_major(previous_entry)
            if previous_entry is not None else 0.0
        )
        previous_quantity = float(
            getattr(positions.get(order.instrument), "quantity", 0.0) or 0.0
        )
        cash = required_cash_for_ledger(state, ledger)
        effective_price = order.get("effective_price")
        price = float(
            effective_price
            if effective_price is not None
            else prices[order.instrument]
        )
        fee = float(order.get("fee_cost", 0.0) or 0.0)
        cash_before = cash.to_major()
        margin_before = margin_reserved_major(ledger)
        historical_fields = historical_by_strategy[strategy]
        product_fields = historical_fields_for_product(
            historical_fields, order.instrument,
        )
        config = config_by_strategy[strategy]
        realized_pnl = 0.0
        margin_accounting = uses_margin_accounting(
            config, historical_fields, order.instrument, ledger_config,
            product_fields=product_fields,
        )
        if margin_accounting:
            cash = apply_margin_accounting_fill(
                cash, positions, config, order.instrument,
                quantity=float(order.quantity), price=price, fee_cost=fee,
                historical_fields=historical_fields, ledger_config=ledger_config,
                product_fields=product_fields,
                state=state, timestamp=ctx.timestamp, offset=order.offset,
            )
        else:
            multiplier = contract_multiplier_from_product_fields(
                product_fields,
                state=state, product=order.instrument, timestamp=ctx.timestamp,
            )
            realized_pnl = apply_cash_accounting_position_fill(
                positions, config, order.instrument,
                quantity=float(order.quantity), price=price,
                historical_fields=historical_fields, ledger_config=ledger_config,
                state=state, timestamp=ctx.timestamp, offset=order.offset,
                multiplier=multiplier,
                product_fields=product_fields,
            )
            notional = (
                float(order.quantity) * price
                * multiplier
            )
            cash = cash - DataMoney.from_major(
                notional + fee, currency=cash.currency,
                use_minor_units=cash.use_minor_units,
            )
        ledger.set(LedgerModule.positions, positions)
        set_cash_for_ledger_pool(state, ledger, cash)
        # Fully-funded products do not mutate any position margin component.
        # Re-summing every position after their fills is therefore redundant;
        # preserve the existing ledger margin fields and reserve the full
        # reconciliation for margin-accounted fills, where the current
        # product's reserved margin may have changed.
        if margin_accounting:
            sync_ledger_margin_reserved(
                ledger, positions,
                changed_product=order.instrument,
                previous_ledger_reserved=margin_before,
                previous_product_reserved=previous_product_reserved,
            )
        margin_after = margin_reserved_major(ledger)
        cash_after_major = float(cash.to_major())
        if margin_accounting:
            realized_pnl = (
                cash_after_major - float(cash_before) + fee
                + margin_after - margin_before
            )
        cash_pool_id = cash_pool_id_for_ledger(state, ledger)
        pool_config = cash_pool_config_for_ledger(state, ledger)
        account_currency = str(getattr(cash.currency, "code", cash.currency))
        fill = record_fill_settlement(
            state, order, timestamp=ctx.timestamp, price=price, fee=fee,
            realized_pnl=realized_pnl,
            cash_before=float(cash_before), cash_after=cash_after_major,
            margin_before=margin_before, margin_after=margin_after,
            account_id=ledger.ledger_id,
            cash_pool_id=cash_pool_id,
            account_currency=account_currency,
            cash_pool_base_currency=str(pool_config.base_currency or ""),
        )
        current_quantity = float(
            getattr(positions.get(order.instrument), "quantity", 0.0) or 0.0
        )
        if config.uses_flow("strategy_runtime_on_position_event"):
            position_event_drafts.extend(
                EventDraft(
                    EventKind.POSITION, ctx.timestamp, strategy, event,
                )
                for event in position_events_for_fill(
                    product=order.instrument,
                    previous_quantity=previous_quantity,
                    quantity=current_quantity,
                    price=price,
                    order_id=order.order_id,
                    fill_id=fill.fill_id,
                    ledger_id=ledger.ledger_id,
                )
            )
        status_event = order_status_event_if_enabled(
            state, order, timestamp=ctx.timestamp,
        )
        if status_event is not None:
            status_event_drafts.append(status_event)
        fill_prices_by_ledger.setdefault(ledger.ledger_id, {})[
            order.instrument
        ] = fill.price
        audit_store.record(
            order, step="ledger_update", label="成交落账",
            timestamp=ctx.timestamp,
            details={
                "fill_id": fill.fill_id,
                "ledger_id": ledger.ledger_id,
                "cash_pool_id": cash_pool_id,
                "account_currency": account_currency,
                "cash_pool_base_currency": str(pool_config.base_currency or ""),
                "price": price,
                "fee_cost": fee,
                "cash_before": float(cash_before),
                "cash_after": cash_after_major,
                "margin_before": margin_before,
                "margin_after": margin_after,
            },
        )
    ctx.set(
        LedgerModule._order_fill_valuation_prices_ref,
        fill_prices_by_ledger,
    )
    ctx.set(LedgerModule.position_events, position_event_drafts)
    ctx.set(LedgerModule.order_status_events, status_event_drafts)
