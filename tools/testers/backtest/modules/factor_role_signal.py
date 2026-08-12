"""Precomputed factor-role evaluation and event publication."""

from __future__ import annotations

from typing import Any

from tools.testers.backtest.modules.factor import (
    FactorModule,
    factor_role_bindings_for,
    factor_runtime_key,
)


def schedule_precomputed_factor_roles(state: Any, ctx: Any) -> None:
    from tools.testers.backtest.modules import factor_signal as runtime

    store = state.factor_signal_store
    for strategy in state.strategy_configs:
        config = state.config_for(strategy)
        if not config.uses_flow("signal_precomputed"):
            continue
        primary = config.get(FactorModule.factor)
        for role, factor in factor_role_bindings_for(config).items():
            if factor is primary:
                store.bind_precomputed_role_table(
                    strategy, role, store.precomputed_table_keys[strategy]
                )
                continue
            calculation_key = runtime._factor_calculation_key(
                factor_runtime_key(factor), config
            )
            schedule_key = runtime._precomputed_schedule_key(calculation_key, config)
            if schedule_key not in store.precomputed_tables:
                table = runtime._evaluate_factor_for_strategies(
                    factor, [strategy], state, ctx
                )
                scheduled = runtime._schedule_table_for_strategy(
                    table, config, factor=factor, state=state
                )
                result_factory = getattr(factor, "to_run_result", None)
                store.put_precomputed_table(
                    schedule_key,
                    scheduled,
                    provenance=getattr(factor, "provenance", None),
                    run_result=(
                        result_factory(table=scheduled)
                        if callable(result_factory) else None
                    ),
                )
            store.bind_precomputed_role_table(strategy, role, schedule_key)


def publish_precomputed_factor_roles(state: Any, ctx: Any, read_values: Any) -> None:
    store = state.factor_signal_store
    for strategy in ctx.active_strategies:
        values_by_role = {
            role: read_values(store, table, ctx, strategy)
            for role, table in store.precomputed_role_tables_for(strategy).items()
        }
        ctx.set_for(FactorModule.factor_role_values, strategy, values_by_role)


def reject_incremental_factor_roles(state: Any) -> None:
    for strategy in state.strategy_configs:
        config = state.config_for(strategy)
        if config.uses_flow("signal_live") and factor_role_bindings_for(config):
            raise NotImplementedError(
                "incremental factor_role_bindings are not supported yet; "
                "use factor_mode='precomputed'"
            )
