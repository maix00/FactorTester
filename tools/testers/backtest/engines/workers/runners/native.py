"""Native event-driven runner — dispatches MARKET_SLICE_CLOSED through
a StagePipeline built from registered ExecutableModules.

The runner:
  - subscribes to MARKET_SLICE_CLOSED events (NOT for-loop over timestamps)
  - builds a StagePipeline from ExecutableModule registrations
  - on each MARKET_SLICE_CLOSED: fills PhaseContext → runs the pipeline
  - knows NO module names, field names, or execution logic
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import numpy as np
import pandas as pd

from ...event_driven.runtime import (
    EventDraft,
    EventEnvelope,
    EventRuntime,
    EventTopic,
    MarketSlice,
    MarketSliceBarrier,
    ReplayEventSource,
)
from ...event_driven.stages import (
    ExecutionStage,
    PhaseContext,
    PhaseHandler,
    StagePipeline,
)
from ...modules import (
    ExecutableModule,
    GroupTestModuleRegistry,
)
from ...strategies.allocation import TrailingVolatilityEstimator
from .common import (
    execution_delay_bars,
    execution_timing,
    market_rule_diagnostics,
    parse_group_strategy_input,
    setting_fallback_diagnostics,
    should_report_progress,
    valuation_price,
)


# ── Helpers ────────────────────────────────────────────────────────


def _positions_dict(instruments: tuple[str, ...], positions: np.ndarray) -> dict[str, float]:
    return {
        instrument: float(positions[index])
        for index, instrument in enumerate(instruments)
    }


def _execution_trace_entry_vector(
    request,
    row: int,
    strategy: Mapping[str, Any],
    current: np.ndarray,
    deltas: np.ndarray,
    cash: float,
    valuation_values: np.ndarray,
    fee_rate: float = 0.0,
) -> dict[str, Any]:
    """Compact trace for the instruments changed by one event."""
    changed = np.flatnonzero(np.abs(deltas) > 1e-12)

    def clean(value: float) -> float:
        value = float(value)
        if abs(value) <= 1e-12:
            return 0.0
        return round(value, 10)

    fill_prices = valuation_values.copy()
    changed_deltas = deltas[changed]
    changed_prices = fill_prices[changed]
    trade_values = np.abs(changed_deltas) * changed_prices
    sell_mask = changed_deltas < -1e-12
    buy_mask = changed_deltas > 1e-12
    sell_proceeds_after_fee = float(np.sum(trade_values[sell_mask] * (1.0 - fee_rate)))
    buy_cost_with_fee = float(np.sum(trade_values[buy_mask] * (1.0 + fee_rate)))

    delta: dict[str, float] = {}
    current_size: dict[str, float] = {}
    target_size: dict[str, float] = {}
    fill_price: dict[str, float] = {}
    notional: dict[str, float] = {}
    for idx, price, trade_value in zip(changed, changed_prices, trade_values, strict=True):
        instrument = request.instruments[int(idx)]
        delta[instrument] = clean(float(deltas[int(idx)]))
        current_size[instrument] = clean(float(current[int(idx)]))
        target_size[instrument] = clean(float(current[int(idx)] + deltas[int(idx)]))
        fill_price[instrument] = clean(float(price))
        notional[instrument] = clean(float(trade_value))
    return {
        "delta": delta,
        "current_size": current_size,
        "target_size": target_size,
        "fill_price": fill_price,
        "notional": notional,
        "cash_before": clean(cash),
        "cash_available_after_sells": clean(float(cash) + sell_proceeds_after_fee),
        "buy_cost_with_fee": clean(buy_cost_with_fee),
        "fee_rate": clean(fee_rate),
        "trace_shape": "changed_only",
    }


def _position_value_snapshot_vector(
    request,
    positions: np.ndarray,
    valuation_values: np.ndarray,
    margin_ratios: np.ndarray,
    margin_mode: str = "none",
) -> tuple[dict[str, float], dict[str, float] | None]:
    active = np.flatnonzero(np.abs(positions) > 1e-12)
    notional = {
        request.instruments[int(index)]: float(positions[index] * valuation_values[index])
        for index in active
    }
    if margin_mode == "none":
        return notional, None
    margin = {
        request.instruments[int(index)]: float(abs(positions[index]) * valuation_values[index] * margin_ratios[index])
        for index in active
    }
    return notional, margin


# ── Module registry → pipeline builder ──────────────────────────────


def _build_pipeline(
    modules: list[ExecutableModule],
) -> StagePipeline:
    """Build a StagePipeline from ExecutableModule instances.

    Each module's `phases` class attribute declares which phases it
    participates in. The pipeline maps each module's `on_<phase>` method
    to the corresponding ExecutionStage.
    """
    pipeline = StagePipeline()
    stage_order = list(ExecutionStage)
    module_phases: dict[str, tuple[PhaseHandler, ...]] = {}
    module_order_map: dict[str, int] = {}

    for mod in modules:
        module_phases[mod.key] = mod.phases
        module_order_map[mod.key] = mod.order
        for ph in mod.phases:
            try:
                es = ExecutionStage(ph.phase)
            except ValueError:
                continue  # skip unknown phase names
            handler_method = getattr(mod, f"on_{ph.phase}", None)
            if handler_method is None:
                continue

            # Wrap the method as a StageHandler
            def _make_handler(
                m: ExecutableModule, method: Callable[[PhaseContext], None],
            ):
                def _handler(ctx: PhaseContext, _event, _runtime) -> None:
                    method(ctx)
                return _handler

            pipeline.register(
                stage=es,
                order=ph.order,
                module_key=mod.key,
                handler=_make_handler(mod, handler_method),
            )
    pipeline.build(module_phases, module_order_map)
    return pipeline


# ── Main runner ─────────────────────────────────────────────────────


def run_group_strategy(payload: Mapping[str, Any], progress=None) -> dict[str, Any]:
    """Run a group strategy backtest using the event-driven pipeline.

    1. Parse input
    2. Build PhaseContext with strategy states
    3. Build StagePipeline from registered ExecutableModules
    4. Wire EventRuntime: ReplayEventSource → MarketSliceBarrier → pipeline
    5. EventRuntime.run() — event-queue-driven loop
    6. Collect results from PhaseContext
    """
    request, memberships, updates, calculators = parse_group_strategy_input(payload)

    # ── Initialize modules via registry (no hardcoded imports) ──
    registry = GroupTestModuleRegistry()
    modules: list[ExecutableModule] = registry.instantiate(*registry.default_module_keys)

    # Bind settings from the first strategy (shared settings pattern)
    if request.strategies:
        first = request.strategies[0]
        for mod in modules:
            mod.bind_settings(dict(first))
    pipeline = _build_pipeline(modules)

    # ── Initialize strategy states ──────────────────────────────
    strategy_states: list[dict[str, Any]] = []
    volatility_estimators: dict[tuple[int, int, float], TrailingVolatilityEstimator] = {}
    volatility_previous_prices: dict[tuple[int, int, float], np.ndarray | None] = {}

    for strategy, calculator in zip(request.strategies, calculators, strict=True):
        strategy_cash = float(strategy.get("initial_capital") or request.initial_cash)
        volatility_key = None
        if getattr(calculator, "allocation_name", "") == "inverse_volatility":
            estimator = calculator.estimator
            volatility_key = (
                int(estimator.lookback),
                int(estimator.min_observations),
                float(estimator.annualization),
            )
            if volatility_key not in volatility_estimators:
                volatility_estimators[volatility_key] = TrailingVolatilityEstimator(
                    tuple(request.instruments),
                    lookback=volatility_key[0],
                    min_observations=volatility_key[1],
                    annualization=volatility_key[2],
                )
                volatility_previous_prices[volatility_key] = None
        strategy_states.append({
            "strategy": strategy,
            "calculator": calculator,
            "volatility_key": volatility_key,
            "initial_value": strategy_cash,
            "cash": strategy_cash,
            "positions": np.zeros(len(request.instruments), dtype=float),
            "pending_targets": [],
            "equity_curve": {},
            "position_curve": {},
            "notional_curve": {},
            "margin_curve": {},
            "execution_trace": {},
            "execution_trace_count": 0,
            "timing": execution_timing(strategy),
            "delay_bars": execution_delay_bars(strategy),
            "collect_execution_trace": bool(strategy.get("collect_execution_trace")),
        })

    # ── Build PhaseContext ──────────────────────────────────────
    ctx = PhaseContext(
        request=request,
        memberships=memberships,
        updates=updates,
        calculators=calculators,
        strategy_states=strategy_states,
        volatility_estimators=volatility_estimators,
        volatility_previous_prices=volatility_previous_prices,
    )

    # ── Wire EventRuntime ───────────────────────────────────────
    run_id = f"native-{request.timestamps[0].isoformat()}-{request.timestamps[-1].isoformat()}"
    runtime = EventRuntime(run_id)

    # Replay source: publishes one MARKET_DATA per timestamp
    replay_source = ReplayEventSource(
        request.timestamps,
        [None] * len(request.timestamps),
    )
    runtime.add_source(replay_source)

    # Barrier: collects product prices → emits MARKET_SLICE_CLOSED
    barrier = MarketSliceBarrier(request.instruments)
    runtime.subscribe(EventTopic.MARKET_DATA, barrier.on_price)

    progress_state: dict[str, Any] = {"row": 0, "total": len(request.timestamps)}

    def _on_market_slice(event: EventEnvelope, rt: EventRuntime) -> None:
        """Per-slice handler: fill context fields, run pipeline."""
        slice_data = event.payload
        if not isinstance(slice_data, MarketSlice):
            return

        row = progress_state["row"]
        timestamp = event.timestamp

        # Fill per-slice fields
        ctx.row = row
        ctx.timestamp = timestamp
        ctx.current_prices = np.asarray([
            request.prices[name][row] for name in request.instruments
        ], dtype=float)
        ctx.valuation_values = ctx.current_prices * np.asarray(request.multipliers[row], dtype=float)
        ctx.volumes_row = (
            np.asarray([request.volumes[name][row] for name in request.instruments], dtype=float)
            if request.volumes is not None else None
        )
        ctx.margin_ratios = np.asarray(request.margin_ratios[row])

        # Update volatility estimators
        for key, estimator in ctx.volatility_estimators.items():
            previous = ctx.volatility_previous_prices.get(key)
            if previous is not None:
                with np.errstate(all="ignore"):
                    returns = ctx.current_prices / previous - 1.0
                estimator.update_values(returns)
            ctx.volatility_previous_prices[key] = ctx.current_prices.copy()
            ctx.volatility_snapshots[key] = estimator.snapshot()

        # ── Per-strategy per-slice loop ─────────────────────────
        valuation_values = ctx.valuation_values
        volumes_row = ctx.volumes_row
        margin_ratios_row = ctx.margin_ratios
        for state in ctx.strategy_states:
            strategy = state["strategy"]
            calculator = state["calculator"]
            positions: np.ndarray = state["positions"]
            cash = float(state["cash"])
            pending_targets: list = state["pending_targets"]
            current_value = float(cash + np.sum(positions * valuation_values))

            # Process due pending targets
            due_targets = [t for due_row, t in pending_targets if due_row <= row]
            state["pending_targets"] = [
                (due_row, t) for due_row, t in pending_targets if due_row > row
            ]
            for pending in due_targets:
                deltas_before_vec = positions.copy() if state["collect_execution_trace"] else None
                cash_before = cash

                # Fill context with per-strategy fields
                ctx.set("weights", np.array([float(pending.get(instr, 0.0))
                                              for instr in request.instruments]))
                ctx.set("prices", ctx.current_prices)
                ctx.set("multipliers", np.asarray(request.multipliers[row], dtype=float))
                ctx.set("lot_sizes", np.asarray(request.lot_sizes[row], dtype=float))
                ctx.set("current_value", current_value)
                ctx.set("positions", positions)
                ctx.set("volumes_row", volumes_row)
                ctx.set("margin_ratios", margin_ratios_row)
                ctx.set("valuation_values", valuation_values)
                ctx.set("cash", cash)
                ctx.set("deltas", None)
                ctx.set("fill_prices", None)

                # Run pipeline phases for this execution
                pipeline.per_slice(ctx, event, rt)

                deltas_vec = ctx.get("deltas")
                if deltas_vec is not None and deltas_before_vec is not None:
                    cash = float(ctx.get("cash", cash))
                    positions = positions + np.asarray(deltas_vec, dtype=float)
                    if bool(np.any(np.abs(deltas_vec) > 1e-12)):
                        state["execution_trace_count"] += 1
                        if state["collect_execution_trace"]:
                            fee_rate = float(ctx.get("fee_rate", 0.0))
                            state["execution_trace"][timestamp.isoformat()] = _execution_trace_entry_vector(
                                request, row, strategy, deltas_before_vec, deltas_vec,
                                cash_before, valuation_values, fee_rate,
                            )
                elif deltas_vec is not None:
                    cash = float(ctx.get("cash", cash))
                    positions = positions + np.asarray(deltas_vec, dtype=float)
                current_value = float(cash + np.sum(positions * valuation_values))

            # Signal generation
            target = calculator.update(
                timestamp,
                np.asarray(ctx.current_prices),
                memberships[row],
                updates[row],
                margin_ratios_row,
                ctx.volatility_snapshots.get(state["volatility_key"]),
            )

            timing = state["timing"]
            if timing == "same_bar" and target is not None:
                deltas_before_vec = positions.copy() if state["collect_execution_trace"] else None
                cash_before = cash

                ctx.set("weights", np.array([float(target.get(instr, 0.0))
                                              for instr in request.instruments]))
                ctx.set("prices", ctx.current_prices)
                ctx.set("multipliers", np.asarray(request.multipliers[row], dtype=float))
                ctx.set("lot_sizes", np.asarray(request.lot_sizes[row], dtype=float))
                ctx.set("current_value", current_value)
                ctx.set("positions", positions)
                ctx.set("volumes_row", volumes_row)
                ctx.set("margin_ratios", margin_ratios_row)
                ctx.set("valuation_values", valuation_values)
                ctx.set("cash", cash)
                ctx.set("deltas", None)
                ctx.set("fill_prices", None)

                pipeline.per_slice(ctx, event, rt)

                deltas_vec = ctx.get("deltas")
                if deltas_vec is not None and deltas_before_vec is not None:
                    cash = float(ctx.get("cash", cash))
                    positions = positions + np.asarray(deltas_vec, dtype=float)
                    if bool(np.any(np.abs(deltas_vec) > 1e-12)):
                        state["execution_trace_count"] += 1
                        if state["collect_execution_trace"]:
                            fee_rate = float(ctx.get("fee_rate", 0.0))
                            state["execution_trace"][timestamp.isoformat()] = _execution_trace_entry_vector(
                                request, row, strategy, deltas_before_vec, deltas_vec,
                                cash_before, valuation_values, fee_rate,
                            )
                elif deltas_vec is not None:
                    cash = float(ctx.get("cash", cash))
                    positions = positions + np.asarray(deltas_vec, dtype=float)
                current_value = float(cash + np.sum(positions * valuation_values))
            elif timing == "next_bar" and target is not None:
                state["pending_targets"].append((row + state["delay_bars"], target))

            # Record curves
            state["cash"] = cash
            state["positions"] = positions
            state["equity_curve"][timestamp.isoformat()] = float(current_value)
            state["position_curve"][timestamp.isoformat()] = _positions_dict(request.instruments, positions)
            notional_values, margin_values = _position_value_snapshot_vector(
                request, positions, valuation_values, margin_ratios_row,
                margin_mode=str(strategy.get("margin_mode", "none")),
            )
            state["notional_curve"][timestamp.isoformat()] = notional_values
            if margin_values is not None:
                state["margin_curve"][timestamp.isoformat()] = margin_values

        progress_state["row"] += 1
        if progress is not None and should_report_progress(progress_state["row"], progress_state["total"]):
            progress(progress_state["row"], progress_state["total"], timestamp)

    runtime.subscribe(EventTopic.MARKET_SLICE_CLOSED, _on_market_slice)

    # ── Run the event loop ──────────────────────────────────────
    runtime.run()

    # ── Build results ───────────────────────────────────────────
    portfolios = {}
    for state in strategy_states:
        calculator = state["calculator"]
        cash_val = float(state["cash"])
        positions: np.ndarray = state["positions"]
        positions_dict = _positions_dict(request.instruments, positions)
        final_prices = np.asarray([
            valuation_price(request, len(request.timestamps) - 1, instrument)
            for instrument in request.instruments
        ], dtype=float)
        portfolios[calculator.strategy_id] = {
            "initial_value": state["initial_value"],
            "final_value": float(cash_val + np.sum(positions * final_prices)),
            "positions": positions_dict,
            "equity_curve": state["equity_curve"],
            "position_curve": state["position_curve"],
            "notional_curve": state["notional_curve"],
            "margin_curve": state["margin_curve"],
            "execution_trace": state["execution_trace"],
            "execution_trace_count": state["execution_trace_count"],
        }
    return {
        "engine": "native",
        "portfolios": portfolios,
        "target_trace": {item.strategy_id: item.target_trace for item in calculators},
        "execution_trace": {
            strategy_id: portfolio.get("execution_trace", {})
            for strategy_id, portfolio in portfolios.items()
        },
        "strategy_diagnostics": {
            item.strategy_id: {
                **item.diagnostics,
                **market_rule_diagnostics(payload),
                **setting_fallback_diagnostics(strategy),
            }
            for item, strategy in zip(calculators, request.strategies, strict=True)
        },
        "event_count": len(request.timestamps),
    }
