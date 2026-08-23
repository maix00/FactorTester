"""Causal signal-time fee estimate using the production fee model."""

from __future__ import annotations

from typing import Any

from tools.testers.backtest.modules.engine import engine_mode_for
from tools.testers.backtest.modules.fee import (
    _market_fee_cost,
    _resolve_fee_mode,
    _resolve_fixed_fee_cost,
)
from tools.testers.backtest.modules.fee_impl.observability import (
    record_fee_runtime_assumption,
)
from tools.testers.backtest.modules.market_data import (
    contract_multiplier_from_product_fields,
    historical_fields_for_product,
)
from tools.testers.backtest.modules.trading_rule import _resolve_method


def estimate_signal_fee(
    state: Any,
    ctx: Any,
    strategy: Any,
    ledger: Any,
    order: Any,
    historical_fields: dict,
    positions: dict,
    price: float,
    *,
    strategy_config: Any | None = None,
    ledger_config: Any | None = None,
    product_fields: dict[str, object] | None = None,
) -> float:
    config = strategy_config if strategy_config is not None else state.config_for(strategy)
    ledger_config = (
        ledger_config
        if ledger_config is not None
        else state.ledger_config_for(ledger)
    )
    mode = _resolve_fee_mode(config, ledger_config)
    fields = (
        product_fields
        if product_fields is not None
        else historical_fields_for_product(historical_fields, order.instrument)
    )
    record_fee_runtime_assumption(
        state,
        strategy=strategy,
        product=order.instrument,
        timestamp=ctx.timestamp,
        mode=mode,
        fields=fields,
    )
    multiplier = contract_multiplier_from_product_fields(
        fields, state=state, product=order.instrument, timestamp=ctx.timestamp,
    )
    fixed = _resolve_fixed_fee_cost(
        mode,
        float(getattr(ledger_config, "fixed_fee_rate", None) or 0.0),
        float(order.quantity),
        price,
        multiplier,
    )
    if fixed is not None:
        return float(fixed)
    method = _resolve_method(
        config,
        order.instrument,
        fields,
        require_exact=engine_mode_for(config) == "exact",
        ledger_config=ledger_config,
    )
    return float(_market_fee_cost(
        order,
        price=price,
        fields=fields,
        position=positions.get(order.instrument),
        fee_mode=mode,
        cost_basis_method=method,
    ))
