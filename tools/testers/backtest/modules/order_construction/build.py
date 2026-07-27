"""Build and register OrderGroups from sized deltas."""

from __future__ import annotations

from tools.testers.backtest.modules.engine import engine_mode_for
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.order_flow import order_flow_store_for
from tools.testers.backtest.modules.trading_rule import _resolve_method
from tools.testers.backtest.modules.target import PairedTargetWeightIntent
from .sizing import strategy_trade_intent

from .decomposition import decompose_position_delta


def construct_orders(state, ctx, module) -> None:
    from tools.testers.backtest.modules.ledger_module import LedgerModule
    from tools.testers.backtest.modules.strategy_book import ledger_for_strategy_product

    audit_store = order_flow_store_for(state)
    for strategy in ctx.active_strategies:
        orders = []
        deltas = ctx.get_for(module.deltas, strategy, {})
        intent = strategy_trade_intent(ctx, strategy)
        shared_parent_id = (
            intent.parent_intent_id
            if isinstance(intent, PairedTargetWeightIntent)
            else ""
        )
        for product in sorted(deltas, key=lambda item: str(getattr(item, "name", item))):
            delta = float(deltas[product] or 0.0)
            if abs(delta) <= 1e-12:
                continue
            ledger = ledger_for_strategy_product(
                state, strategy, product, timestamp=ctx.timestamp,
            )
            position = ledger.get(LedgerModule.positions, {}).get(product)
            current = float(getattr(position, "quantity", 0.0) or 0.0)
            needs_close = current and (current > 0) != (delta > 0)
            method = "FIFO"
            exact = False
            if needs_close:
                config = state.config_for(strategy)
                exact = engine_mode_for(config) == "exact"
                historical_fields = ctx.get_for(
                    MarketDataModule.current_historical_fields, strategy,
                    ctx.get(MarketDataModule.current_historical_fields, {}),
                )
                method = _resolve_method(
                    config, product, historical_fields,
                    require_exact=exact,
                    ledger_config=state.ledger_config_for(ledger),
                )
            group_id = audit_store.next_group_id(strategy, ctx.timestamp)
            parent_intent_id = shared_parent_id or f"{group_id}:intent"
            group, children = decompose_position_delta(
                strategy=strategy,
                product=product,
                timestamp=ctx.timestamp,
                delta=delta,
                position=position,
                group_id=group_id,
                parent_intent_id=parent_intent_id,
                order_ids=order_id_stream(audit_store, strategy, ctx.timestamp),
                cost_basis_method=method,
                require_exact_offsets=exact,
                supersedes_group_id=state.order_store.superseded_group_id_by_scope.pop(
                    (strategy, product), "",
                ),
            )
            if isinstance(intent, PairedTargetWeightIntent):
                for order in children:
                    order.set(
                        "paired_execution_policy",
                        intent.execution_policy,
                    )
            state.order_store.register_group(group)
            for order in children:
                ledger_id = getattr(ledger, "ledger_id", None)
                if ledger_id in (None, ""):
                    ledger_id = getattr(getattr(ledger, "ledger", None), "name", None)
                if ledger_id not in (None, ""):
                    order.set("ledger_id", str(ledger_id))
                state.order_store.register_order(order)
                audit_store.record(
                    order, step="construct_order", label="构造原子订单",
                    details={
                        "group_policy": group.execution_policy,
                        "child_order_ids": group.child_order_ids,
                        "paired_execution_policy": getattr(
                            intent, "execution_policy", None,
                        ),
                    },
                )
            orders.extend(children)
        ctx.set_for(module.orders, strategy, orders)


def order_id_stream(audit_store, strategy, timestamp):
    while True:
        yield audit_store.next_order_id(strategy, timestamp)
