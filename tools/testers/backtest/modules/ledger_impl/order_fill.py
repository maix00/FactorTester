"""Settle one same-time ORDER batch into ledgers."""

from __future__ import annotations

from tools.data.types.data_money import DataMoney
from tools.testers.backtest.modules.cash_pool import set_cash_for_ledger_pool
from tools.testers.backtest.modules.market_data import (
    MarketDataModule,
    contract_multiplier_from_fields,
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
        config = config_by_strategy[strategy]
        realized_pnl = 0.0
        margin_accounting = uses_margin_accounting(
            config, historical_fields, order.instrument, ledger_config,
        )
        if margin_accounting:
            cash = apply_margin_accounting_fill(
                cash, positions, config, order.instrument,
                quantity=float(order.quantity), price=price, fee_cost=fee,
                historical_fields=historical_fields, ledger_config=ledger_config,
                state=state, timestamp=ctx.timestamp, offset=order.offset,
            )
        else:
            multiplier = contract_multiplier_from_fields(
                historical_fields, order.instrument,
                state=state, timestamp=ctx.timestamp,
            )
            realized_pnl = apply_cash_accounting_position_fill(
                positions, config, order.instrument,
                quantity=float(order.quantity), price=price,
                historical_fields=historical_fields, ledger_config=ledger_config,
                state=state, timestamp=ctx.timestamp, offset=order.offset,
                multiplier=multiplier,
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
        sync_ledger_margin_reserved(ledger, positions)
        margin_after = margin_reserved_major(ledger)
        if margin_accounting:
            realized_pnl = (
                float(cash.to_major()) - float(cash_before) + fee
                + margin_after - margin_before
            )
        fill = record_fill_settlement(
            state, order, timestamp=ctx.timestamp, price=price, fee=fee,
            realized_pnl=realized_pnl,
            cash_before=float(cash_before), cash_after=float(cash.to_major()),
            margin_before=margin_before, margin_after=margin_after,
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
                "cash_pool_id": cash_pool_id_for_ledger(state, ledger),
                "price": price,
                "fee_cost": fee,
                "cash_before": float(cash_before),
                "cash_after": float(cash.to_major()),
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
