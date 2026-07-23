"""Build and register OrderGroups from sized deltas."""

from __future__ import annotations

from tools.testers.backtest.modules.order_flow import order_flow_store_for
from tools.testers.backtest.modules.trading_rule import _resolve_method

from .decomposition import decompose_position_delta


def construct_orders(state, ctx, module) -> None:
    from tools.testers.backtest.modules.ledger_module import LedgerModule
    from tools.testers.backtest.modules.strategy_book import ledger_for_strategy_product

    audit_store = order_flow_store_for(state)
    for strategy in ctx.active_strategies:
        orders = []
        deltas = ctx.get_for(module.deltas, strategy, {})
        for product in sorted(deltas, key=lambda item: str(getattr(item, "name", item))):
            delta = float(deltas[product] or 0.0)
            if abs(delta) <= 1e-12:
                continue
            ledger = ledger_for_strategy_product(state, strategy, product)
            position = ledger.get(LedgerModule.positions, {}).get(product)
            current = float(getattr(position, "quantity", 0.0) or 0.0)
            needs_close = current and (current > 0) != (delta > 0)
            method = "FIFO"
            if needs_close:
                method = _resolve_method(
                    state.config_for(strategy), product,
                    ledger_config=state.ledger_config_for(ledger),
                )
            group_id = audit_store.next_group_id(strategy, ctx.timestamp)
            parent_intent_id = f"{group_id}:intent"
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
            )
            state.order_store.register_group(group)
            for order in children:
                state.order_store.register_order(order)
                audit_store.record(
                    order, step="construct_order", label="构造原子订单",
                    details={
                        "group_policy": group.execution_policy,
                        "child_order_ids": group.child_order_ids,
                    },
                )
            orders.extend(children)
        ctx.set_for(module.orders, strategy, orders)


def order_id_stream(audit_store, strategy, timestamp):
    while True:
        yield audit_store.next_order_id(strategy, timestamp)
